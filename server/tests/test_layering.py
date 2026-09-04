"""The dependency arrows, checked by parsing rather than by grepping (§2, §2.1).

The greps in CONVENTIONS.md §2 are what a reviewer runs by hand. These are the
same rules with the ambiguity removed: "only FK targets" is decided against the
actual foreign keys in ``Base.metadata``, not against somebody's memory of them.
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.core.models import metadata
from src.core.reads import CROSS_MODULE_READS

MODULES_DIR = Path(__file__).resolve().parents[1] / "src" / "modules"
CORE_DIR = Path(__file__).resolve().parents[1] / "src" / "core"

#: ``core/models.py`` is the ORM registry and §10 requires it to import every
#: model. It is the single, named exception to "core imports no module".
CORE_REGISTRY = CORE_DIR / "models.py"


def _module_of_table() -> dict[str, str]:
    """``registered_numbers`` -> ``numbers``, read off the model classes."""
    owners: dict[str, str] = {}
    for path in sorted(MODULES_DIR.glob("*/models.py")):
        module = path.parent.name
        source = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(source):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "__tablename__"
                for target in node.targets
            ):
                if isinstance(node.value, ast.Constant):
                    owners[node.value.value] = module
    return owners


def _model_classes() -> dict[str, tuple[str, str]]:
    """``CallModel`` -> (module, table)."""
    classes: dict[str, tuple[str, str]] = {}
    for path in sorted(MODULES_DIR.glob("*/models.py")):
        module = path.parent.name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            table = next(
                (
                    child.value.value
                    for child in node.body
                    if isinstance(child, ast.Assign)
                    and any(
                        isinstance(t, ast.Name) and t.id == "__tablename__"
                        for t in child.targets
                    )
                    and isinstance(child.value, ast.Constant)
                ),
                None,
            )
            if table:
                classes[node.name] = (module, table)
    return classes


def _fk_target_modules(module: str, owners: dict[str, str]) -> set[str]:
    """Every module this one has a foreign key into."""
    targets: set[str] = set()
    for table in metadata.tables.values():
        if owners.get(table.name) != module:
            continue
        for fk in table.foreign_keys:
            referred = fk.column.table.name
            owner = owners.get(referred)
            if owner and owner != module:
                targets.add(owner)
    return targets


def _model_imports(path: Path) -> set[tuple[str, str]]:
    """``{(module, ClassName)}`` for every ``from src.modules.X.models import Y``."""
    found: set[tuple[str, str]] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        parts = node.module.split(".")
        if parts[:2] == ["src", "modules"] and parts[-1] == "models":
            for alias in node.names:
                found.add((parts[2], alias.name))
    return found


def test_core_imports_no_module_except_the_registry() -> None:
    """§2: the arrows point one way, or ``core`` depends on a module again."""
    offenders = [
        path.name
        for path in sorted(CORE_DIR.glob("*.py"))
        if path != CORE_REGISTRY and "from src.modules" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"core/ imports a module: {offenders}. BonviZvonki's core imported "
        "modules/users and the arrows pointed both ways. core/models.py is the "
        "only exception, because §10 requires the registry to import every model."
    )


def test_a_module_only_imports_models_it_has_a_foreign_key_into() -> None:
    """§2: "only same-module, FK targets, and the modules in core/reads.py".

    Decided against the actual foreign keys rather than against memory: if
    ``calls`` gains a column referencing ``commands``, this widens by itself,
    and if it loses one, the stale import fails here.
    """
    owners = _module_of_table()
    classes = _model_classes()
    violations: list[str] = []
    for path in sorted(MODULES_DIR.glob("*/*.py")):
        module = path.parent.name
        if path.name in ("models.py", "__init__.py") or module in CROSS_MODULE_READS:
            continue
        allowed = _fk_target_modules(module, owners) | {module}
        for imported_module, class_name in sorted(_model_imports(path)):
            if imported_module not in allowed:
                violations.append(
                    f"{module}/{path.name} imports {imported_module}.{class_name} "
                    f"(no foreign key into {imported_module})"
                )
            elif class_name in classes and classes[class_name][0] != imported_module:
                violations.append(f"{module}/{path.name}: {class_name} is not in {imported_module}")
    assert violations == [], (
        "call the other module's service instead:\n  " + "\n  ".join(violations)
    )


def test_cross_module_reads_declared() -> None:
    """§2.1: a holder of the exception owns no table and reads only its list."""
    owners = _module_of_table()
    for module, allowed in CROSS_MODULE_READS.items():
        module_dir = MODULES_DIR / module
        if not module_dir.exists():
            continue  # the module is not built yet; the declaration waits for it
        assert not (module_dir / "models.py").exists(), (
            f"{module} gained a models.py and therefore loses the §2.1 exception"
        )
        assert module not in owners.values()
        for path in sorted(module_dir.glob("*.py")):
            for imported_module, class_name in sorted(_model_imports(path)):
                assert f"{imported_module}.{class_name}" in allowed, (
                    f"{module} reads {imported_module}.{class_name}, which is not "
                    "in its core/reads.py entry"
                )


def test_cross_module_read_holders_never_write() -> None:
    """§2.1 rule 2: a module that owns nothing has nothing to write."""
    forbidden = ("session.add", "session.delete", "insert(", "update(", "delete(")
    for module in CROSS_MODULE_READS:
        module_dir = MODULES_DIR / module
        if not module_dir.exists():
            continue
        for path in sorted(module_dir.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for token in forbidden:
                assert token not in source, f"{module}/{path.name} writes: {token}"


def test_cross_module_read_holders_never_select_a_bare_entity() -> None:
    """§2.1 rule 3: aggregates and projections only, so nothing can leak.

    ``select(CallModel)`` loads an ORM entity that could then be handed out of
    the module; ``select(CallModel.id, func.count())`` cannot.
    """
    import re

    pattern = re.compile(r"select\(\s*[A-Z][A-Za-z]*Model\s*\)")
    for module in CROSS_MODULE_READS:
        module_dir = MODULES_DIR / module
        if not module_dir.exists():
            continue
        for path in sorted(module_dir.glob("*.py")):
            assert not pattern.search(path.read_text(encoding="utf-8")), (
                f"{module}/{path.name} selects a bare entity; project columns instead"
            )


def test_no_router_contains_sql_or_a_commit() -> None:
    """§2's first two checks, so they run in CI and not only by hand."""
    import re

    api_dir = Path(__file__).resolve().parents[1] / "src" / "api"
    # Word-bounded: a substring search matches "landing_context(" for "text("
    # and turns a real check into a false alarm nobody trusts.
    patterns = {
        "select(": re.compile(r"\bselect\("),
        "session.execute": re.compile(r"\bsession\.execute\b"),
        "text(": re.compile(r"\btext\("),
        ".commit()": re.compile(r"\.commit\(\)"),
    }
    offenders: list[str] = []
    for path in sorted(api_dir.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for label, pattern in patterns.items():
            if pattern.search(source):
                offenders.append(f"{path.name}: {label}")
    assert offenders == [], (
        "a router is doing the service layer's job: " + ", ".join(offenders)
    )


def test_nothing_binds_the_clock_function_directly() -> None:
    """``from src.core import clock`` — never ``from src.core.clock import now``.

    Not style. ``frozen_clock`` patches ``core.clock.now``, and a module that
    has already bound the name keeps the real one: three silence-detection
    tests passed against the wall clock before this was fixed, which means they
    were testing nothing.
    """
    src = Path(__file__).resolve().parents[1] / "src"
    offenders = [
        str(path.relative_to(src))
        for path in sorted(src.rglob("*.py"))
        if path.name != "clock.py"
        and "from src.core.clock import now" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"these bind clock.now and are unpatchable by frozen_clock: {offenders}"
    )


def test_rules_modules_are_pure() -> None:
    """§2: no framework, no ORM, no project imports in a ``rules.py``."""
    for path in sorted(MODULES_DIR.glob("*/rules.py")):
        source = path.read_text(encoding="utf-8")
        for token in ("fastapi", "sqlalchemy", "import src"):
            assert token not in source, f"{path.parent.name}/rules.py imports {token}"
