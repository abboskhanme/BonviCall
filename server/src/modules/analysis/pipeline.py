"""The orchestrator: queue -> claim -> transcribe -> score -> write.

Cheapest first. The call's type is already known (``calls.call_type``, stamped
at ingest and re-stamped by ``reclassify_calls``), so the two gates that cost
nothing are applied before the two stages that cost money.

Four properties are decided in this file, and each one has an incident behind
it:

* **Idempotency.** Every stage asks "is this already done?" before it spends
  anything. A re-run — a restarted worker, an operator pressing the button, a
  job that ran twice — writes no second row and makes no second provider call.
* **A visible failure.** Every stop is written to ``call_analysis_state`` with
  a code from the closed ``AnalysisFailure`` enum. "No score and no reason" is
  not a state this module can produce.
* **Bounded concurrency.** ``run_batch`` runs ``analysis.concurrency`` calls at
  a time, each in its own session.
* **Short transactions.** ``commit()`` at every stage boundary, and that is not
  a tidiness habit — see :meth:`AnalysisPipeline._run_stages`.

**No Redis, no Celery, no ``CallLock``** (§5). Two claimers never take the same
row because the claim is ``SELECT ... FOR UPDATE SKIP LOCKED`` followed by an
``UPDATE`` out of ``queued`` and a commit, all before any provider is touched.
BonviZvonki needed a distributed lock for that and paid twice for one call when
it was absent; here the database does it.

On ``CallModel``. This module imports it, which ``tests/test_layering.py``
permits (``call_analysis_state.call_id`` is a foreign key into ``calls``) and
which SPEC-ANALYTICS §1.1 asks to be used sparingly. It is used for two things
only: the set-based dispatch gate of §2.6, which is one statement and cannot be
assembled from per-row service calls, and reading one call's facts inside a
worker. Neither is a visibility decision — **scope is still decided by
``CallService.get(principal, id)``**, in the service layer, where a principal
exists. A worker job has none, and inventing one would be a lie.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from time import perf_counter

import sqlalchemy as sa
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock, database
from src.core.enums import (
    AnalysisFailure,
    AnalysisStage,
    CallDisposition,
    CallType,
)
from src.core.errors import ErrorCode, NotFoundError
from src.core.logging import get_logger
from src.modules.analysis.config import PROGRESS_EVERY, AnalysisConfig, load_config
from src.modules.analysis.entities import (
    TRANSIENT_FAILURES,
    AnalysisError,
    BatchReport,
    CallOutcome,
    NotAnalysable,
    Stage,
    StageResult,
    stage_for,
)
from src.modules.analysis.errors import ProviderError, redact
from src.modules.analysis.factory import get_asr_client, get_llm_client
from src.modules.analysis.limits import asr_cost_micro_usd, cap_state
from src.modules.analysis.models import (
    CallAnalysisStateModel,
    CallTranscriptModel,
)
from src.modules.analysis.providers.types import ASRClient, LLMClient
from src.modules.analysis.score import ScoreStage
from src.modules.analysis.score_writer import delete_score, existing_score
from src.modules.analysis.transcribe import TranscribeStage
from src.modules.audio.service import AudioService
from src.modules.calls.models import CallModel

log = get_logger(__name__)


# --- The three seams a test replaces ---------------------------------------


async def _asr(session: AsyncSession) -> ASRClient:
    return await get_asr_client(session)


async def _llm(session: AsyncSession) -> LLMClient:
    return await get_llm_client(session)


@asynccontextmanager
async def _session() -> AsyncIterator[AsyncSession]:
    """One session per call, from the process-wide maker.

    ``database.get_sessionmaker()`` and not a bound name: binding it makes it
    unpatchable and ``tests/test_layering.py`` fails on the import.
    """
    async with database.get_sessionmaker()() as session:
        yield session


@dataclass(slots=True)
class PipelineDeps:
    """Everything the pipeline reaches outside itself, in one replaceable place.

    This is what lets the whole pipeline run in a test with no vendor key, no
    network and no bill — and it is why there is **no "test mode" branch** in
    the production code, which could be switched on by accident on a live
    system.

    BonviZvonki's third seam, ``open_recording``, is gone: the recording is a
    local file reached through ``AudioService.analysis_source`` (§3), and
    ``modules/audio`` is the only module allowed to open it.
    """

    asr_factory: Callable[[AsyncSession], Awaitable[ASRClient]] = field(default=_asr)
    llm_factory: Callable[[AsyncSession], Awaitable[LLMClient]] = field(default=_llm)
    #: A fresh session per call in ``run_batch``. Each call commits at its own
    #: stage boundaries, so they cannot share one.
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]] = field(
        default=_session
    )


def default_deps() -> PipelineDeps:
    return PipelineDeps()


# --- The state row ----------------------------------------------------------


async def ensure_state(
    session: AsyncSession, call_id: uuid.UUID
) -> CallAnalysisStateModel:
    """The row, created if it is not there. Safe against a race.

    ``ON CONFLICT DO NOTHING`` and then a read, rather than "look, then
    insert": the button and the dispatch job can arrive on the same call within
    the same second, and the unique index is the only thing that settles it.
    """
    await session.execute(
        pg_insert(CallAnalysisStateModel)
        .values(call_id=call_id, stage=AnalysisStage.QUEUED)
        .on_conflict_do_nothing(index_elements=[CallAnalysisStateModel.call_id])
    )
    return (
        await session.execute(
            select(CallAnalysisStateModel).where(
                CallAnalysisStateModel.call_id == call_id
            )
        )
    ).scalar_one()


# --- One call ---------------------------------------------------------------


class AnalysisPipeline:
    """Runs one call, or a batch of them, against one settings snapshot."""

    def __init__(
        self, config: AnalysisConfig, deps: PipelineDeps | None = None
    ) -> None:
        self.config = config
        self.deps = deps or default_deps()
        self.transcribe_stage = TranscribeStage(self.deps, config)
        self.score_stage = ScoreStage(self.deps, config)

    async def process_call(self, call_id: uuid.UUID, *, force: bool = False) -> CallOutcome:
        """One call in a session of its own."""
        async with self.deps.session_factory() as session:
            return await self.process_in_session(session, call_id, force=force)

    async def process_in_session(
        self, session: AsyncSession, call_id: uuid.UUID, *, force: bool = False
    ) -> CallOutcome:
        started = perf_counter()
        outcome = CallOutcome(call_id=call_id, stage=AnalysisStage.QUEUED)

        call = await session.get(CallModel, call_id)
        if call is None:
            raise NotFoundError(ErrorCode.CALL_NOT_FOUND)
        outcome.call_type = call.call_type.value

        state = await ensure_state(session, call_id)
        state.attempts += 1
        state.last_run_at = clock.now()
        state.stage = AnalysisStage.TRANSCRIBING
        # A previous run's reason is cleared here and not at the end. The CHECK
        # says a reason is present exactly when the stage is failed or skipped,
        # so a retry that left the old code behind would be rejected by the
        # database the moment the stage moved to ``transcribing``.
        self._clear_failure(state)
        # COMMIT IMMEDIATELY, for the reasons spelled out in ``_run_stages``:
        # another session has to be able to see the attempt, and the row must
        # not stay locked for the tens of seconds a provider takes.
        await session.commit()

        try:
            await self._run_stages(session, call, state, outcome, force=force)
        except AnalysisError as exc:
            self._stop(state, outcome, exc.failure, exc.message, exc.stage)
        except ProviderError as exc:
            self._stop(
                state,
                outcome,
                AnalysisFailure(exc.code),
                redact(exc.message),
                self._stage_of(outcome),
            )
        except asyncio.CancelledError:
            # A cancelled call is a worker shutting down, not a failure of this
            # call. Leave the row mid-flight: ``analysis_stale_reset`` closes it
            # as ``interrupted``, which is transient and gets re-queued.
            raise
        except Exception as exc:
            # The mapping of last resort. The class name goes into the detail,
            # which is the difference between "something went wrong" and a line
            # somebody can act on.
            self._stop(
                state,
                outcome,
                AnalysisFailure.INTERNAL,
                f"{type(exc).__name__}: {redact(str(exc))}",
                self._stage_of(outcome),
            )
            log.exception("analysis_call_crashed", call_id=str(call_id))

        outcome.elapsed_ms = int((perf_counter() - started) * 1000)
        state.duration_ms = outcome.elapsed_ms
        await session.commit()
        return outcome

    async def _run_stages(
        self,
        session: AsyncSession,
        call: CallModel,
        state: CallAnalysisStateModel,
        outcome: CallOutcome,
        *,
        force: bool,
    ) -> None:
        # --- The free gate, re-checked here as well as in dispatch (§2.6) ---
        #
        # Re-checked because a row can sit in the queue for minutes and the
        # facts can move: ``reclassify_calls`` restamps ``call_type``, and
        # retention can take the audio. Cheap, and it is the difference between
        # a wasted provider call and a correctly recorded skip.
        self._assert_analysable(call)

        # --- Stage 1: the transcript ---------------------------------------
        #
        # ``flush()`` would not do. Two measured reasons:
        #
        # 1. A VISIBLE STAGE. ``flush()`` leaves the write inside the
        #    transaction, where nobody else can read it, and the transaction
        #    only closed when the whole pipeline finished — so "transcribing"
        #    was a state the database never showed. Checked on the system this
        #    is ported from: with a worker demonstrably busy on two calls, its
        #    state table held no row in that stage at all and the queue page
        #    said "empty".
        # 2. LOCKS. ``flush()`` locks the rows until the commit, and ASR + LLM
        #    + retries is tens of seconds (~60 s on a 429). Every other write
        #    touching those rows waited. Seen in ``pg_stat_activity``: the
        #    worker "idle in transaction" for 37 seconds and another query
        #    stuck on ``Lock: transactionid``.
        #
        # The price is that a process killed here leaves the call in
        # ``transcribing``. That is not damage, it is the intended outcome: a
        # stuck call is visible, ``analysis_stale_reset`` closes it, and the
        # next dispatch picks it up idempotently.
        transcribe, transcript = await self.transcribe_stage.run(
            session, call, force=force
        )
        outcome.transcribe = transcribe
        state.asr_calls += transcribe.provider_calls
        if transcribe.result is StageResult.DONE:
            state.transcribed_at = clock.now()
            # Only on DONE. A re-run that found the transcript already there
            # spent nothing, and adding the price again would inflate the very
            # number the monthly cap is measured against.
            self._charge(
                state,
                outcome,
                asr_cost_micro_usd(self.config, transcript.audio_duration_ms),
            )

        state.stage = AnalysisStage.SCORING
        # Same reason as above: the scoring stage has to be visible, and the
        # rows must not stay locked while the model thinks.
        await session.commit()

        if call.call_type is not CallType.EXTERNAL:
            # An internal call, transcribed because ``analysis.transcribe_internal``
            # is on, but NOT scored: a colleague conversation judged against a
            # sales rubric would lower an employee's average for no reason.
            #
            # AN OLD SCORE IS DELETED. The call may have been scored earlier,
            # when the line directory was empty and its type was ``unknown``.
            # Leaving that number puts the system at odds with itself: the page
            # says "not scored" while the analytics still counts it. A score is
            # derived data and can be recomputed; a false figure is one nobody
            # notices.
            if await delete_score(session, call.id):
                log.info(
                    "analysis_stale_score_removed",
                    call_id=str(call.id),
                    call_type=call.call_type.value,
                )
            raise NotAnalysable(
                "an internal call is transcribed but not scored",
                failure=AnalysisFailure.CALL_TYPE_INTERNAL,
                stage=Stage.SCORE,
            )

        # --- Stage 2: the score --------------------------------------------
        score = await self.score_stage.run(session, call, transcript, force=force)
        outcome.score = score
        state.llm_calls += score.provider_calls

        row = await existing_score(session, call.id)
        if row is not None:
            outcome.overall_score = row.overall_score
            outcome.needs_review = row.needs_review
        if score.result is StageResult.DONE:
            state.scored_at = clock.now()
            self._charge(state, outcome, (row.cost_micro_usd or 0) if row else 0)

        state.stage = AnalysisStage.COMPLETED
        self._clear_failure(state)
        outcome.stage = AnalysisStage.COMPLETED

    def _assert_analysable(self, call: CallModel) -> None:
        """The §2.6 gate, in the order that spends the least to decide.

        Every refusal here is a fact about the call rather than about the run,
        so all of them are recorded as ``skipped``. Two of them —
        ``call_type_unknown`` and ``call_type_internal`` — can stop being true,
        and dispatch statement (b) is what notices.
        """
        if call.call_type is CallType.UNKNOWN:
            # The line directory is empty, so this call cannot be told from a
            # colleague's. Never guessed: BonviZvonki defaulted the other way
            # and mislabelled 82 of 98 calls, which means scoring colleagues
            # against a sales rubric — money spent to lower somebody's average
            # unfairly.
            raise NotAnalysable(
                "the line directory does not say whether this call is internal",
                failure=AnalysisFailure.CALL_TYPE_UNKNOWN,
                stage=Stage.TRANSCRIBE,
            )
        if call.call_type is CallType.INTERNAL and not self.config.transcribe_internal:
            raise NotAnalysable(
                "internal calls are not transcribed (analysis.transcribe_internal)",
                failure=AnalysisFailure.CALL_TYPE_INTERNAL,
                stage=Stage.TRANSCRIBE,
            )
        if call.disposition is not CallDisposition.ANSWERED or not call.has_audio:
            # An unanswered call had no conversation, so there is nothing to
            # transcribe and — by the audio module's own attribution rule — no
            # recording either. One code covers both, and it is the honest one.
            raise NotAnalysable(
                "the call has no recording",
                failure=AnalysisFailure.NO_AUDIO,
                stage=Stage.TRANSCRIBE,
            )
        if (call.duration_sec or 0) < self.config.min_duration_sec:
            raise NotAnalysable(
                f"{call.duration_sec or 0}s is under the "
                f"{self.config.min_duration_sec}s floor",
                failure=AnalysisFailure.CALL_TOO_SHORT,
                stage=Stage.TRANSCRIBE,
            )

    # --- The state row ------------------------------------------------------

    @staticmethod
    def _charge(
        state: CallAnalysisStateModel, outcome: CallOutcome, micro_usd: int
    ) -> None:
        """Record what this run spent, on the row and on the outcome.

        The row's figure is the call's running total — the monthly cap sums it
        — while the outcome carries only what **this** run cost, which is what
        the batch report adds up.
        """
        if micro_usd <= 0:
            return
        state.cost_micro_usd += micro_usd
        outcome.cost_micro_usd += micro_usd

    @staticmethod
    def _clear_failure(state: CallAnalysisStateModel) -> None:
        state.failure_code = None
        state.failure_stage = None
        state.failure_detail = None

    @staticmethod
    def _stage_of(outcome: CallOutcome) -> Stage:
        """Which half was running when it stopped.

        Read off the outcome rather than tracked in a variable: the transcribe
        stage is recorded the moment it returns, so anything after that point
        belongs to scoring.
        """
        return Stage.SCORE if outcome.transcribe is not None else Stage.TRANSCRIBE

    def _stop(
        self,
        state: CallAnalysisStateModel,
        outcome: CallOutcome,
        failure: AnalysisFailure,
        detail: str,
        stage: Stage | None,
    ) -> None:
        """Record the stop. ``skipped`` or ``failed`` is decided by the code.

        Never by the exception class — see ``entities.stage_for``.
        """
        terminal = stage_for(failure)
        state.stage = terminal
        state.failure_code = failure
        state.failure_stage = (stage or self._stage_of(outcome)).value
        state.failure_detail = detail

        outcome.stage = terminal
        outcome.failure = failure
        outcome.failure_detail = detail

        if terminal is AnalysisStage.SKIPPED:
            log.info(
                "analysis_skipped",
                call_id=str(outcome.call_id),
                failure=str(failure),
                reason=detail,
            )
        else:
            log.error(
                "analysis_failed",
                call_id=str(outcome.call_id),
                stage=state.failure_stage,
                failure=str(failure),
                reason=detail,
            )

    # --- A batch ------------------------------------------------------------

    async def run_batch(
        self, call_ids: Sequence[uuid.UUID], *, force: bool = False
    ) -> BatchReport:
        """Run the list with bounded concurrency, one session per call.

        Progress is logged every ``PROGRESS_EVERY`` calls with the rate, so a
        queue that has stopped moving is visible from the log rather than from
        a database query somebody has to think of.
        """
        report = BatchReport(started_at=clock.now())
        semaphore = asyncio.Semaphore(max(1, self.config.concurrency))
        started = perf_counter()
        done = 0
        tally = asyncio.Lock()

        log.info(
            "analysis_batch_start",
            calls=len(call_ids),
            concurrency=self.config.concurrency,
            asr_rpm=self.config.asr_rpm,
            llm_rpm=self.config.llm_rpm,
            force=force,
        )

        async def worker(call_id: uuid.UUID) -> None:
            nonlocal done
            async with semaphore:
                try:
                    outcome = await asyncio.wait_for(
                        self.process_call(call_id, force=force),
                        timeout=self.config.call_timeout_sec,
                    )
                except TimeoutError:
                    # The row is left where it was; the state row still says
                    # ``transcribing``/``scoring`` and the stale reset closes
                    # it. Writing it from here would need a second session,
                    # since this one is gone with the cancelled task.
                    outcome = CallOutcome(
                        call_id=call_id,
                        stage=AnalysisStage.FAILED,
                        failure=AnalysisFailure.TIMEOUT,
                        failure_detail=(
                            f"not finished within {self.config.call_timeout_sec}s"
                        ),
                    )
                    log.error("analysis_call_timeout", call_id=str(call_id))
                except Exception as exc:
                    outcome = CallOutcome(
                        call_id=call_id,
                        stage=AnalysisStage.FAILED,
                        failure=AnalysisFailure.INTERNAL,
                        failure_detail=f"{type(exc).__name__}: {redact(str(exc))}",
                    )
                    log.exception("analysis_call_lost", call_id=str(call_id))

            async with tally:
                report.add(outcome)
                done += 1
                if done % PROGRESS_EVERY == 0 or done == len(call_ids):
                    elapsed = perf_counter() - started
                    log.info(
                        "analysis_progress",
                        done=done,
                        total=len(call_ids),
                        completed=report.completed,
                        failed=report.failed,
                        not_analysable=report.not_analysable,
                        needs_review=report.needs_review,
                        elapsed_sec=round(elapsed, 1),
                        calls_per_min=round(done / elapsed * 60, 1) if elapsed else 0,
                    )

        await asyncio.gather(*(worker(call_id) for call_id in call_ids))

        report.elapsed_sec = perf_counter() - started
        log.info("analysis_batch_done", **report.as_dict())
        return report


# ===========================================================================
#  The four job bodies (§5). ``jobs.py`` is the thin wrapper worker.py sees.
# ===========================================================================


def eligible_calls(config: AnalysisConfig, moment=None) -> sa.Select:
    """The §2.6 gate as one SELECT of call ids. No provider contact, no writes.

    ``disposition = 'answered'`` (an unanswered call has no conversation),
    a **live** recording, at least ``analysis.min_duration_sec`` of it, and
    ``call_type = 'external'``.

    THE AUDIO CONDITION IS NOT ``has_audio``. ``apply_retention`` deletes the
    blob, sets ``call_audio.deleted_at`` and leaves ``calls.has_audio`` true on
    purpose — the row is the record that a recording once existed. A gate that
    trusted the flag would queue calls whose bytes are gone and discover it one
    provider client at a time. ``AudioService.live_audio_call_ids()`` is the
    audio module's own answer to "is there still a file", which is where that
    rule belongs.

    ``duration_sec`` and ``disposition`` are already tied together by a CHECK on
    ``calls`` (``answered_has_duration``), so the duration rule cannot let an
    unanswered call through by accident.
    """
    since = (moment or clock.now()) - timedelta(hours=config.lookback_hours)
    return (
        select(CallModel.id)
        .where(
            CallModel.disposition == CallDisposition.ANSWERED,
            CallModel.has_audio.is_(True),
            CallModel.duration_sec >= config.min_duration_sec,
            CallModel.call_type == CallType.EXTERNAL,
            CallModel.received_at >= since,
            CallModel.id.in_(AudioService.live_audio_call_ids()),
        )
        .order_by(CallModel.received_at)
    )


async def dispatch(
    session: AsyncSession, config: AnalysisConfig | None = None
) -> int:
    """Queue what is eligible, and re-queue what has become eligible (§5).

    Two statements, both pure SQL, no provider contact, safe to run any number
    of times. Returns how many rows it queued or re-queued.
    """
    config = config or await load_config(session)
    if not config.enabled:
        return 0

    caps = await cap_state(session, config)
    if caps.blocked:
        # Queueing into a reached cap would build a backlog that only spends
        # money the moment somebody raises the cap, which is the opposite of
        # what a cap is for.
        log.warning("analysis_dispatch_capped", reason=caps.reason, cap=caps.reached)
        return 0

    queued = await _queue_new(session, config)
    requeued = await _requeue_recheckable(session, config)
    await session.commit()
    if queued or requeued:
        log.info("analysis_dispatched", queued=queued, requeued=requeued)
    return queued + requeued


async def _queue_new(session: AsyncSession, config: AnalysisConfig) -> int:
    """Statement (a): eligible calls with no state row at all."""
    candidates = eligible_calls(config).where(
        ~sa.exists().where(CallAnalysisStateModel.call_id == CallModel.id)
    )
    source = (
        select(sa.func.gen_random_uuid(), CallModel.id)
        .where(CallModel.id.in_(candidates.limit(config.max_calls_per_run)))
        # Only ``id`` and ``call_id`` are supplied: ``stage``, ``queued_at``,
        # the counters and the timestamps all have server defaults, and an
        # INSERT ... SELECT applies them. Listing them here would be a second
        # copy of the defaults, free to drift from ``models.py``.
        .order_by(CallModel.received_at)
    )
    statement = (
        pg_insert(CallAnalysisStateModel)
        .from_select(["id", "call_id"], source)
        # Belt and braces against a concurrent hand-run: the NOT EXISTS above
        # is evaluated at plan time, the unique index is the fact.
        .on_conflict_do_nothing(index_elements=[CallAnalysisStateModel.call_id])
    )
    result = await session.execute(statement)
    return int(result.rowcount or 0)


async def _requeue_recheckable(session: AsyncSession, config: AnalysisConfig) -> int:
    """Statement (b): ``skipped`` rows whose reason has stopped being true.

    This is what makes §2.6's self-healing real. A ``skipped`` row is not
    invisible to dispatch: once an admin fills the line directory and
    ``reclassify_calls`` restamps ``calls.call_type``, these calls re-enter the
    queue by themselves. Without it every call analysed before the directory
    existed would stay skipped for ever, and nobody would know to look.

    The two statements below are written against exactly the two members of
    :data:`~src.modules.analysis.entities.RECHECKABLE_SKIPS`.
    ``test_pipeline_shape`` is what fails if a third is ever added with no
    statement to match it — a reason that claims to heal itself and never does
    is the silent half of the failure §2.6 exists to prevent.

    Only the two reasons in ``RECHECKABLE_SKIPS`` are re-examined. The rest —
    no audio, expired audio, too short — are facts that will not change, and
    re-queueing them would be a loop that costs a provider call every lap.
    """
    requeued = 0

    # ``call_type_unknown`` whose call is no longer unknown.
    no_longer_unknown = select(CallModel.id).where(
        CallModel.call_type != CallType.UNKNOWN
    )
    requeued += await _requeue(
        session,
        AnalysisFailure.CALL_TYPE_UNKNOWN,
        no_longer_unknown,
    )

    # ``call_type_internal`` whose call is no longer internal — or which is
    # still internal, but internal calls are transcribed now. The setting is
    # part of the reason, so a change to it has to be re-checkable too.
    if config.transcribe_internal:
        no_longer_internal = select(CallModel.id)
    else:
        no_longer_internal = select(CallModel.id).where(
            CallModel.call_type != CallType.INTERNAL
        )
    requeued += await _requeue(
        session,
        AnalysisFailure.CALL_TYPE_INTERNAL,
        no_longer_internal,
    )
    return requeued


async def _requeue(
    session: AsyncSession, failure: AnalysisFailure, calls: sa.Select
) -> int:
    result = await session.execute(
        update(CallAnalysisStateModel)
        .where(
            CallAnalysisStateModel.stage == AnalysisStage.SKIPPED,
            CallAnalysisStateModel.failure_code == failure,
            CallAnalysisStateModel.call_id.in_(calls),
        )
        .values(
            stage=AnalysisStage.QUEUED,
            failure_code=None,
            failure_stage=None,
            failure_detail=None,
            # Back of the queue, not the front: it has waited, but a call that
            # arrived five minutes ago has not been analysed at all yet.
            queued_at=sa.func.now(),
        )
    )
    return int(result.rowcount or 0)


async def claim(session: AsyncSession, limit: int) -> list[uuid.UUID]:
    """Take up to ``limit`` queued rows, exclusively, and commit before working.

    ``FOR UPDATE SKIP LOCKED`` is the whole of BonviZvonki's ``CallLock``, done
    by the database: a second claimer steps over the locked rows instead of
    waiting for them, so two workers — or a scheduled run and a hand-run
    ``make job n=analysis_run`` — can never take the same call and pay for it
    twice.

    The ``UPDATE`` out of ``queued`` and the commit both happen **before any
    provider is touched**, which is what makes the exclusivity outlive the
    transaction.
    """
    if limit <= 0:
        return []
    rows = (
        (
            await session.execute(
                select(CallAnalysisStateModel.call_id)
                .where(CallAnalysisStateModel.stage == AnalysisStage.QUEUED)
                .order_by(CallAnalysisStateModel.queued_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    call_ids = list(rows)
    if not call_ids:
        return []
    await session.execute(
        update(CallAnalysisStateModel)
        .where(CallAnalysisStateModel.call_id.in_(call_ids))
        .values(
            stage=AnalysisStage.TRANSCRIBING,
            last_run_at=clock.now(),
            # The CHECK admits a reason only on a stopped row, so a re-claimed
            # failure must drop its old one in the same statement.
            failure_code=None,
            failure_stage=None,
            failure_detail=None,
        )
    )
    await session.commit()
    return call_ids


async def run_queue(
    session: AsyncSession,
    *,
    config: AnalysisConfig | None = None,
    deps: PipelineDeps | None = None,
) -> int:
    """Claim and process a slice of the queue. **The only job that spends money.**

    Everything that could stop it does so here, before a single row is claimed:
    the feature flag, then both monthly caps. Nothing below this function limits
    anything — a loop over ``get_asr_client()`` would bill without bound.
    """
    config = config or await load_config(session)
    if not config.enabled:
        return 0

    caps = await cap_state(session, config)
    if caps.blocked:
        # Logged at warning with the cap that tripped, because the two need
        # different actions: a call cap is raised by a person who has decided
        # to spend more, a cost cap by one who has checked the invoice.
        #
        # NOTE: §4.5 also asks for an ``analysis_cost_cap_reached`` alert here.
        # ``AlertKind`` has no such member yet — see the task report — and
        # raising a neighbouring kind would send somebody to the wrong
        # subsystem, so this stays a log line until the enum value lands.
        log.warning(
            "analysis_cost_cap_reached",
            cap=caps.reached,
            reason=caps.reason,
            calls=caps.usage.calls,
            cost_micro_usd=caps.usage.cost_micro_usd,
        )
        return 0

    call_ids = await claim(session, config.concurrency * 4)
    if not call_ids:
        return 0

    pipeline = AnalysisPipeline(config, deps)
    report = await pipeline.run_batch(call_ids)
    return report.total


def select_transient_failures(
    config: AnalysisConfig, *, moment=None, limit: int = 2000
) -> sa.Select:
    """Rows that failed for a reason that repairs itself (§5).

    WHY THIS IS A SEPARATE SELECT. Dispatch works on a ``received_at`` window;
    widening that window to reach old failures would change every caller,
    including an operator asking for one particular week. This is its own
    query, and only the nightly job runs it.

    WHY IT EXISTS AT ALL. The nightly run used to re-read a 48-hour window and
    nothing else. Measured: 885 calls had failed on a rate limit and most were
    older than two days, so they were permanently ``failed`` — the quota reset
    the next morning and nothing ever looked at them again. Not a bug anyone
    saw; a forgotten population.

    Oldest ``last_run_at`` first, so a backlog drains instead of the same fresh
    rows being retried every night while the old ones never reach the front.
    """
    cutoff = (moment or clock.now()) - timedelta(days=config.retry_transient_days)
    return (
        select(CallAnalysisStateModel.call_id)
        .where(
            CallAnalysisStateModel.stage == AnalysisStage.FAILED,
            CallAnalysisStateModel.failure_code.in_(sorted(TRANSIENT_FAILURES)),
            CallAnalysisStateModel.last_run_at >= cutoff,
        )
        .order_by(CallAnalysisStateModel.last_run_at.asc())
        .limit(limit)
    )


async def requeue_transient(
    session: AsyncSession, config: AnalysisConfig | None = None
) -> int:
    """Put transient failures back in the queue. Returns how many."""
    config = config or await load_config(session)
    if not config.enabled:
        return 0
    result = await session.execute(
        update(CallAnalysisStateModel)
        .where(
            CallAnalysisStateModel.call_id.in_(select_transient_failures(config))
        )
        .values(
            stage=AnalysisStage.QUEUED,
            failure_code=None,
            failure_stage=None,
            failure_detail=None,
            queued_at=sa.func.now(),
        )
    )
    await session.commit()
    count = int(result.rowcount or 0)
    if count:
        log.info("analysis_transient_requeued", calls=count)
    return count


async def reset_stale_running(
    session: AsyncSession, config: AnalysisConfig | None = None
) -> int:
    """Close rows stuck in a running stage (§5).

    The pipeline commits at every stage boundary on purpose, which means a
    killed worker leaves a visible half-finished row rather than an invisible
    rollback. This is what closes them; the next dispatch or nightly retry
    picks them up, because ``interrupted`` is transient.

    ``last_run_at IS NULL`` is left alone: that row never ran, so there is
    nothing stale about it.

    Twice ``analysis.call_timeout_sec``, not once: a call that is exactly at
    its own ceiling is being cancelled by ``run_batch`` at that moment, and two
    writers closing the same row from different angles is the race this margin
    avoids.
    """
    config = config or await load_config(session)
    cutoff = clock.now() - timedelta(seconds=2 * config.call_timeout_sec)
    result = await session.execute(
        update(CallAnalysisStateModel)
        .where(
            CallAnalysisStateModel.stage.in_(
                [AnalysisStage.TRANSCRIBING, AnalysisStage.SCORING]
            ),
            CallAnalysisStateModel.last_run_at.is_not(None),
            CallAnalysisStateModel.last_run_at < cutoff,
        )
        .values(
            stage=AnalysisStage.FAILED,
            failure_code=AnalysisFailure.INTERRUPTED,
            # The old stage names which half was interrupted. Evaluated against
            # the row as it was, so the CASE reads the pre-update value.
            failure_stage=sa.case(
                (
                    CallAnalysisStateModel.stage == AnalysisStage.TRANSCRIBING,
                    Stage.TRANSCRIBE.value,
                ),
                else_=Stage.SCORE.value,
            ),
            failure_detail=(
                "the run did not finish; the worker was restarted or the call "
                "exceeded analysis.call_timeout_sec"
            ),
        )
    )
    await session.commit()
    count = int(result.rowcount or 0)
    if count:
        log.warning("analysis_stale_reset", calls=count)
    return count


async def queue_call(
    session: AsyncSession, call_id: uuid.UUID, *, force: bool = False
) -> CallAnalysisStateModel:
    """Put one call at the front of the queue — the panel's button (§6.2).

    Never runs a provider call: the worker picks it up within two minutes. An
    LLM round trip behind an HTTP request is how a panel times out and a user
    presses the button again.

    ``force`` additionally clears the transcript and the score so both are
    recomputed, and that is the only path in the product that spends money
    twice on one call.
    """
    state = await ensure_state(session, call_id)
    if force:
        await delete_score(session, call_id)
        transcript = await session.execute(
            sa.delete(CallTranscriptModel).where(
                CallTranscriptModel.call_id == call_id
            )
        )
        log.info(
            "analysis_force_requeued",
            call_id=str(call_id),
            transcripts_removed=int(transcript.rowcount or 0),
        )
        state.asr_calls = 0
        state.llm_calls = 0
        state.transcribed_at = None
        state.scored_at = None
        state.cost_micro_usd = 0
    state.stage = AnalysisStage.QUEUED
    state.failure_code = None
    state.failure_stage = None
    state.failure_detail = None
    state.queued_at = clock.now()
    await session.flush()
    return state
