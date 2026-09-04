"""Device telemetry ingest: heartbeat, drift, delta, events, version gate.

The value of the whole product depends on **absence being an event**: an OEM
battery manager killing the capture service is invisible unless the server
notices that a phone stopped saying anything (R3). These are the tests for
noticing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from src.core.enums import AlertKind, AppVariant, InstallationStatus
from src.modules.alerts.models import AlertModel
from src.modules.devices.models import (
    CallLogDeltaModel,
    CapabilityStateModel,
    CapabilityTransitionModel,
    DeviceHealthModel,
)

pytestmark = pytest.mark.asyncio

HEARTBEAT = "/api/device/v1/heartbeat"
CAPABILITIES = "/api/device/v1/capabilities"


def beat(**overrides) -> dict:
    payload = {
        "device_epoch_ms": int(datetime.now(UTC).timestamp() * 1000),
        "device_timezone": "Asia/Tashkent",
        "device_rtt_ms": 180,
        "app_version": "1.0.0",
        "app_variant": "modern34",
        "api_level": 33,
        "battery_level": 71,
        "battery_charging": False,
        "battery_optimisation_exempt": True,
        "free_storage_bytes": 4_000_000_000,
        "queue_records": 0,
        "queue_bytes": 0,
        "network_type": "wifi",
        "service_running": True,
        "capture_enabled": True,
        "recording_route": "oem_file_harvest",
        "recording_route_ok": True,
        "ws_connected": True,
    }
    payload.update(overrides)
    return payload


async def test_a_heartbeat_writes_every_uc17_field(
    db, installation_factory, device_client_factory
) -> None:
    installation = await installation_factory()
    client = await device_client_factory(installation)
    response = await client.post(HEARTBEAT, json=beat())

    assert response.status_code == 200
    assert response.json()["server_time"]
    health = await db.get(DeviceHealthModel, installation.id)
    assert health.battery_level == 71
    assert health.battery_optimisation_exempt is True
    assert health.queue_records == 0
    assert health.recording_route_ok is True
    assert health.last_heartbeat_at is not None


async def test_the_heartbeat_computes_clock_skew(
    db, installation_factory, device_client_factory
) -> None:
    """N36: the device's raw clock is evidence, and this is where it is read."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    behind = int((datetime.now(UTC) - timedelta(hours=2)).timestamp() * 1000)
    body = (await client.post(HEARTBEAT, json=beat(device_epoch_ms=behind))).json()
    assert 7100 < body["clock_skew_sec"] < 7300
    health = await db.get(DeviceHealthModel, installation.id)
    assert health.clock_skew_sec == body["clock_skew_sec"]


async def test_a_dead_service_raises_an_alert(
    db, installation_factory, device_client_factory
) -> None:
    """UC-05: the app reports it, because the OS may refuse to restart it."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    await client.post(HEARTBEAT, json=beat(service_running=False))
    kinds = (await db.scalars(sa.select(AlertModel.kind))).all()
    assert AlertKind.SERVICE_NOT_RUNNING in kinds


async def test_a_returning_device_clears_its_offline_alert(
    db, installation_factory, device_client_factory
) -> None:
    """A phone that fixed itself must not leave an admin a box to tick."""
    from src.modules.devices.service import DeviceService

    installation = await installation_factory()
    db.add(
        DeviceHealthModel(
            installation_id=installation.id,
            last_heartbeat_at=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    await db.flush()
    offline = await DeviceService(db).sweep_offline()
    assert installation.id in offline

    client = await device_client_factory(installation)
    await client.post(HEARTBEAT, json=beat())
    alert = await db.scalar(
        sa.select(AlertModel).where(AlertModel.kind == AlertKind.DEVICE_OFFLINE)
    )
    assert alert.resolved_at is not None


# --- Capability drift (T37, UC-06, UC-18) ----------------------------------


def capability(name: str, state: str) -> dict:
    return {
        "capability": name,
        "state": state,
        "checked_at": datetime.now(UTC).isoformat(),
        "detail": "1s test capture 32 kB",
    }


async def test_the_first_report_stores_state_without_alerting(
    db, installation_factory, device_client_factory
) -> None:
    installation = await installation_factory()
    client = await device_client_factory(installation)
    response = await client.post(
        CAPABILITIES,
        json={"capabilities": [capability("microphone", "granted_working")]},
    )
    assert response.status_code == 200
    assert response.json()["alerts_raised"] == 0
    stored = await db.scalar(
        sa.select(CapabilityStateModel).where(
            CapabilityStateModel.installation_id == installation.id
        )
    )
    assert stored.state.value == "granted_working"


async def test_losing_the_microphone_alerts_by_name_inside_the_request(
    db, installation_factory, device_client_factory
) -> None:
    """UC-06's ten-minute bound becomes a reporting-interval question."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    await client.post(
        CAPABILITIES, json={"capabilities": [capability("microphone", "granted_working")]}
    )
    response = await client.post(
        CAPABILITIES, json={"capabilities": [capability("microphone", "denied")]}
    )
    assert response.json()["transitions"] == 1
    assert response.json()["alerts_raised"] == 1

    alert = await db.scalar(
        sa.select(AlertModel).where(
            AlertModel.kind == AlertKind.PERMISSION_LOST_MICROPHONE
        )
    )
    assert alert is not None
    assert alert.installation_id == installation.id
    assert alert.agent_id == installation.agent_id
    assert alert.detail["from"] == "granted_working"


async def test_granted_not_working_is_a_reportable_state(
    db, installation_factory, device_client_factory
) -> None:
    """The OEM permission-manager case UC-03 names: not a green tick."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    await client.post(
        CAPABILITIES, json={"capabilities": [capability("call_log", "granted_working")]}
    )
    response = await client.post(
        CAPABILITIES,
        json={"capabilities": [capability("call_log", "granted_not_working")]},
    )
    assert response.json()["alerts_raised"] == 1


async def test_recovering_resolves_rather_than_raising_again(
    db, installation_factory, device_client_factory
) -> None:
    installation = await installation_factory()
    client = await device_client_factory(installation)
    for state in ("granted_working", "denied", "granted_working"):
        await client.post(
            CAPABILITIES, json={"capabilities": [capability("microphone", state)]}
        )
    alert = await db.scalar(
        sa.select(AlertModel).where(
            AlertModel.kind == AlertKind.PERMISSION_LOST_MICROPHONE
        )
    )
    assert alert.resolved_at is not None


async def test_repeats_bump_the_count_rather_than_inserting_rows(
    db, installation_factory, device_client_factory
) -> None:
    """A phone reporting every two minutes must not make 720 rows a day."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    await client.post(
        CAPABILITIES, json={"capabilities": [capability("microphone", "granted_working")]}
    )
    for _ in range(3):
        await client.post(
            CAPABILITIES, json={"capabilities": [capability("microphone", "denied")]}
        )
        await client.post(
            CAPABILITIES,
            json={"capabilities": [capability("microphone", "granted_not_working")]},
        )
    rows = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AlertModel)
        .where(AlertModel.installation_id == installation.id)
    )
    assert rows == 1


async def test_every_change_appends_a_transition(
    db, installation_factory, device_client_factory
) -> None:
    """The evidence behind an alert has to outlive the alert."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    for state in ("granted_working", "denied", "granted_working"):
        await client.post(
            CAPABILITIES, json={"capabilities": [capability("microphone", state)]}
        )
    count = await db.scalar(
        sa.select(sa.func.count())
        .select_from(CapabilityTransitionModel)
        .where(CapabilityTransitionModel.installation_id == installation.id)
    )
    assert count == 3


async def test_an_agent_cannot_acknowledge_an_alert_from_the_app(
    db, installation_factory, device_client_factory
) -> None:
    """UC-06/UC-18: nothing in the device API can touch the alerts table."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    await client.post(
        CAPABILITIES, json={"capabilities": [capability("microphone", "granted_working")]}
    )
    await client.post(
        CAPABILITIES, json={"capabilities": [capability("microphone", "denied")]}
    )
    alert = await db.scalar(sa.select(AlertModel))
    refused = await client.post(f"/api/v1/alerts/{alert.id}/ack")
    assert refused.status_code in (401, 403, 404)
    await db.refresh(alert)
    assert alert.acknowledged_at is None


async def test_only_an_admin_acknowledges(db, admin, manager, installation_factory) -> None:
    from src.core.enums import AlertSeverity
    from src.modules.alerts.service import AlertService

    installation = await installation_factory()
    alert = await AlertService(db).raise_alert(
        kind=AlertKind.DEVICE_OFFLINE,
        severity=AlertSeverity.WARNING,
        scope=installation.id,
        installation_id=installation.id,
    )
    await db.flush()
    assert (await manager.post(f"/api/v1/alerts/{alert.id}/ack")).status_code == 403
    assert (await admin.post(f"/api/v1/alerts/{alert.id}/ack")).status_code == 200


# --- The production rig (T40) ----------------------------------------------


async def test_the_call_log_delta_is_stored_and_generated(
    db, installation_factory, device_client_factory
) -> None:
    installation = await installation_factory()
    client = await device_client_factory(installation)
    response = await client.post(
        "/api/device/v1/call-log-delta",
        json={
            "period_date": "2026-09-04",
            "device_counted": 31,
            "uploaded_count": 30,
            "subscription_unknown_count": 2,
        },
    )
    assert response.status_code == 200
    assert response.json()["delta"] == 1
    row = await db.scalar(sa.select(CallLogDeltaModel))
    assert row.subscription_unknown_count == 2, (
        "counted separately and never folded into the rate — the fail-closed "
        "rule made visible"
    )


async def test_a_partial_sweep_never_erases_a_full_one(
    db, installation_factory, device_client_factory
) -> None:
    installation = await installation_factory()
    client = await device_client_factory(installation)
    body = {"period_date": "2026-09-04", "device_counted": 31, "uploaded_count": 30}
    await client.post("/api/device/v1/call-log-delta", json=body)
    lower = await client.post(
        "/api/device/v1/call-log-delta", json={**body, "device_counted": 12}
    )
    assert lower.json()["device_counted"] == 31


# --- Device events ----------------------------------------------------------


async def test_a_known_event_raises_its_alert(
    db, installation_factory, device_client_factory
) -> None:
    installation = await installation_factory()
    client = await device_client_factory(installation)
    response = await client.post(
        "/api/device/v1/events", json={"events": [{"kind": "queue_full"}]}
    )
    assert response.json()["alerts_raised"] == 1
    kinds = (await db.scalars(sa.select(AlertModel.kind))).all()
    assert AlertKind.QUEUE_FULL in kinds


async def test_an_unknown_event_is_never_dropped(
    db, installation_factory, device_client_factory
) -> None:
    """A device telling us something we do not understand is itself news."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    response = await client.post(
        "/api/device/v1/events", json={"events": [{"kind": "something_new"}]}
    )
    assert response.json()["alerts_raised"] == 1
    alert = await db.scalar(sa.select(AlertModel))
    assert alert.detail["event"] == "something_new"
    assert alert.severity.value == "info"


async def test_a_routine_event_is_logged_not_alerted(
    db, installation_factory, device_client_factory
) -> None:
    installation = await installation_factory()
    client = await device_client_factory(installation)
    response = await client.post(
        "/api/device/v1/events", json={"events": [{"kind": "boot_completed"}]}
    )
    assert response.json()["alerts_raised"] == 0
    assert await db.scalar(sa.select(sa.func.count()).select_from(AlertModel)) == 0


# --- The version gate (N34, T50) -------------------------------------------


async def _publish(db, version_code: int) -> None:
    from src.modules.catalog.models import AppVersionModel

    db.add(
        AppVersionModel(
            version="9.9.9",
            version_code=version_code,
            variant=AppVariant.MODERN34,
            apk_path="releases/x.apk",
            apk_sha256="d" * 64,
            size_bytes=1,
            published_at=datetime.now(UTC),
            is_current=True,
        )
    )
    await db.flush()


async def _raise_minimum(db, version_code: int) -> None:
    from src.modules.settings.models import AppSettingModel

    row = await db.get(AppSettingModel, "app.min_supported_version_code")
    row.value = version_code
    await db.flush()


async def test_old_client_drains_then_refused(
    db, client, installation_factory, device_client_factory
) -> None:
    """N34, and **the order is the rule** (SPEC §4.3, CONVENTIONS §4 rule 4).

    An under-version client uploads its backlog with 200s, and only then does
    its next refresh return 426. Refusing first destroys the records it is
    holding. This test may not be weakened.
    """
    from src.modules.calls.tests.test_calls_api import call_payload

    installation = await installation_factory(app_version="1.0.0")
    device = await device_client_factory(installation)
    await _publish(db, 900)
    await _raise_minimum(db, 900)

    # 1. The backlog goes up. Ingest never refuses on version.
    for _ in range(20):
        response = await device.post(
            "/api/device/v1/calls", json={"calls": [call_payload()]}
        )
        assert response.status_code == 200, "ingest must accept any version, forever"
        assert response.json()["results"][0]["status"] == "created"

    # 2. While the queue is non-empty, refresh keeps working.
    await device.post(HEARTBEAT, json=beat(queue_records=20, queue_bytes=4096))
    still_working = await client.post(
        "/api/device/v1/auth/refresh", json={"refresh_token": device.refresh_token}
    )
    assert still_working.status_code == 200, (
        "refusing before the queue drains would destroy the 20 records above"
    )

    # 3. The queue drains, and only now is the client refused.
    await device.post(HEARTBEAT, json=beat(queue_records=0, queue_bytes=0))
    refused = await client.post(
        "/api/device/v1/auth/refresh",
        json={"refresh_token": still_working.json()["refresh_token"]},
    )
    assert refused.status_code == 426
    assert refused.json()["error"]["code"] == "app_version_unsupported"


async def test_a_device_that_never_reported_a_queue_is_not_refused(
    db, client, installation_factory, device_client_factory
) -> None:
    """We have not seen its backlog, so we do not know it is safe to refuse."""
    installation = await installation_factory(app_version="1.0.0")
    device = await device_client_factory(installation)
    await _publish(db, 900)
    await _raise_minimum(db, 900)
    response = await client.post(
        "/api/device/v1/auth/refresh", json={"refresh_token": device.refresh_token}
    )
    assert response.status_code == 200


async def test_the_update_block_tells_the_app_before_it_is_refused(
    db, installation_factory, device_client_factory
) -> None:
    """SPEC §4.3: the app keeps capturing and shows the update screen."""
    installation = await installation_factory(app_version="1.0.0")
    device = await device_client_factory(installation)
    await _publish(db, 900)
    await _raise_minimum(db, 900)
    body = (await device.post(HEARTBEAT, json=beat())).json()
    assert body["update"]["required"] is True
    assert body["update"]["min_version_code"] == 900
    assert body["update"]["apk_url"] == "/api/v1/app/download/900"
    assert body["update"]["message_uz"]


async def test_a_current_client_is_not_asked_to_update(
    db, installation_factory, device_client_factory
) -> None:
    installation = await installation_factory(app_version="1.0.0")
    device = await device_client_factory(installation)
    body = (await device.post(HEARTBEAT, json=beat())).json()
    assert body["update"]["required"] is False


async def test_telemetry_needs_a_verified_installation(
    installation_factory, device_client_factory
) -> None:
    installation = await installation_factory(status=InstallationStatus.PENDING)
    device = await device_client_factory(installation)
    assert (await device.post(HEARTBEAT, json=beat())).status_code == 403


async def test_telemetry_without_a_token_is_401(client) -> None:
    assert (await client.post(HEARTBEAT, json=beat())).status_code == 401


# --- Silence detection (T38, UC-27) ----------------------------------------


async def _silent_device(db, installation_factory, hours_ago: float, moment=None):
    """An active installation whose last contact was ``hours_ago`` before
    ``moment`` — which must be the frozen clock, not the wall clock."""
    from src.core import clock

    base = moment or clock.now()
    installation = await installation_factory()
    db.add(
        DeviceHealthModel(
            installation_id=installation.id,
            last_heartbeat_at=base - timedelta(hours=hours_ago),
            last_call_at=base - timedelta(hours=hours_ago),
            service_running=True,
        )
    )
    await db.flush()
    return installation


async def test_a_silent_device_alerts_while_others_report(
    db, installation_factory, frozen_clock
) -> None:
    """UC-27: one phone quiet while the fleet works is that phone's problem."""
    from src.modules.devices.service import DeviceService

    # Midday on a Monday, so the silence is entirely inside working hours.
    frozen_clock(datetime(2026, 9, 7, 9, 0, tzinfo=UTC))
    quiet = await _silent_device(db, installation_factory, hours_ago=6)
    await _silent_device(db, installation_factory, hours_ago=0.1)

    silent = await DeviceService(db).detect_silence()
    assert quiet.id in silent
    kinds = (await db.scalars(sa.select(AlertModel.kind))).all()
    assert AlertKind.DEVICE_SILENT in kinds
    assert AlertKind.FLEET_SILENT not in kinds


async def test_the_whole_fleet_going_quiet_is_one_critical_alert(
    db, installation_factory, frozen_clock
) -> None:
    """Fifteen phones at once is not fifteen device problems.

    It is one server, network or release problem, and it wakes somebody.
    """
    from src.modules.devices.service import DeviceService

    frozen_clock(datetime(2026, 9, 7, 12, 0, tzinfo=UTC))
    for _ in range(3):
        await _silent_device(db, installation_factory, hours_ago=3)

    await DeviceService(db).detect_silence()
    fleet = await db.scalar(
        sa.select(AlertModel).where(AlertModel.kind == AlertKind.FLEET_SILENT)
    )
    assert fleet is not None
    assert fleet.severity.value == "critical"
    assert (
        await db.scalar(
            sa.select(sa.func.count())
            .select_from(AlertModel)
            .where(AlertModel.kind == AlertKind.DEVICE_SILENT)
        )
        == 0
    ), "the fleet alert replaces the per-device noise, it does not add to it"


async def test_silence_overnight_does_not_alert(
    db, installation_factory, frozen_clock
) -> None:
    """A phone that stopped reporting at 20:00 and is asked at 07:00 has been
    quiet for eleven hours and **zero working hours**."""
    from src.modules.devices.service import DeviceService

    # 07:00 Tashkent on a Tuesday is 02:00 UTC; the device last spoke at 20:00
    # Tashkent the evening before, which is the end of the working window.
    frozen_clock(datetime(2026, 9, 8, 2, 0, tzinfo=UTC))
    await _silent_device(db, installation_factory, hours_ago=11)
    await _silent_device(db, installation_factory, hours_ago=11)

    await DeviceService(db).detect_silence()
    assert await db.scalar(sa.select(sa.func.count()).select_from(AlertModel)) == 0


async def test_a_revoked_installation_is_not_expected_to_report(
    db, installation_factory, frozen_clock
) -> None:
    from src.modules.devices.service import DeviceService

    frozen_clock(datetime(2026, 9, 7, 9, 0, tzinfo=UTC))
    revoked = await installation_factory(status=InstallationStatus.REVOKED)
    db.add(
        DeviceHealthModel(
            installation_id=revoked.id,
            last_heartbeat_at=datetime.now(UTC) - timedelta(days=30),
        )
    )
    await db.flush()
    assert await DeviceService(db).detect_silence() == []


async def test_the_offline_sweep_names_the_agent(
    db, installation_factory
) -> None:
    """UC-17's alert has to say who, or an admin cannot act on it."""
    from src.modules.devices.service import DeviceService

    installation = await installation_factory()
    db.add(
        DeviceHealthModel(
            installation_id=installation.id,
            last_heartbeat_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    await db.flush()
    await DeviceService(db).sweep_offline()
    alert = await db.scalar(
        sa.select(AlertModel).where(AlertModel.kind == AlertKind.DEVICE_OFFLINE)
    )
    assert alert.agent_id == installation.agent_id
    assert alert.installation_id == installation.id
