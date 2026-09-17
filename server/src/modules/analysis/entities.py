"""Scoring value objects — the names the rubric's output is spoken in.

Nothing here is a database column. ``ScoreBlock`` and ``RedFlagType`` are the
keys inside the ``blocks`` and ``red_flags`` JSONB documents, which is why they
are not in ``core/enums.py``: that file is the catalogue of PostgreSQL enum
types (CONVENTIONS.md §10), and a JSONB key is not one. ``Sentiment`` **did**
become a column and therefore moved — use ``core.enums.CallSentiment``.

The labels stay out of here on purpose. BonviZvonki carried ``BLOCK_LABEL_UZ``
and ``RED_FLAG_LABEL_UZ`` beside these enums; in BonviCall the panel's
``uz.json`` owns every string a person reads (CONVENTIONS.md §14).

SPEC-ANALYTICS §1.4 and §1.3 — the second half of this file is the pipeline's
own vocabulary: the two stages, their outcomes, the internal exceptions and the
two failure sets the jobs filter on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from src.core.enums import AnalysisFailure, AnalysisStage
from src.modules.analysis.rubric_default import DEFAULT_RUBRIC


class ScoreBlock(StrEnum):
    """The four blocks of the rubric, as they appear in ``call_scores.blocks``."""

    SCRIPT = "script"  # A - script and structure
    COMMUNICATION = "communication"  # B - conduct
    RESOLUTION = "resolution"  # C - resolving the problem
    SALES_SKILL = "sales_skill"  # D - selling


#: Block maxima are **derived from the rubric**, never written out by hand.
#
# These values were once typed a second time and the two copies diverged:
# ``sales_skill`` was 15 in the code and 25 in the rubric. The analytics cut
# then drew 25/15 = 167 % and the bar left the chart, in front of a manager.
# One source, or none.
BLOCK_MAX: dict[ScoreBlock, int] = {
    ScoreBlock(block["key"]): int(block["max"]) for block in DEFAULT_RUBRIC["blocks"]
}


class RedFlagType(StrEnum):
    """Serious breaches. Each one subtracts, and one of them zeroes the score."""

    PROFANITY = "profanity"  # abuse or swearing -> score 0
    SHOUTING = "shouting"  # -20
    UNREALISTIC_PROMISE = "unrealistic_promise"  # -15
    BADMOUTHING = "badmouthing"  # the company or a colleague -> -15
    OFF_POLICY_DEAL = "off_policy_deal"  # a private deal outside the price list -> -25
    IGNORED_COMPLAINT = "ignored_complaint"  # -10


#: Mirrors the rubric's ``red_flags`` table. The **validator reads the rubric**,
#: not this dict — this exists for code that needs the number without loading
#: the rubric, and ``tests/test_scoring.py`` asserts the two agree.
RED_FLAG_PENALTY: dict[RedFlagType, int] = {
    RedFlagType.PROFANITY: -100,  # in practice: the overall score becomes 0
    RedFlagType.SHOUTING: -20,
    RedFlagType.UNREALISTIC_PROMISE: -15,
    RedFlagType.BADMOUTHING: -15,
    RedFlagType.OFF_POLICY_DEAL: -25,
    RedFlagType.IGNORED_COMPLAINT: -10,
}


@dataclass(slots=True)
class ScoreSummary:
    """One call's final score, as the panel reads it."""

    overall: int
    blocks: dict[str, int]
    red_flag_count: int
    confidence_pct: int
    needs_review: bool

    @property
    def grade(self) -> str:
        """The score as a band. The panel colours from this, never from the number."""
        if self.overall >= 85:
            return "excellent"
        if self.overall >= 70:
            return "good"
        if self.overall >= 55:
            return "average"
        return "poor"


# ===========================================================================
#  The pipeline half (SPEC-ANALYTICS §1.3, §2.4)
# ===========================================================================
#
# Two stages, both idempotent:
#
#   1. ``transcribe`` — the recording -> ASR -> one ``call_transcripts`` row
#   2. ``score``      — that text + the pinned rubric -> LLM -> one ``call_scores`` row
#
# ``AnalysisStage`` (the column) says where a call stands; ``Stage`` below says
# which half of the work was running. BonviZvonki's third stage, ``route``, is
# gone: ``call_type`` is classified at ingest by ``calls/rules.py`` and
# re-stamped by ``reclassify_calls``, so deriving it a second time here would be
# a second implementation of a rule CONVENTIONS.md §7 already made singular.


class Stage(StrEnum):
    """Which half of the pipeline. The values of ``failure_stage``.

    A CHECK constraint on ``call_analysis_state`` admits exactly these two
    strings, so this enum and the column cannot drift apart.
    """

    TRANSCRIBE = "transcribe"
    SCORE = "score"


class StageResult(StrEnum):
    """How one stage ended.

    ``SKIPPED`` is the idempotent path — the work was already done and **no
    provider was called**, which is the property every re-run test asserts.
    """

    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


#: Failures worth trying again, and deliberately **only** these.
#
# WHY THE SET IS NARROW. Retrying a permanent failure every night buys the same
# answer at the same price for ever. What belongs here is a cause that repairs
# itself: a quota that resets, a vendor that was briefly unavailable, a worker
# that was killed mid-call.
#
# WHY THE SET EXISTS AT ALL. BonviZvonki's nightly run only looked at a
# 48-hour window, so 885 calls that failed on a daily quota stayed ``failed``
# for ever — the quota reset the next morning and nothing ever looked at them
# again. ``analysis_retry_transient`` reads exactly this set (§5).
#
# Not in it, on purpose: ``transcript_empty`` (there is no speech in that
# recording today and there will be none tomorrow), ``score_invalid``,
# ``audio_too_large`` and every configuration failure.
TRANSIENT_FAILURES: frozenset[AnalysisFailure] = frozenset(
    {
        AnalysisFailure.PROVIDER_RATE_LIMIT,
        AnalysisFailure.PROVIDER_COOLDOWN,
        AnalysisFailure.PROVIDER_UNAVAILABLE,
        AnalysisFailure.PROVIDER_NETWORK,
        AnalysisFailure.INTERRUPTED,
        AnalysisFailure.TIMEOUT,
    }
)

#: Facts about the **call** rather than about the run. A row that stops on one
#: of these is ``skipped`` and not ``failed`` — see :func:`stage_for`.
NOT_ANALYSABLE_FAILURES: frozenset[AnalysisFailure] = frozenset(
    {
        AnalysisFailure.NO_AUDIO,
        AnalysisFailure.AUDIO_EXPIRED,
        AnalysisFailure.CALL_TOO_SHORT,
        AnalysisFailure.CALL_TYPE_UNKNOWN,
        AnalysisFailure.CALL_TYPE_INTERNAL,
    }
)


def stage_for(failure: AnalysisFailure) -> AnalysisStage:
    """Terminal stage for a failure code — ``skipped`` or ``failed`` (§2.4).

    Decided from the **code** and never from the exception class that carried
    it. The two are written in different places: ``AudioNotAnalysable`` comes
    out of ``modules/audio`` holding either ``call_too_short`` (a skip) or
    ``audio_too_large`` (a real failure), so a mapping keyed on the class would
    file one of them under the wrong heading. One rule, one place.
    """
    if failure in NOT_ANALYSABLE_FAILURES:
        return AnalysisStage.SKIPPED
    return AnalysisStage.FAILED


#: The two ``skipped`` reasons dispatch re-checks, and the only two that can
#: stop being true (§2.6). Both are facts about the *line directory* rather than
#: about the call: once an admin fills it and ``reclassify_calls`` restamps
#: ``calls.call_type``, these rows go back to ``queued`` by themselves.
#:
#: Everything else — no audio, expired audio, too short — is a fact about the
#: call that will not change, and re-queueing it would be a loop.
RECHECKABLE_SKIPS: frozenset[AnalysisFailure] = frozenset(
    {
        AnalysisFailure.CALL_TYPE_UNKNOWN,
        AnalysisFailure.CALL_TYPE_INTERNAL,
    }
)


# --- Internal exceptions ----------------------------------------------------
#
# These never leave the module and never become an HTTP status. Each one
# carries the ``AnalysisFailure`` that will be written to
# ``call_analysis_state.failure_code``, so there is no translation table
# between "what went wrong" and "what is recorded" to keep in step.


class AnalysisError(Exception):
    """A named stop, with the failure code it will be recorded under."""

    failure: AnalysisFailure = AnalysisFailure.INTERNAL

    def __init__(
        self,
        message: str,
        *,
        failure: AnalysisFailure | None = None,
        stage: Stage | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if failure is not None:
            self.failure = failure
        self.stage = stage


class NotAnalysable(AnalysisError):
    """This call is not going to be analysed, and that is a normal outcome.

    Recorded as ``skipped`` and **never** as ``failed`` (§2.4). The distinction
    is the reason BonviZvonki grew a ``skipped`` stage in the first place: a
    panel that paints "this was a colleague call" in the same red as "the vendor
    rejected our key" teaches an operator to ignore both.
    """

    failure = AnalysisFailure.NO_AUDIO


class TranscriptEmpty(AnalysisError):
    """The ASR answered with no text.

    ``failed`` rather than ``skipped``, and **permanent**: an answered call that
    recorded silence (``capture_returned_silence``) gives the same empty answer
    tomorrow, at the same price.
    """

    failure = AnalysisFailure.TRANSCRIPT_EMPTY


class ProviderCooldownActive(AnalysisError):
    """The role is sitting out a quota, so the stage never started.

    A FAILURE and not a skip, deliberately: the call is perfectly ordinary and
    only *now* is impossible. The code is in :data:`TRANSIENT_FAILURES`, so the
    nightly retry picks it up however old it is.
    """

    failure = AnalysisFailure.PROVIDER_COOLDOWN


# --- Outcomes ---------------------------------------------------------------


@dataclass(slots=True)
class StageOutcome:
    """What one stage did, including what it cost."""

    stage: Stage
    result: StageResult
    detail: str = ""
    failure: AnalysisFailure | None = None
    #: Requests that actually reached a provider — i.e. that cost money. A
    #: request that came back 429 is not counted: the vendor refused it and did
    #: not bill for it.
    provider_calls: int = 0
    elapsed_ms: int = 0
    audio_bytes: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def ok(self) -> bool:
        return self.result is not StageResult.FAILED


@dataclass(slots=True)
class CallOutcome:
    """One call's whole trip through the pipeline."""

    call_id: UUID
    stage: AnalysisStage
    transcribe: StageOutcome | None = None
    score: StageOutcome | None = None
    failure: AnalysisFailure | None = None
    failure_detail: str | None = None
    needs_review: bool = False
    overall_score: int | None = None
    call_type: str | None = None
    cost_micro_usd: int = 0
    elapsed_ms: int = 0

    @property
    def failed(self) -> bool:
        return self.stage is AnalysisStage.FAILED

    @property
    def scored(self) -> bool:
        return self.overall_score is not None

    @property
    def asr_calls(self) -> int:
        return self.transcribe.provider_calls if self.transcribe else 0

    @property
    def llm_calls(self) -> int:
        """Provider calls spent on scoring, retries included.

        This is the number that answers "how many requests did one recording
        cost us" and "why is the vendor's quota full", so the invalid-response
        retries are inside it rather than beside it.
        """
        return self.score.provider_calls if self.score else 0


@dataclass(slots=True)
class BatchReport:
    """The tally one ``analysis_run`` returns, and the one it logs."""

    total: int = 0
    completed: int = 0
    """Finished without a failure — **not** necessarily scored."""
    scored: int = 0
    """A score row was written. Fewer than ``completed`` is normal."""
    not_scorable_type: int = 0
    """Finished, but deliberately not scored because of the call's type.

    Counted apart because without it the report lies: "completed: 63" reads as
    63 scored calls, and in the measured case 96 % of them were not scored at
    all."""
    failed: int = 0
    skipped: int = 0
    """A re-run in which every stage was already done — no provider was called."""
    not_analysable: int = 0
    """Stopped on a fact about the call: no audio, expired audio, too short,
    or a type that is not scored. The ``skipped`` stage, and not a failure."""
    asr_calls: int = 0
    llm_calls: int = 0
    needs_review: int = 0
    audio_bytes: int = 0
    cost_micro_usd: int = 0
    started_at: datetime | None = None
    elapsed_sec: float = 0.0
    failures: dict[str, int] = field(default_factory=dict)

    def add(self, outcome: CallOutcome) -> None:
        self.total += 1
        self.asr_calls += outcome.asr_calls
        self.llm_calls += outcome.llm_calls
        self.cost_micro_usd += outcome.cost_micro_usd
        if outcome.transcribe:
            self.audio_bytes += outcome.transcribe.audio_bytes

        if outcome.stage is AnalysisStage.FAILED:
            self.failed += 1
            key = str(outcome.failure or AnalysisFailure.INTERNAL)
            self.failures[key] = self.failures.get(key, 0) + 1
            return

        if outcome.stage is AnalysisStage.SKIPPED:
            self.not_analysable += 1
            if outcome.failure is AnalysisFailure.CALL_TYPE_INTERNAL:
                self.not_scorable_type += 1
            return

        self.completed += 1
        if outcome.scored:
            self.scored += 1
            if outcome.needs_review:
                self.needs_review += 1

        # A re-run: not one provider call was made. Measured on
        # ``provider_calls`` and not on "was there a score stage", because a
        # call that is not scored has no score stage at all and used to be
        # counted as new work every single time.
        if outcome.asr_calls == 0 and outcome.llm_calls == 0:
            self.skipped += 1

    @property
    def per_minute(self) -> float:
        if self.elapsed_sec <= 0:
            return 0.0
        return round(self.total / self.elapsed_sec * 60.0, 1)

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "completed": self.completed,
            "scored": self.scored,
            "not_scorable_type": self.not_scorable_type,
            "failed": self.failed,
            "skipped_idempotent": self.skipped,
            "not_analysable": self.not_analysable,
            "asr_calls": self.asr_calls,
            "llm_calls": self.llm_calls,
            "needs_review": self.needs_review,
            "audio_bytes": self.audio_bytes,
            "cost_micro_usd": self.cost_micro_usd,
            "elapsed_sec": round(self.elapsed_sec, 2),
            "calls_per_minute": self.per_minute,
            "failures": dict(self.failures),
        }
