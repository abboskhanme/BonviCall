"""The alerts inbox (T39, UC-06, UC-18, UC-27).

**Acknowledgement is ``admin``-only and nothing in the device API can touch
this table.** UC-06 and UC-18 are explicit that the agent whose phone stopped
capturing cannot dismiss or suppress the alert about it — otherwise the alert
is a notification to the one person with a reason to silence it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from src.core.deps import PrincipalDep, SessionDep
from src.core.enums import AlertSeverity
from src.core.permissions import Perm, require_permission
from src.modules.alerts.schemas import AlertListResponse, AlertResponse
from src.modules.alerts.service import AlertService

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get(
    "",
    response_model=AlertListResponse,
    dependencies=[Depends(require_permission(Perm.ALERTS_READ))],
)
async def list_alerts(
    session: SessionDep,
    severity: AlertSeverity | None = None,
    open_only: bool = True,
    limit: int = 200,
    agent_id: uuid.UUID | None = None,
) -> AlertListResponse:
    """Severity, cause, agent, device, first/last seen and the repeat count.

    ``agent_id`` is what the agent's own card reads. The alerts page shows the
    open list and nothing else since 2026-09-14 — an inbox that never empties
    is an inbox nobody works — so one person's closed history is answered here
    instead of by a second page.
    """
    items, total, open_count = await AlertService(session).list(
        severity=severity, open_only=open_only, limit=limit, agent_id=agent_id
    )
    return AlertListResponse(
        items=items,
        total=total,
        open_count=open_count,
    )


@router.post(
    "/{alert_id}/ack",
    response_model=AlertResponse,
    dependencies=[Depends(require_permission(Perm.ALERTS_ACK))],
)
async def acknowledge_alert(
    alert_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> AlertResponse:
    """Admin only. An alert can be acknowledged, never deleted."""
    alert = await AlertService(session).acknowledge(alert_id, principal.id)
    return AlertResponse.model_validate(alert)
