"""The panel's reads, and the button that queues one call (SPEC-ANALYTICS §6.2).

This is the read half of the module. The write half — rewinding the state
machine — is ``pipeline.queue_call``, and it stays beside the state machine;
what happens here is the four refusals that decide whether the button may be
pressed at all, and the transaction around the rewind.

**Visibility is not re-implemented here.** ``CallService.get(principal, id)``
decides which calls a principal can see, so a call belonging to another agent
is a 404 exactly as it is everywhere else (§4.1 rule 2) — a 403 would confirm
the row exists, which tells a salesperson that a colleague spoke to a given
number. The list is narrowed by :meth:`AnalysisService._scoped`, which is
``DeviceService._scoped``'s shape keyed on the fleet-wide permission over
*calls*, because these rows are facts about calls.

**Nothing here contacts a provider.** An LLM round trip behind an HTTP request
is how a panel times out and a user presses the button a second time. The
button writes a queued row and the worker picks it up within two minutes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.clock import TASHKENT
from src.core.deps import Principal
from src.core.enums import AnalysisFailure, AnalysisStage
from src.core.errors import ConflictError, ErrorCode
from src.core.pagination import Cursor, Page, apply_keyset
from src.core.permissions import Perm
from src.core.settings_keys import SettingKey
from src.modules.analysis.config import AnalysisConfig, load_config
from src.modules.analysis.entities import NotAnalysable
from src.modules.analysis.errors import ProviderConfigError, redact
from src.modules.analysis.factory import resolve
from src.modules.analysis.limits import CapState, cap_state, month_start
from src.modules.analysis.models import (
    AiProviderCooldownModel,
    CallAnalysisStateModel,
    CallScoreModel,
    CallTranscriptModel,
)
from src.modules.analysis.pipeline import (
    AnalysisPipeline,
    queue_call,
    select_transient_failures,
)
from src.modules.analysis.providers.types import ROLE_ASR, ROLE_LLM
from src.modules.analysis.schemas import (
    SCORE_BAND_RANGE,
    AnalysisCallHeader,
    AnalysisFailureRow,
    AnalysisFilters,
    AnalysisListItem,
    AnalysisMonthResponse,
    AnalysisStageCounts,
    AnalysisStateResponse,
    AnalysisStatusResponse,
    CallAnalysisResponse,
    NotAnalysableCount,
    ProviderCooldownResponse,
    ScoreResponse,
    TranscriptResponse,
)
from src.modules.calls.models import CallModel
from src.modules.calls.service import CallService
from src.modules.settings.service import SettingsService

#: ``GET /analysis/status`` returns this many failures and no more, server-side.
#: A page that exists to answer "what broke" needs the last few, not a history:
#: none of the three endpoints is a list endpoint and SPEC §4.7's cursor
#: conventions do not apply to them (§6.2).
RECENT_FAILURE_LIMIT = 20


class AnalysisService:
    """One call's analysis, the list, the operational view, and the button."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.calls = CallService(session)

    # --- Scope ------------------------------------------------------------

    def _scoped(self, statement: sa.Select, principal: Principal) -> sa.Select:
        """Narrow to the principal's own agent unless they see every call.

        Keyed on ``calls:read`` and not on ``analysis:read``: these rows are
        facts about calls, and whoever may see the call may see what the
        pipeline made of it. Today the question never arises — ``analysis:read``
        is granted to ``admin`` and ``manager``, both of whom hold ``calls:read``
        (§6.1), and ``sales`` holds neither, so a salesperson is refused by the
        router with a 403 before reaching this. The narrowing is written anyway
        because §12 Q1 records that reversing that decision is "this line plus a
        ``:own`` scope in the query" — and this is that scope, already correct on
        the day somebody adds the grant.
        """
        if principal.has(Perm.CALLS_READ):
            return statement
        # A principal with own-scope and no linked agent sees nothing rather
        # than everything, exactly as ``CallService._scoped`` decides it.
        return statement.where(CallModel.agent_id == principal.agent_id)

    # --- One call (§6.2, §7.4) --------------------------------------------

    async def get_call(
        self, principal: Principal, call_id: uuid.UUID
    ) -> CallAnalysisResponse:
        """One call's analysis, whether or not it has ever been analysed.

        A call the pipeline has never touched answers 200 with ``state``,
        ``transcript`` and ``score`` all null — **not 404**. 404 here would mean
        "no such call", and the page has to be able to tell that apart from
        "not analysed yet": one of them offers a button and the other does not.
        """
        call = await self.calls.get(principal, call_id)
        # One settings row, not ``load_config``: this page needs the flag and
        # nothing else, and the full snapshot is twenty-two round trips to
        # learn one boolean on the most-read of the four endpoints.
        enabled = await SettingsService(self.session).get_bool(
            SettingKey.ANALYSIS_ENABLED
        )

        state = await self._state_of(call.id)
        transcript = await self.session.scalar(
            select(CallTranscriptModel).where(CallTranscriptModel.call_id == call.id)
        )
        score = await self.session.scalar(
            select(CallScoreModel).where(CallScoreModel.call_id == call.id)
        )
        return CallAnalysisResponse(
            call_id=call.id,
            enabled=enabled,
            call=(await self._headers([call]))[0],
            state=AnalysisStateResponse.model_validate(state) if state else None,
            transcript=(
                TranscriptResponse.model_validate(transcript) if transcript else None
            ),
            score=ScoreResponse.model_validate(score) if score else None,
        )

    # --- The list (§7.3) ---------------------------------------------------

    async def list(
        self,
        principal: Principal,
        limit: int,
        cursor: Cursor | None = None,
        with_total: bool = False,
        filters: AnalysisFilters | None = None,
    ) -> Page[AnalysisListItem]:
        """A cursor page of analysed calls, ordered ``started_at DESC, id DESC``.

        **Every call the pipeline has touched, not only the scored ones.** The
        page is called "Baholashlar" and the scores are what a reader comes for,
        but §7.3 puts ``stage`` in the columns and in the filters — and a stage
        filter over scored rows only would answer "failed: nothing found" on a
        day when the queue is full of failures, which is the one day it is asked.

        Ordered on ``started_at`` and not ``received_at`` because this list is
        read as a diary of conversations (§7.3); the tiebreak is ``id``, without
        which paging duplicates the rows whose sort values tie.
        """
        statement = self._filtered(principal, filters)

        total = None
        if with_total:
            total = await self.session.scalar(
                select(func.count()).select_from(statement.subquery())
            )

        paged = apply_keyset(
            statement, CallModel.started_at, CallModel.id, cursor, descending=True
        ).limit(limit + 1)
        rows = list((await self.session.execute(paged)).all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            Cursor(rows[-1][0].started_at, rows[-1][0].id).encode()
            if has_more and rows
            else None
        )
        return Page(
            items=await self._items(rows),
            next_cursor=next_cursor,
            has_more=has_more,
            total=total,
        )

    def _filtered(
        self, principal: Principal, filters: AnalysisFilters | None
    ) -> sa.Select:
        """The scoped, filtered query the list and its count both run.

        One builder, so the ``total`` on screen and the rows under it cannot
        disagree — the rule ``CallService._filtered`` exists for.

        ``call_scores`` is an OUTER join: a queued or failed call has no score
        and must still appear, which is the difference between a queue somebody
        can watch and a list that only shows finished work.
        """
        statement = self._scoped(
            select(CallModel, CallAnalysisStateModel, CallScoreModel)
            .join(
                CallAnalysisStateModel,
                CallAnalysisStateModel.call_id == CallModel.id,
            )
            .outerjoin(CallScoreModel, CallScoreModel.call_id == CallModel.id),
            principal,
        )
        if filters is None:
            return statement

        if filters.agent_id:
            statement = statement.where(CallModel.agent_id.in_(filters.agent_id))
        if filters.stage:
            statement = statement.where(CallAnalysisStateModel.stage.in_(filters.stage))
        if filters.needs_review is not None:
            # ``is_(False)`` and not ``!= True``: an unscored call has a NULL
            # here, and NULL is neither. "Not flagged" means scored and cleared,
            # which is the question a reviewer is actually asking.
            statement = statement.where(
                CallScoreModel.needs_review.is_(filters.needs_review)
            )
        if filters.score_band:
            # ``SCORE_BAND_RANGE`` is keyed by the same four names the field is
            # typed as, so an unknown band is refused by Pydantic and never
            # reaches a lookup here — one validation point, in the schema,
            # where §2 says field shape belongs.
            statement = statement.where(
                sa.or_(
                    *(
                        CallScoreModel.overall_score.between(
                            *SCORE_BAND_RANGE[band]
                        )
                        for band in filters.score_band
                    )
                )
            )
        # Business dates are Asia/Tashkent calendar days against ``started_at``:
        # a call made yesterday and uploaded today belongs to yesterday (D-08).
        if filters.date_from is not None:
            statement = statement.where(
                CallModel.started_at
                >= datetime.combine(filters.date_from, time.min, tzinfo=TASHKENT)
            )
        if filters.date_to is not None:
            statement = statement.where(
                CallModel.started_at
                < datetime.combine(filters.date_to, time.min, tzinfo=TASHKENT)
                + timedelta(days=1)
            )
        return statement

    async def _items(self, rows: list[sa.Row]) -> list[AnalysisListItem]:
        """Page rows to what the list renders, in a fixed number of queries."""
        headers = await self._headers([row[0] for row in rows])
        return [
            AnalysisListItem(
                call=header,
                stage=state.stage,
                failure_code=state.failure_code,
                overall_score=score.overall_score if score else None,
                needs_review=bool(score and score.needs_review),
                red_flag_types=_red_flag_types(score),
                scored_at=score.scored_at if score else None,
            )
            for header, (_call, state, score) in zip(headers, rows, strict=True)
        ]

    async def _headers(self, calls: list[CallModel]) -> list[AnalysisCallHeader]:
        """The call facts §7.4 asks for, resolved for a whole page at once.

        Built on ``CallService.views``, which resolves the agent's name for the
        page in one query rather than one per row. It answers more than this
        needs — the registered line, the handset model, the audio summary — and
        that is two round trips this page does not use. It is still the right
        call: the alternative is a second implementation of "enrich a list of
        calls", and a per-row name lookup here would be the N+1 that is fine at
        fifty rows and fatal at fifty thousand.
        """
        return [
            AnalysisCallHeader(
                call_id=view.id,
                started_at=view.started_at,
                agent_id=view.agent_id,
                agent_name=view.agent_name,
                remote_number=view.remote_number,
                duration_sec=view.duration_sec,
                direction=view.direction,
                disposition=view.disposition,
                call_type=view.call_type,
            )
            for view in await self.calls.views(calls)
        ]

    # --- The button (§6.2) -------------------------------------------------

    async def queue(
        self, principal: Principal, call_id: uuid.UUID, *, force: bool = False
    ) -> AnalysisStateResponse:
        """Queue one call now. Returns the state row, created or not.

        Re-posting is indistinguishable from the first post: the response is
        always 200 with the same state object, which is §5's idempotency shape
        applied to a panel write. ``force`` additionally clears the transcript
        and the score so both are recomputed — **the only path in the product
        that spends money twice on one call**.

        The four refusals run in §6.2's order, which is also cheapest first:
        the feature flag, then this call's own facts, then the month's caps,
        then whether a provider is configured at all. None of them contacts a
        vendor.
        """
        call = await self.calls.get(principal, call_id)
        config = await load_config(self.session)

        if not config.enabled:
            raise ConflictError(ErrorCode.ANALYSIS_DISABLED)

        self._assert_analysable(call, config)

        caps = await cap_state(self.session, config)
        if caps.blocked:
            # Which cap, in the detail: "raise the price cap" and "raise the
            # call cap" are different actions taken by different people for
            # different reasons (§4.5).
            raise ConflictError(
                ErrorCode.ANALYSIS_COST_CAP_REACHED,
                detail={"cap": caps.reached, "reason": caps.reason},
            )

        await self._assert_ai_configured()

        state = await queue_call(self.session, call.id, force=force)
        # ``queue_call`` flushes; the service owns the transaction (§2).
        await self.session.commit()
        return AnalysisStateResponse.model_validate(state)

    @staticmethod
    def _assert_analysable(call: CallModel, config: AnalysisConfig) -> None:
        """§2.6's gate, evaluated by the pipeline's own copy of it.

        Deliberately not re-written here. ``config.py`` records what two copies
        of one analysis rule cost the system this is ported from: the dispatch
        gate read ``min_duration_sec`` from the environment and the pre-run
        check read it from settings, the two said 30 and 10, and the button
        reported "0 calls" while the setting looked applied. The button and the
        worker have to refuse the same calls or the button is a lie, so there is
        one evaluation of the rule and this asks it.

        One case it deliberately does not cover: when retention deletes a
        recording it leaves ``calls.has_audio`` true — the row is the record
        that a recording once existed — so such a call is queued here and the
        worker records ``audio_expired`` at the transcribe stage, having spent
        nothing (§2.6). Catching it here would mean this method asking audio
        storage whether the bytes are still there, and no module outside
        ``modules/audio`` may do that.

        Constructing a pipeline for one gate is cheap: its two stages hold a
        rate limiter and a cooldown handle and touch neither network nor
        database until they are run.
        """
        try:
            AnalysisPipeline(config)._assert_analysable(call)
        except NotAnalysable as refusal:
            raise ConflictError(
                ErrorCode.CALL_NOT_ANALYSABLE,
                detail={"rule": refusal.failure.value, "reason": refusal.message},
            ) from refusal

    async def _assert_ai_configured(self) -> None:
        """Both roles resolve to a provider, a model and a key — or 409.

        Checked before the row is queued rather than discovered by the worker:
        a queue filling up with calls that cannot run is a backlog that spends
        money the moment somebody fixes the key, and the person pressing the
        button is the one who can fix it now.

        ``resolve`` reads two settings rows and one environment value. No
        network, no SDK import, nothing that can hang inside a request.
        """
        for role in (ROLE_ASR, ROLE_LLM):
            try:
                await resolve(self.session, role)
            except ProviderConfigError as exc:
                raise ConflictError(
                    ErrorCode.AI_NOT_CONFIGURED,
                    detail={"role": str(role), "reason": redact(exc.message)},
                ) from exc

    # --- The operational view (§7.5) ---------------------------------------

    async def status(self, principal: Principal) -> AnalysisStatusResponse:
        """Counts per stage, what broke, who is in cooldown, what the month cost.

        The aggregates are fleet-wide and the failure rows are scoped. That
        split is deliberate: "how many calls are queued" is a fact about the
        pipeline and tells nobody whose calls they are, while a failure row
        carries a ``call_id``, so it goes through the same narrowing as the list.
        """
        config = await load_config(self.session)
        caps = await cap_state(self.session, config)

        return AnalysisStatusResponse(
            enabled=config.enabled,
            stages=await self._stage_counts(),
            waiting_retry=await self._waiting_retry(config),
            not_analysable=await self._skip_counts(),
            cooldowns=await self._cooldowns(),
            month=await self._month(config, caps),
            recent_failures=await self._recent_failures(principal),
        )

    async def _stage_counts(self) -> AnalysisStageCounts:
        """One GROUP BY, not six COUNTs."""
        rows = (
            await self.session.execute(
                select(CallAnalysisStateModel.stage, func.count()).group_by(
                    CallAnalysisStateModel.stage
                )
            )
        ).all()
        # Absent stages stay at the schema's zero, so the panel draws six bars
        # on a quiet day instead of defaulting missing keys itself.
        return AnalysisStageCounts(**{stage.value: count for stage, count in rows})

    async def _waiting_retry(self, config: AnalysisConfig) -> int:
        """Failures the nightly job will pick up by itself.

        Counted through ``select_transient_failures`` rather than through a
        second definition of "transient": getting that membership wrong is how
        885 rate-limited calls stayed permanently failed after the quota they
        were waiting on had reset (§5).
        """
        return int(
            await self.session.scalar(
                select(func.count()).select_from(
                    select_transient_failures(config).subquery()
                )
            )
            or 0
        )

    async def _skip_counts(self) -> list[NotAnalysableCount]:
        """Skips by reason, largest first.

        ``skipped`` is not a failure (§2.4). This is what makes "412 calls are
        waiting on the line directory" visible rather than silent — two of these
        reasons stop being true by themselves once an admin fills the directory.
        """
        rows = (
            await self.session.execute(
                select(CallAnalysisStateModel.failure_code, func.count())
                .where(CallAnalysisStateModel.stage == AnalysisStage.SKIPPED)
                .group_by(CallAnalysisStateModel.failure_code)
                .order_by(func.count().desc())
            )
        ).all()
        return [
            NotAnalysableCount(code=code, calls=count)
            for code, count in rows
            if code is not None
        ]

    async def _cooldowns(self) -> list[ProviderCooldownResponse]:
        """The roles sitting out right now. Expired rows are not "a cooldown"."""
        now = clock.now()
        rows = (
            (
                await self.session.execute(
                    select(AiProviderCooldownModel)
                    .where(AiProviderCooldownModel.until_at > now)
                    .order_by(AiProviderCooldownModel.until_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return [
            ProviderCooldownResponse(
                role=row.role.value,
                # Rounded up, as ``ProviderCooldown.remaining`` rounds it: a
                # cooldown with 0.4 s left has not ended.
                seconds_left=max(0, int((row.until_at - now).total_seconds() + 0.999)),
                reason_code=row.reason_code,
                started_at=row.started_at,
                until_at=row.until_at,
                detail=row.detail,
            )
            for row in rows
        ]

    async def _month(
        self, config: AnalysisConfig, caps: CapState
    ) -> AnalysisMonthResponse:
        """The month's measured units and cost, against both caps.

        The units are reported beside the cost on purpose: while no vendor
        price has been entered every call costs 0, and a panel rendering
        "$0.00" would say the feature is free. ``priced`` is what stops that
        (§11.1), and the minutes and tokens are the measurement task 12 turns
        into a real per-call figure.
        """
        since = month_start()
        audio_ms = int(
            await self.session.scalar(
                select(
                    func.coalesce(func.sum(CallTranscriptModel.audio_duration_ms), 0)
                ).where(CallTranscriptModel.transcribed_at >= since)
            )
            or 0
        )
        tokens = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(CallScoreModel.prompt_tokens), 0),
                    func.coalesce(func.sum(CallScoreModel.completion_tokens), 0),
                ).where(CallScoreModel.scored_at >= since)
            )
        ).one()
        return AnalysisMonthResponse(
            date_from=since.astimezone(TASHKENT).date(),
            calls=caps.usage.calls,
            # Whole minutes, rounded half up — the same arithmetic
            # ``asr_cost_micro_usd`` bills on, so the figure on screen and the
            # figure in the cap describe the same audio.
            audio_minutes=(audio_ms + 30_000) // 60_000,
            prompt_tokens=int(tokens[0]),
            completion_tokens=int(tokens[1]),
            cost_micro_usd=caps.usage.cost_micro_usd,
            priced=config.priced,
            cap_micro_usd=caps.cap_micro_usd,
            cap_calls=caps.cap_calls,
        )

    async def _recent_failures(self, principal: Principal) -> list[AnalysisFailureRow]:
        """The last twenty failures, newest attempt first.

        Scoped like the list: these rows name a call. Ordered on ``last_run_at``
        because the question is "what broke most recently", and a row whose run
        never started has nothing to say here — it is still queued.
        """
        rows = (
            await self.session.execute(
                self._scoped(
                    select(CallAnalysisStateModel, CallModel.started_at)
                    .join(CallModel, CallModel.id == CallAnalysisStateModel.call_id)
                    .where(CallAnalysisStateModel.stage == AnalysisStage.FAILED),
                    principal,
                )
                .order_by(
                    CallAnalysisStateModel.last_run_at.desc().nullslast(),
                    CallAnalysisStateModel.call_id.desc(),
                )
                .limit(RECENT_FAILURE_LIMIT)
            )
        ).all()
        return [
            AnalysisFailureRow(
                call_id=state.call_id,
                started_at=started_at,
                stage=state.failure_stage,
                # A ``failed`` row always carries a code — the ``stopped_has_reason``
                # CHECK says so — and the fallback keeps a read endpoint from
                # 500ing if one ever did not.
                code=state.failure_code or AnalysisFailure.INTERNAL,
                detail=state.failure_detail,
                attempts=state.attempts,
                last_run_at=state.last_run_at,
            )
            for state, started_at in rows
        ]

    # --- Shared helpers ----------------------------------------------------

    async def _state_of(self, call_id: uuid.UUID) -> CallAnalysisStateModel | None:
        return await self.session.scalar(
            select(CallAnalysisStateModel).where(
                CallAnalysisStateModel.call_id == call_id
            )
        )


def _red_flag_types(score: CallScoreModel | None) -> list[str]:
    """The chips for one row: the types, sorted and de-duplicated.

    The quotes and timestamps stay behind on the detail page. A list of fifty
    conversations is not a place to ship fifty customers' words, and the chips
    only need to say *what* was flagged.
    """
    if score is None:
        return []
    return sorted(
        {
            str(flag["type"])
            for flag in score.red_flags
            if isinstance(flag, dict) and flag.get("type")
        }
    )


__all__ = ["RECENT_FAILURE_LIMIT", "AnalysisService"]
