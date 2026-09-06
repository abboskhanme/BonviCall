"""The installations sweeps (T151, T152).

``funnel_refresh`` had **no test** before 2026-09-06, which is how it came to
be deleted by an overwrite and noticed only by an import error in a list of job
names. These tests are the reconstruction's evidence and the reason the next
overwrite fails loudly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from src.core.enums import (
    AlertKind,
    FunnelStage,
    InstallationStatus,
    VerificationMethod,
)
from src.modules.alerts.models import AlertModel
from src.modules.devices.models import DeviceHealthModel
from src.modules.installations.jobs import (
    collapse_abandoned_enrolments,
    funnel_refresh,
)
from src.modules.installations.models import InstallationModel

pytestmark = pytest.mark.asyncio


# --- funnel_refresh --------------------------------------------------------


async def test_a_verified_phone_reaches_number_verified(db, installation_factory):
    installation = await installation_factory(
        verified_at=datetime.now(UTC),
        verification_method=VerificationMethod.SIM_MSISDN,
    )
    await db.flush()

    await funnel_refresh(db)
    await db.refresh(installation)
    assert installation.funnel_stage is FunnelStage.NUMBER_VERIFIED


async def test_an_attested_binding_stays_visibly_weaker(db, installation_factory):
    """T142: attested is weaker evidence than proven and must not silently
    render as the same thing."""
    installation = await installation_factory(
        verified_at=datetime.now(UTC),
        verification_method=VerificationMethod.ADMIN_ATTESTED,
        attest_reason="SIM reports no MSISDN",
    )
    await db.flush()

    await funnel_refresh(db)
    await db.refresh(installation)
    assert installation.funnel_stage is FunnelStage.VERIFIED_BY_ADMIN


async def test_a_phone_that_never_worked_is_not_reported_as_one_that_stopped(
    db, installation_factory
):
    """``was_healthy`` is the parameter that keeps these apart. Without it a
    handset that never captured anything would read ``install_disappeared``,
    which sends an admin looking for a phone Play Protect removed."""
    installation = await installation_factory(
        verified_at=datetime.now(UTC),
        verification_method=VerificationMethod.SIM_MSISDN,
    )
    db.add(
        DeviceHealthModel(
            installation_id=installation.id,
            last_heartbeat_at=datetime.now(UTC) - timedelta(hours=48),
            recording_route_ok=False,
        )
    )
    await db.flush()

    await funnel_refresh(db)
    await db.refresh(installation)
    assert installation.funnel_stage is not FunnelStage.INSTALL_DISAPPEARED


async def test_a_phone_that_worked_and_went_silent_is_install_disappeared(
    db, installation_factory
):
    installation = await installation_factory(
        verified_at=datetime.now(UTC),
        verification_method=VerificationMethod.SIM_MSISDN,
    )
    db.add(
        DeviceHealthModel(
            installation_id=installation.id,
            last_heartbeat_at=datetime.now(UTC) - timedelta(hours=48),
            recording_route_ok=True,
        )
    )
    await db.flush()

    await funnel_refresh(db)
    await db.refresh(installation)
    assert installation.funnel_stage is FunnelStage.INSTALL_DISAPPEARED


async def test_an_unfinished_enrolment_raises_enrolment_stalled(
    db, installation_factory
):
    """The alert an admin needs while the agent is still holding the phone."""
    installation = await installation_factory(status=InstallationStatus.PENDING)
    installation.created_at = datetime.now(UTC) - timedelta(hours=2)
    await db.flush()

    await funnel_refresh(db)
    alert = await db.scalar(
        sa.select(AlertModel).where(AlertModel.kind == AlertKind.ENROLMENT_STALLED)
    )
    assert alert is not None
    assert alert.installation_id == installation.id


async def test_finishing_clears_the_stall(db, installation_factory):
    """Otherwise an admin ticks off somebody who finished twenty minutes ago."""
    installation = await installation_factory(status=InstallationStatus.PENDING)
    installation.created_at = datetime.now(UTC) - timedelta(hours=2)
    await db.flush()
    await funnel_refresh(db)

    installation.status = InstallationStatus.ACTIVE
    installation.verified_at = datetime.now(UTC)
    installation.verification_method = VerificationMethod.SIM_MSISDN
    await db.flush()
    await funnel_refresh(db)

    alert = await db.scalar(
        sa.select(AlertModel).where(AlertModel.kind == AlertKind.ENROLMENT_STALLED)
    )
    assert alert.resolved_at is not None


async def test_the_stuck_clock_does_not_reset_on_every_sweep(
    db, installation_factory
):
    """``funnel_changed_at`` answers "how long have they been stuck". Touching
    it on an unchanged stage would make that number always read five minutes."""
    installation = await installation_factory(status=InstallationStatus.PENDING)
    await db.flush()
    await funnel_refresh(db)
    await db.refresh(installation)
    first = installation.funnel_changed_at

    await funnel_refresh(db)
    await db.refresh(installation)
    assert installation.funnel_changed_at == first


# --- collapse_abandoned_enrolments -----------------------------------------


async def _abandoned(db, installation_factory, number=None, age_hours=5):
    installation = await installation_factory(
        status=InstallationStatus.PENDING, number=number
    )
    installation.created_at = datetime.now(UTC) - timedelta(hours=age_hours)
    await db.flush()
    return installation


async def test_an_abandoned_attempt_is_collapsed_once_a_later_one_exists(
    db, installation_factory, registered_number_factory
):
    number = await registered_number_factory()
    first = await _abandoned(db, installation_factory, number=number)
    await _abandoned(db, installation_factory, number=number, age_hours=1)

    assert await collapse_abandoned_enrolments(db) == 1
    await db.refresh(first)
    assert first.status is InstallationStatus.REPLACED


async def test_an_attempt_with_no_successor_is_left_alone(
    db, installation_factory
):
    """The most important row on the page: somebody stuck right now.

    Collapsing it would hide the person this product exists to notice.
    """
    stuck = await _abandoned(db, installation_factory)
    assert await collapse_abandoned_enrolments(db) == 0
    await db.refresh(stuck)
    assert stuck.status is InstallationStatus.PENDING


async def test_a_phone_that_reported_is_never_collapsed(
    db, installation_factory, registered_number_factory
):
    """One heartbeat means it got somewhere, and what happened afterwards is a
    different question."""
    number = await registered_number_factory()
    reported = await _abandoned(db, installation_factory, number=number)
    db.add(
        DeviceHealthModel(
            installation_id=reported.id, last_heartbeat_at=datetime.now(UTC)
        )
    )
    await _abandoned(db, installation_factory, number=number, age_hours=1)
    await db.flush()

    assert await collapse_abandoned_enrolments(db) == 0
    await db.refresh(reported)
    assert reported.status is InstallationStatus.PENDING


async def test_nothing_is_deleted(db, installation_factory, registered_number_factory):
    """"This agent tried to enrol eleven times on the third of September" is
    evidence about the product, not clutter."""
    number = await registered_number_factory()
    await _abandoned(db, installation_factory, number=number)
    await _abandoned(db, installation_factory, number=number, age_hours=1)
    before = await db.scalar(sa.select(sa.func.count()).select_from(InstallationModel))

    await collapse_abandoned_enrolments(db)
    after = await db.scalar(sa.select(sa.func.count()).select_from(InstallationModel))
    assert after == before


async def test_running_it_twice_changes_nothing_more(
    db, installation_factory, registered_number_factory
):
    number = await registered_number_factory()
    await _abandoned(db, installation_factory, number=number)
    await _abandoned(db, installation_factory, number=number, age_hours=1)

    assert await collapse_abandoned_enrolments(db) == 1
    assert await collapse_abandoned_enrolments(db) == 0
