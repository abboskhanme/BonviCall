"""Call analysis for the panel (SPEC-ANALYTICS §6.2, §7).

**The path is ``/analysis/calls/{call_id}`` and not ``/calls/{call_id}/analysis``**
so that the whole server surface lands in new files. Adding a route to
``api/panel/calls.py`` would mean editing the router behind the product's
busiest page for a cosmetic gain, and §7's client decision is that the analysis
is a section of its own with nothing inside the existing pages changing.

Reading a score is reviewing work; running one sends a customer recording to a
vendor and spends money. That is why ``manager`` holds ``analysis:read`` and not
``analysis:run`` — the same line the registry already draws at ``settings:write``
and ``installations:revoke``. ``sales`` holds neither (§6.1, §12 Q1), so a
salesperson is refused here with a 403 and never reaches the service.

A call belonging to another agent is a **404** exactly as everywhere else: the
service asks ``CallService.get(principal, call_id)`` and does not re-implement
scope.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.core.deps import PrincipalDep, SessionDep
from src.core.enums import AnalysisStage
from src.core.pagination import MAX_LIMIT, Cursor, clamp_limit
from src.core.permissions import Perm, require_permission
from src.modules.analysis.schemas import (
    AnalysisFilters,
    AnalysisListResponse,
    AnalysisStateResponse,
    AnalysisStatusResponse,
    CallAnalysisResponse,
    QueueCallRequest,
    ScoreBand,
)
from src.modules.analysis.service import AnalysisService

router = APIRouter(prefix="/analysis", tags=["Analysis"])

_read = require_permission(Perm.ANALYSIS_READ)
_run = require_permission(Perm.ANALYSIS_RUN)


def analysis_filters(
    agent_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    stage: Annotated[list[AnalysisStage] | None, Query()] = None,
    score_band: Annotated[list[ScoreBand] | None, Query()] = None,
    needs_review: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> AnalysisFilters:
    """§7.3's filter set, as one dependency.

    ``score_band`` is typed as the four names rather than as two numbers, so
    the browser never has to know where a band starts — the thresholds are the
    server's, derived from the one property the panel colours a row from.
    """
    return AnalysisFilters(
        agent_id=agent_id,
        stage=stage,
        score_band=list(score_band) if score_band else None,
        needs_review=needs_review,
        date_from=date_from,
        date_to=date_to,
    )


FiltersDep = Annotated[AnalysisFilters, Depends(analysis_filters)]


@router.get("/calls", response_model=AnalysisListResponse, dependencies=[Depends(_read)])
async def list_analysed_calls(
    principal: PrincipalDep,
    session: SessionDep,
    filters: FiltersDep,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
    with_total: bool = False,
) -> AnalysisListResponse:
    """A cursor page, newest conversation first (§7.3).

    Keyset and not offset, through the same ``cursor`` idiom as the calls list:
    no row that existed when paging started is skipped or returned twice, which
    an OFFSET cannot give while the pipeline keeps finishing calls underneath.

    The sort is fixed at ``started_at DESC``. There is one ordering a reader of
    this page wants — the newest conversation — and a sort control that can
    disagree with the cursor is a way to lose rows for no gain.
    """
    page = await AnalysisService(session).list(
        principal=principal,
        limit=clamp_limit(limit, MAX_LIMIT),
        cursor=Cursor.decode(cursor) if cursor else None,
        with_total=with_total,
        filters=filters,
    )
    return AnalysisListResponse(
        items=page.items,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        total=page.total,
    )


@router.get(
    "/status", response_model=AnalysisStatusResponse, dependencies=[Depends(_read)]
)
async def analysis_status(
    principal: PrincipalDep, session: SessionDep
) -> AnalysisStatusResponse:
    """What is waiting, what broke, and what the month has cost (§7.5).

    Declared **above** ``/calls/{call_id}``: the two do not collide, but the
    literal route staying above the parameterised one is the habit that keeps
    them from colliding the day a path is renamed.

    Not paged. ``recent_failures`` is capped at twenty server-side, and none of
    the four fields below it is a list of rows to walk (§6.2).
    """
    return await AnalysisService(session).status(principal)


@router.get(
    "/calls/{call_id}",
    response_model=CallAnalysisResponse,
    dependencies=[Depends(_read)],
)
async def get_call_analysis(
    call_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> CallAnalysisResponse:
    """One call's state, transcript and score, plus the call's own facts.

    A call the pipeline has never touched answers 200 with all three null —
    **not 404** — because the page must tell "not analysed" from "no such
    call". A call belonging to another agent is the 404.
    """
    return await AnalysisService(session).get_call(principal, call_id)


@router.post(
    "/calls/{call_id}",
    response_model=AnalysisStateResponse,
    dependencies=[Depends(_run)],
)
async def queue_call_analysis(
    call_id: uuid.UUID,
    payload: QueueCallRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> AnalysisStateResponse:
    """Queue one call; the worker picks it up within two minutes.

    **Never runs a provider call inside the request.** An LLM round trip behind
    an HTTP request is how a panel times out and a user presses the button
    again — and each press would be a second bill.

    Returns 200 with the state row whether it was created or already there, so
    a re-press is indistinguishable from the first press. The four ways this
    answers 409 — the feature is off, the call is not analysable, the month's
    cap is reached, no provider is configured — are decided in the service.
    """
    return await AnalysisService(session).queue(
        principal, call_id, force=payload.force
    )
