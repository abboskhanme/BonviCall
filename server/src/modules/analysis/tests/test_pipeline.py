"""The orchestrator: idempotency, every skip path, the caps and the cooldown.

**No test here reaches a provider.** Both clients are stubbed at the protocol
(``PipelineDeps``), so the whole file runs with no vendor key, no network and no
bill — which is the only way a pipeline test can be run on every commit.

The claims this file is responsible for:

* running a call twice writes one row and makes no second provider call;
* every ``AnalysisFailure`` the pipeline can produce is reachable and lands on
  the right stage (``skipped`` is not a failure, SPEC-ANALYTICS §2.4);
* the dispatch gate of §2.6, including the recording retention has deleted;
* the claim is exclusive;
* the two monthly caps stop the only job that spends money;
* a cooldown stops the next call before it opens any audio.
"""

from __future__ import annotations

import dataclasses
import json
from contextlib import nullcontext
from datetime import timedelta

import pytest
import sqlalchemy as sa

from src.core import clock
from src.core.enums import (
    AiRole,
    AnalysisFailure,
    AnalysisStage,
    CallDisposition,
    CallType,
)
from src.modules.analysis.config import AnalysisConfig
from src.modules.analysis.entities import Stage
from src.modules.analysis.errors import ProviderAuthError, ProviderUnavailableError
from src.modules.analysis.limits import ProviderCooldown
from src.modules.analysis.models import (
    AiProviderCooldownModel,
    CallAnalysisStateModel,
    CallScoreModel,
    CallTranscriptModel,
)
from src.modules.analysis.pipeline import (
    AnalysisPipeline,
    PipelineDeps,
    claim,
    dispatch,
    queue_call,
    requeue_transient,
    reset_stale_running,
    run_queue,
)
from src.modules.analysis.rubric_default import DEFAULT_RUBRIC
from src.modules.analysis.tests.stubs import StubASR, StubLLM
from src.modules.analysis.validator import na_budget
from src.modules.settings.models import AppSettingModel

pytestmark = pytest.mark.asyncio

BLOCKS = DEFAULT_RUBRIC["blocks"]
FLAGS = DEFAULT_RUBRIC["red_flags"]


# --- Harness ---------------------------------------------------------------


def make_config(**overrides) -> AnalysisConfig:
    """A settings snapshot with the seeded defaults, minus the waiting.

    ``backoff_base_sec = 0`` so a retry test does not sleep: the wait itself is
    ``limits.with_backoff``'s business and is tested there, not here.
    """
    base = AnalysisConfig(
        enabled=True,
        min_duration_sec=30,
        transcribe_internal=False,
        lookback_hours=168,
        max_calls_per_run=200,
        concurrency=1,
        asr_rpm=0,
        llm_rpm=0,
        max_retries=4,
        backoff_base_sec=0,
        backoff_max_sec=0,
        max_wait_sec=60,
        quota_cooldown_sec=1800,
        invalid_retries=2,
        call_timeout_sec=900,
        retry_transient_days=7,
        monthly_cost_cap_micro_usd=50_000_000,
        monthly_max_calls=3000,
        price_asr_micro_usd_per_minute=0,
        price_llm_micro_usd_per_1k_input_tokens=0,
        price_llm_micro_usd_per_1k_output_tokens=0,
        asr_language="uz",
    )
    return dataclasses.replace(base, **overrides)


@pytest.fixture
def asr() -> StubASR:
    return StubASR()


@pytest.fixture
def llm() -> StubLLM:
    return StubLLM(rubric_blocks=BLOCKS, rubric_red_flags=FLAGS)


@pytest.fixture
def deps(db, asr: StubASR, llm: StubLLM) -> PipelineDeps:
    """Both clients stubbed, and one session — the test's own.

    ``nullcontext(db)`` keeps every write inside the transaction the ``db``
    fixture rolls back, so nothing escapes the test. It is safe because these
    tests run at ``concurrency = 1``; a second concurrent call would need a
    second connection and could not see this one's uncommitted rows anyway.
    """
    return PipelineDeps(
        asr_factory=lambda _session: _ready(asr),
        llm_factory=lambda _session: _ready(llm),
        session_factory=lambda: nullcontext(db),
    )


async def _ready(client):
    return client


async def analysable_call(call_factory, audio_factory, **overrides):
    """An answered, external call with a recording on disk."""
    call = await call_factory(
        has_audio=True,
        audio_missing_reason=None,
        call_type=overrides.pop("call_type", CallType.EXTERNAL),
        duration_sec=overrides.pop("duration_sec", 180),
        **overrides,
    )
    await audio_factory(call=call)
    return call


async def run_one(db, deps, call, *, config=None, force=False):
    return await AnalysisPipeline(config or make_config(), deps).process_in_session(
        db, call.id, force=force
    )


async def state_of(db, call_id) -> CallAnalysisStateModel:
    return (
        await db.execute(
            sa.select(CallAnalysisStateModel).where(
                CallAnalysisStateModel.call_id == call_id
            )
        )
    ).scalar_one()


async def count_of(db, model, call_id) -> int:
    return await db.scalar(
        sa.select(sa.func.count()).select_from(model).where(model.call_id == call_id)
    )


async def set_setting(db, key: str, value) -> None:
    row = await db.get(AppSettingModel, key)
    row.value = value
    await db.flush()


# --- The happy path, and idempotency ---------------------------------------


async def test_a_scored_call_leaves_a_transcript_a_score_and_a_completed_state(
    db, deps, asr, llm, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)

    outcome = await run_one(db, deps, call)

    assert outcome.stage is AnalysisStage.COMPLETED
    assert outcome.failure is None
    assert outcome.overall_score is not None

    transcript = (
        await db.execute(
            sa.select(CallTranscriptModel).where(CallTranscriptModel.call_id == call.id)
        )
    ).scalar_one()
    assert transcript.text == asr.text
    assert transcript.provider == "stub"
    # The bytes the ASR saw are the bytes the file holds: the stream really was
    # read, rather than a handle handed over unopened.
    assert asr.bytes_seen == transcript.audio_bytes

    score = (
        await db.execute(
            sa.select(CallScoreModel).where(CallScoreModel.call_id == call.id)
        )
    ).scalar_one()
    assert score.rubric_version == "v1"
    assert score.overall_score == outcome.overall_score

    state = await state_of(db, call.id)
    assert state.stage is AnalysisStage.COMPLETED
    assert state.failure_code is None
    assert (state.asr_calls, state.llm_calls) == (1, 1)
    assert state.transcribed_at is not None and state.scored_at is not None


async def test_running_twice_writes_one_row_and_pays_nothing_the_second_time(
    db, deps, asr, llm, call_factory, audio_factory
) -> None:
    """The property every re-run depends on: a restart costs nothing."""
    call = await analysable_call(call_factory, audio_factory)

    first = await run_one(db, deps, call)
    second = await run_one(db, deps, call)

    assert (asr.calls, llm.calls) == (1, 1), "the second run called a provider"
    assert await count_of(db, CallTranscriptModel, call.id) == 1
    assert await count_of(db, CallScoreModel, call.id) == 1
    assert second.stage is AnalysisStage.COMPLETED
    assert second.overall_score == first.overall_score

    state = await state_of(db, call.id)
    # The counters are money spent, so they must not move either. ``attempts``
    # is the number of runs and SHOULD move — that is how a re-run is visible.
    assert (state.asr_calls, state.llm_calls) == (1, 1)
    assert state.attempts == 2


async def test_force_recomputes_both_halves_and_is_the_only_way_to_pay_twice(
    db, deps, asr, llm, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)
    await run_one(db, deps, call)

    await run_one(db, deps, call, force=True)

    assert (asr.calls, llm.calls) == (2, 2)
    assert await count_of(db, CallTranscriptModel, call.id) == 1
    assert await count_of(db, CallScoreModel, call.id) == 1


async def test_queue_call_with_force_clears_the_transcript_and_the_score(
    db, deps, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)
    await run_one(db, deps, call)

    state = await queue_call(db, call.id, force=True)

    assert state.stage is AnalysisStage.QUEUED
    assert state.failure_code is None
    assert (state.asr_calls, state.llm_calls, state.cost_micro_usd) == (0, 0, 0)
    assert await count_of(db, CallTranscriptModel, call.id) == 0
    assert await count_of(db, CallScoreModel, call.id) == 0


async def test_the_scoring_stage_is_given_the_call_s_real_duration(
    db, deps, llm, call_factory, audio_factory
) -> None:
    """The ``na`` budget is derived from the duration, so it has to arrive.

    Handing ``None`` down instead is not a small mistake: the second ``na``
    guard switches off silently, and the measured result was seven criteria
    dropped and 8 of 12 calls scoring 100.
    """
    call = await analysable_call(call_factory, audio_factory, duration_sec=612)

    await run_one(db, deps, call)

    prompt = llm.prompts[0]
    assert "Davomiyligi: 10 daq 12 son" in prompt
    # The same number the validator will enforce, printed for the model.
    assert f"`na` CHEGARASI: {na_budget(612)} ball" in prompt


async def test_both_provider_clients_are_closed(
    db, deps, asr, llm, call_factory, audio_factory
) -> None:
    """A stage that returns without closing leaks a connection pool per call.

    One leak is nothing; a worker that scores for a week runs out of file
    descriptors.
    """
    call = await analysable_call(call_factory, audio_factory)

    await run_one(db, deps, call)

    assert asr.closed == 1
    assert llm.closed == 1


async def test_the_client_is_closed_even_when_the_stage_fails(
    db, deps, asr, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)
    asr.error = ProviderAuthError("key rejected")

    await run_one(db, deps, call)

    assert asr.closed == 1


# --- Every skip path of §2.4 ------------------------------------------------


async def test_an_unknown_call_type_is_skipped_and_costs_nothing(
    db, deps, asr, llm, call_factory, audio_factory
) -> None:
    """An empty line directory must never be guessed past.

    Scoring a colleague conversation against a sales rubric is money spent to
    lower somebody's average unfairly, and it cannot be undone.
    """
    call = await analysable_call(call_factory, audio_factory)
    call.call_type = CallType.UNKNOWN
    await db.flush()

    outcome = await run_one(db, deps, call)

    assert outcome.stage is AnalysisStage.SKIPPED
    assert outcome.failure is AnalysisFailure.CALL_TYPE_UNKNOWN
    assert (asr.calls, llm.calls) == (0, 0)
    state = await state_of(db, call.id)
    assert state.stage is AnalysisStage.SKIPPED
    assert state.failure_stage == Stage.TRANSCRIBE.value


async def test_an_internal_call_is_not_transcribed_by_default(
    db, deps, asr, llm, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory, call_type=CallType.INTERNAL)

    outcome = await run_one(db, deps, call)

    assert outcome.failure is AnalysisFailure.CALL_TYPE_INTERNAL
    assert (asr.calls, llm.calls) == (0, 0)
    assert await count_of(db, CallTranscriptModel, call.id) == 0


async def test_an_internal_call_is_transcribed_but_never_scored_when_enabled(
    db, deps, asr, llm, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory, call_type=CallType.INTERNAL)

    outcome = await run_one(
        db, deps, call, config=make_config(transcribe_internal=True)
    )

    assert outcome.stage is AnalysisStage.SKIPPED
    assert outcome.failure is AnalysisFailure.CALL_TYPE_INTERNAL
    assert asr.calls == 1, "the transcript is wanted"
    assert llm.calls == 0, "the score is not"
    assert await count_of(db, CallTranscriptModel, call.id) == 1
    assert await count_of(db, CallScoreModel, call.id) == 0
    state = await state_of(db, call.id)
    assert state.transcribed_at is not None
    assert state.failure_stage == Stage.SCORE.value


async def test_an_internal_call_loses_a_score_it_should_never_have_had(
    db, deps, call_factory, audio_factory, score_factory
) -> None:
    """The type can become known later; the old number must not survive it.

    Leaving it puts the system at odds with itself — the page says "not
    scored" while the analytics keeps counting the figure into an average.
    """
    call = await analysable_call(call_factory, audio_factory, call_type=CallType.INTERNAL)
    await score_factory(call=call, overall_score=43)

    await run_one(db, deps, call, config=make_config(transcribe_internal=True))

    assert await count_of(db, CallScoreModel, call.id) == 0


async def test_a_call_with_no_recording_is_skipped(
    db, deps, asr, call_factory
) -> None:
    call = await call_factory(call_type=CallType.EXTERNAL, duration_sec=180)

    outcome = await run_one(db, deps, call)

    assert outcome.stage is AnalysisStage.SKIPPED
    assert outcome.failure is AnalysisFailure.NO_AUDIO
    assert asr.calls == 0


async def test_an_unanswered_call_is_skipped_as_having_no_recording(
    db, deps, call_factory
) -> None:
    # ``no_answer`` is the outgoing spelling; ``missed`` is incoming-only and
    # the CHECK on ``calls`` refuses the other combination outright.
    call = await call_factory(
        call_type=CallType.EXTERNAL, disposition=CallDisposition.NO_ANSWER
    )

    outcome = await run_one(db, deps, call)

    assert outcome.failure is AnalysisFailure.NO_AUDIO


async def test_a_call_flagged_as_having_audio_with_no_row_is_skipped(
    db, deps, asr, call_factory
) -> None:
    """``has_audio`` without a ``call_audio`` row: the second line of defence.

    The gate cannot see this, so the pre-run check has to, and it must cost
    nothing to discover.
    """
    call = await call_factory(
        call_type=CallType.EXTERNAL,
        duration_sec=180,
        has_audio=True,
        audio_missing_reason=None,
    )

    outcome = await run_one(db, deps, call)

    assert outcome.failure is AnalysisFailure.NO_AUDIO
    assert asr.calls == 0


async def test_audio_removed_by_retention_is_skipped_as_expired(
    db, deps, asr, call_factory, audio_factory
) -> None:
    """``deleted_at`` is set and ``calls.has_audio`` stays true, on purpose."""
    call = await analysable_call(call_factory, audio_factory)
    await db.execute(
        sa.text(
            "UPDATE call_audio SET deleted_at = now(), deleted_reason = 'retention' "
            "WHERE call_id = :call_id"
        ),
        {"call_id": call.id},
    )

    outcome = await run_one(db, deps, call)

    assert outcome.stage is AnalysisStage.SKIPPED
    assert outcome.failure is AnalysisFailure.AUDIO_EXPIRED
    assert asr.calls == 0
    assert call.has_audio is True, "the call row still records that audio existed"


async def test_a_short_call_is_skipped_before_anything_is_opened(
    db, deps, asr, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory, duration_sec=12)

    outcome = await run_one(db, deps, call)

    assert outcome.failure is AnalysisFailure.CALL_TOO_SHORT
    assert asr.calls == 0


async def test_a_recording_shorter_than_the_floor_is_skipped_by_the_audio_module(
    db, deps, asr, call_factory, audio_factory
) -> None:
    """The recording's own length, not the call log's.

    The two disagree exactly when the recorder truncated the call, which is the
    case where paying to transcribe is most obviously wasted. It only works
    because ``min_duration_ms`` is passed down — the default is ``None``, which
    means "do not judge".
    """
    call = await analysable_call(call_factory, audio_factory, duration_sec=180)
    await db.execute(
        sa.text("UPDATE call_audio SET duration_ms = 4000 WHERE call_id = :call_id"),
        {"call_id": call.id},
    )

    outcome = await run_one(db, deps, call)

    assert outcome.stage is AnalysisStage.SKIPPED
    assert outcome.failure is AnalysisFailure.CALL_TOO_SHORT
    assert asr.calls == 0
    # The audio module's own words, stored verbatim: it measured the file, and
    # rewriting its sentence here would be a second description of one fact.
    state = await state_of(db, call.id)
    assert state.failure_detail == "4000 ms of audio, floor is 30000 ms"


async def test_an_oversized_recording_fails_before_a_byte_is_allocated(
    db, deps, asr, call_factory, audio_factory, monkeypatch
) -> None:
    """``audio_too_large`` is a FAILURE, not a skip — it is not a fact about
    the conversation, and §2.1 files it under permanent."""
    call = await analysable_call(call_factory, audio_factory)
    monkeypatch.setattr(
        "src.modules.analysis.transcribe.MAX_AUDIO_BYTES", 16, raising=True
    )

    outcome = await run_one(db, deps, call)

    assert outcome.stage is AnalysisStage.FAILED
    assert outcome.failure is AnalysisFailure.AUDIO_TOO_LARGE
    assert asr.calls == 0
    state = await state_of(db, call.id)
    assert "16-byte ceiling" in state.failure_detail


async def test_an_empty_transcript_is_a_permanent_failure(
    db, deps, asr, llm, call_factory, audio_factory
) -> None:
    """Silence gives the same empty answer tomorrow, at the same price."""
    call = await analysable_call(call_factory, audio_factory)
    asr.text = "   "

    outcome = await run_one(db, deps, call)

    assert outcome.stage is AnalysisStage.FAILED
    assert outcome.failure is AnalysisFailure.TRANSCRIPT_EMPTY
    assert llm.calls == 0
    assert await count_of(db, CallTranscriptModel, call.id) == 0


async def test_an_unknown_exception_is_recorded_as_internal_with_its_class_name(
    db, deps, asr, call_factory, audio_factory
) -> None:
    """A closed enum that cannot represent a surprise turns it into a write
    error, which is the opposite of what a failure column is for."""
    call = await analysable_call(call_factory, audio_factory)
    asr.error = ZeroDivisionError("nobody foresaw this")

    outcome = await run_one(db, deps, call)

    assert outcome.stage is AnalysisStage.FAILED
    assert outcome.failure is AnalysisFailure.INTERNAL
    state = await state_of(db, call.id)
    assert "ZeroDivisionError" in state.failure_detail


async def test_a_provider_error_keeps_its_own_code(
    db, deps, asr, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)
    asr.error = ProviderAuthError("the key is wrong")

    outcome = await run_one(db, deps, call)

    assert outcome.failure is AnalysisFailure.PROVIDER_AUTH
    state = await state_of(db, call.id)
    assert state.failure_stage == Stage.TRANSCRIBE.value


async def test_a_failure_in_the_scoring_half_is_attributed_to_it(
    db, deps, llm, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)
    llm.error = ProviderUnavailableError("the model is busy")

    outcome = await run_one(db, deps, call, config=make_config(max_retries=0))

    assert outcome.failure is AnalysisFailure.PROVIDER_UNAVAILABLE
    state = await state_of(db, call.id)
    assert state.failure_stage == Stage.SCORE.value
    # The transcript survives: the money spent on it is not thrown away by a
    # failure in the half that comes after.
    assert await count_of(db, CallTranscriptModel, call.id) == 1


async def test_an_invalid_score_is_permanent_after_the_re_asks(
    db, deps, llm, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)
    llm.responses = [json.dumps({"blocks": {}, "confidence": 0.9})]

    outcome = await run_one(db, deps, call, config=make_config(invalid_retries=1))

    assert outcome.stage is AnalysisStage.FAILED
    assert outcome.failure is AnalysisFailure.SCORE_INVALID
    assert llm.calls == 2, "asked again once, then gave up"


async def test_a_retried_run_clears_the_previous_reason(
    db, deps, asr, call_factory, audio_factory
) -> None:
    """The CHECK admits a reason only on a stopped row.

    A retry that left the old code behind would be rejected by the database the
    moment the stage moved to ``transcribing`` — which is a 500 in a worker,
    for a call that was about to succeed.
    """
    call = await analysable_call(call_factory, audio_factory)
    asr.error = ProviderAuthError("the key is wrong")
    await run_one(db, deps, call)
    asr.error = None

    outcome = await run_one(db, deps, call)

    assert outcome.stage is AnalysisStage.COMPLETED
    state = await state_of(db, call.id)
    assert state.failure_code is None
    assert state.failure_detail is None


# --- The cooldown -----------------------------------------------------------


async def test_a_cooldown_stops_the_stage_before_the_audio_is_opened(
    db, deps, asr, call_factory, audio_factory, provider_cooldown_factory
) -> None:
    """The measured failure this prevents: ~36,000 pointless uploads against a
    quota that had already run out."""
    call = await analysable_call(call_factory, audio_factory)
    await provider_cooldown_factory(role=AiRole.ASR)

    outcome = await run_one(db, deps, call)

    assert outcome.stage is AnalysisStage.FAILED
    assert outcome.failure is AnalysisFailure.PROVIDER_COOLDOWN
    assert asr.calls == 0
    assert asr.bytes_seen == 0


async def test_an_asr_cooldown_does_not_stop_the_scoring_of_an_existing_transcript(
    db, deps, llm, call_factory, audio_factory, transcript_factory,
    provider_cooldown_factory,
) -> None:
    """One account, two roles, two quotas. They are counted apart on purpose."""
    call = await analysable_call(call_factory, audio_factory)
    await transcript_factory(call=call)
    await provider_cooldown_factory(role=AiRole.ASR)

    outcome = await run_one(db, deps, call)

    assert outcome.stage is AnalysisStage.COMPLETED
    assert llm.calls == 1


async def test_a_daily_quota_opens_a_cooldown_for_the_whole_fleet(
    db, deps, asr, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)
    asr.fail_with_429 = 1
    asr.daily_quota = True

    outcome = await run_one(db, deps, call)

    assert outcome.failure is AnalysisFailure.PROVIDER_RATE_LIMIT
    assert asr.fail_with_429 == 0, "a daily quota is never retried"
    left = await ProviderCooldown(AiRole.ASR).remaining(db)
    assert 1700 < left <= 1800, "the quota cooldown, not the short one"


async def test_a_longer_cooldown_is_never_shortened(db) -> None:
    """Two workers hitting 429 seconds apart: the second one's short window
    must not cancel the first one's daily quota."""
    cooldown = ProviderCooldown(AiRole.LLM)
    await cooldown.start(
        db, 1800, reason=AnalysisFailure.PROVIDER_RATE_LIMIT, detail="daily"
    )

    kept = await cooldown.start(
        db, 30, reason=AnalysisFailure.PROVIDER_RATE_LIMIT, detail="a burst"
    )

    assert kept > 1000
    row = await db.get(AiProviderCooldownModel, AiRole.LLM)
    assert row.detail == "daily", "the long one is intact, reason included"


async def test_a_cooldown_can_be_extended(db) -> None:
    cooldown = ProviderCooldown(AiRole.ASR)
    await cooldown.start(db, 30, reason=AnalysisFailure.PROVIDER_RATE_LIMIT)

    now_in_force = await cooldown.start(
        db, 1800, reason=AnalysisFailure.PROVIDER_RATE_LIMIT
    )

    assert now_in_force > 1700


async def test_a_transient_429_is_retried_and_then_succeeds(
    db, deps, asr, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)
    asr.fail_with_429 = 2

    outcome = await run_one(db, deps, call)

    assert outcome.stage is AnalysisStage.COMPLETED
    assert asr.calls == 1, "one billable call; the two refusals are not billed"
    state = await state_of(db, call.id)
    assert state.asr_calls == 1


# --- The dispatch gate (§2.6) ----------------------------------------------


async def test_dispatch_queues_an_eligible_call(
    db, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)

    queued = await dispatch(db, make_config())

    assert queued == 1
    state = await state_of(db, call.id)
    assert state.stage is AnalysisStage.QUEUED
    assert state.failure_code is None


async def test_dispatch_never_queues_a_call_whose_audio_retention_deleted(
    db, call_factory, audio_factory
) -> None:
    """``calls.has_audio`` stays true when the blob goes, by design.

    A gate written on that flag alone queues calls whose bytes are gone and
    then pays a client round trip, one call at a time, to find out.
    """
    call = await analysable_call(call_factory, audio_factory)
    await db.execute(
        sa.text(
            "UPDATE call_audio SET deleted_at = now(), deleted_reason = 'retention' "
            "WHERE call_id = :call_id"
        ),
        {"call_id": call.id},
    )

    queued = await dispatch(db, make_config())

    assert queued == 0
    assert await count_of(db, CallAnalysisStateModel, call.id) == 0


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"call_type": CallType.INTERNAL}, "a colleague conversation"),
        ({"call_type": CallType.UNKNOWN}, "the line directory is empty"),
        ({"duration_sec": 11}, "under analysis.min_duration_sec"),
        (
            {"disposition": CallDisposition.NO_ANSWER, "duration_sec": 0},
            "there was no conversation",
        ),
    ],
)
async def test_dispatch_leaves_an_ineligible_call_alone(
    db, call_factory, audio_factory, overrides, why
) -> None:
    call = await analysable_call(call_factory, audio_factory, **overrides)

    assert await dispatch(db, make_config()) == 0, why
    assert await count_of(db, CallAnalysisStateModel, call.id) == 0


async def test_dispatch_ignores_a_call_older_than_the_lookback_window(
    db, call_factory, audio_factory
) -> None:
    call = await analysable_call(
        call_factory, audio_factory, received_at=clock.now() - timedelta(days=30)
    )

    assert await dispatch(db, make_config(lookback_hours=168)) == 0
    assert await count_of(db, CallAnalysisStateModel, call.id) == 0


async def test_dispatch_respects_the_per_tick_ceiling(
    db, call_factory, audio_factory
) -> None:
    for _ in range(3):
        await analysable_call(call_factory, audio_factory)

    queued = await dispatch(db, make_config(max_calls_per_run=2))

    assert queued == 2


async def test_dispatch_is_safe_to_run_twice(db, call_factory, audio_factory) -> None:
    await analysable_call(call_factory, audio_factory)

    first = await dispatch(db, make_config())
    second = await dispatch(db, make_config())

    assert (first, second) == (1, 0)


async def test_dispatch_requeues_a_call_the_directory_can_now_classify(
    db, call_factory, audio_factory, analysis_state_factory
) -> None:
    """§2.6's self-healing, and the reason a skipped row is not invisible.

    Without this, every call analysed before the line directory existed stays
    skipped for ever and nobody knows to look.
    """
    call = await analysable_call(call_factory, audio_factory)
    state = await analysis_state_factory(
        call=call,
        stage=AnalysisStage.SKIPPED,
        failure_code=AnalysisFailure.CALL_TYPE_UNKNOWN,
    )

    requeued = await dispatch(db, make_config())

    assert requeued == 1
    await db.refresh(state)
    assert state.stage is AnalysisStage.QUEUED
    assert state.failure_code is None


async def test_dispatch_requeues_internal_calls_when_the_setting_is_turned_on(
    db, call_factory, audio_factory, analysis_state_factory
) -> None:
    """The setting is part of the reason, so changing it has to be re-checkable."""
    call = await analysable_call(call_factory, audio_factory, call_type=CallType.INTERNAL)
    state = await analysis_state_factory(
        call=call,
        stage=AnalysisStage.SKIPPED,
        failure_code=AnalysisFailure.CALL_TYPE_INTERNAL,
    )

    assert await dispatch(db, make_config(transcribe_internal=False)) == 0
    assert await dispatch(db, make_config(transcribe_internal=True)) == 1

    await db.refresh(state)
    assert state.stage is AnalysisStage.QUEUED


async def test_dispatch_never_requeues_a_reason_that_cannot_change(
    db, call_factory, audio_factory, analysis_state_factory
) -> None:
    """Re-queueing "no audio" would be a loop that costs a claim every lap."""
    call = await analysable_call(call_factory, audio_factory)
    state = await analysis_state_factory(
        call=call,
        stage=AnalysisStage.SKIPPED,
        failure_code=AnalysisFailure.NO_AUDIO,
    )

    assert await dispatch(db, make_config()) == 0

    await db.refresh(state)
    assert state.stage is AnalysisStage.SKIPPED


# --- The claim --------------------------------------------------------------


async def test_two_claimers_never_take_the_same_row(
    db, call_factory, audio_factory
) -> None:
    calls = [await analysable_call(call_factory, audio_factory) for _ in range(3)]
    await dispatch(db, make_config())

    first = await claim(db, 2)
    second = await claim(db, 2)

    assert len(first) == 2 and len(second) == 1
    assert set(first) & set(second) == set()
    assert set(first) | set(second) == {call.id for call in calls}


async def test_claiming_moves_the_row_out_of_queued_before_any_provider_call(
    db, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)
    await dispatch(db, make_config())

    await claim(db, 4)

    state = await state_of(db, call.id)
    assert state.stage is AnalysisStage.TRANSCRIBING
    assert state.last_run_at is not None


async def test_claiming_clears_a_previous_reason(
    db, call_factory, audio_factory, analysis_state_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)
    state = await analysis_state_factory(
        call=call,
        stage=AnalysisStage.QUEUED,
        failure_code=None,
        failure_detail="left over",
    )

    await claim(db, 4)

    await db.refresh(state)
    assert state.failure_detail is None


async def test_claiming_an_empty_queue_returns_nothing(db) -> None:
    assert await claim(db, 4) == []


# --- The flag and the two caps (§4.4, §4.5) --------------------------------


async def test_the_feature_is_off_until_somebody_turns_it_on(
    db, deps, call_factory, audio_factory
) -> None:
    """The seeded default. Deploying phase 1 changes nothing that runs."""
    await analysable_call(call_factory, audio_factory)

    assert await dispatch(db) == 0
    assert await run_queue(db, deps=deps) == 0


async def test_the_flag_stops_the_only_job_that_spends(
    db, deps, asr, llm, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)
    await dispatch(db, make_config())

    processed = await run_queue(db, config=make_config(enabled=False), deps=deps)

    assert processed == 0
    assert (asr.calls, llm.calls) == (0, 0)
    state = await state_of(db, call.id)
    assert state.stage is AnalysisStage.QUEUED, "nothing was even claimed"


async def test_the_monthly_call_cap_stops_the_run_before_a_row_is_claimed(
    db, deps, asr, llm, call_factory, audio_factory, analysis_state_factory
) -> None:
    """The cap that actually protects the account on day one: the money cap
    cannot trip while the price is unset, and the price starts unset."""
    await analysable_call(call_factory, audio_factory)
    await dispatch(db, make_config())
    for _ in range(2):
        done = await call_factory()
        await analysis_state_factory(
            call=done, stage=AnalysisStage.COMPLETED, last_run_at=clock.now()
        )

    processed = await run_queue(db, config=make_config(monthly_max_calls=2), deps=deps)

    assert processed == 0
    assert (asr.calls, llm.calls) == (0, 0)


async def test_the_monthly_cost_cap_sums_what_was_really_spent(
    db, deps, asr, call_factory, audio_factory, analysis_state_factory
) -> None:
    """Summed over every state row, not only the completed ones: a call that
    failed halfway still paid for the request it made."""
    await analysable_call(call_factory, audio_factory)
    await dispatch(db, make_config())
    spent = await call_factory()
    await analysis_state_factory(
        call=spent,
        stage=AnalysisStage.FAILED,
        failure_code=AnalysisFailure.TRANSCRIPT_EMPTY,
        last_run_at=clock.now(),
        cost_micro_usd=9_000_000,
    )

    processed = await run_queue(
        db, config=make_config(monthly_cost_cap_micro_usd=9_000_000), deps=deps
    )

    assert processed == 0
    assert asr.calls == 0


async def test_a_cap_of_zero_means_stop(
    db, deps, asr, call_factory, audio_factory
) -> None:
    """Task 12 sets ``monthly_max_calls = 20`` for a controlled trial, so the
    value has to be read as a limit and never as "unlimited"."""
    await analysable_call(call_factory, audio_factory)
    await dispatch(db, make_config())

    assert await run_queue(db, config=make_config(monthly_max_calls=0), deps=deps) == 0
    assert asr.calls == 0


async def test_dispatch_queues_nothing_once_a_cap_is_reached(
    db, call_factory, audio_factory, analysis_state_factory
) -> None:
    """A backlog built behind a reached cap only spends the moment somebody
    raises the cap, which is the opposite of what a cap is for."""
    call = await analysable_call(call_factory, audio_factory)
    done = await call_factory()
    await analysis_state_factory(
        call=done, stage=AnalysisStage.COMPLETED, last_run_at=clock.now()
    )

    assert await dispatch(db, make_config(monthly_max_calls=1)) == 0
    assert await count_of(db, CallAnalysisStateModel, call.id) == 0


async def test_last_month_s_spending_does_not_count_against_this_month(
    db, deps, call_factory, audio_factory, analysis_state_factory
) -> None:
    old = await call_factory()
    await analysis_state_factory(
        call=old,
        stage=AnalysisStage.COMPLETED,
        last_run_at=clock.now() - timedelta(days=62),
    )
    await analysable_call(call_factory, audio_factory)

    processed = await run_queue(
        db, config=make_config(monthly_max_calls=1, concurrency=1), deps=deps
    )

    assert processed == 0, "nothing was queued yet"
    assert await dispatch(db, make_config(monthly_max_calls=1)) == 1


# --- The whole run ----------------------------------------------------------


async def test_run_queue_claims_and_analyses_what_dispatch_queued(
    db, deps, asr, llm, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)
    await dispatch(db, make_config())

    processed = await run_queue(db, config=make_config(), deps=deps)

    assert processed == 1
    assert (asr.calls, llm.calls) == (1, 1)
    state = await state_of(db, call.id)
    assert state.stage is AnalysisStage.COMPLETED


async def test_a_second_run_of_the_queue_finds_nothing_and_spends_nothing(
    db, deps, asr, llm, call_factory, audio_factory
) -> None:
    await analysable_call(call_factory, audio_factory)
    await dispatch(db, make_config())
    await run_queue(db, config=make_config(), deps=deps)

    processed = await run_queue(db, config=make_config(), deps=deps)

    assert processed == 0
    assert (asr.calls, llm.calls) == (1, 1)


# --- The stale reset --------------------------------------------------------


@pytest.mark.parametrize(
    ("stage", "expected_half"),
    [
        (AnalysisStage.TRANSCRIBING, Stage.TRANSCRIBE.value),
        (AnalysisStage.SCORING, Stage.SCORE.value),
    ],
)
async def test_a_row_stuck_in_a_running_stage_is_closed_as_interrupted(
    db, analysis_state_factory, stage, expected_half
) -> None:
    """The commit at every stage boundary is what leaves the row visible; this
    is what closes it. ``interrupted`` is transient, so it comes back."""
    state = await analysis_state_factory(
        stage=stage, last_run_at=clock.now() - timedelta(hours=1)
    )

    closed = await reset_stale_running(db, make_config(call_timeout_sec=900))

    assert closed == 1
    await db.refresh(state)
    assert state.stage is AnalysisStage.FAILED
    assert state.failure_code is AnalysisFailure.INTERRUPTED
    assert state.failure_stage == expected_half


async def test_a_row_that_never_ran_is_left_alone(db, analysis_state_factory) -> None:
    """``last_run_at IS NULL`` is not stale — that row never started."""
    state = await analysis_state_factory(
        stage=AnalysisStage.TRANSCRIBING, last_run_at=None
    )

    assert await reset_stale_running(db, make_config()) == 0

    await db.refresh(state)
    assert state.stage is AnalysisStage.TRANSCRIBING


async def test_a_call_still_within_its_own_timeout_is_left_alone(
    db, analysis_state_factory
) -> None:
    state = await analysis_state_factory(
        stage=AnalysisStage.SCORING, last_run_at=clock.now() - timedelta(minutes=5)
    )

    assert await reset_stale_running(db, make_config(call_timeout_sec=900)) == 0

    await db.refresh(state)
    assert state.stage is AnalysisStage.SCORING


# --- The nightly transient retry -------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        AnalysisFailure.PROVIDER_RATE_LIMIT,
        AnalysisFailure.PROVIDER_COOLDOWN,
        AnalysisFailure.PROVIDER_UNAVAILABLE,
        AnalysisFailure.PROVIDER_NETWORK,
        AnalysisFailure.INTERRUPTED,
        AnalysisFailure.TIMEOUT,
    ],
)
async def test_a_transient_failure_is_put_back_in_the_queue(
    db, analysis_state_factory, failure
) -> None:
    """885 calls once stayed ``failed`` for ever because the quota reset the
    next morning and nothing ever looked at them again."""
    state = await analysis_state_factory(
        stage=AnalysisStage.FAILED,
        failure_code=failure,
        last_run_at=clock.now() - timedelta(days=3),
    )

    assert await requeue_transient(db, make_config()) == 1

    await db.refresh(state)
    assert state.stage is AnalysisStage.QUEUED
    assert state.failure_code is None


@pytest.mark.parametrize(
    "failure",
    [
        AnalysisFailure.TRANSCRIPT_EMPTY,
        AnalysisFailure.SCORE_INVALID,
        AnalysisFailure.PROVIDER_AUTH,
        AnalysisFailure.AUDIO_TOO_LARGE,
        AnalysisFailure.AI_NOT_CONFIGURED,
    ],
)
async def test_a_permanent_failure_is_never_retried(
    db, analysis_state_factory, failure
) -> None:
    """Retrying one every night buys the same answer at the same price."""
    state = await analysis_state_factory(
        stage=AnalysisStage.FAILED,
        failure_code=failure,
        last_run_at=clock.now() - timedelta(days=1),
    )

    assert await requeue_transient(db, make_config()) == 0

    await db.refresh(state)
    assert state.stage is AnalysisStage.FAILED


async def test_a_transient_failure_older_than_the_window_is_left_alone(
    db, analysis_state_factory
) -> None:
    state = await analysis_state_factory(
        stage=AnalysisStage.FAILED,
        failure_code=AnalysisFailure.PROVIDER_RATE_LIMIT,
        last_run_at=clock.now() - timedelta(days=30),
    )

    assert await requeue_transient(db, make_config(retry_transient_days=7)) == 0

    await db.refresh(state)
    assert state.stage is AnalysisStage.FAILED


# --- Settings ---------------------------------------------------------------


async def test_the_config_is_read_from_app_settings(db) -> None:
    """Every knob is a row, so it can be changed without a deploy."""
    from src.core.settings_keys import SettingKey
    from src.modules.analysis.config import load_config

    await set_setting(db, SettingKey.ANALYSIS_ENABLED, True)
    await set_setting(db, SettingKey.ANALYSIS_MIN_DURATION_SEC, 45)
    await set_setting(db, SettingKey.ANALYSIS_ASR_LANGUAGE, "")

    config = await load_config(db)

    assert config.enabled is True
    assert config.min_duration_sec == 45
    # Empty is legal and means "provider, you detect it".
    assert config.asr_language is None
    assert config.priced is False


async def test_the_language_from_settings_reaches_the_provider(
    db, deps, asr, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)

    await run_one(db, deps, call, config=make_config(asr_language="ru"))

    assert asr.languages == ["ru"]


async def test_the_filename_handed_to_the_vendor_names_only_the_call(
    db, deps, asr, call_factory, audio_factory
) -> None:
    """It is read by a third party in another country; the call id is all it
    needs, and the employee's name is not its business (§11.5)."""
    call = await analysable_call(call_factory, audio_factory)

    await run_one(db, deps, call)

    assert asr.filenames == [f"call-{call.id}.ogg"]


# --- Cost -------------------------------------------------------------------


async def test_an_unpriced_call_costs_zero_and_that_is_not_free(
    db, deps, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)

    await run_one(db, deps, call)

    state = await state_of(db, call.id)
    assert state.cost_micro_usd == 0
    score = (
        await db.execute(
            sa.select(CallScoreModel).where(CallScoreModel.call_id == call.id)
        )
    ).scalar_one()
    # NULL, not 0: "nobody has entered a price", never "this was free".
    assert score.cost_micro_usd is None


async def test_the_asr_price_is_charged_against_the_measured_minutes(
    db, deps, call_factory, audio_factory
) -> None:
    call = await analysable_call(call_factory, audio_factory)
    await db.execute(
        sa.text("UPDATE call_audio SET duration_ms = 120000 WHERE call_id = :call_id"),
        {"call_id": call.id},
    )

    await run_one(
        db, deps, call, config=make_config(price_asr_micro_usd_per_minute=4_000)
    )

    state = await state_of(db, call.id)
    # Two minutes at 4,000 micro-USD a minute, computed in the test.
    assert state.cost_micro_usd == 8_000


async def test_a_re_run_does_not_charge_for_work_it_did_not_do(
    db, deps, call_factory, audio_factory
) -> None:
    """The cap is measured against this column, so a re-run that added the
    price again would close the month early on work nobody paid for."""
    call = await analysable_call(call_factory, audio_factory)
    await db.execute(
        sa.text("UPDATE call_audio SET duration_ms = 60000 WHERE call_id = :call_id"),
        {"call_id": call.id},
    )
    config = make_config(price_asr_micro_usd_per_minute=4_000)

    await run_one(db, deps, call, config=config)
    await run_one(db, deps, call, config=config)

    state = await state_of(db, call.id)
    assert state.cost_micro_usd == 4_000
