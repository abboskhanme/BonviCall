"""Scheduled work owned by ``alerts`` (T151).

One job, and it exists because of a fleet with 269 installation rows for six
agents. Every superseded phone kept raising, nobody acknowledged work they
could not do, and 69 open alerts buried the handful that named a live handset.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import InstallationStatus
from src.core.logging import get_logger
from src.modules.alerts.models import AlertModel
from src.modules.alerts.service import AlertService
from src.modules.installations.models import InstallationModel

log = get_logger(__name__)


async def close_superseded_alerts(session: AsyncSession) -> int:
    """Resolve open alerts whose installation is no longer the live one.

    ``AlertService`` refuses to *raise* against a superseded phone and
    ``resolve_all_for`` closes its alerts at the moment it is replaced, so on a
    server that has always had both this finds nothing. It exists for the ones
    raised before either rule, and as the answer to a phone superseded by a
    path that forgets to call it — a sweep is cheaper than being certain every
    caller remembers.

    Idempotent: it only sees rows with ``resolved_at IS NULL``, so a second run
    finds nothing. It never deletes an alert — the row stays, so "this phone
    was offline last Tuesday" is still answerable (UC-27).
    """
    stale = list(
        (
            await session.scalars(
                select(AlertModel.installation_id)
                .join(
                    InstallationModel,
                    InstallationModel.id == AlertModel.installation_id,
                )
                .where(
                    AlertModel.resolved_at.is_(None),
                    InstallationModel.status.notin_(
                        (InstallationStatus.ACTIVE, InstallationStatus.PENDING)
                    ),
                )
                .distinct()
            )
        ).all()
    )
    service = AlertService(session)
    closed = 0
    for installation_id in stale:
        closed += await service.resolve_all_for(installation_id)
    await session.commit()
    if closed:
        log.info("superseded_alerts_closed", alerts=closed, installations=len(stale))
    return closed
