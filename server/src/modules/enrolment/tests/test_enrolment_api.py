"""Enrolment: codes, redemption and the two verification routes (T32, T34)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from src.core import ratelimit
from src.core.enums import (
    AuditAction,
    EnrolmentOutcome,
    FunnelStage,
    InstallationStatus,
    ReceiverKind,
    ReceiverStatus,
    VerificationMethod,
)
from src.core.security import sha256_hex
from src.modules.audit.models import AuditLogModel
from src.modules.enrolment.models import CallbackReceiverModel, EnrolmentAttemptModel
from src.modules.enrolment.service import MAX_CODE_ATTEMPTS

pytestmark = pytest.mark.asyncio

REDEEM = "/api/device/v1/enrolment/redeem"


def redeem_body(code: str, **overrides) -> dict:
    payload = {
        "code": code,
        "device": {
            "manufacturer": "Xiaomi",
            "model": "Redmi Note 12",
            "android_release": "13",
            "api_level": 33,
            "build_fingerprint_hash": "a" * 64,
        },
        "app": {"version": "1.0.0", "version_code": 100, "variant": "modern34"},
        "device_fingerprint": "f" * 64,
        "device_epoch_ms": 1788000000000,
        "device_timezone": "Asia/Tashkent",
        "sim_subscription_id": 2,
        "sim_slot": 1,
    }
    payload.update(overrides)
    return payload


# --- Issuing (panel) --------------------------------------------------------


async def test_admin_issues_a_code_for_an_assigned_number(
    admin, agent_factory, registered_number_factory
) -> None:
    agent = await agent_factory(full_name="Aziz")
    number = await registered_number_factory(agent=agent)
    response = await admin.post(f"/api/v1/numbers/{number.id}/enrolment-code")
    assert response.status_code == 201
    body = response.json()
    assert len(body["code"]) == 8
    assert body["agent_id"] == str(agent.id), "the agent is frozen at issue"


async def test_a_code_cannot_be_issued_for_an_unassigned_number(
    admin, registered_number_factory
) -> None:
    """Nobody holds the line, so the landing page could not name a person."""
    number = await registered_number_factory()
    response = await admin.post(f"/api/v1/numbers/{number.id}/enrolment-code")
    assert response.status_code == 409


async def test_a_manager_cannot_issue_a_code(
    manager, agent_factory, registered_number_factory
) -> None:
    agent = await agent_factory()
    number = await registered_number_factory(agent=agent)
    assert (
        await manager.post(f"/api/v1/numbers/{number.id}/enrolment-code")
    ).status_code == 403


# --- Redemption (device, public) -------------------------------------------


async def test_redeeming_a_code_creates_a_pending_installation(
    client, enrolment_code_factory
) -> None:
    """Pending, not active: verification is what binds the number."""
    code = await enrolment_code_factory()
    response = await client.post(REDEEM, json=redeem_body(code.code))
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == InstallationStatus.PENDING.value
    assert body["provisional_token"]
    assert body["number"]["display"].startswith("+998 ")
    assert body["verification"]["required"] is True


async def test_a_second_redemption_is_409_and_names_the_device(
    client, enrolment_code_factory
) -> None:
    code = await enrolment_code_factory()
    await client.post(REDEEM, json=redeem_body(code.code))
    second = await client.post(
        REDEEM,
        json=redeem_body(code.code, device_fingerprint="b" * 64),
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "enrolment_code_used"
    assert second.json()["error"]["detail"]["device_model"] == "Xiaomi Redmi Note 12"


async def test_an_expired_code_is_410_not_404(client, enrolment_code_factory) -> None:
    """410 says "it existed and is gone", which is a different next action."""
    code = await enrolment_code_factory(
        expires_at=datetime.now(UTC) - timedelta(hours=1)
    )
    response = await client.post(REDEEM, json=redeem_body(code.code))
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "enrolment_code_expired"


async def test_an_unknown_code_is_404(client) -> None:
    response = await client.post(REDEEM, json=redeem_body("ZZZZ9999"))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "enrolment_code_not_found"


async def test_every_failure_is_recorded_with_a_timestamp(
    db, client, enrolment_code_factory
) -> None:
    """UC-01: the admin's list is how a stalled rollout becomes visible."""
    code = await enrolment_code_factory()
    await client.post(REDEEM, json=redeem_body("ZZZZ9999"))
    await client.post(REDEEM, json=redeem_body(code.code))

    outcomes = (
        await db.scalars(sa.select(EnrolmentAttemptModel.outcome))
    ).all()
    assert EnrolmentOutcome.CODE_NOT_FOUND in outcomes
    assert EnrolmentOutcome.OK in outcomes


async def test_a_confusable_code_still_redeems(client, enrolment_code_factory) -> None:
    """The agent typed l for 1; the code is still theirs."""
    await enrolment_code_factory(code="K7M4PQ21")
    response = await client.post(REDEEM, json=redeem_body("k7m4-pq2l"))
    assert response.status_code == 201


async def test_five_attempts_revoke_the_code(db, client, enrolment_code_factory) -> None:
    code = await enrolment_code_factory(
        expires_at=datetime.now(UTC) - timedelta(hours=1)
    )
    for _ in range(5):
        await client.post(REDEEM, json=redeem_body(code.code))
    await db.refresh(code)
    assert code.revoked_at is not None


# --- Verification route 1 ---------------------------------------------------


async def test_msisdn_verification_activates_and_issues_tokens(
    db, installation_factory, device_client_factory, registered_number_factory,
    agent_factory
) -> None:
    agent = await agent_factory()
    number = await registered_number_factory(agent=agent, e164="+998901112233")
    installation = await installation_factory(
        agent=agent, number=number, status=InstallationStatus.PENDING
    )
    device = await device_client_factory(installation)

    response = await device.post(
        "/api/device/v1/enrolment/verify/msisdn",
        json={"line1_number": "+998 90 111-22-33", "subscription_id": 2, "sim_slot": 1},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "matched"
    assert response.json()["tokens"]["access_token"]
    await db.refresh(installation)
    assert installation.status is InstallationStatus.ACTIVE
    assert installation.sim_subscription_id == 2


async def test_an_empty_msisdn_moves_the_flow_on_rather_than_matching(
    db, installation_factory, device_client_factory
) -> None:
    """UC-04's non-negotiable rule, at the wire."""
    installation = await installation_factory(status=InstallationStatus.PENDING)
    device = await device_client_factory(installation)
    response = await device.post(
        "/api/device/v1/enrolment/verify/msisdn", json={"line1_number": None}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "msisdn_unavailable"
    await db.refresh(installation)
    assert installation.status is InstallationStatus.PENDING


async def test_a_different_number_is_a_mismatch_not_an_empty(
    installation_factory, device_client_factory, registered_number_factory,
    agent_factory
) -> None:
    """The app's next screen differs: one says which SIM, the other moves on."""
    agent = await agent_factory()
    number = await registered_number_factory(agent=agent, e164="+998901112233")
    installation = await installation_factory(
        agent=agent, number=number, status=InstallationStatus.PENDING
    )
    device = await device_client_factory(installation)
    response = await device.post(
        "/api/device/v1/enrolment/verify/msisdn", json={"line1_number": "+998935554433"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "number_mismatch"


# --- Verification route 2 ---------------------------------------------------


async def _receiver(db, token: str = "receiver-token", up: bool = True):
    receiver = CallbackReceiverModel(
        name="Office gateway",
        msisdn="+998712000000",
        kind=ReceiverKind.GSM_GATEWAY,
        token_hash=sha256_hex(token),
        last_heartbeat_at=datetime.now(UTC) if up else None,
        status=ReceiverStatus.UP if up else ReceiverStatus.DOWN,
    )
    db.add(receiver)
    await db.flush()
    return receiver


async def test_the_callback_challenge_is_refused_when_no_receiver_is_up(
    installation_factory, device_client_factory
) -> None:
    """Raising a challenge nobody can satisfy is worse than saying so."""
    installation = await installation_factory(status=InstallationStatus.PENDING)
    device = await device_client_factory(installation)
    response = await device.post("/api/device/v1/enrolment/verify/callback/start")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "callback_receiver_down"


async def test_a_dialled_callback_verifies_the_right_installation(
    db, installation_factory, device_client_factory, registered_number_factory,
    agent_factory, service_token
) -> None:
    """The end-to-end path that most Uzbek SIMs will actually take."""
    await _receiver(db)
    agent = await agent_factory()
    number = await registered_number_factory(agent=agent, e164="+998901112233")
    installation = await installation_factory(
        agent=agent, number=number, status=InstallationStatus.PENDING
    )
    device = await device_client_factory(installation)

    started = await device.post("/api/device/v1/enrolment/verify/callback/start")
    assert started.status_code == 200
    verification_id = started.json()["verification_id"]

    pending = await device.get(
        f"/api/device/v1/enrolment/verify/callback/status?verification_id={verification_id}"
    )
    assert pending.json()["state"] == "pending"

    reported = await service_token.post(
        "/api/service/v1/callback-events",
        headers={"Authorization": "Bearer receiver-token"},
        json={"caller_e164": "+998901112233", "cli_presented": True},
    )
    assert reported.status_code == 200
    assert reported.json()["matched"] is True

    matched = await device.get(
        f"/api/device/v1/enrolment/verify/callback/status?verification_id={verification_id}"
    )
    assert matched.json()["state"] == "matched"
    assert matched.json()["tokens"]["access_token"]
    await db.refresh(installation)
    assert installation.status is InstallationStatus.ACTIVE


async def test_a_withheld_caller_id_matches_nothing_and_is_recorded(
    db, service_token
) -> None:
    """This is R19 happening, and it is why admin attestation exists."""
    await _receiver(db)
    response = await service_token.post(
        "/api/service/v1/callback-events",
        headers={"Authorization": "Bearer receiver-token"},
        json={"caller_e164": None, "cli_presented": False},
    )
    assert response.status_code == 200
    assert response.json()["matched"] is False
    outcomes = (await db.scalars(sa.select(EnrolmentAttemptModel.outcome))).all()
    assert EnrolmentOutcome.NO_CALLER_ID in outcomes


async def test_a_heartbeat_is_an_event_with_no_caller(db, service_token) -> None:
    """§9.4: the receiver proves it is alive by posting, not by seeing a call."""
    receiver = await _receiver(db, up=False)
    response = await service_token.post(
        "/api/service/v1/callback-events",
        headers={"Authorization": "Bearer receiver-token"},
        json={"heartbeat": True},
    )
    assert response.status_code == 200
    assert response.json() == {
        "stored": False,
        "matched": False,
        "receiver_status": "up",
    }
    await db.refresh(receiver)
    assert receiver.last_heartbeat_at is not None


async def test_an_expired_challenge_becomes_expired_on_the_next_poll(
    db, installation_factory, device_client_factory
) -> None:
    from src.modules.enrolment.models import NumberVerificationModel

    await _receiver(db)
    installation = await installation_factory(status=InstallationStatus.PENDING)
    device = await device_client_factory(installation)
    started = await device.post("/api/device/v1/enrolment/verify/callback/start")
    verification_id = started.json()["verification_id"]

    verification = await db.get(NumberVerificationModel, uuid.UUID(verification_id))
    verification.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()

    response = await device.get(
        f"/api/device/v1/enrolment/verify/callback/status?verification_id={verification_id}"
    )
    assert response.json()["state"] == "expired"
    assert response.json()["failure"] == "timeout"


async def test_the_receiver_endpoint_needs_the_callback_scope(
    db, admin, manager
) -> None:
    """UC-29: a machine token scoped elsewhere cannot report callbacks."""
    await _receiver(db)
    for http_client in (admin, manager):
        response = await http_client.post(
            "/api/service/v1/callback-events", json={"heartbeat": True}
        )
        assert response.status_code == 403


async def test_the_enrolment_banner_says_when_nobody_can_enrol(db, admin) -> None:
    """If the receiver is down the page says so before anyone tries."""
    down = (await admin.get("/api/v1/enrolment/receiver-status")).json()
    assert down["enrolment_possible"] is False

    await _receiver(db)
    up = (await admin.get("/api/v1/enrolment/receiver-status")).json()
    assert up["enrolment_possible"] is True
    assert up["receiver_msisdn"] == "+998712000000"


async def test_the_receiver_banner_has_a_real_type(db, admin) -> None:
    """§15: an untyped body reaches the contract as a free-form map.

    This is the one endpoint whose failure means nobody can enrol, so it
    should be the best-specified thing on the page rather than the least.
    """
    down = (await admin.get("/api/v1/enrolment/receiver-status")).json()
    assert down == {
        "enrolment_possible": False,
        "receiver_name": None,
        "receiver_msisdn": None,
        "status": "down",
        "active_receivers": 0,
    }

    await _receiver(db)
    up = (await admin.get("/api/v1/enrolment/receiver-status")).json()
    assert up["enrolment_possible"] is True
    assert up["status"] == "up"
    assert up["active_receivers"] == 1
    assert up["receiver_msisdn"] == "+998712000000"


# --- a tunnel that dies between the commit and the response ----------------


async def _redeem_body(code: str, fingerprint: str) -> dict:
    from datetime import UTC, datetime

    return {
        "code": code,
        "device_fingerprint": fingerprint,
        "device_epoch_ms": int(datetime.now(UTC).timestamp() * 1000),
        "device_timezone": "Asia/Tashkent",
        "app": {"variant": "modern34", "version": "1.1.0", "version_code": 2},
        "device": {
            "manufacturer": "Samsung",
            "model": "SM-A546E",
            "android_release": "14",
            "api_level": 34,
            "build_fingerprint_hash": "b" * 64,
        },
        "sim_slot": 0,
        "sim_subscription_id": 1,
    }


async def test_the_same_handset_recovers_a_redemption_whose_response_was_lost(
    db, client, enrolment_code_factory
) -> None:
    """The first step of enrolment, over a tunnel that dies. The field case.

    The server commits, the tunnel drops before the 201 arrives, the app
    retries. Refusing it burns the agent's single-use code and strands them
    until an admin issues another — over the same connection that just failed.
    """
    code = await enrolment_code_factory()
    body = await _redeem_body(code.code, "f" * 64)

    first = await client.post("/api/device/v1/enrolment/redeem", json=body)
    assert first.status_code == 201
    second = await client.post("/api/device/v1/enrolment/redeem", json=body)

    assert second.status_code == 201, second.text
    assert second.json()["installation_id"] == first.json()["installation_id"]
    # A usable token, because the first one was never received.
    assert second.json()["provisional_token"]


async def test_a_different_handset_is_still_refused(
    db, client, enrolment_code_factory
) -> None:
    """The recovery is keyed on the fingerprint, so it cannot become a way for
    a second phone to redeem a code it happens to know."""
    code = await enrolment_code_factory()
    assert (
        await client.post(
            "/api/device/v1/enrolment/redeem", json=await _redeem_body(code.code, "f" * 64)
        )
    ).status_code == 201

    other = await client.post(
        "/api/device/v1/enrolment/redeem", json=await _redeem_body(code.code, "a" * 64)
    )
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "enrolment_code_used"


async def test_a_verified_installation_cannot_be_re_redeemed(
    db, client, enrolment_code_factory, installation_factory
) -> None:
    """Once the number is verified the code is genuinely spent.

    Otherwise anybody holding the code could mint credentials for a live
    installation, which is a way to take one over rather than a way to recover
    from a dropped connection.
    """
    from src.core.enums import InstallationStatus
    from src.modules.installations.models import InstallationModel

    code = await enrolment_code_factory()
    body = await _redeem_body(code.code, "f" * 64)
    first = await client.post("/api/device/v1/enrolment/redeem", json=body)
    assert first.status_code == 201

    installation = await db.get(
        InstallationModel, uuid.UUID(first.json()["installation_id"])
    )
    installation.status = InstallationStatus.ACTIVE
    await db.flush()

    again = await client.post("/api/device/v1/enrolment/redeem", json=body)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "enrolment_code_used"


# --- Route 3: self-declared, and the status poll (§9.3) ---------------------
#
# These two exist because of a dead end the fleet actually sits in: route 1 is
# empty on Uzbek SIMs, route 2 needs a receiver line nobody has provided, and
# admin attestation could not reach the phone. Every test below fails against
# the code as it stood before them.


async def test_a_handset_with_no_proving_route_can_still_finish(
    db, installation_factory, device_client_factory
) -> None:
    """The dead end, closed. Pending → active on the code alone."""
    installation = await installation_factory(status=InstallationStatus.PENDING)
    device = await device_client_factory(installation)

    response = await device.post("/api/device/v1/enrolment/verify/self")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "self_declared"
    assert body["tokens"]["access_token"], "without a real pair it cannot upload"
    await db.refresh(installation)
    assert installation.status is InstallationStatus.ACTIVE


async def test_self_declaring_is_recorded_as_the_weakest_binding(
    db, installation_factory, device_client_factory
) -> None:
    """SPEC §9.3: the identity anchor degrades visibly or not at all.

    If this ever reports ``number_verified`` the panel shows an unproven
    binding as a proven one, and nobody goes back to attest it.
    """
    installation = await installation_factory(status=InstallationStatus.PENDING)
    device = await device_client_factory(installation)

    await device.post("/api/device/v1/enrolment/verify/self")

    await db.refresh(installation)
    assert installation.verification_method is VerificationMethod.SELF_DECLARED
    assert installation.funnel_stage is FunnelStage.SELF_DECLARED
    assert installation.verified_at is not None

    audited = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AuditLogModel)
        .where(
            AuditLogModel.object_id == installation.id,
            AuditLogModel.action == AuditAction.INSTALLATION_SELF_DECLARED,
        )
    )
    assert audited == 1, "the one activation route with no proof must be auditable"


async def test_self_declaring_is_refused_when_the_setting_is_off(
    db, installation_factory, device_client_factory
) -> None:
    """A configuration answer, not a retryable one."""
    await db.execute(
        sa.text(
            "UPDATE app_settings SET value = 'false'::jsonb "
            "WHERE key = 'enrolment.allow_self_declared'"
        )
    )
    await db.flush()
    installation = await installation_factory(status=InstallationStatus.PENDING)
    device = await device_client_factory(installation)

    response = await device.post("/api/device/v1/enrolment/verify/self")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "self_declared_disabled"
    await db.refresh(installation)
    assert installation.status is InstallationStatus.PENDING


async def test_a_revoked_handset_cannot_self_declare_its_way_back(
    installation_factory, device_client_factory
) -> None:
    """UC-08: a revoked installation re-enrols with a new code, or not at all.

    Refused at the token, not in the handler: the principal resolver rejects
    both revoked states before any route sees the request. Asserted here anyway
    because the route is new and the rule is the one that matters — a revoked
    handset must not be able to hand itself a fresh binding.
    """
    installation = await installation_factory(status=InstallationStatus.REVOKED)
    device = await device_client_factory(installation)

    response = await device.post("/api/device/v1/enrolment/verify/self")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "installation_revoked"


async def test_self_declaring_twice_re_mints_rather_than_conflicting(
    db, installation_factory, device_client_factory
) -> None:
    """The lost response, on the link this app is installed over."""
    installation = await installation_factory(status=InstallationStatus.PENDING)
    device = await device_client_factory(installation)

    first = await device.post("/api/device/v1/enrolment/verify/self")
    second = await device.post("/api/device/v1/enrolment/verify/self")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["tokens"]["access_token"]
    assert (
        first.json()["tokens"]["refresh_token"]
        != second.json()["tokens"]["refresh_token"]
    ), "a fresh pair, because the phone has nothing to present"


async def test_self_declaring_does_not_downgrade_a_proven_binding(
    db, installation_factory, device_client_factory, agent_factory,
    registered_number_factory
) -> None:
    """An already-proven installation keeps its method.

    Otherwise a stray retry from a phone that verified properly would rewrite
    its own binding as unproven — the exact silent degradation §9.3 forbids.
    """
    agent = await agent_factory()
    number = await registered_number_factory(agent=agent, e164="+998901112233")
    installation = await installation_factory(
        agent=agent, number=number, status=InstallationStatus.PENDING
    )
    device = await device_client_factory(installation)
    await device.post(
        "/api/device/v1/enrolment/verify/msisdn",
        json={"line1_number": "+998 90 111-22-33", "subscription_id": 2, "sim_slot": 1},
    )

    await device.post("/api/device/v1/enrolment/verify/self")

    await db.refresh(installation)
    assert installation.verification_method is VerificationMethod.SIM_MSISDN
    assert installation.funnel_stage is FunnelStage.NUMBER_VERIFIED


async def test_a_pending_handset_polling_status_gets_no_tokens(
    installation_factory, device_client_factory
) -> None:
    """Waiting is an answer. A credential is not."""
    installation = await installation_factory(status=InstallationStatus.PENDING)
    device = await device_client_factory(installation)

    response = await device.get("/api/device/v1/enrolment/status")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "pending"
    assert body["tokens"] is None


async def test_admin_attestation_reaches_the_phone_through_status(
    db, admin, installation_factory, device_client_factory
) -> None:
    """The hole this endpoint was added for.

    Attesting activated the installation server-side and the handset had no way
    to find out — the real pair is minted at verification, so a phone waiting on
    an admin waited for ever. Now its own screen completes itself.
    """
    installation = await installation_factory(status=InstallationStatus.PENDING)
    device = await device_client_factory(installation)
    assert (await device.get("/api/device/v1/enrolment/status")).json()["tokens"] is None

    attested = await admin.post(
        f"/api/v1/installations/{installation.id}/attest",
        json={"reason": "raqam qo'lda tekshirildi"},
    )
    assert attested.status_code == 200

    response = await device.get("/api/device/v1/enrolment/status")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "attested", "weaker than proven, and rendered as such"
    assert body["tokens"]["access_token"]
    await db.refresh(installation)
    assert installation.status is InstallationStatus.ACTIVE


# --- Rate limiting (SPEC §4.0) ---------------------------------------------
#
# Ten FAILED redemptions an hour from one address. The word "failed" is the
# whole design and `core/ratelimit.py` argues it: the fleet enrols over one
# office Wi-Fi, so fifteen handsets are one address here.


async def test_working_through_codes_is_refused_after_ten_misses(client) -> None:
    limit = ratelimit.ENROLMENT_REDEEM_PER_IP.requests
    for _ in range(limit):
        missed = await client.post(REDEEM, json=redeem_body("ZZZZ9999"))
        assert missed.status_code == 404

    refused = await client.post(REDEEM, json=redeem_body("ZZZZ9998"))
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "rate_limited"
    assert int(refused.headers["Retry-After"]) > 0


async def test_a_whole_office_can_enrol_from_one_address(
    client, enrolment_code_factory
) -> None:
    """The case the limit must not break, and would have.

    Fifteen salespeople, one Wi-Fi, one afternoon: to a server behind Caddy
    that is a single source address making fifteen redemptions. Counting the
    successful ones would have told the eleventh of them to come back in an
    hour, on the first day the product was used.
    """
    handsets = ratelimit.ENROLMENT_REDEEM_PER_IP.requests + 5
    for n in range(handsets):
        # Spelled out rather than taken from the factory's default, which ends
        # in two hex characters — fifteen of those collide on the unique index
        # often enough to fail this test about one run in three.
        code = await enrolment_code_factory(code=f"K7M4PQ{n:02d}")
        accepted = await client.post(
            REDEEM,
            json=redeem_body(code.code, device_fingerprint=f"{n:064d}"),
        )
        assert accepted.status_code == 201, accepted.json()


async def test_the_handset_retrying_a_lost_response_is_not_an_attempt(
    client, enrolment_code_factory
) -> None:
    """`_resume_redeem` is the field recovery path, not a guess.

    The tunnel drops after the server commits and before the 201 arrives, so
    the app re-sends the code it holds — that is what it is built to do. If
    those repeats counted, the phone with the worst connection in the fleet
    would be the one the limiter turned away.
    """
    code = await enrolment_code_factory()
    first = await client.post(REDEEM, json=redeem_body(code.code))
    assert first.status_code == 201

    for _ in range(ratelimit.ENROLMENT_REDEEM_PER_IP.requests + 3):
        again = await client.post(REDEEM, json=redeem_body(code.code))
        assert again.status_code == 201
        assert again.json()["installation_id"] == first.json()["installation_id"]


async def test_the_per_code_half_of_the_limit_is_the_code_row_not_this_window(
    db, client, enrolment_code_factory
) -> None:
    """SPEC §4.0 asks for five per code, and that half predates this one.

    It is counted on the code itself and auto-revokes, so it survives a restart
    and is not per-process. Asserted here so nobody adds a second counter for
    the same rule when they come to read §4.0.
    """
    code = await enrolment_code_factory(
        expires_at=datetime.now(UTC) - timedelta(minutes=1)
    )
    for _ in range(MAX_CODE_ATTEMPTS):
        await client.post(REDEEM, json=redeem_body(code.code))

    await db.refresh(code)
    assert code.attempt_count == MAX_CODE_ATTEMPTS
    assert code.revoked_at is not None
    # And the retries an owner makes on a code they DID redeem never reach
    # this, because the revoke is guarded on `redeemed_at is None`.
