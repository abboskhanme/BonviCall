"""Call activity for the panel — volume and answerability.

Ported from BonviZvonki ``modules/analytics/presentation/router.py``
(``/analytics/activity`` and ``/analytics/activity/missed-clients``). It lives
under ``/activity`` rather than under ``/reports`` or ``/analytics``: the whole
surface of this port lands in new files, so nothing on the busiest existing
router is edited for it, and there is no ``analytics`` module here to name.

═══ ACCESS ═════════════════════════════════════════════════════════════════
``calls:read`` or ``calls:read:own``, because this is the calls table asked a
different question. A ``sales`` principal holds the second, passes the gate,
and ``ActivityService`` narrows the query to their own agent — the house rule
(CONVENTIONS.md §11): the permission admits, the QUERY narrows, and there is
never a second check in a router. ``reports:read`` is deliberately not the
gate: every other report is fleet-wide by shape and a salesperson holds none of
them, which would have made own-scope unreachable.

A caller who asks for an agent they may not see is answered **404**, never 403.
BonviZvonki raises ``ForbiddenError`` here; a 403 confirms that the agent
exists and spoke to that number, which is exactly what SPEC §4.1 rule 2
forbids.
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.core import clock
from src.core.clock import TASHKENT
from src.core.deps import PrincipalDep, SessionDep
from src.core.errors import BadRequestError, ErrorCode, NotFoundError
from src.core.permissions import Perm, require_any_permission
from src.modules.activity.rules import (
    CALLBACK_WINDOW_HOURS,
    Window,
    WindowInvalid,
    activity_window,
)
from src.modules.activity.schemas import (
    ActivityDayRow,
    ActivityHourRow,
    ActivityResponse,
    AgentActivityRow,
    MissedClientRow,
    MissedClientsResponse,
)
from src.modules.activity.service import ActivityService

router = APIRouter(prefix="/activity", tags=["Activity"])

_read = require_any_permission(Perm.CALLS_READ, Perm.CALLS_READ_OWN)

#: The four one-click windows the report offers. 365 is the hard bound, so a
#: pasted URL cannot ask for a decade of daily bars.
DaysParam = Annotated[
    int,
    Query(ge=1, le=365, description="Last N calendar days (1 / 7 / 15 / 30)."),
]


def report_window(
    days: DaysParam = 7,
    date_from: Annotated[
        date | None,
        Query(description="Asia/Tashkent calendar date. Overrides `days`."),
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Asia/Tashkent calendar date, INCLUSIVE.")
    ] = None,
) -> Window:
    """The window, resolved once for BOTH endpoints.

    ⚠️ It must not be computed twice. If the summary and the per-agent detail
    resolve different windows the detail contradicts the total, and the tool
    built to prove a number is what destroys trust in it.

    The bounds are calendar ``date`` values, so "up to the 16th" includes the
    whole of the 16th by construction. BonviZvonki takes ``datetime`` here and
    needs two helpers to survive it — ``_inclusive_end``, because its filter is
    ``started_at <= date_to`` and a bare date meant midnight, and ``_as_utc``,
    because Pydantic parses ``?date_from=2026-08-10`` into a NAIVE datetime
    which then raises ``TypeError`` against an aware one and answers 500.
    """
    try:
        return activity_window(
            days=days,
            date_from=date_from,
            date_to=date_to,
            today=clock.today_tashkent(),
            zone=TASHKENT,
        )
    except WindowInvalid as invalid:
        raise BadRequestError(
            ErrorCode.BAD_REQUEST, detail={"field": invalid.field_name}
        ) from invalid


WindowDep = Annotated[Window, Depends(report_window)]


def _row(row) -> AgentActivityRow:
    """One aggregate as its wire row. The derived figures are the dataclass's
    properties, so screen and file cannot compute them differently."""
    return AgentActivityRow(
        agent_id=row.agent_id,
        agent_name=row.agent_name,
        outbound_total=row.outbound_total,
        outbound_answered=row.outbound_answered,
        outbound_no_answer=row.outbound_no_answer,
        inbound_total=row.inbound_total,
        inbound_answered=row.inbound_answered,
        missed=row.missed,
        missed_called_back=row.missed_called_back,
        missed_addressable=row.missed_addressable,
        missed_open=row.missed_open,
        missed_clients=row.missed_clients,
        clients_reached=row.clients_reached,
        clients_unreached=row.clients_unreached,
        missed_rate=row.missed_rate,
        callback_rate=row.callback_rate,
        callback_median_minutes=row.callback_median_minutes,
        total=row.total,
        talk_seconds=row.talk_seconds,
    )


@router.get("", response_model=ActivityResponse, dependencies=[Depends(_read)])
async def activity_report(
    principal: PrincipalDep,
    session: SessionDep,
    window: WindowDep,
    agent_id: Annotated[list[uuid.UUID] | None, Query()] = None,
) -> ActivityResponse:
    """Who called whom, how many went unanswered, and who was called back.

    ⚠️ There is no single "unanswered" number. An unanswered INCOMING call is
    the company failing to pick up; an unanswered OUTGOING call is a customer
    who was busy. Measured over 7 days of real data: 983 and 1047. Adding them
    doubles the figure, destroys its meaning and blames the employee for it.

    A ``sales`` caller sees only their own row, and the ``agent_id`` filter in
    the URL is ignored for them rather than merged.
    """
    report = await ActivityService(session).report(
        principal, window, agent_id=agent_id
    )
    assert report.total is not None
    return ActivityResponse(
        days=window.days,
        date_from=window.date_from,
        date_to=window.date_to,
        callback_window_hours=CALLBACK_WINDOW_HOURS,
        callback_median_minutes=report.callback_median_minutes,
        days_series=[
            ActivityDayRow(
                day=day.day,
                inbound=day.inbound,
                inbound_answered=day.inbound_answered,
                missed=day.missed,
                outbound=day.outbound,
                outbound_no_answer=day.outbound_no_answer,
            )
            for day in report.days_series
        ],
        hours_series=[
            ActivityHourRow(
                hour=hour.hour,
                inbound=hour.inbound,
                inbound_answered=hour.inbound_answered,
                missed=hour.missed,
                outbound=hour.outbound,
                outbound_no_answer=hour.outbound_no_answer,
                missed_rate=hour.missed_rate,
            )
            for hour in report.hours_series
        ],
        agents=[_row(row) for row in report.agents],
        total=_row(report.total),
    )


@router.get(
    "/missed-clients",
    response_model=MissedClientsResponse,
    dependencies=[Depends(_read)],
)
async def missed_clients(
    principal: PrincipalDep,
    session: SessionDep,
    window: WindowDep,
    agent_id: Annotated[uuid.UUID, Query(description="The employee to explain.")],
) -> MissedClientsResponse:
    """Proves the number in the table, customer by customer.

    ⚠️ Same window and same logic as the summary — otherwise "9 in the table,
    8 in the list" and nobody trusts either.

    An agent this caller may not read is a 404, and so is an agent that does
    not exist: the two answers are identical on purpose.
    """
    service = ActivityService(session)
    if not service.may_read_agent(principal, agent_id):
        raise NotFoundError()
    name = await service.agent_name(agent_id)
    if name is None:
        raise NotFoundError()

    rows = await service.missed_clients(agent_id, window)
    return MissedClientsResponse(
        agent_id=agent_id,
        agent_name=name,
        date_from=window.date_from,
        date_to=window.date_to,
        callback_window_hours=CALLBACK_WINDOW_HOURS,
        clients=[
            MissedClientRow(
                phone_key=row.phone_key,
                contact_name=row.contact_name,
                attempts=row.attempts,
                first_missed_at=row.first_missed_at,
                last_missed_at=row.last_missed_at,
                contacted_at=row.contacted_at,
                contacted_by=row.contacted_by,
                contact_inbound=row.contact_inbound,
                minutes_to_contact=row.minutes_to_contact,
            )
            for row in rows
        ],
        unreached=sum(1 for row in rows if row.contacted_at is None),
    )
