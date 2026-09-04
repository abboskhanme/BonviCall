"""Seed the first admin and the reference data (T148).

Run once against a fresh database, after ``alembic upgrade head``::

    docker compose run --rm backend python -m src.seed

Idempotent: running it twice changes nothing. The settings defaults are seeded
by the migration itself (SPEC §3.8), so this file only creates the things a
migration should not — an account with a password.

**It refuses to run in production with the default password still in place.**
An unreachable panel and a panel with a known password are both deployment
failures, and only one of them is loud. This makes the second one loud too.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys

from sqlalchemy import func, select

from src.core import database

# Every process entry point imports the registry before touching a model
# (CONVENTIONS.md §10). Without this line the first FK string to resolve raises
# NoReferencedTableError — which is exactly what this file did before the line
# existed, and exactly the failure the registry is for.
from src.core import models as _model_registry  # noqa: F401
from src.core.config import get_settings
from src.core.enums import UserRole
from src.core.logging import configure_logging, get_logger
from src.core.security import MIN_PASSWORD_LENGTH, hash_password
from src.modules.users.models import UserModel

log = get_logger(__name__)

DEFAULT_ADMIN_EMAIL = "admin@bonvi.uz"
INSECURE_PASSWORDS = frozenset({"", "change_me", "admin", "password"})


async def seed_first_admin() -> tuple[str, str] | None:
    """Create the first admin. Returns ``(email, password)`` when one was made.

    The password is returned so the caller can print it **once**: a seeded
    account nobody can log into is a seed that did not work, and that is
    exactly what happened — the first admin was created with a password nobody
    had recorded, and the panel could not be demonstrated with it.
    """
    settings = get_settings()
    email = os.environ.get("SEED_ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL)
    password = os.environ.get("SEED_ADMIN_PASSWORD", "")
    generated = False

    if settings.is_production and password in INSECURE_PASSWORDS:
        # Same rule as assert_production_ready(): a server with a known
        # password and an unreachable one are both deployment failures, and
        # only one of them is loud.
        raise RuntimeError(
            "refusing to seed a production admin without SEED_ADMIN_PASSWORD"
        )
    if not password:
        # Outside production, generate one and say what it is. The alternative
        # is refusing, which turns `make up` into a support question.
        password = secrets.token_urlsafe(12)
        generated = True
    if len(password) < MIN_PASSWORD_LENGTH:
        raise RuntimeError(
            f"SEED_ADMIN_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters"
        )

    async with database.get_sessionmaker()() as session:
        existing = await session.scalar(select(func.count()).select_from(UserModel))
        if existing:
            log.info("seed_skipped", reason="users already exist", count=existing)
            return None
        session.add(
            UserModel(
                email=email,
                password_hash=hash_password(password),
                full_name="Administrator",
                role=UserRole.ADMIN,
                # Whoever typed this password still knows it, generated or not.
                must_change_password=True,
            )
        )
        await session.commit()
    # Never the password: N26 forbids a secret in a log line, and this one is
    # printed to the operator's terminal instead.
    log.info("seed_admin_created", email=email, password_generated=generated)
    return email, password


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.environment)
    try:
        created = asyncio.run(seed_first_admin())
    except RuntimeError as exc:
        print(f"seed refused: {exc}", file=sys.stderr)
        return 1
    if created is None:
        print("nothing to seed: an account already exists")
        return 0
    email, password = created
    # Printed once, to stdout, and nowhere else. The account is created with
    # must_change_password=True, so this credential's only job is the first
    # login.
    print("=" * 62)
    print("First admin created. This is shown once and is not stored anywhere.")
    print(f"  email:    {email}")
    print(f"  password: {password}")
    print("You will be asked to change it on first login.")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
