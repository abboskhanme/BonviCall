"""The analytics dashboard for the panel (SPEC-ANALYTICS phase 2, §7).

Six reports over the calls this product has already scored: the KPI cards, the
trend, the leaderboard, the rubric blocks, the breaches and the score
histogram. Ported from ``../BonviZvonki/.../analytics/presentation/router.py``,
whose ``/activity`` and ``/activity/missed-clients`` endpoints stay behind —
they answer a question about call *volume* and callbacks and read a
``clients`` table this product does not have.

``/filters`` stays behind too: it existed to feed the agent dropdown, and this
panel already has ``GET /agents`` with an ``agents:read`` gate that every
holder of ``analysis:read`` also has. A second endpoint returning the same
roster is a second thing to keep in step.

**Everything here is gated on ``Perm.ANALYSIS_READ``.** No new permission: an
average of scores is the same fact as the scores themselves, so whoever may
read a call's score may read a hundred of them at once. ``admin`` and
``manager`` hold it; ``sales`` holds neither it nor ``analysis:run`` (§6.1,
§12 Q1), so a salesperson is refused here with a 403 and never reaches the
service. The service narrows by agent anyway, for the day that decision is
reversed.

Nothing here is paged. Each response is a **report** — the answer to one
question, not a window onto rows — so SPEC §4.7's cursor conventions do not
apply, and the one thing that could grow without bound (the trend) is capped
at 550 points by ``rules.MAX_BUCKETS``.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.core.deps import PrincipalDep, SessionDep
from src.core.enums import CallType
from src.core.permissions import Perm, require_permission
from src.modules.analytics.schemas import (
    DEFAULT_DAYS,
    MAX_DAYS,
    AgentRankingResponse,
    AnalyticsFilters,
    AnalyticsOverviewResponse,
    AnalyticsTimeseriesResponse,
    BlockBreakdownResponse,
    Bucket,
    RedFlagBreakdownResponse,
    ScoreDistributionResponse,
)
from src.modules.analytics.service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])

_read = require_permission(Perm.ANALYSIS_READ)


def analytics_filters(
    days: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_DAYS,
            description=(
                "Last N Asia/Tashkent calendar days, today included. Ignored "
                "once both dates are given."
            ),
        ),
    ] = DEFAULT_DAYS,
    date_from: date | None = None,
    date_to: date | None = None,
    agent_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    call_type: CallType | None = None,
) -> AnalyticsFilters:
    """The filter set of §7, as one dependency shared by all six reports.

    ``days`` and the two dates live together on purpose: the dashboard opens on
    a preset and the date fields narrow it, and a caller who sends one bound
    only gets a window that ends today rather than a 500 — which is what
    BonviZvonki answered to ``?date_from=…`` alone on three of these paths,
    because its filter mixed a naive datetime with an aware one.
    """
    return AnalyticsFilters.resolve(
        days=days,
        date_from=date_from,
        date_to=date_to,
        agent_id=agent_id,
        call_type=call_type,
    )


FiltersDep = Annotated[AnalyticsFilters, Depends(analytics_filters)]


@router.get(
    "/overview",
    response_model=AnalyticsOverviewResponse,
    dependencies=[Depends(_read)],
)
async def analytics_overview(
    principal: PrincipalDep, session: SessionDep, filters: FiltersDep
) -> AnalyticsOverviewResponse:
    """The KPI cards, each with its change against the previous equal window.

    ``calls`` counts **scored** conversations and ``call_types`` accounts for
    every other one: without that pairing, "6" in a month of 22,000 calls reads
    as a system that lost the rest.
    """
    return await AnalyticsService(session).overview(principal, filters)


@router.get(
    "/timeseries",
    response_model=AnalyticsTimeseriesResponse,
    dependencies=[Depends(_read)],
)
async def analytics_timeseries(
    principal: PrincipalDep,
    session: SessionDep,
    filters: FiltersDep,
    bucket: Bucket = "day",
) -> AnalyticsTimeseriesResponse:
    """Calls and average score per day, week or month.

    Every period in the window is returned, empty ones included: a categorical
    axis draws five points the same way over a week and over a quarter, so
    omitting the quiet days makes the period filter look broken.
    """
    return await AnalyticsService(session).timeseries(principal, filters, bucket)


@router.get(
    "/agents", response_model=AgentRankingResponse, dependencies=[Depends(_read)]
)
async def analytics_agent_ranking(
    principal: PrincipalDep, session: SessionDep, filters: FiltersDep
) -> AgentRankingResponse:
    """Agents by average score, with the places gained since the last period."""
    return await AnalyticsService(session).agent_ranking(principal, filters)


@router.get(
    "/blocks", response_model=BlockBreakdownResponse, dependencies=[Depends(_read)]
)
async def analytics_block_breakdown(
    principal: PrincipalDep, session: SessionDep, filters: FiltersDep
) -> BlockBreakdownResponse:
    """Each rubric block's average, against the maximum the rubric gives it."""
    return await AnalyticsService(session).block_breakdown(principal, filters)


@router.get(
    "/red-flags",
    response_model=RedFlagBreakdownResponse,
    dependencies=[Depends(_read)],
)
async def analytics_red_flag_breakdown(
    principal: PrincipalDep, session: SessionDep, filters: FiltersDep
) -> RedFlagBreakdownResponse:
    """How often each kind of breach was found, commonest first."""
    return await AnalyticsService(session).red_flag_breakdown(principal, filters)


@router.get(
    "/distribution",
    response_model=ScoreDistributionResponse,
    dependencies=[Depends(_read)],
)
async def analytics_score_distribution(
    principal: PrincipalDep, session: SessionDep, filters: FiltersDep
) -> ScoreDistributionResponse:
    """Scored calls per ten-point band — always ten bands, empty ones included."""
    return await AnalyticsService(session).score_distribution(principal, filters)
