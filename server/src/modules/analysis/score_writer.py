"""Writing one score to the database — idempotent.

``call_scores.call_id`` is UNIQUE: one score per call. A job that runs a second
time creates NO second row — it overwrites the one that is there, which is what
makes re-running safe and what makes "did this cost money twice?" answerable
from ``call_analysis_state.llm_calls`` rather than from a row count.

The two payload shapes below are load-bearing and their warnings are not
decoration — both describe a page that went blank in production.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.enums import CallSentiment, TranscriptQuality
from src.modules.analysis.models import CallScoreModel
from src.modules.analysis.rules import ReviewDecision
from src.modules.analysis.validator import ScoreDraft


async def existing_score(session: AsyncSession, call_id: UUID) -> CallScoreModel | None:
    return (
        await session.execute(
            select(CallScoreModel).where(CallScoreModel.call_id == call_id)
        )
    ).scalar_one_or_none()


async def delete_score(session: AsyncSession, call_id: UUID) -> bool:
    """Delete the score. ``True`` means a row was there and is gone.

    WHY THIS FUNCTION EXISTS. A call's type can become known later: this was not
    a sales conversation, so it must not be scored against a sales rubric. But
    it may have been scored BEFORE — when the line directory was still empty and
    ``classify_call_type`` returned ``unknown``, or under a different type.

    Leaving the old score puts the system at odds with itself: the screen says
    "not scored", while the analytics still counts the number and keeps dragging
    the employee's average down. A score is derived data and can be recomputed;
    a false figure is one nobody notices.
    """
    row = await existing_score(session, call_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def save_score(
    session: AsyncSession,
    *,
    call_id: UUID,
    draft: ScoreDraft,
    review: ReviewDecision,
    provider: str,
    model: str,
    rubric_version: str,
    llm_calls: int = 1,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cost_micro_usd: int | None = None,
) -> CallScoreModel:
    """Write the score. An existing row is overwritten (a re-score).

    ``cost_micro_usd=None`` means **not priced** and never "free" (§11.1): the
    admin has not entered a price for this model, so the call cost something
    nobody has measured yet.
    """
    row = await existing_score(session, call_id)
    if row is None:
        row = CallScoreModel(call_id=call_id)
        session.add(row)

    row.provider = provider[:32]
    row.model = model[:64]
    row.rubric_version = rubric_version[:16]
    row.overall_score = draft.overall
    row.blocks = _blocks_payload(draft)
    row.block_details = _block_details_payload(draft)
    row.red_flags = draft.red_flags
    row.outcome_signal = draft.outcome_signal
    row.sentiment = CallSentiment(draft.sentiment)
    row.transcript_quality = TranscriptQuality(draft.transcript_quality)
    row.coaching_note = draft.coaching_note
    row.confidence_pct = draft.confidence_pct
    row.needs_review = review.needs_review
    row.review_reasons = review.reasons
    row.llm_calls = llm_calls
    row.prompt_tokens = prompt_tokens
    row.completion_tokens = completion_tokens
    row.cost_micro_usd = cost_micro_usd
    row.scored_at = clock.now()

    await session.flush()
    return row


def _blocks_payload(draft: ScoreDraft) -> dict[str, int]:
    """``call_scores.blocks`` — a FLAT ``{block_key: score}``.

    Its consumers expect exactly this shape and cannot survive another one: the
    analytics cut runs ``float(value)`` over every value (an object gives
    ``TypeError`` -> 500), and the call detail page draws the value directly (an
    object and React does not open the page at all).

    So nothing nested and no extra key — no ``_meta`` in particular, which once
    appeared as a fifth "block" in the cut. The evidence and the workings live
    in their own column, ``block_details``.

    WARNING: the value is the figure computed WITHIN the applied criteria
    (``max x earned / applicable``), not the raw sum. A block that applies not at
    all is absent from this dict entirely: drawing it as 0 on the radar chart
    would make the employee look at fault.
    """
    return dict(draft.block_scores)


def _block_details_payload(draft: ScoreDraft) -> dict[str, Any]:
    """``call_scores.block_details`` — the evidence and the workings.

    ``meta`` is kept so that "why 78?" can be answered later without recomputing
    the penalties and the totals — or paying to re-run the model.

    WARNING: the ``applicable_*`` fields belong here too. The call page needs
    exactly those to show "68 / 75 points (3 criteria do not apply to this
    conversation)". Without them a manager adds up the blocks on the screen and
    finds they do not match the overall score.
    """
    return {
        "blocks": draft.blocks,
        "meta": {
            "blocks_total": draft.blocks_total,
            "applicable_max": draft.applicable_max,
            "applicable_points": draft.applicable_points,
            "earned_points": draft.earned_points,
            "na_criteria": draft.na_criteria,
            "na_over_budget": draft.na_over_budget,
            # Discrepancies that did not affect the score — so "why 60?" can
            # still be answered afterwards
            "warnings": draft.warnings,
            "scenario": draft.scenario,
            "penalty_total": draft.penalty_total,
            "zeroed_by_red_flag": draft.zeroed,
            "language_detected": draft.language_detected,
            "transcript_quality": draft.transcript_quality,
        },
    }
