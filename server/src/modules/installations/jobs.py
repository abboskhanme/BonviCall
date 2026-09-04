"""Scheduled work owned by ``installations`` (T151, T152).

``funnel_refresh`` recomputes every installation's stage and persists it, so
the rollout page is **one query** rather than a per-row computation over a
fleet that an admin refreshes every fifteen seconds during a go-live.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.enums import (
    AlertKind,
    AlertSeverity,
    CapabilityState,
    FunnelStage,
    InstallationStatus,
)
from src.core.logging import get_logger
from src.modules.alerts.service import AlertService
from src.modules.devices.models import CapabilityStateModel, DeviceHealthModel
from src.modules.devices.rules import REQUIRED_CAPABILITIES
from src.modules.installations.models import InstallationModel
from src.modules.installations.rules import resolve_funnel_stage

log = get_logger(__name__)

#: SPEC §10.3: an agent stuck in one non-terminal stage for this long is an
#: ``info`` alert. A silently stalled rollout looks exactly like a working one.
STALLED_AFTER_HOURS = 48

TERMINAL_STAGES = frozenset(
    {FunnelStage.CAPTURING, FunnelStage.REVOKED, FunnelStage.INSTALL_DISAPPEARED}
)


async def funnel_refresh(session: AsyncSession) -> int:
    """Recompute every stage; alert on entry to the two that need a human.

    Idempotent: a stage that has not changed is not written and
    ``funnel_changed_at`` is left alone, so running this twice does not reset
    the clock the rollout page shows as "time in stage".
    """
    moment = clock.now()
    rows = list(
        (
            await session.scalars(
                select(InstallationModel).where(
                    InstallationModel.status != InstallationStatus.REVOKED
                )
            )
        ).all()
    )
    alerts = AlertService(session)
    changed = 0

    for installation in rows:
        health = await session.get(DeviceHealthModel, installation.id)
        states = {
            row.capability.value: row.state
            for row in (
                await session.scalars(
                    select(CapabilityStateModel).where(
                        CapabilityStateModel.installation_id == installation.id
                    )
                )
            ).all()
        }
        last_contact = health.last_heartbeat_at if health else None
        silent_hours = (
            (moment - last_contact).total_seconds() / 3600
            if last_contact is not None
            else None
        )
        stage = FunnelStage(
            resolve_funnel_stage(
                status=installation.status.value,
                verification_method=(
                    installation.verification_method.value
                    if installation.verification_method
                    else None
                ),
                capabilities_all_working=bool(states)
                and all(
                    states.get(name) is CapabilityState.GRANTED_WORKING
                    for name in REQUIRED_CAPABILITIES
                ),
                service_running=bool(health and health.service_running),
                silent_hours=silent_hours,
                was_healthy=bool(health and health.capture_enabled),
                needs_assistance=installation.funnel_stage
                is FunnelStage.NEEDS_ASSISTED_INSTALL,
                has_live_code=False,
            )
        )

        if stage is installation.funnel_stage:
            # Nothing changed. Leaving funnel_changed_at alone is what makes
            # "time in stage" mean anything on the rollout page.
            if (
                stage not in TERMINAL_STAGES
                and (moment - installation.funnel_changed_at).total_seconds()
                > STALLED_AFTER_HOURS * 3600
            ):
                await alerts.raise_alert(
                    kind=AlertKind.ENROLMENT_STALLED,
                    severity=AlertSeverity.INFO,
                    scope=installation.id,
                    installation_id=installation.id,
                    agent_id=installation.agent_id,
                    detail={"stage": stage.value, "hours": STALLED_AFTER_HOURS},
                )
            continue

        previous = installation.funnel_stage
        installation.funnel_stage = stage
        installation.funnel_changed_at = moment
        changed += 1
        log.info(
            "funnel_stage_changed",
            installation_id=str(installation.id),
            from_stage=previous.value,
            to_stage=stage.value,
        )

        if stage is FunnelStage.INSTALL_DISAPPEARED:
            # Distinct from device_offline on purpose: a phone in a lift comes
            # back, an app Play Protect deleted does not, and the admin's next
            # action differs (UC-02).
            await alerts.raise_alert(
                kind=AlertKind.INSTALL_DISAPPEARED,
                severity=AlertSeverity.CRITICAL,
                scope=installation.id,
                installation_id=installation.id,
                agent_id=installation.agent_id,
            )
        elif stage is FunnelStage.NEEDS_ASSISTED_INSTALL:
            await alerts.raise_alert(
                kind=AlertKind.ENROLMENT_STALLED,
                severity=AlertSeverity.INFO,
                scope=installation.id,
                installation_id=installation.id,
                agent_id=installation.agent_id,
                detail={"stage": stage.value},
            )

    await session.commit()
    return changed
