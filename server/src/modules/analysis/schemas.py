"""Analysis wire schemas (SPEC-ANALYTICS §6.2, §7).

Three panel pages read this module and nothing else reads it: the scored-call
list (§7.3), one call's analysis (§7.4) and the operational queue view (§7.5).
Every field below exists because one of those three renders it.

**Neither response object is a list of rows**, which is why
:class:`CallAnalysisResponse` and :class:`AnalysisStatusResponse` avoid the
``ListResponse`` suffix rather than joining ``test_conformance``'s
``NOT_A_LIST`` set (§6.2). :class:`AnalysisListResponse` *is* a list and
carries ``items`` + ``total`` like every other one.

Three fields are deliberately ``dict``/``str`` rather than a closed type, and
each says why at its declaration: they are JSONB documents written under a
pinned ``rubric_version``, and a read endpoint that validated yesterday's
document against today's enum would answer 500 for a row nobody can repair.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.core.enums import (
    AnalysisFailure,
    AnalysisStage,
    CallDirection,
    CallDisposition,
    CallSentiment,
    CallType,
    TranscriptQuality,
)
from src.modules.analysis.entities import ScoreSummary

# --- The score band, derived and never retyped -------------------------------

#: The four bands the list filters on. They are the panel's vocabulary for a
#: score, and ``ScoreSummary.grade`` is their definition (§1.4).
ScoreBand = Literal["excellent", "good", "average", "poor"]


def _band_of(score: int) -> str:
    """``ScoreSummary.grade`` for a bare number, with the rest of it ignored."""
    return ScoreSummary(
        overall=score,
        blocks={},
        red_flag_count=0,
        confidence_pct=0,
        needs_review=False,
    ).grade


#: ``band -> (lowest score in it, highest)``, **computed from**
#: ``ScoreSummary.grade`` at import rather than written out.
#
# The thresholds 85/70/55 live in ``entities.ScoreSummary`` and the panel
# colours a row from that property. Typing them a second time here to build a
# SQL ``BETWEEN`` is precisely the mistake ``BLOCK_MAX`` records — two copies of
# one number, diverged, and a 167 % bar drawn in front of a manager. Scanning
# 0..100 once at import costs nothing and cannot drift.
SCORE_BAND_RANGE: dict[str, tuple[int, int]] = {
    band: (
        min(score for score in range(101) if _band_of(score) == band),
        max(score for score in range(101) if _band_of(score) == band),
    )
    for band in {_band_of(score) for score in range(101)}
}


# --- The call's own facts, so the page needs one request ---------------------


class AnalysisCallHeader(BaseModel):
    """Which conversation this is (§7.4).

    Carried in the analysis response on purpose: the detail page must say
    *whose call, when, with whom and how long* without sending the reader to
    the calls section to find out. The analysis section is a section of its own
    (§7), so a link there is a navigation away from the page, not a tooltip.

    ``agent_name`` is resolved server-side for the same reason
    ``CallResponse`` resolves it — a name lookup per row in the browser is the
    N+1 problem with a different owner.
    """

    call_id: uuid.UUID
    started_at: datetime = Field(
        description="When the conversation happened. The list sorts on this (§7.3)."
    )
    agent_id: uuid.UUID
    agent_name: str
    remote_number: str | None = Field(
        description="As the device saw it. NULL when the caller withheld it."
    )
    duration_sec: int
    direction: CallDirection
    disposition: CallDisposition
    call_type: CallType = Field(
        description=(
            "Why a call was or was not scored: only `external` is scored, and "
            "`unknown` means the line directory cannot tell yet (§2.6)."
        )
    )


# --- The pipeline's own bookkeeping ------------------------------------------


class AnalysisStateResponse(BaseModel):
    """``call_analysis_state`` as the panel reads it (§6.2).

    Also the whole answer to ``POST /analysis/calls/{id}``: queueing returns
    the state and nothing else, so a first press and a re-press are
    indistinguishable (§5's shape, applied to a panel write).
    """

    model_config = ConfigDict(from_attributes=True)

    stage: AnalysisStage
    attempts: int
    asr_calls: int = Field(
        description="Requests that reached a provider, i.e. that cost money."
    )
    llm_calls: int
    cost_micro_usd: int = Field(
        description=(
            "Measured units x the admin-entered price. 0 also means **not "
            "priced** — see `AnalysisMonthResponse.priced` (§11.1)."
        )
    )
    queued_at: datetime
    last_run_at: datetime | None
    transcribed_at: datetime | None
    scored_at: datetime | None
    failure_code: AnalysisFailure | None = Field(
        description=(
            "Why the call stopped. Present exactly when the stage is `failed` "
            "or `skipped` — a database CHECK, not a habit. The Uzbek headline "
            "is keyed off this in the panel's uz.json."
        )
    )
    failure_stage: str | None = Field(
        description="`transcribe` or `score` — which half spent money before stopping."
    )
    failure_detail: str | None = Field(
        description=(
            "The provider's own message, redacted. Technical English beside "
            "the code, never the sentence a user reads."
        )
    )


# --- The transcript ----------------------------------------------------------


class TranscriptResponse(BaseModel):
    """One call's transcript (§7.4's transcript block).

    ``audio_bytes`` and ``asr_ms`` are stored but not returned: they are cost
    measurement (§11.1), they belong to the month's figures on the status page,
    and a per-call byte count is not something the detail page renders.
    """

    model_config = ConfigDict(from_attributes=True)

    text: str = Field(
        description=(
            "Verbatim, in the '[MM:SS] SPEAKER_n: ...' form. The timestamps are "
            "not decoration — phase 2's click-a-line-to-seek reads them."
        )
    )
    language: str | None = Field(
        description="What was asked of the provider, or NULL when it detected it."
    )
    provider: str
    model: str
    word_count: int = Field(
        description=(
            "Real spoken words, service tokens stripped (`rules.count_words`). "
            "Stored so the review rule and the panel agree on one number."
        )
    )
    audio_duration_ms: int | None
    transcribed_at: datetime


# --- The score ---------------------------------------------------------------


class RedFlagOut(BaseModel):
    """One incident, with the evidence for it.

    Every incident is returned, including repeats of one type: a manager
    confirming an accusation needs the time and the quote of both. ``counted``
    marks the one that actually moved the score — the penalty is charged once
    per type, and the array's penalties sum to the total applied.
    """

    type: str = Field(
        description=(
            "The rubric's red-flag key. A string and not a closed enum on "
            "purpose: the rubric is versioned (`rubric_version`) and phase 2 "
            "reads it from a row, so a score written under v1 must stay "
            "readable after v2 adds a flag. The panel renders an unknown key "
            "as the key."
        )
    )
    label: str
    severity: str
    timestamp: str | None = Field(
        description="'[MM:SS]' into the recording, when the model located it."
    )
    quote: str
    penalty: int
    counted: bool


class OutcomeSignalOut(BaseModel):
    """What the conversation ended in, when it said so."""

    type: str = Field(description="The rubric's outcome vocabulary; see `RedFlagOut.type`.")
    products_mentioned: list[str]
    quantity_mentioned: int | None
    confidence: float = Field(
        description=(
            "The model's own 0..1 confidence in this signal. A float inside a "
            "JSONB document, which §10's no-float rule is about columns."
        )
    )
    evidence: str | None


class ScoreResponse(BaseModel):
    """One call's verdict and the evidence for it (§7.4's score block)."""

    model_config = ConfigDict(from_attributes=True)

    overall_score: int = Field(description="0-100, recomputed by the validator.")
    blocks: dict[str, int] = Field(
        description=(
            "FLAT {block_key: points}, already normalised to the criteria that "
            "applied. **Never recomputed in the panel.** Keyed by the rubric's "
            "own block keys, so it is a map rather than four named fields: a "
            "rubric change must not need a server release to render."
        )
    )
    block_details: dict[str, Any] = Field(
        description=(
            "{blocks: {...evidence per criterion...}, meta: {...}} — how the "
            "number was reached, so 'why 78?' is answerable without paying to "
            "re-run. `meta.applicable_max` is what lets a header read '68 / 75' "
            "honestly when criteria did not apply (§7.4)."
        )
    )
    red_flags: list[RedFlagOut]
    outcome_signal: OutcomeSignalOut | None
    sentiment: CallSentiment | None
    transcript_quality: TranscriptQuality
    coaching_note: str | None
    confidence_pct: int
    needs_review: bool
    review_reasons: list[dict[str, Any]] = Field(
        description=(
            "[{code, params}]. The panel renders the sentence from uz.json, so "
            "the column holds a machine reason and never display copy (§1.6)."
        )
    )
    rubric_version: str = Field(
        description="Stamped per score: a rubric change never re-bases old numbers."
    )
    provider: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_micro_usd: int | None = Field(
        description="NULL while the price is unset — null means not priced, never free."
    )
    scored_at: datetime


# --- GET /analysis/calls/{call_id} -------------------------------------------


class CallAnalysisResponse(BaseModel):
    """Everything the detail page needs, in one request (§6.2, §7.4).

    ``state``, ``transcript`` and ``score`` are **independently nullable**. A
    call the pipeline has never touched answers 200 with all three null — not
    404, because the page must be able to tell "not analysed" from "no such
    call", and only one of those two is worth an error.

    ``enabled`` is repeated here rather than left to ``/analysis/status`` for
    the same reason: deciding what to render must not cost two round trips to
    learn a boolean.
    """

    call_id: uuid.UUID
    enabled: bool = Field(
        description=(
            "`analysis.enabled`. False plus a null state means the page says "
            "'o'chirilgan' and offers no button — pressing it would 409 (§7.4)."
        )
    )
    call: AnalysisCallHeader
    state: AnalysisStateResponse | None
    transcript: TranscriptResponse | None
    score: ScoreResponse | None


class QueueCallRequest(BaseModel):
    """``POST /analysis/calls/{call_id}`` — the panel's button (§6.2)."""

    force: bool = Field(
        default=False,
        description=(
            "Clear the existing transcript and score so both are recomputed. "
            "**The only way to spend money twice on one call**, which is why "
            "it is a body field and not a query parameter somebody pastes."
        ),
    )


# --- GET /analysis/calls -----------------------------------------------------


class AnalysisListItem(BaseModel):
    """One row of the scored-call list (§7.3).

    The columns §7.3 names and nothing more. No transcript text: a list of
    fifty conversations is not a place to ship fifty transcripts, and the
    detail page is one click away.
    """

    call: AnalysisCallHeader
    stage: AnalysisStage
    failure_code: AnalysisFailure | None
    overall_score: int | None = Field(
        description="NULL until the call is scored — a queued row still has a place in the list."
    )
    needs_review: bool
    red_flag_types: list[str] = Field(
        description=(
            "Sorted and de-duplicated, for the chips. The quotes stay on the "
            "detail page: a customer's words do not belong in a list payload."
        )
    )
    scored_at: datetime | None


class AnalysisListResponse(BaseModel):
    """A cursor page of analysed calls, newest conversation first (§7.3)."""

    items: list[AnalysisListItem]
    next_cursor: str | None
    has_more: bool
    total: int | None = Field(
        default=None,
        description="Counted only when asked, exactly as /calls does it.",
    )


class AnalysisFilters(BaseModel):
    """§7.3's filter set: date range, agent, stage, score band."""

    agent_id: list[uuid.UUID] | None = None
    stage: list[AnalysisStage] | None = None
    score_band: list[ScoreBand] | None = Field(
        default=None,
        description=(
            "One or more of excellent/good/average/poor. Translated to a score "
            "range by SCORE_BAND_RANGE, which is derived from the same property "
            "the panel colours from. Typed as the four names so an unknown band "
            "is refused here rather than returning a silently empty page — "
            "which would read as 'no calls scored well'."
        ),
    )
    needs_review: bool | None = Field(
        default=None, description="The review queue is this flag (§1.4)."
    )
    date_from: date | None = Field(
        default=None, description="Asia/Tashkent calendar date, inclusive (D-10)."
    )
    date_to: date | None = Field(
        default=None, description="Asia/Tashkent calendar date, inclusive."
    )


# --- GET /analysis/status ----------------------------------------------------


class AnalysisStageCounts(BaseModel):
    """Calls per stage. One field per ``AnalysisStage`` member, always present.

    A fixed object rather than a map, so a stage with nothing in it is a
    visible zero instead of an absent key the panel has to default. The six
    fields are pinned against the enum by a test.
    """

    queued: int = 0
    transcribing: int = 0
    scoring: int = 0
    completed: int = 0
    skipped: int = Field(
        default=0,
        description="**Not a failure** and the panel must not paint it as one (§2.4).",
    )
    failed: int = 0


class NotAnalysableCount(BaseModel):
    """One reason calls are being skipped, and how many (§7.5)."""

    code: AnalysisFailure
    calls: int


class ProviderCooldownResponse(BaseModel):
    """A role sitting out a quota or an outage.

    The first thing an operator needs when the queue goes quiet, which is why
    the cooldown is a table and not a cache key with a TTL (§1.3).
    """

    role: str = Field(description="asr | llm. One cooldown per role.")
    seconds_left: int
    reason_code: AnalysisFailure = Field(
        description="A daily quota and a 503 read very differently."
    )
    started_at: datetime
    until_at: datetime
    detail: str | None


class AnalysisFailureRow(BaseModel):
    """One recent failure, with enough to act on it (§7.5)."""

    call_id: uuid.UUID
    started_at: datetime
    stage: str | None = Field(description="Which half was running: transcribe | score.")
    code: AnalysisFailure
    detail: str | None
    attempts: int
    last_run_at: datetime | None


class AnalysisMonthResponse(BaseModel):
    """This Tashkent calendar month's spend against the caps (§4.5, §11.1).

    Tashkent and not UTC because the person reading the bill lives there: a
    month turning over at 05:00 local would put the first five hours of every
    month into the previous one's cap.
    """

    date_from: date = Field(
        description=(
            "First day of the current Asia/Tashkent month. Named like every "
            "other window in this API; §6.2 sketched it as `from`, which is not "
            "a Python identifier."
        )
    )
    calls: int = Field(description="State rows that reached `completed` this month.")
    audio_minutes: int = Field(description="Measured ASR input — the billing unit.")
    prompt_tokens: int
    completion_tokens: int
    cost_micro_usd: int
    priced: bool = Field(
        description=(
            "Whether any vendor price has been entered. **False is what stops "
            "the panel rendering $0.00 and implying the feature is free** — a "
            "cost of zero because nobody typed a price is not a free feature."
        )
    )
    cap_micro_usd: int
    cap_calls: int = Field(
        description=(
            "The cap that actually protects the account until a price is "
            "entered, because an unpriced month can never reach the money one."
        )
    )


class AnalysisStatusResponse(BaseModel):
    """The operational view: what is waiting, what broke, what it cost (§7.5).

    This is where an admin answers "why has nothing been scored since
    Tuesday". It exists in phase 1 because without it that question has no
    answer short of opening the database.
    """

    enabled: bool
    stages: AnalysisStageCounts
    waiting_retry: int = Field(
        description=(
            "Failed on a transient code and inside the nightly retry's reach, "
            "so it will be tried again by itself. Separate from `stages.failed` "
            "on purpose: one of them needs a person and the other does not."
        )
    )
    not_analysable: list[NotAnalysableCount] = Field(
        description=(
            "Skips by reason, so '412 calls are waiting on the line directory' "
            "is visible rather than silent (§2.6)."
        )
    )
    cooldowns: list[ProviderCooldownResponse] = Field(
        description="Only the roles currently sitting out; empty is the normal state."
    )
    month: AnalysisMonthResponse
    recent_failures: list[AnalysisFailureRow] = Field(
        description="Newest first, capped at 20 server-side. Not a paged list (§6.2)."
    )
