"""The six analytics aggregates (SPEC-ANALYTICS phase 2).

Ported from ``../BonviZvonki/services/backend/src/modules/analytics/application/
services.py`` and rewired onto BonviCall's tables: their ``calls`` is our
``calls``, their ``call_scores`` is our ``call_scores``. Their ``surveys`` and
``clients`` joins do not come across — the CSAT survey channel is phase 3 and
this product holds neither table — so the client rating, the AI/client
divergence and the "rated but no calls" tail are gone rather than faked.

**This module owns no table** (CONVENTIONS.md §2.1). It is declared in
``core/reads.py``, it reads three other modules' models, it issues projections
and aggregates only — never a bare entity select — and it writes nothing. What
crosses back out is ``analytics/schemas.py``'s own types. (That sentence avoids
spelling the forbidden expression out: ``test_layering`` greps for it textually,
and a docstring quoting the rule fails the rule.)

Everything here is one GROUP BY rather than a loop over rows. That is the whole
reason the §2.1 exception exists: assembling six dashboard panels from per-row
service calls is fine over fifty scored calls and fatal over fifty thousand,
and the version somebody replaces it with later is a raw query nobody reviews.

Four seams changed from their code, each because BonviCall already decided the
question:

* **The window is Asia/Tashkent calendar days, half-open in instants.** Theirs
  was ``started_at <= date_to`` with an ``_inclusive_end`` helper pushing a bare
  date to 23:59:59.999999, and a comment recording that without it the last
  day's work vanished from the screen. Here the house rule (D-08,
  ``CallService._filtered``) gives the same answer without the helper.
* **The trend truncates in Asia/Tashkent, not in UTC.** ``date_trunc('day',
  started_at)`` runs in the session's zone, which is UTC here, so a call at
  02:00 Tashkent would be drawn on the previous day and the 22:00 spike would
  land on the next one. ``timezone(<zone>, started_at)`` first is the fix.
* **There is no ``status = completed`` condition**, because BonviCall has no
  such column: a call row *is* a completed call, and where the pipeline stands
  lives in ``call_analysis_state`` (SPEC-ANALYTICS §2.4). The inner join to
  ``call_scores`` is what narrows the score panels.
* **One filter builder.** Theirs needed two — ``_apply`` mixed score predicates
  into the WHERE, so ``_call_type_counts`` had to repeat the date and agent
  conditions by hand and carried a warning about keeping them in step. With the
  score filters out of the set (§7.3 keeps date range, agent and call type),
  every query here goes through :meth:`AnalyticsService._filtered`.
"""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy import Select, case, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.clock import TASHKENT
from src.core.deps import Principal
from src.core.enums import CallType
from src.core.permissions import Perm
from src.modules.agents.models import AgentModel
from src.modules.analysis.entities import BLOCK_MAX
from src.modules.analysis.models import CallScoreModel
from src.modules.analysis.rubric_service import RubricService
from src.modules.analytics import rules
from src.modules.analytics.schemas import (
    AgentRankingResponse,
    AgentRankRowOut,
    AnalyticsFilters,
    AnalyticsOverviewResponse,
    AnalyticsTimeseriesResponse,
    AnalyticsWindow,
    BlockBreakdownResponse,
    BlockScoreOut,
    Bucket,
    CallTypeCountsOut,
    CountMetricOut,
    RedFlagBreakdownResponse,
    RedFlagCountOut,
    ScoreBucketOut,
    ScoreDistributionResponse,
    ScoreMetricOut,
    TimeseriesPointOut,
)
from src.modules.calls.models import CallModel

#: ``{block key: maximum}``, **derived from the rubric** and flattened to plain
#: strings so a JSONB key can be looked up without constructing an enum that
#: would raise on a key a later rubric adds. ``BLOCK_MAX`` itself is built from
#: ``DEFAULT_RUBRIC`` at import: the two were once typed separately, diverged
#: 25 against 15, and the radar chart drew 106 %.
#
# **This is the FALLBACK, not the source.** It was the source until the
# ``rubrics`` table landed (migration 012); :meth:`AnalyticsService._block_max`
# now reads the active row and falls back to this when the table is empty —
# BonviZvonki's ``_rubric_block_limits``, which is the function their 106 % bar
# was fixed in. Reading a constant while an admin edits the rubric in the panel
# is exactly how that bar comes back.
BLOCK_MAX_BY_KEY: dict[str, int] = {str(block): limit for block, limit in BLOCK_MAX.items()}

#: The histogram's bands: 0-9 … 80-89, then 90-100. Ten, always all ten.
SCORE_BAND_WIDTH = 10
SCORE_BAND_FLOORS: tuple[int, ...] = tuple(range(0, 100, SCORE_BAND_WIDTH))
TOP_SCORE = 100


def _whole_seconds(value: object) -> int:
    """A mean duration as whole seconds; 0 where nothing was measured.

    Zero rather than null because ``duration_sec`` is ``NOT NULL DEFAULT 0``
    and the card reads "o'rtacha davomiylik" — over no calls, zero is the
    truthful figure and a dash would suggest the column was missing.
    """
    rounded = rules.round_half_up(value) if value is not None else None
    return rounded if rounded is not None else 0


class AnalyticsService:
    """Read-only aggregates over ``calls``, ``call_scores`` and ``agents``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- Scope -------------------------------------------------------------

    def _scoped(self, statement: Select, principal: Principal) -> Select:
        """Narrow to the principal's own agent unless they see every call.

        ``AnalysisService._scoped``'s shape, keyed on ``calls:read`` for the
        same reason: these rows are facts about calls, and whoever may see the
        call may see what the pipeline made of it. Today the branch is not
        reachable through the router — ``analysis:read`` belongs to ``admin``
        and ``manager``, both of whom hold ``calls:read``, and ``sales`` holds
        neither — but the narrowing is written and tested anyway, because
        SPEC-ANALYTICS §12 Q1 records that granting a salesperson their own
        scores is "this line plus a ``:own`` scope in the query", and this is
        that scope, already correct on the day somebody adds the grant.
        """
        if principal.has(Perm.CALLS_READ):
            return statement
        # A principal with own-scope and no linked agent sees nothing rather
        # than everything, exactly as ``CallService._scoped`` decides it.
        return statement.where(CallModel.agent_id == principal.agent_id)

    # --- The one filter builder --------------------------------------------

    def _filtered(
        self, statement: Select, principal: Principal, filters: AnalyticsFilters
    ) -> Select:
        """Scope, window, agent and call type — for every query in this file.

        One builder, so no two panels on one screen can disagree about which
        calls they were drawn from. That is the rule ``CallService._filtered``
        exists for, and the defect it prevents here is worse than a wrong total:
        six numbers that each look plausible and do not add up.
        """
        lower, upper = rules.day_bounds(filters.date_from, filters.date_to, TASHKENT)
        statement = self._scoped(statement, principal).where(
            CallModel.started_at >= lower, CallModel.started_at < upper
        )
        if filters.agent_id:
            statement = statement.where(CallModel.agent_id.in_(filters.agent_id))
        if filters.call_type is not None:
            statement = statement.where(CallModel.call_type == filters.call_type)
        return statement

    def _scored(
        self, statement: Select, principal: Principal, filters: AnalyticsFilters
    ) -> Select:
        """:meth:`_filtered` plus the inner join every score panel needs.

        Inner, deliberately: a call the pipeline skipped or has not reached has
        no score to average, and counting it as a zero would punish an agent for
        a recording that never arrived.
        """
        return self._filtered(
            statement.join(CallScoreModel, CallScoreModel.call_id == CallModel.id),
            principal,
            filters,
        )

    @staticmethod
    def _window(filters: AnalyticsFilters) -> dict[str, date]:
        """The window every response echoes back, as constructor arguments."""
        return {"date_from": filters.date_from, "date_to": filters.date_to}

    # --- 1. The KPI cards ---------------------------------------------------

    async def overview(
        self, principal: Principal, filters: AnalyticsFilters
    ) -> AnalyticsOverviewResponse:
        """Scored calls, average score, red flags and call length, with deltas."""
        current = await self._totals(principal, filters)

        previous_from, previous_to = rules.previous_window(
            filters.date_from, filters.date_to
        )
        # ``model_copy`` and not a hand-built filter: BonviZvonki built one by
        # hand, forgot three fields, and compared a filtered period against an
        # unfiltered one — "+25.6 %" where nothing had moved. A filter added
        # later is carried here for free.
        previous_filters = filters.model_copy(
            update={"date_from": previous_from, "date_to": previous_to}
        )
        previous = await self._totals(principal, previous_filters)

        call_types = await self._call_type_counts(principal, filters)
        current_score = rules.to_one_place(current.avg_score)

        return AnalyticsOverviewResponse(
            **self._window(filters),
            calls=CountMetricOut(
                value=current.calls,
                delta_percent=rules.delta_percent(current.calls, previous.calls),
            ),
            calls_total=sum(call_types.model_dump().values()),
            call_types=call_types,
            ai_score=ScoreMetricOut(
                value=current_score,
                delta_percent=rules.delta_percent(
                    current_score, rules.to_one_place(previous.avg_score)
                ),
            ),
            red_flags=CountMetricOut(
                value=current.red_flag_calls,
                delta_percent=rules.delta_percent(
                    current.red_flag_calls, previous.red_flag_calls
                ),
            ),
            avg_duration_sec=_whole_seconds(current.avg_duration),
            compared_with=AnalyticsWindow(
                date_from=previous_from, date_to=previous_to
            ),
        )

    async def _totals(self, principal: Principal, filters: AnalyticsFilters) -> sa.Row:
        """The four headline numbers, in one pass over the scored calls."""
        statement = self._scored(
            select(
                func.count(CallModel.id).label("calls"),
                func.avg(CallScoreModel.overall_score).label("avg_score"),
                # ``count(case(...))`` rather than ``sum(case(..., else_=0))``:
                # the same number, and it cannot answer NULL over an empty
                # window. It is also the idiom ``gaps/service.py`` already uses.
                func.count(
                    case((func.jsonb_array_length(CallScoreModel.red_flags) > 0, 1))
                ).label("red_flag_calls"),
                func.avg(CallModel.duration_sec).label("avg_duration"),
            ).select_from(CallModel),
            principal,
            filters,
        )
        return (await self.session.execute(statement)).one()

    async def _call_type_counts(
        self, principal: Principal, filters: AnalyticsFilters
    ) -> CallTypeCountsOut:
        """Calls by type — **not** joined to a score.

        This is the row that explains the headline. The ``calls`` metric counts
        scored conversations; without this breakdown a manager who reads "6" in
        a month of 22,000 calls concludes the system lost the rest. Measured in
        BonviZvonki: 72 against 22,026 for one period, with the neighbouring
        page reporting 21,513 — a factor of 300 between two screens.
        """
        rows = (
            await self.session.execute(
                self._filtered(
                    select(CallModel.call_type, func.count().label("calls"))
                    .select_from(CallModel)
                    .group_by(CallModel.call_type),
                    principal,
                    filters,
                )
            )
        ).all()
        counts = {str(call_type): 0 for call_type in CallType}
        for call_type, calls in rows:
            counts[str(call_type)] = int(calls)
        return CallTypeCountsOut(**counts)

    # --- 2. The trend -------------------------------------------------------

    async def timeseries(
        self, principal: Principal, filters: AnalyticsFilters, bucket: Bucket
    ) -> AnalyticsTimeseriesResponse:
        """Calls and average score per day, week or month.

        ``timezone(<zone>, started_at)`` before ``date_trunc`` is not a detail:
        ``date_trunc`` works in the session's zone, which is UTC, so without it
        a call at 02:00 Tashkent is drawn on the previous day. The zone name
        comes from ``core.clock.TASHKENT`` — nobody spells it twice (§6).
        """
        period = func.date_trunc(
            sa.literal(bucket, sa.Text),
            func.timezone(sa.literal(TASHKENT.key, sa.Text), CallModel.started_at),
        )
        statement = self._scored(
            select(
                period.label("period"),
                func.count(CallModel.id).label("calls"),
                func.avg(CallScoreModel.overall_score).label("ai_score"),
            )
            .select_from(CallModel)
            .group_by(period)
            .order_by(period),
            principal,
            filters,
        )
        rows = (await self.session.execute(statement)).all()
        measured = {
            row.period.date(): (int(row.calls), rules.to_one_place(row.ai_score))
            for row in rows
        }

        starts = rules.bucket_starts(filters.date_from, filters.date_to, bucket)
        filled = starts is not None
        if starts is None:
            # Past the ceiling: return what the database had rather than filling
            # 3,000 points nobody can read.
            starts = sorted(measured)

        return AnalyticsTimeseriesResponse(
            **self._window(filters),
            bucket=bucket,
            filled=filled,
            points=[
                TimeseriesPointOut(
                    period_start=start,
                    calls=measured.get(start, (0, None))[0],
                    ai_score=measured.get(start, (0, None))[1],
                )
                for start in starts
            ],
        )

    # --- 3. The leaderboard -------------------------------------------------

    async def agent_ranking(
        self, principal: Principal, filters: AnalyticsFilters
    ) -> AgentRankingResponse:
        """Agents by average score, with the places gained since last period."""
        rows = await self._ranking_rows(principal, filters)

        previous_from, previous_to = rules.previous_window(
            filters.date_from, filters.date_to
        )
        previous = await self._ranking_rows(
            principal,
            filters.model_copy(
                update={"date_from": previous_from, "date_to": previous_to}
            ),
        )
        previous_rank = {row.agent_id: index + 1 for index, row in enumerate(previous)}

        items = []
        for index, row in enumerate(rows):
            rank = index + 1
            before = previous_rank.get(row.agent_id)
            items.append(
                AgentRankRowOut(
                    agent_id=row.agent_id,
                    agent_name=row.agent_name,
                    rank=rank,
                    # Positive means moved up, i.e. the rank number went down.
                    rank_delta=(before - rank) if before is not None else None,
                    calls=int(row.calls),
                    ai_score=rules.to_one_place(row.ai_score),
                    red_flags=int(row.red_flag_calls),
                    avg_duration_sec=_whole_seconds(row.avg_duration),
                )
            )
        return AgentRankingResponse(
            **self._window(filters), items=items, total=len(items)
        )

    async def _ranking_rows(
        self, principal: Principal, filters: AnalyticsFilters
    ) -> list[sa.Row]:
        """One row per agent with a scored call, best average first.

        **The name is the tiebreak.** Ordering on the average alone leaves two
        agents on the same score in whatever order the plan produced, so a rank
        flips between two requests and the "places gained" column invents
        movement that did not happen.
        """
        statement = self._scored(
            select(
                AgentModel.id.label("agent_id"),
                AgentModel.full_name.label("agent_name"),
                func.count(CallModel.id).label("calls"),
                func.avg(CallScoreModel.overall_score).label("ai_score"),
                func.count(
                    case((func.jsonb_array_length(CallScoreModel.red_flags) > 0, 1))
                ).label("red_flag_calls"),
                func.avg(CallModel.duration_sec).label("avg_duration"),
            )
            .select_from(CallModel)
            .join(AgentModel, AgentModel.id == CallModel.agent_id)
            .group_by(AgentModel.id, AgentModel.full_name)
            .order_by(
                func.avg(CallScoreModel.overall_score).desc(), AgentModel.full_name
            ),
            principal,
            filters,
        )
        return list((await self.session.execute(statement)).all())

    # --- 4. The rubric blocks ----------------------------------------------

    async def _block_max(self) -> dict[str, int]:
        """``{block key: maximum}`` from the **active** rubric.

        The rubric is editable (migration 012), so the maxima a percentage is
        taken against must come from the row the scores were produced under —
        not from the constant this module used to read. An admin who moves five
        points from ``script`` to ``objections`` otherwise leaves the radar
        chart dividing by a number nobody uses any more, which is a bar over
        100 %: the defect BonviZvonki shipped and ``_rubric_block_limits``
        fixed.

        Falls back to :data:`BLOCK_MAX_BY_KEY` when the table is empty (the
        pinned default is genuinely the rubric then) or when a stored block
        carries no usable ``max``, so a malformed row degrades to the old
        behaviour rather than emptying the chart.
        """
        active = await RubricService(self.session).active()
        if not active.stored:
            return BLOCK_MAX_BY_KEY

        limits: dict[str, int] = {}
        for block in active.blocks:
            key = block.get("key")
            maximum = block.get("max")
            if not isinstance(key, str) or not isinstance(maximum, int):
                continue
            limits[key] = maximum
        return limits or BLOCK_MAX_BY_KEY

    async def block_breakdown(
        self, principal: Principal, filters: AnalyticsFilters
    ) -> BlockBreakdownResponse:
        """Each rubric block's average, as points and as a percentage of its max.

        The averaging happens **in the database**, over ``jsonb_each(blocks)``,
        rather than by loading every score document into Python as BonviZvonki
        does. Their loop is a few hundred objects on their data and fifty
        thousand on a year of this one's, for four numbers.

        Their two defensive rules survive as SQL conditions, because both are
        real: a key beginning with ``_`` is metadata (``_meta``) and would
        appear as a fifth block, and a non-numeric value used to raise
        ``TypeError`` and take the whole endpoint to a 500.
        """
        # The columns are declared with their types rather than by name: an
        # untyped ``value`` leaves ``jsonb_typeof($1)`` and ``CAST(value AS
        # NUMERIC)`` for PostgreSQL to resolve against an unknown, and an
        # ambiguous operator is a 500 from a read endpoint.
        entries = (
            func.jsonb_each(CallScoreModel.blocks)
            .table_valued(
                sa.column("key", sa.Text), sa.column("value", postgresql.JSONB)
            )
            .lateral()
        )
        # The LATERAL is joined **after** ``_scored`` has added ``call_scores``:
        # it reads that table, and a JOIN rendered before the one it depends on
        # is a "missing FROM-clause entry" at query time.
        statement = (
            self._scored(
                select(
                    entries.c.key.label("block"),
                    func.avg(entries.c.value.cast(sa.Numeric)).label("mean"),
                    func.count().label("scored_calls"),
                ).select_from(CallModel),
                principal,
                filters,
            )
            .join(entries, sa.true())
            .where(
                func.jsonb_typeof(entries.c.value) == "number",
                # ``left(key, 1) <> '_'`` and not ``NOT LIKE '\\_%'``: the
                # underscore is a LIKE wildcard, and the version that reads
                # naturally is the one that silently matches every key.
                func.left(entries.c.key, 1) != "_",
            )
            .group_by(entries.c.key)
        )
        measured = {
            row.block: (row.mean, int(row.scored_calls))
            for row in (await self.session.execute(statement)).all()
        }

        items = []
        # The rubric's own order, so the radar chart's axes do not move between
        # requests. A block the rubric does not name is left out: we would not
        # know what to divide it by.
        for block, limit in (await self._block_max()).items():
            found = measured.get(block)
            if found is None or limit <= 0:
                continue
            mean, scored_calls = found
            percent = rules.ratio_percent(mean, limit)
            score = rules.to_one_place(mean)
            if percent is None or score is None:
                continue
            items.append(
                BlockScoreOut(
                    block=block,
                    score=score,
                    max=limit,
                    percent=percent,
                    scored_calls=scored_calls,
                )
            )
        return BlockBreakdownResponse(**self._window(filters), items=items)

    # --- 5. The breaches ----------------------------------------------------

    async def red_flag_breakdown(
        self, principal: Principal, filters: AnalyticsFilters
    ) -> RedFlagBreakdownResponse:
        """How often each kind of breach was found, commonest first.

        Counted in the database over ``jsonb_array_elements(red_flags)``, for
        the reason :meth:`block_breakdown` gives.

        BonviZvonki also handled a bare string in the array
        (``str(flag) if not a dict``). That branch does not come across:
        ``score_writer`` is the only writer of this column and writes
        ``[{type, severity, timestamp, quote}]``, which its own test pins. A
        fallback for a shape nothing can produce is a second format nobody
        notices they have started relying on.
        """
        flags = (
            func.jsonb_array_elements(CallScoreModel.red_flags)
            .table_valued(sa.column("value", postgresql.JSONB))
            .lateral()
        )
        flag_type = flags.c.value["type"].astext
        # Joined after the score table, for the reason `block_breakdown` gives.
        statement = (
            self._scored(
                select(
                    flag_type.label("type"), func.count().label("count")
                ).select_from(CallModel),
                principal,
                filters,
            )
            .join(flags, sa.true())
            .where(flag_type.is_not(None))
            .group_by(flag_type)
            # The name is the tiebreak, so two equally common breaches do not
            # swap places between two reads of the same page.
            .order_by(func.count().desc(), flag_type)
        )
        rows = (await self.session.execute(statement)).all()
        items = [RedFlagCountOut(type=row.type, count=int(row.count)) for row in rows]
        return RedFlagBreakdownResponse(
            **self._window(filters),
            items=items,
            total=sum(item.count for item in items),
        )

    # --- 6. The histogram ---------------------------------------------------

    async def score_distribution(
        self, principal: Principal, filters: AnalyticsFilters
    ) -> ScoreDistributionResponse:
        """Scored calls per ten-point band. Always ten bands.

        ``least(..., 9)`` is the fix for a perfect score: ``floor(100/10)*10``
        is 100, which BonviZvonki reported as an eleventh band labelled
        "100-109". A 100 belongs in the top bar.
        """
        band = func.least(
            func.floor(CallScoreModel.overall_score / SCORE_BAND_WIDTH),
            len(SCORE_BAND_FLOORS) - 1,
        ).label("band")
        statement = self._scored(
            select(band, func.count().label("calls"))
            .select_from(CallModel)
            .group_by(band)
            .order_by(band),
            principal,
            filters,
        )
        rows = (await self.session.execute(statement)).all()
        measured = {int(row.band) * SCORE_BAND_WIDTH: int(row.calls) for row in rows}

        items = [
            ScoreBucketOut(
                floor=floor,
                # The top band closes at 100, the rest at their ninth point.
                ceiling=(
                    TOP_SCORE
                    if floor == SCORE_BAND_FLOORS[-1]
                    else floor + SCORE_BAND_WIDTH - 1
                ),
                calls=measured.get(floor, 0),
            )
            for floor in SCORE_BAND_FLOORS
        ]
        return ScoreDistributionResponse(
            **self._window(filters),
            items=items,
            scored_calls=sum(item.calls for item in items),
        )


__all__ = ["BLOCK_MAX_BY_KEY", "SCORE_BAND_FLOORS", "AnalyticsService"]
