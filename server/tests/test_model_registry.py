"""The single ORM model registry, and the enum catalogue (§10, T147).

BonviZvonki carries "every model must be imported or FK resolution fails at
runtime" as folklore. Here it is a test: a model that is not reachable from
``core.models`` fails CI instead of raising ``NoReferencedTableError`` in
production, on one code path, in whichever unrelated module happens to resolve
the foreign key first.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import sqlalchemy as sa

from src.core.database import Base
from src.core.enums import PG_ENUM_TYPES
from src.core.models import metadata

MODULES_DIR = Path(__file__).resolve().parents[1] / "src" / "modules"
VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"
MIGRATION = VERSIONS_DIR / "001_create_release1_schema.py"


def _declared_model_classes() -> dict[str, str]:
    """Every ``*Model`` class defined in a module's ``models.py``, read from disk.

    Read from disk rather than from imports on purpose: importing the modules
    would *be* the registration this test is trying to prove happened.
    """
    found: dict[str, str] = {}
    for path in sorted(MODULES_DIR.glob("*/models.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and any(
                isinstance(base, ast.Name) and base.id == "Base" for base in node.bases
            ):
                found[node.name] = f"{path.parent.name}.models"
    return found


def test_model_registry_complete() -> None:
    """Every model on disk is reachable from ``core.models``."""
    import src.core.models as registry

    declared = _declared_model_classes()
    assert declared, "no models found on disk — the walk is broken, not the registry"
    missing = sorted(name for name in declared if not hasattr(registry, name))
    assert missing == [], (
        f"not imported in src/core/models.py: {missing}. "
        "A model reachable only through a router import raises "
        "NoReferencedTableError at runtime, in production."
    )


def test_registry_metadata_holds_every_table() -> None:
    """One table per model class, and every class mapped."""
    mapped = {mapper.class_.__name__ for mapper in Base.registry.mappers}
    declared = _declared_model_classes()
    assert set(declared) <= mapped
    assert len(metadata.tables) == len(declared)


def test_every_foreign_key_resolves() -> None:
    """The failure this whole file exists to prevent, asserted directly."""
    for table in metadata.tables.values():
        for fk in table.foreign_keys:
            assert fk.column is not None, f"{table.name}.{fk.parent.name}"


def test_naming_convention_is_applied_to_every_constraint() -> None:
    """Deterministic names, or a constraint gets dropped under one name and
    recreated under another on the next machine."""
    for table in metadata.tables.values():
        for constraint in table.constraints:
            assert constraint.name, f"{table.name}: unnamed {type(constraint).__name__}"
        for index in table.indexes:
            assert index.name, table.name


def test_no_float_column_anywhere() -> None:
    """§10: no ``float`` in a persisted column, on any table.

    These quantities are compared against thresholds on three platforms and
    float rounds differently on each.
    """
    offenders = [
        f"{table.name}.{column.name}"
        for table in metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, sa.Float | sa.REAL | sa.DOUBLE_PRECISION)
    ]
    assert offenders == []


def test_every_datetime_column_is_timezone_aware() -> None:
    """§6: all DB timestamps are ``timestamptz``; date-only values use ``Date``."""
    naive = [
        f"{table.name}.{column.name}"
        for table in metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, sa.DateTime) and not column.type.timezone
    ]
    assert naive == []


def test_every_column_documents_itself() -> None:
    """§10: every column says where its value comes from and why it exists."""
    undocumented = [
        f"{table.name}.{column.name}"
        for table in metadata.tables.values()
        for column in table.columns
        if not column.doc
    ]
    assert undocumented == []


def test_every_entry_point_imports_the_registry() -> None:
    """§10: ``main.py``, ``seed.py`` and any future ``worker.py`` import it.

    Not theory — ``seed.py`` shipped without the import and raised
    ``NoReferencedTableError`` on ``users.agent_id`` the first time it ran. A
    process that touches a model without the registry loaded fails on whichever
    foreign key happens to resolve first.
    """
    src = Path(__file__).resolve().parents[1] / "src"
    entry_points = [src / "main.py", src / "seed.py", src / "worker.py"]
    missing = [
        path.name
        for path in entry_points
        if path.exists() and "from src.core import models" not in path.read_text()
    ]
    assert missing == [], f"entry points not importing core.models: {missing}"


#: ``ALTER TYPE <name> ADD VALUE [IF NOT EXISTS] '<value>'`` in a later revision.
#: PostgreSQL cannot remove an enum value, so the migrations only ever add.
ADD_VALUE = re.compile(
    r"ALTER TYPE (\w+) ADD VALUE (?:IF NOT EXISTS )?'([\w]+)'"
)

#: The literal table a revision that creates enum types declares at the top of
#: itself, so the values are in the diff a reviewer reads.
PG_ENUMS_BLOCK = re.compile(
    r"PG_ENUMS: dict\[str, tuple\[str, \.\.\.\]\] = \{(.*?)\n\}", re.S
)


def _enum_values_from_migrations() -> dict[str, list[str]]:
    """What the database's enums hold after every revision has run.

    Every revision's ``PG_ENUMS`` table, merged, plus every ``ADD VALUE``.

    It read the baseline alone twice over: once while there was one revision,
    and again after ``ADD VALUE`` was layered on top of it. Both readings were
    blind to a revision that *creates a type of its own* — 010 does, and the
    baseline is frozen, so the values would have been invisible here and the
    assertion below would have failed for a schema that was entirely correct.
    "The test broke, edit the baseline" is the habit that would then put an
    analysis table back into 001.
    """
    values: dict[str, list[str]] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        block = PG_ENUMS_BLOCK.search(path.read_text(encoding="utf-8"))
        if block is None:
            continue
        namespace: dict[str, object] = {}
        exec("PG_ENUMS = {" + block.group(1) + "\n}", namespace)  # noqa: S102
        for name, items in namespace["PG_ENUMS"].items():
            assert name not in values, (
                f"{path.name} re-declares the enum type {name}. A type is created "
                "by exactly one revision; a later one adds values to it."
            )
            values[name] = list(items)
    assert values, "no revision declares a PG_ENUMS table — the parser is broken"

    for path in sorted(VERSIONS_DIR.glob("*.py")):
        for enum_name, value in ADD_VALUE.findall(path.read_text(encoding="utf-8")):
            assert enum_name in values, f"{path.name} alters unknown enum {enum_name}"
            if value not in values[enum_name]:
                values[enum_name].append(value)
    return values


def test_migration_enum_table_matches_core_enums() -> None:
    """The migrations write the enum values out; the code declares them.

    Two lists on purpose — a migration must keep its meaning after the
    application's enums move on — so this test is what keeps them equal *today*.
    """
    migration_enums = _enum_values_from_migrations()

    assert set(migration_enums) == set(PG_ENUM_TYPES)
    for name, values in migration_enums.items():
        assert sorted(values) == sorted(
            member.value for member in PG_ENUM_TYPES[name]
        ), name


def test_migration_creates_the_extensions_it_declares() -> None:
    """``btree_gist`` missing means the exclusion constraint silently never exists."""
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'EXTENSIONS: tuple[str, ...] = ("btree_gist", "citext")' in source
    assert 'CREATE EXTENSION IF NOT EXISTS "btree_gist"' in source
    assert 'CREATE EXTENSION IF NOT EXISTS "citext"' in source


def test_the_migration_has_no_drop_in_upgrade() -> None:
    """Autogenerate emits spurious DROPs; every revision was read (§10, T102).

    Walks the whole history rather than the baseline alone: the rule is about
    the habit of committing autogenerate's output unread, and that habit is
    most dangerous on the revisions written after the schema had real data in
    it. A deliberate drop is still possible — it goes in its own revision with
    the reason in the docstring, and it fails here first.
    """
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        upgrade = source.split("def upgrade() -> None:")[1].split("def downgrade")[0]
        assert "op.drop_" not in upgrade, path.name
