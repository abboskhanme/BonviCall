"""Customer ratings for the panel (BonviZvonki ``modules/surveys`` router).

═══ ACCESS ═════════════════════════════════════════════════════════════════
``analysis:read`` **or** ``calls:read:own``, and both halves are deliberate.

``core/permissions.py`` is frozen (T18), there is no ``surveys:*`` in it, and
this endpoint needs two things at once: admin and manager see the whole fleet,
a salesperson sees their own figures. The only own-scope constants that exist
are ``devices:read:own``, ``calls:read:own`` and ``audio:play:own``.

* ``analysis:read`` admits admin and manager. A customer's rating of an
  employee is an assessment of that employee's call work, which is the subject
  ``analysis:read`` already gates, and the registry's reason for withholding it
  from ``sales`` — "an unreviewed score of their own work invites a dispute the
  tool cannot win" — is about exactly this kind of number.
* ``calls:read:own`` admits a salesperson, and the SERVICE narrows the query to
  their own agent. That is the house rule (§11): the permission admits, the
  query narrows, and there is never a second check in a router. It is also N41's
  transparency, which already grants an employee their own calls and their own
  phone's health.

``reports:read`` was considered and rejected: every other report is fleet-wide
by shape, no role holds an own-scope sibling of it, and the salesperson's own
view — which the source ships **on** by default (``score_only``) — would have
been permanently unreachable rather than one grant away.

**The honest constants are ``surveys:read`` / ``surveys:read:own``.** The
report says so.
═══════════════════════════════════════════════════════════════════════════

⚠️ ``/red-flags`` is declared before nothing in particular — there is no
parameterised sibling on this router — but it is worth noting that
BonviZvonki's equivalent lives on a router that also serves ``/{token}/open``,
where the order DOES matter and is commented there.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.core import clock
from src.core.clock import TASHKENT
from src.core.deps import PrincipalDep, SessionDep
from src.core.errors import BadRequestError, ErrorCode
from src.core.permissions import Perm, require_any_permission
from src.modules.surveys import rules
from src.modules.surveys.schemas import (
    FeedbackItem,
    FeedbackResponse,
    RedFlagOption,
)
from src.modules.surveys.service import SurveyService

router = APIRouter(prefix="/surveys", tags=["Surveys"])

# `surveys:read` / `surveys:read:own`, declared for these ratings on
# 2026-09-17. They were gated on `analysis:read` OR `calls:read:own` while the
# registry was closed to the unit that wrote this module; the pair now says what
# it gates, and the own-scope half is granted to `sales` where `analysis:read`
# deliberately is not — a customer's own words about an employee are the thing
# N41's transparency is for, and a machine score of their work is not.
# The service still narrows an own-scope caller to their own agent.
_read = require_any_permission(Perm.SURVEYS_READ, Perm.SURVEYS_READ_OWN)


@router.get(
    "/red-flags", response_model=list[RedFlagOption], dependencies=[Depends(_read)]
)
async def red_flags() -> list[RedFlagOption]:
    """The misconduct registry — the single source, never copied client-side.

    The panel renders whatever comes back and holds no list of its own, so a
    new criterion appears without a frontend deploy. The labels are Uzbek
    because they are what a customer reads in their own chat; the keys are what
    the answers store, and a key is never renamed.

    Behind the read gate here, where BonviZvonki serves it publicly: there the
    customer-facing app needs it and shares a router with the panel. Here that
    app is a separate, unmounted surface with its own copy of the list in its
    own response, so the panel's copy has no reason to be open.
    """
    return [
        RedFlagOption(key=key, label=label) for key, label in SurveyService.red_flags()
    ]


@router.get("", response_model=FeedbackResponse, dependencies=[Depends(_read)])
async def feedback(
    principal: PrincipalDep,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=rules.MAX_WINDOW_DAYS)] = rules.DEFAULT_WINDOW_DAYS,
    date_from: Annotated[
        date | None,
        Query(description="Asia/Tashkent calendar date. Overrides `days`."),
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Asia/Tashkent calendar date, INCLUSIVE.")
    ] = None,
    agent_id: Annotated[uuid.UUID | None, Query()] = None,
    search: Annotated[
        str | None,
        Query(
            max_length=120,
            description=(
                "Employee name. The SERVER filters, because the average and "
                "the distribution have to match what was found — filtering the "
                "rendered list would leave a headline describing a different "
                "set of answers."
            ),
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
) -> FeedbackResponse:
    """What customers said, and how much of it this caller may see.

    ⚠️ A ``sales`` caller gets the summary and **never the rows**. One Telegram
    group is one customer, so one visible rating row identifies who wrote it,
    and the anonymity was promised to that customer in their own chat.
    ``items_withheld`` says so explicitly, so the panel can distinguish "your
    ratings are not itemised" from "nobody has ever rated you".

    The ``agent_id`` filter is ignored for a salesperson rather than merged —
    the service narrows to their own agent whatever the URL says.
    """
    try:
        window = rules.report_window(
            days=days,
            date_from=date_from,
            date_to=date_to,
            today=clock.today_tashkent(),
            zone=TASHKENT,
        )
    except rules.WindowInvalid as invalid:
        raise BadRequestError(
            ErrorCode.BAD_REQUEST, detail={"field": invalid.field_name}
        ) from invalid

    report = await SurveyService(session).feedback(
        principal, window, agent_id=agent_id, search=search, limit=limit
    )
    return FeedbackResponse(
        average=report.average,
        count=report.count,
        ready=report.ready,
        min_responses=report.min_responses,
        distribution=report.distribution,
        response_rate=report.response_rate,
        items_withheld=report.items_withheld,
        items=[
            FeedbackItem(
                id=item.id,
                agent_id=item.agent_id,
                agent_name=item.agent_name,
                csat=item.csat,
                resolution=item.resolution,
                comment=item.comment,
                red_flags=item.red_flags,
                responded_at=item.responded_at,
            )
            for item in report.items
        ],
    )
