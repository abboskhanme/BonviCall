"""Scheduled work owned by ``installations`` (T151).

``funnel_refresh`` was **reconstructed on 2026-09-06** after I overwrote this
file: it and the ``enrolment_stalled`` alert it raises were the only callers of
``rules.resolve_funnel_stage``, so both went with it. The rule itself survived
untouched and is the contract this is rebuilt against — its parameter list is
the specification of what has to be gathered here. It is a reconstruction, not
a recovery, and it is written down so the next reader knows which.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.enums import (
    AlertKind,
    AlertSeverity,
    FunnelStage,
    InstallationStatus,
)
from src.core.logging import get_logger
from src.modules.alerts.service import AlertService
from src.modules.devices.models import CapabilityStateModel, DeviceHealthModel
from src.modules.devices.rules import REQUIRED_CAPABILITIES, WORKING_STATES
from src.modules.enrolment.service import EnrolmentService
from src.modules.installations.models import InstallationModel
from src.modules.installations.rules import resolve_funnel_stage

log = get_logger(__name__)

#: An installation that has not reached ``number_verified`` in this long is
#: stalled: somebody started and did not finish, and nobody will notice unless
#: the server says so (UC-02, R17).
STALLED_AFTER_MINUTES = 30

#: How long an abandoned attempt is left alone. The successor's existence is
#: the real signal, so this is only a guard against collapsing a row a phone is
#: still working with while a second was created seconds ago — a retry burst
#: looks exactly like abandonment for the first few minutes.
GRACE_HOURS = 1


async def collapse_abandoned_enrolments(session: AsyncSession) -> int:
    """Mark superseded, never-completed enrolment attempts as ``replaced``.

    **Three conditions, and each one is load-bearing:**

    * ``pending`` — a verified installation is somebody's working phone.
    * **never reported** — no ``device_health`` row at all. A phone that has
      sent even one heartbeat is a phone that got somewhere, and what happened
      to it afterwards is a different question.
    * **a later installation exists on the same number.** This is the one that
      matters. A ``pending`` installation with no successor is *somebody stuck
      right now*, which is the opposite of noise — it is the single most
      important row on the page, and collapsing it would hide the person this
      product exists to notice.

    **Collapsed, never deleted.** The row stays, so "this agent tried to enrol
    eleven times on the third of September" is still answerable — that is
    evidence about the product, not clutter. ``enrolment_attempts`` keeps every
    attempt with its timestamp and outcome and is not touched at all; this only
    moves a status so the fleet page can tell a dead attempt from a live one.

    No audit row per installation: two hundred rows of one action would bury
    the log the way these rows buried the fleet page, and nothing here is a
    decision a person made. The count is logged once.

    Idempotent: a collapsed row is no longer ``pending``, so a second run finds
    nothing.
    """
    cutoff = clock.now() - timedelta(hours=GRACE_HOURS)

    later = InstallationModel.__table__.alias("later")
    has_successor = (
        select(func.count())
        .select_from(later)
        .where(
            later.c.number_id == InstallationModel.number_id,
            later.c.created_at > InstallationModel.created_at,
        )
        .correlate(InstallationModel)
        .scalar_subquery()
    )

    rows = list(
        (
            await session.scalars(
                select(InstallationModel)
                .outerjoin(
                    DeviceHealthModel,
                    DeviceHealthModel.installation_id == InstallationModel.id,
                )
                .where(
                    InstallationModel.status == InstallationStatus.PENDING,
                    DeviceHealthModel.installation_id.is_(None),
                    InstallationModel.created_at < cutoff,
                    has_successor > 0,
                )
            )
        ).all()
    )

    alerts = AlertService(session)
    for installation in rows:
        installation.status = InstallationStatus.REPLACED
        # Whatever it raised while it looked live goes with it.
        await alerts.resolve_all_for(installation.id)
    await session.commit()

    if rows:
        log.info("abandoned_enrolments_collapsed", installations=len(rows))
    return len(rows)


async def funnel_refresh(session: AsyncSession) -> int:
    """Recompute every installation's funnel stage (T152, SPEC §10.1).

    The stage is derived, not reported: it is a reading of health,
    capabilities, verification and time, and any of those can change without
    the phone saying anything — a silent handset moves from ``capturing`` to
    ``install_disappeared`` by doing nothing at all. So it is swept rather than
    written at the moment of a request.

    Raises ``enrolment_stalled`` for an installation that has not reached
    verification within ``STALLED_AFTER_MINUTES``. That is the alert an admin
    needs while the agent is still holding the phone; afterwards it is a
    postmortem.

    Idempotent: writing the same stage twice is a no-op, and
    ``funnel_changed_at`` only moves when the stage actually does — otherwise
    "how long have they been stuck" would reset on every sweep and the one
    number this page exists for would always read five minutes.
    """
    moment = clock.now()
    rows = (
        await session.execute(
            select(InstallationModel, DeviceHealthModel).outerjoin(
                DeviceHealthModel,
                DeviceHealthModel.installation_id == InstallationModel.id,
            )
        )
    ).all()
    if not rows:
        return 0

    ids = [installation.id for installation, _ in rows]
    states = await _capability_states(session, ids)
    # Asked of the module that owns the table, not read from it (§2).
    stalled_alerts = await AlertService(session).open_for(
        AlertKind.ENROLMENT_STALLED, ids
    )
    live_codes = await EnrolmentService(session).numbers_with_a_live_code()

    alerts = AlertService(session)
    changed = 0
    for installation, health in rows:
        silent_hours = (
            (moment - health.last_heartbeat_at).total_seconds() / 3600
            if health is not None and health.last_heartbeat_at is not None
            else None
        )
        owned = states.get(installation.id, {})
        stage = resolve_funnel_stage(
            status=installation.status.value,
            verification_method=(
                installation.verification_method.value
                if installation.verification_method
                else None
            ),
            capabilities_all_working=bool(owned)
            and all(owned.get(name) in WORKING_STATES for name in REQUIRED_CAPABILITIES),
            service_running=bool(health and health.service_running),
            silent_hours=silent_hours,
            # "It stopped working" must not be reported for a phone that never
            # worked — that is the distinction the rule's parameter exists for.
            was_healthy=bool(health and health.recording_route_ok),
            needs_assistance=installation.id in stalled_alerts,
            has_live_code=installation.number_id in live_codes,
        )
        if installation.funnel_stage.value != stage:
            installation.funnel_stage = FunnelStage(stage)
            installation.funnel_changed_at = moment
            changed += 1

        if _is_stalled(installation, moment):
            await alerts.raise_alert(
                kind=AlertKind.ENROLMENT_STALLED,
                severity=AlertSeverity.WARNING,
                scope=installation.id,
                installation_id=installation.id,
                agent_id=installation.agent_id,
                detail={"stage": stage, "minutes": STALLED_AFTER_MINUTES},
            )
        elif installation.status is InstallationStatus.ACTIVE:
            # They got there. Clear it rather than leaving an admin to tick off
            # somebody who finished twenty minutes ago.
            await alerts.resolve(AlertKind.ENROLMENT_STALLED, installation.id)

    await session.commit()
    if changed:
        log.info("funnel_refreshed", changed=changed, installations=len(rows))
    return changed


def _is_stalled(installation: InstallationModel, moment) -> bool:
    """Started, not finished, and long enough ago to be worth a person."""
    if installation.status is not InstallationStatus.PENDING:
        return False
    return moment - installation.created_at > timedelta(minutes=STALLED_AFTER_MINUTES)


async def _capability_states(session: AsyncSession, ids) -> dict:
    rows = (
        await session.execute(
            select(
                CapabilityStateModel.installation_id,
                CapabilityStateModel.capability,
                CapabilityStateModel.state,
            ).where(CapabilityStateModel.installation_id.in_(set(ids)))
        )
    ).all()
    states: dict = {}
    for installation_id, capability, state in rows:
        states.setdefault(installation_id, {})[capability.value] = state.value
    return states


