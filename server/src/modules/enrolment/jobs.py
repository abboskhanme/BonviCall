"""Scheduled work owned by ``enrolment`` (T151, SPEC §9.4).

The receiver sweep is the one that matters most here: **if every receiver is
down, nobody in the fleet can enrol.** That makes its health a monitored
product state, not an operational detail, and the absence of enrolment must be
an event rather than a quiet stall.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.enums import AlertKind, AlertSeverity, ReceiverStatus
from src.core.logging import get_logger
from src.modules.alerts.service import AlertService
from src.modules.enrolment.models import CallbackEventModel, CallbackReceiverModel
from src.modules.enrolment.service import EnrolmentService
from src.modules.settings.service import SettingsService

log = get_logger(__name__)

SETTING_CALLBACK_RETENTION_DAYS = "retention.callback_events_days"


async def receiver_health(session: AsyncSession) -> int:
    """Recompute receiver status; alert when every one of them is down.

    The alert is fleet-scoped rather than per-receiver: an admin does not need
    to know which gateway died, they need to know that enrolment has stopped.
    """
    moment = clock.now()
    receivers = list(
        (
            await session.scalars(
                select(CallbackReceiverModel).where(
                    CallbackReceiverModel.is_active.is_(True)
                )
            )
        ).all()
    )
    alerts = AlertService(session)
    changed = 0
    for receiver in receivers:
        status = EnrolmentService.status_for(receiver.last_heartbeat_at, moment)
        if status is not receiver.status:
            receiver.status = status
            receiver.status_changed_at = moment
            changed += 1
            log.info(
                "receiver_status_changed", receiver=receiver.name, status=status.value
            )

    if receivers and all(r.status is ReceiverStatus.DOWN for r in receivers):
        await alerts.raise_alert(
            kind=AlertKind.CALLBACK_RECEIVER_DOWN,
            severity=AlertSeverity.CRITICAL,
            scope="fleet",
            detail={"receivers": len(receivers)},
        )
    else:
        await alerts.resolve(AlertKind.CALLBACK_RECEIVER_DOWN, "fleet")
    await session.commit()
    return changed


async def callback_event_retention(session: AsyncSession) -> int:
    """Delete callback events past their retention (SPEC §3.4).

    These are inbound call records of employees' work numbers and have no value
    once the enrolment is done, so they are **deleted**, not soft-deleted:
    keeping a record of who rang what, forever, for no purpose, is exactly the
    thing this product promises not to do.
    """
    days = await SettingsService(session).get_int(SETTING_CALLBACK_RETENTION_DAYS)
    cutoff = clock.now() - timedelta(days=days)
    result = await session.execute(
        delete(CallbackEventModel).where(CallbackEventModel.received_at < cutoff)
    )
    await session.commit()
    return result.rowcount or 0
