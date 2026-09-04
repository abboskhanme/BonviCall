"""Scheduled work owned by ``devices`` (T151, SPEC §10.4).

``silence_detection`` is the one with a trap in it. It runs every five minutes,
including at 03:00, and it must **not** alert then: the comparison is in
working hours, so a phone that stopped reporting at 20:00 has been quiet for
zero working hours at 03:00 and eleven at 19:00 the next day. An alerting
system that cries wolf outside business hours gets muted, and then it is not an
alerting system.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.logging import get_logger
from src.modules.devices.models import CallLogDeltaModel
from src.modules.devices.service import DeviceService

log = get_logger(__name__)

#: N3: a delta that reconciled is closed; one that has not after this long is
#: a real gap and belongs in the report rather than in a pending queue.
DELTA_CLOSE_AFTER_HOURS = 24


async def offline_sweep(session: AsyncSession) -> int:
    """Mark devices offline and raise ``device_offline`` (UC-17).

    Idempotent through the alert dedupe key: a phone that stays offline for a
    day produces one alert with a rising ``occurrence_count``, not 1,440.
    """
    return len(await DeviceService(session).sweep_offline())


async def silence_detection(session: AsyncSession) -> int:
    """UC-27, working-hours aware.

    The scheduler is deliberately *not* told to skip nights: the working-hours
    arithmetic already returns zero elapsed time outside business hours, and
    skipping would delay a genuine alert until well after 08:00 on Monday.
    Getting it right in the rule rather than in the cron expression also means
    a holiday added to the settings takes effect without a redeploy.
    """
    return len(await DeviceService(session).detect_silence())


async def call_log_delta_close(session: AsyncSession) -> int:
    """Close reconciled deltas; leave the rest for the gap report (N3).

    A delta only closes when the device's own count and ours agree. One that
    never agrees stays open on purpose — that is the measurement telling us
    something was lost, and closing it would erase the finding.
    """
    cutoff = clock.now() - timedelta(hours=DELTA_CLOSE_AFTER_HOURS)
    rows = list(
        (
            await session.scalars(
                select(CallLogDeltaModel).where(
                    CallLogDeltaModel.closed_at.is_(None),
                    CallLogDeltaModel.delta == 0,
                    CallLogDeltaModel.first_reported_at < cutoff,
                )
            )
        ).all()
    )
    for row in rows:
        row.closed_at = clock.now()
    await session.commit()
    return len(rows)
