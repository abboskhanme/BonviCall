"""Structural claims about the pipeline — read from the source, not the database.

Four properties that no behavioural test can see, and every one of them is a
line SPEC-ANALYTICS draws around this module:

* the claim really is ``FOR UPDATE SKIP LOCKED`` (§5) — without ``SKIP
  LOCKED`` the second claimer *waits* instead of stepping over, which looks
  identical in a single-connection test and stalls a worker in production;
* no file here opens a recording by path (§3.3, SPEC §6);
* no broker survived the port (§5);
* nothing under ``api/`` imports the pipeline (§1.1) — everything that costs
  money sits behind the worker.

Synchronous on purpose, which is why they are in a file of their own: this
module carries no ``asyncio`` mark.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import sqlalchemy as sa

from src.core.enums import AnalysisFailure, AnalysisStage
from src.modules.analysis import pipeline as pipeline_module
from src.modules.analysis.entities import RECHECKABLE_SKIPS
from src.modules.analysis.models import CallAnalysisStateModel


def _module_files() -> list[Path]:
    """Every ``.py`` in ``modules/analysis``, tests included."""
    module = Path(pipeline_module.__file__).parent
    return sorted(module.rglob("*.py"))


def _code_only(path: Path) -> str:
    """The file with its comments and its docstrings removed.

    WHY NOT A PLAIN GREP. SPEC-ANALYTICS §10 states these two checks as
    ``grep -rn`` over the module, and a substring grep cannot tell a dependency
    from a sentence about one: it already reports ``redistribute`` in
    ``prompt.py`` and in ``test_scoring.py``, neither of which has anything to
    do with a key-value store. That is the same trap §1.1 describes for
    ``dict.update(``, hit for real. Tokenising first checks the property that
    was meant — nothing here IMPORTS or CALLS any of it — while leaving the
    prose free to explain what was replaced and why.
    """
    import tokenize

    kept: list[str] = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    return " ".join(kept)


def test_the_claim_query_is_for_update_skip_locked() -> None:
    """BonviZvonki's ``CallLock`` is this clause, done by the database.

    Asserted on the SQL rather than only on behaviour: without SKIP LOCKED the
    second claimer *waits* instead of stepping over, which looks identical in a
    single-connection test and stalls the worker in production.
    """
    statement = (
        sa.select(CallAnalysisStateModel.call_id)
        .where(CallAnalysisStateModel.stage == AnalysisStage.QUEUED)
        .order_by(CallAnalysisStateModel.queued_at)
        .limit(4)
        .with_for_update(skip_locked=True)
    )
    rendered = str(statement.compile(dialect=sa.dialects.postgresql.dialect()))
    assert "FOR UPDATE" in rendered and "SKIP LOCKED" in rendered
    # And the production query is that query. Read off the source, because the
    # statement is built inside the function and never returned.
    source = inspect.getsource(pipeline_module.claim)
    assert "with_for_update(skip_locked=True)" in source


def test_nothing_in_this_module_opens_an_audio_file_by_path() -> None:
    """SPEC §6: no module outside ``modules/audio`` may open a recording.

    The review check, run in CI rather than by hand.
    """
    offenders = [
        path.name
        for path in _module_files()
        for token in ("LocalFsAudioStorage", "audio_storage_path")
        if token in _code_only(path)
    ]
    assert offenders == [], (
        "the analysis module reached for a storage path; it receives a "
        f"callable and never a key: {offenders}"
    )


def test_no_broker_survived_the_port() -> None:
    """§5: no Celery, no Redis, no ``CallLock``."""
    offenders: list[str] = []
    for path in _module_files():
        code = _code_only(path).lower()
        for token in ("redis", "celery"):
            if token in code:
                offenders.append(f"{path.name}: {token}")
    assert offenders == [], (
        "a broker came across with the port; the advisory lock, FOR UPDATE "
        f"SKIP LOCKED and the cooldown table replace all of it: {offenders}"
    )


def test_no_router_imports_the_pipeline() -> None:
    """§1.1: everything that spends money is behind ``jobs.py``.

    A router that imported the orchestrator could run a provider call inside an
    HTTP request, which is how a panel times out and the user presses the
    button again — paying twice.
    """
    api = Path(pipeline_module.__file__).parents[3] / "api"
    offenders = [
        str(path.relative_to(api))
        for path in sorted(api.rglob("*.py"))
        if "analysis.pipeline" in path.read_text(encoding="utf-8")
        or "analysis import pipeline" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"a router reached past the service layer: {offenders}"


def test_dispatch_has_a_statement_for_every_recheckable_skip() -> None:
    """A third re-checkable reason must not be added without a statement.

    ``_requeue_recheckable`` handles the two below by name. A new member of
    ``RECHECKABLE_SKIPS`` with nothing to re-check it would be a reason that
    claims to heal itself and never does — which is the silent half of the
    failure §2.6 exists to prevent.
    """
    assert RECHECKABLE_SKIPS == {
        AnalysisFailure.CALL_TYPE_UNKNOWN,
        AnalysisFailure.CALL_TYPE_INTERNAL,
    }
    source = inspect.getsource(pipeline_module._requeue_recheckable)
    for failure in RECHECKABLE_SKIPS:
        assert failure.name in source, f"dispatch never re-checks {failure.value}"
