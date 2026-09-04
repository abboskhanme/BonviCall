"""Installation lifecycle: rebinding, revocation, attestation (T35, T142)."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from src.core.enums import (
    AlertKind,
    FunnelStage,
    InstallationStatus,
    VerificationMethod,
)
from src.modules.alerts.models import AlertModel
from src.modules.installations.models import InstallationModel
from src.modules.installations.service import InstallationService

pytestmark = pytest.mark.asyncio


async def test_verifying_a_second_phone_replaces_the_first(
    db, installation_factory, agent_factory, registered_number_factory, device_factory
) -> None:
    """UC-07: exactly one active installation per number, and a visible rebind."""
    agent = await agent_factory()
    number = await registered_number_factory(agent=agent)
    first = await installation_factory(agent=agent, number=number)
    second = await installation_factory(
        agent=agent,
        number=number,
        status=InstallationStatus.PENDING,
        device=await device_factory(build_fingerprint_hash="b" * 64),
    )

    await InstallationService(db).activate(second, VerificationMethod.CALLBACK)
    await db.flush()

    assert (await db.get(InstallationModel, first.id)).status is InstallationStatus.REPLACED
    assert (await db.get(InstallationModel, second.id)).status is InstallationStatus.ACTIVE
    rebinds = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AlertModel)
        .where(AlertModel.kind == AlertKind.INSTALLATION_REBOUND)
    )
    assert rebinds == 1, "an unexpected rebinding is what a stolen credential looks like"


async def test_revoking_kills_every_issued_token(
    db, admin, installation_factory, device_client_factory
) -> None:
    """UC-08: token_version moves, so tokens already on the phone are dead."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    assert (await client.get("/api/device/v1/enrolment/token")).status_code == 200

    response = await admin.post(f"/api/v1/installations/{installation.id}/revoke", json={})
    assert response.status_code == 200
    assert response.json()["confirmed"] is False, (
        "Bonvi does not own the handset; claiming a completed wipe would be a lie"
    )

    refused = await client.get("/api/device/v1/enrolment/token")
    assert refused.status_code == 401


async def test_revocation_reports_what_was_still_queued(
    db, admin, installation_factory
) -> None:
    """The admin's next question is always "did we lose anything"."""
    from src.modules.devices.models import DeviceHealthModel

    installation = await installation_factory()
    db.add(
        DeviceHealthModel(
            installation_id=installation.id, queue_records=7, queue_bytes=1024
        )
    )
    await db.flush()
    body = (
        await admin.post(f"/api/v1/installations/{installation.id}/revoke", json={})
    ).json()
    assert body["pending_records"] == 7
    assert body["pending_bytes"] == 1024


async def test_attestation_needs_a_reason_and_is_shown_as_weaker(
    db, admin, installation_factory
) -> None:
    """T142: attested is not proven, and the funnel must never blur the two."""
    installation = await installation_factory(status=InstallationStatus.PENDING)
    refused = await admin.post(
        f"/api/v1/installations/{installation.id}/attest", json={"reason": ""}
    )
    assert refused.status_code == 422

    response = await admin.post(
        f"/api/v1/installations/{installation.id}/attest",
        json={"reason": "Operator suppresses caller id on this SIM"},
    )
    assert response.status_code == 200
    assert response.json()["verification_method"] == "admin_attested"
    assert response.json()["funnel_stage"] == FunnelStage.VERIFIED_BY_ADMIN.value


async def test_attestation_writes_an_audit_row(db, admin, installation_factory) -> None:
    from src.core.enums import AuditAction
    from src.modules.audit.models import AuditLogModel

    installation = await installation_factory(status=InstallationStatus.PENDING)
    await admin.post(
        f"/api/v1/installations/{installation.id}/attest",
        json={"reason": "CLI withheld by the operator"},
    )
    rows = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AuditLogModel)
        .where(AuditLogModel.action == AuditAction.INSTALLATION_ATTESTED)
    )
    assert rows == 1


async def test_only_an_admin_may_revoke_or_attest(manager, installation_factory) -> None:
    installation = await installation_factory()
    assert (
        await manager.post(f"/api/v1/installations/{installation.id}/revoke", json={})
    ).status_code == 403
    assert (
        await manager.post(
            f"/api/v1/installations/{installation.id}/attest", json={"reason": "no"}
        )
    ).status_code == 403


async def test_a_manager_may_read_installations(manager, installation_factory) -> None:
    await installation_factory()
    assert (await manager.get("/api/v1/installations")).status_code == 200


async def test_sales_cannot_read_installations(sales, installation_factory) -> None:
    await installation_factory()
    assert (await sales.get("/api/v1/installations")).status_code == 403


async def test_without_a_token_it_is_401(client) -> None:
    assert (await client.get("/api/v1/installations")).status_code == 401


async def test_an_unknown_installation_is_404(admin) -> None:
    assert (
        await admin.get(f"/api/v1/installations/{uuid.uuid4()}")
    ).status_code == 404


async def test_a_device_refresh_token_rotates_and_a_replay_kills_the_pair(
    db, installation_factory, device_client_factory, client
) -> None:
    """N24 on the device side: reuse increments token_version."""
    installation = await installation_factory()
    device = await device_client_factory(installation)
    spent = device.refresh_token

    first = await client.post(
        "/api/device/v1/auth/refresh", json={"refresh_token": spent}
    )
    assert first.status_code == 200

    replay = await client.post(
        "/api/device/v1/auth/refresh", json={"refresh_token": spent}
    )
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "refresh_reused"
