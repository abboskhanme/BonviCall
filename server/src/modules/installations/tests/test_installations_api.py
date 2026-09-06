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
    assert (await client.get("/api/device/v1/calls")).status_code == 200

    response = await admin.post(f"/api/v1/installations/{installation.id}/revoke", json={})
    assert response.status_code == 200
    assert response.json()["confirmed"] is False, (
        "Bonvi does not own the handset; claiming a completed wipe would be a lie"
    )

    # Any device route: revocation moves ``token_version``, so the token dies
    # in the principal resolver rather than per route.
    refused = await client.get("/api/device/v1/calls")
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


async def test_the_set_of_routes_that_hand_out_device_tokens_is_closed() -> None:
    """N34 has exactly **one** refusal point, and that is the whole design.

    A stale client drains its queue on 200s and is refused only at
    ``POST /auth/refresh``, once it has told us the queue is empty. Any *other*
    route that issues a token pair lets a refused phone keep going for ever.

    ``GET /api/device/v1/enrolment/token`` was exactly that: no caller, no
    version check, and it turned a 30-minute access token into a 90-day refresh
    token with none of the rotation that makes ``credential_replay``
    detectable. Deleted 2026-09-05. This is what stops the next one.

    Adding a route here is a decision about the version gate. Make it
    deliberately: put it in the list and say why.
    """
    from src.main import create_app

    #: Route -> why it may hand out credentials.
    ALLOWED_ISSUERS = {
        "/api/device/v1/auth/refresh": "the gate itself; refuses under-version once drained",
        "/api/device/v1/enrolment/redeem": "provisional token only; cannot upload a call",
        "/api/device/v1/enrolment/verify/msisdn": "the real pair, after the number is proved",
        "/api/device/v1/enrolment/verify/callback/status": "the same pair, callback route",
    }
    token_schemas = {"DeviceTokenPairOut", "IssuedTokensOut", "DeviceRedeemOut"}

    issuers = set()
    for route in create_app().routes:
        path = getattr(route, "path", "")
        model = getattr(route, "response_model", None)
        if path.startswith("/api/device/v1") and getattr(model, "__name__", "") in token_schemas:
            issuers.add(path)
        # A route can also nest one, as the verification responses do.
        elif path.startswith("/api/device/v1") and model is not None:
            nested = getattr(model, "model_fields", {})
            if any(
                getattr(field.annotation, "__name__", "") in token_schemas
                for field in nested.values()
            ):
                issuers.add(path)

    assert issuers <= set(ALLOWED_ISSUERS), (
        f"a new device route hands out credentials: {sorted(issuers - set(ALLOWED_ISSUERS))}. "
        "The version gate lives on refresh and only on refresh — adding an "
        "issuer is a decision about N34, so record it in ALLOWED_ISSUERS."
    )
    assert "/api/device/v1/enrolment/token" not in issuers


# --- a refresh token used twice (N24) --------------------------------------


async def test_a_reused_refresh_token_is_attributed_and_both_pairs_die(
    db, client, installation_factory, device_client_factory
) -> None:
    """The gap the docstring used to claim was closed, and now is.

    A spent refresh token matched no row, so the server could refuse it and
    nothing else. The worst arrangement followed: whoever used the stolen token
    **first** kept a working pair, the real handset was refused, and no record
    said anything had happened.
    """
    import sqlalchemy as sa

    from src.core.enums import AlertKind
    from src.modules.alerts.models import AlertModel
    from src.modules.installations.service import InstallationService

    installation = await installation_factory()
    first = await InstallationService(db).issue_device_pair(installation)
    await db.flush()

    # The thief gets there first and rotates.
    stolen = await client.post(
        "/api/device/v1/auth/refresh", json={"refresh_token": first.refresh_token}
    )
    assert stolen.status_code == 200
    thief_pair = stolen.json()

    # The real handset presents the same token a moment later.
    replayed = await client.post(
        "/api/device/v1/auth/refresh", json={"refresh_token": first.refresh_token}
    )
    assert replayed.status_code == 401
    assert replayed.json()["error"]["code"] == "refresh_reused"

    await db.refresh(installation)
    # Both are dead: the thief's fresh pair too, which is the point.
    assert installation.refresh_token_hash is None
    assert installation.previous_refresh_token_hash is None
    thief_again = await client.post(
        "/api/device/v1/auth/refresh",
        json={"refresh_token": thief_pair["refresh_token"]},
    )
    assert thief_again.status_code == 401

    alert = await db.scalar(
        sa.select(AlertModel).where(AlertModel.kind == AlertKind.CREDENTIAL_REPLAY)
    )
    assert alert is not None
    assert alert.detail["reason"] == "refresh_token_reused"
    # It says what it cannot know.
    assert alert.detail["attributable_to_device"] is False


async def test_the_installation_stays_active_so_the_queue_is_not_lost(
    db, client, installation_factory
) -> None:
    """SPEC §4.3: a credential problem is not a reason to refuse records.

    Re-enrolling on the same number keeps the phone's queue, because the
    duplicate-call check is keyed on ``number_id`` and that does not change.
    Marking the installation revoked here would throw away calls to punish a
    token.
    """
    from src.core.enums import InstallationStatus
    from src.modules.installations.service import InstallationService

    installation = await installation_factory()
    pair = await InstallationService(db).issue_device_pair(installation)
    await db.flush()
    await client.post("/api/device/v1/auth/refresh", json={"refresh_token": pair.refresh_token})
    await client.post("/api/device/v1/auth/refresh", json={"refresh_token": pair.refresh_token})

    await db.refresh(installation)
    assert installation.status is InstallationStatus.ACTIVE


async def test_an_unknown_token_raises_no_alert(
    db, client, installation_factory
) -> None:
    """Only a token we *issued* is a replay. Random bytes are noise, and an
    alert per guess would let anyone fill an admin's inbox."""
    import sqlalchemy as sa

    from src.core.enums import AlertKind
    from src.modules.alerts.models import AlertModel

    await installation_factory()
    response = await client.post(
        "/api/device/v1/auth/refresh", json={"refresh_token": "not-a-token-we-issued"}
    )
    assert response.status_code == 401
    assert await db.scalar(
        sa.select(sa.func.count())
        .select_from(AlertModel)
        .where(AlertModel.kind == AlertKind.CREDENTIAL_REPLAY)
    ) == 0
