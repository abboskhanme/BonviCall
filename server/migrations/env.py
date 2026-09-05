"""Alembic environment.

The URL comes from ``core.config`` (or ``-x db_url=...``), never from
``alembic.ini``: the test suite runs ``upgrade head`` against ``bonvicall_test``
on every run, and a URL baked into a file is how somebody eventually migrates
the wrong database.

**A downgrade against the configured dev/production database is refused.**
Not theoretical: ``docker compose run -e POSTGRES_DB=throwaway backend alembic
downgrade base`` reads as if it targets a throwaway, and does not — the URL is
one whole string from ``.env`` and ``POSTGRES_DB`` never reaches it. That
command emptied the development database on 2026-09-05. Selecting a database
with an environment variable that is not the one in use is a mistake the tool
should catch, so it does.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

# Importing the registry — not the individual modules — is what guarantees
# every mapper is known before autogenerate compares anything (CONVENTIONS §10).
from src.core.config import get_settings
from src.core.models import metadata as target_metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    override = context.get_x_argument(as_dictionary=True).get("db_url")
    return override or get_settings().database_url


def _guard_destructive_run(url: str) -> None:
    """Refuse ``downgrade`` against the dev/production database.

    A downgrade is not a migration, it is a ``DROP`` of everything the head
    created, and the person running one is nearly always aiming at a throwaway.
    Passing ``-x db_url=...`` (which is how you *actually* choose a database
    here) or ``-x i_know_this_is_destructive=yes`` gets through; nothing else
    does.

    The check reads the requested revision rather than the command name because
    Alembic does not hand the command name to ``env.py``. ``base``, ``-N`` and
    ``head:base`` are how a downgrade is spelled on the command line.
    """
    arguments = context.get_x_argument(as_dictionary=True)
    if "db_url" in arguments or arguments.get("i_know_this_is_destructive") == "yes":
        return

    settings = get_settings()
    if url != settings.database_url:
        return

    destination = getattr(getattr(config, "cmd_opts", None), "revision", None)
    if destination is None:
        return
    destination = str(destination)
    target = destination.split(":")[-1]
    if target == "base" or target.startswith("-"):
        raise RuntimeError(
            "Refusing to downgrade the configured database "
            f"({settings.postgres_db!r}). It is the development or production "
            "database, and a downgrade drops every table the head created.\n"
            "  For a throwaway:      alembic -x db_url=<url> downgrade base\n"
            "  If you mean this one: alembic -x i_know_this_is_destructive=yes \\\n"
            "                                downgrade base\n"
            "  Note: POSTGRES_DB does NOT select the database — DATABASE_URL is "
            "one whole string."
        )


def run_migrations_offline() -> None:
    """Emit SQL to stdout — used to *read* a migration before it is applied."""
    url = _database_url()
    _guard_destructive_run(url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # Server defaults are compared as strings and PostgreSQL rewrites them
        # ("0" becomes "0::integer"), so comparing them turns `alembic check`
        # into permanent noise. Types and columns are compared; defaults are
        # reviewed in the diff like any other DDL.
        compare_server_default=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    url = _database_url()
    _guard_destructive_run(url)
    section["sqlalchemy.url"] = url
    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
