"""The pure layer imports nothing (SPEC-ANALYTICS §1.1, §9.2).

``tests/test_layering.py::test_rules_modules_are_pure`` only globs ``*/rules.py``,
so the other three files here would have the property and no check on it. This
is that check.

WHY IT IS WORTH A TEST. These four files are the layer a test can exercise with
no database, no session and no vendor key — which is what makes the ported
scoring tests run at all, and what makes a prompt change verifiable in seconds
instead of against a live provider. The property is one careless ``from
src.core.settings import ...`` away from being lost, and nothing else in the
suite would notice.
"""

from __future__ import annotations

import ast
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parents[1]

#: The files that must stay importless. ``entities.py`` is deliberately absent:
#: it derives ``BLOCK_MAX`` from the rubric and therefore imports one
#: same-module constant, which is the lesser evil against two copies of the
#: block maxima (they once diverged 25 vs 15 and drew a 167 % bar).
PURE_MODULES = ("prompt.py", "validator.py", "rubric_default.py", "rules.py")

#: Everything a pure module is allowed to import. Standard library only, and
#: only the parts that cannot reach a socket, a file or a clock.
ALLOWED_ROOTS = frozenset(
    {
        "__future__",
        "collections",
        "dataclasses",
        "enum",
        "json",
        "math",
        "re",
        "typing",
    }
)


def _imported_roots(path: Path) -> set[str]:
    """Every top-level module name this file imports."""
    roots: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # a relative import is still an import of this tree
                roots.add(".")
            elif node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_the_pure_modules_import_nothing_from_the_project() -> None:
    offenders: list[str] = []
    for name in PURE_MODULES:
        for root in sorted(_imported_roots(MODULE_DIR / name)):
            if root in ("src", ".", "sqlalchemy", "fastapi", "pydantic", "structlog"):
                offenders.append(f"{name} imports {root}")
    assert offenders == [], (
        "the pure scoring layer gained a dependency:\n  " + "\n  ".join(offenders)
    )


def test_the_pure_modules_import_only_the_standard_library() -> None:
    """Stricter than the rule above, and the one that actually holds the line.

    A denylist only catches what somebody thought of. This says what is allowed,
    so ``httpx`` or ``google.genai`` appearing in the prompt file fails here
    rather than at the first paid call.
    """
    offenders: list[str] = []
    for name in PURE_MODULES:
        for root in sorted(_imported_roots(MODULE_DIR / name) - ALLOWED_ROOTS):
            offenders.append(f"{name} imports {root}")
    assert offenders == [], (
        "not in the allow-list of a pure module:\n  " + "\n  ".join(offenders)
    )


def test_the_pure_modules_hold_no_session_and_no_orm() -> None:
    """A second reading of the same property, by the names rather than the imports.

    An import can be made local to a function; these strings cannot hide.
    """
    forbidden = ("AsyncSession", "session.", "select(", "Mapped[", "Depends(")
    offenders: list[str] = []
    for name in PURE_MODULES:
        source = (MODULE_DIR / name).read_text(encoding="utf-8")
        for token in forbidden:
            if token in source:
                offenders.append(f"{name}: {token}")
    assert offenders == [], "the pure layer touched the database: " + ", ".join(
        offenders
    )


def test_the_pure_modules_do_not_read_the_clock() -> None:
    """Pure means deterministic: the same input gives the same answer forever.

    A score that depends on when it was computed cannot be re-derived, and
    "why 78?" becomes unanswerable the next day.
    """
    for name in PURE_MODULES:
        source = (MODULE_DIR / name).read_text(encoding="utf-8")
        assert "datetime" not in source, f"{name} reads the clock"
