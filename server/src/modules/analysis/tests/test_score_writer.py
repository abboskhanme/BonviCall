"""Writing one score — the shape of the row and the idempotency of the write.

The only tests in task 5 that touch a database, and they are here rather than
with the pipeline because the claims are about this file: ``call_scores.call_id``
is UNIQUE, so a second run overwrites rather than inserts, and ``blocks`` stays
flat all the way into JSONB.

Both payload shapes below have a production failure behind them: a nested value
in ``blocks`` 500s the analytics cut and blanks the React call page.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from src.core.enums import CallSentiment, TranscriptQuality
from src.modules.analysis.models import CallScoreModel
from src.modules.analysis.rubric_default import DEFAULT_RUBRIC, RUBRIC_VERSION
from src.modules.analysis.rules import ReviewReason, decide
from src.modules.analysis.score_writer import (
    delete_score,
    existing_score,
    save_score,
)
from src.modules.analysis.tests.stubs import build_payload
from src.modules.analysis.validator import validate

pytestmark = pytest.mark.asyncio

BLOCKS = DEFAULT_RUBRIC["blocks"]
FLAGS = DEFAULT_RUBRIC["red_flags"]


def _draft(**kwargs):
    raw = json.dumps(build_payload(BLOCKS, FLAGS, **kwargs), ensure_ascii=False)
    return validate(raw, rubric_blocks=BLOCKS, rubric_red_flags=FLAGS)


def _review(draft):
    return decide(
        confidence_pct=draft.confidence_pct,
        transcript_quality=draft.transcript_quality,
        transcript_text=" ".join(["so'z"] * 200),
        duration_sec=180,
        red_flag_types=[f["type"] for f in draft.red_flags],
        ai_score=draft.overall,
        na_over_budget=draft.na_over_budget,
    )


async def _save(db, call, draft, **overrides):
    return await save_score(
        db,
        call_id=call.id,
        draft=draft,
        review=_review(draft),
        **{
            "provider": "gemini",
            "model": "gemini-3.1-flash-lite",
            "rubric_version": RUBRIC_VERSION,
            **overrides,
        },
    )


async def test_a_score_is_written_with_every_column_the_panel_reads(
    db, call_factory
) -> None:
    call = await call_factory()
    draft = _draft(seed=1)

    row = await _save(db, call, draft, prompt_tokens=7_200, completion_tokens=900)

    assert row.overall_score == draft.overall
    assert row.confidence_pct == draft.confidence_pct
    assert row.rubric_version == "v1"
    assert row.provider == "gemini"
    assert row.transcript_quality == TranscriptQuality(draft.transcript_quality)
    assert row.sentiment == CallSentiment(draft.sentiment)
    assert row.prompt_tokens == 7_200
    assert row.scored_at is not None


async def test_the_blocks_column_stays_flat(db, call_factory) -> None:
    """Read back through JSONB, not just as it was assigned.

    The analytics cut casts every value with ``float()`` and the call page draws
    it directly; an object in either place is a 500 and a blank screen.
    """
    call = await call_factory()

    await _save(db, call, _draft(seed=2))
    await db.commit()
    row = await existing_score(db, call.id)

    assert set(row.blocks) == {b["key"] for b in BLOCKS}
    assert all(isinstance(v, int) for v in row.blocks.values())
    assert "_meta" not in row.blocks
    # The evidence lives in its own column and has not leaked
    assert set(row.block_details) == {"blocks", "meta"}


async def test_writing_twice_updates_one_row(db, call_factory) -> None:
    """``call_id`` is UNIQUE — this is what makes re-running a job safe."""
    call = await call_factory()

    first = await _save(db, call, _draft(seed=3))
    # Read off before the second write: the session's identity map hands back
    # the SAME object, so holding a reference would silently compare a value
    # with itself and the test would pass whatever the writer did.
    first_id, first_score = first.id, first.overall_score

    second = await _save(db, call, _draft(seed=4, ratio=0.4))

    count = await db.scalar(
        select(func.count())
        .select_from(CallScoreModel)
        .where(CallScoreModel.call_id == call.id)
    )
    assert count == 1
    assert second.id == first_id, "the same row, updated"
    assert second.overall_score != first_score


async def test_a_red_flag_puts_the_score_in_the_review_queue(
    db, call_factory
) -> None:
    call = await call_factory()
    draft = _draft(seed=5, red_flags=("shouting",))

    row = await _save(db, call, draft)

    assert row.needs_review is True
    assert [r["code"] for r in row.review_reasons] == [ReviewReason.RED_FLAG]
    assert row.review_reasons[0]["params"] == {"types": ["shouting"]}


async def test_an_unpriced_score_is_null_and_not_zero(db, call_factory) -> None:
    """NULL means "not priced". Zero would read as "this call was free"."""
    call = await call_factory()

    row = await _save(db, call, _draft(seed=6))

    assert row.cost_micro_usd is None


async def test_deleting_a_score_is_safe_to_repeat(db, call_factory) -> None:
    """Called when a call turns out not to be scorable after all.

    Leaving the old row puts the product at odds with itself: the screen says
    "not scored" while the analytics keeps counting the number against the
    employee's average.
    """
    call = await call_factory()
    await _save(db, call, _draft(seed=7))

    assert await delete_score(db, call.id) is True
    assert await delete_score(db, call.id) is False
    assert await existing_score(db, call.id) is None
