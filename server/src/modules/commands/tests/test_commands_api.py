"""The command lifecycle (T55, UC-16).

The rule that matters most is negative: **no call row is ever linked to a
failed command.** A panel showing a dial that failed next to a call that
happened is a contradiction an admin cannot resolve.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from src.core.enums import AuditAction, CommandStatus
from src.modules.audit.models import AuditLogModel
from src.modules.commands.models import CommandModel
from src.modules.commands.service import CommandService

pytestmark = pytest.mark.asyncio


async def test_a_manager_can_dial(manager, installation_factory) -> None:
    installation = await installation_factory()
    response = await manager.post(
        f"/api/v1/devices/{installation.id}/commands",
        json={"kind": "dial", "number": "+998 93 555-44-33"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "pending"


async def test_the_dialled_number_is_normalised(db, manager, installation_factory) -> None:
    installation = await installation_factory()
    body = (
        await manager.post(
            f"/api/v1/devices/{installation.id}/commands",
            json={"kind": "dial", "number": "8 93 555 44 33"},
        )
    ).json()
    command = await db.get(CommandModel, uuid.UUID(body["id"]))
    assert command.payload["number"] == "+998935554433"


async def test_issuing_a_command_is_audited_under_its_own_action(
    db, manager, installation_factory
) -> None:
    """It is the only action in the product that reaches into hardware the
    company does not own, so it is filterable on its own."""
    installation = await installation_factory()
    await manager.post(
        f"/api/v1/devices/{installation.id}/commands",
        json={"kind": "dial", "number": "+998935554433"},
    )
    row = await db.scalar(
        sa.select(AuditLogModel).where(
            AuditLogModel.action == AuditAction.COMMAND_ISSUED
        )
    )
    assert row is not None
    assert row.detail["kind"] == "dial"
    assert row.detail["agent_id"] == str(installation.agent_id)


async def test_a_manager_cannot_push_config_or_log_a_device_out(
    manager, installation_factory
) -> None:
    """``commands:dial`` is not ``settings:write`` (SPEC §4.7)."""
    installation = await installation_factory()
    for kind in ("config", "logout"):
        response = await manager.post(
            f"/api/v1/devices/{installation.id}/commands", json={"kind": kind}
        )
        assert response.status_code == 403, kind


async def test_an_admin_can_push_config(admin, installation_factory) -> None:
    installation = await installation_factory()
    response = await admin.post(
        f"/api/v1/devices/{installation.id}/commands", json={"kind": "recheck"}
    )
    assert response.status_code == 202


async def test_sales_cannot_dial_anybody(sales, installation_factory) -> None:
    installation = await installation_factory()
    response = await sales.post(
        f"/api/v1/devices/{installation.id}/commands",
        json={"kind": "dial", "number": "+998935554433"},
    )
    assert response.status_code == 403


async def test_a_dial_without_a_number_is_refused(manager, installation_factory) -> None:
    installation = await installation_factory()
    response = await manager.post(
        f"/api/v1/devices/{installation.id}/commands", json={"kind": "dial"}
    )
    assert response.status_code == 409


async def test_the_device_collects_and_acknowledges(
    db, manager, installation_factory, device_client_factory
) -> None:
    installation = await installation_factory()
    device = await device_client_factory(installation)
    issued = (
        await manager.post(
            f"/api/v1/devices/{installation.id}/commands",
            json={"kind": "dial", "number": "+998935554433"},
        )
    ).json()

    pending = (await device.get("/api/device/v1/commands")).json()
    assert [c["command_id"] for c in pending["commands"]] == [issued["id"]]
    assert pending["commands"][0]["number"] == "+998935554433"

    await device.post(
        f"/api/device/v1/commands/{issued['id']}/ack", json={"status": "acknowledged"}
    )
    command = await db.get(CommandModel, uuid.UUID(issued["id"]))
    assert command.status is CommandStatus.ACKNOWLEDGED
    assert command.latency_ms is not None, "UC-16's bar is measured, not assumed"


async def test_an_expired_dial_is_never_handed_over(
    db, manager, installation_factory, device_client_factory
) -> None:
    """UC-16: a phone that wakes after three minutes must not ring."""
    installation = await installation_factory()
    device = await device_client_factory(installation)
    issued = (
        await manager.post(
            f"/api/v1/devices/{installation.id}/commands",
            json={"kind": "dial", "number": "+998935554433"},
        )
    ).json()
    command = await db.get(CommandModel, uuid.UUID(issued["id"]))
    command.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()

    pending = (await device.get("/api/device/v1/commands")).json()
    assert pending["commands"] == []
    await db.refresh(command)
    assert command.status is CommandStatus.EXPIRED


async def test_an_acknowledged_dial_links_its_call(
    db, manager, installation_factory, device_client_factory, call_factory
) -> None:
    installation = await installation_factory()
    device = await device_client_factory(installation)
    call = await call_factory(installation=installation)
    issued = (
        await manager.post(
            f"/api/v1/devices/{installation.id}/commands",
            json={"kind": "dial", "number": "+998935554433"},
        )
    ).json()

    await device.post(
        f"/api/device/v1/commands/{issued['id']}/ack",
        json={
            "status": "acknowledged",
            "result_client_call_id": str(call.client_call_id),
        },
    )
    await db.refresh(call)
    assert call.command_id == uuid.UUID(issued["id"])


async def test_no_call_is_ever_linked_to_a_failed_command(
    db, manager, installation_factory, device_client_factory, call_factory
) -> None:
    """UC-16's acceptance criterion, and the one that must not regress.

    The partial unique index stops two calls claiming one command; this stops a
    call being attached to a command that never succeeded.
    """
    installation = await installation_factory()
    device = await device_client_factory(installation)
    call = await call_factory(installation=installation)
    issued = (
        await manager.post(
            f"/api/v1/devices/{installation.id}/commands",
            json={"kind": "dial", "number": "+998935554433"},
        )
    ).json()

    await device.post(
        f"/api/device/v1/commands/{issued['id']}/ack",
        json={
            "status": "failed",
            "failure_reason": "no_permission",
            "result_client_call_id": str(call.client_call_id),
        },
    )
    command = await db.get(CommandModel, uuid.UUID(issued["id"]))
    assert command.status is CommandStatus.FAILED
    assert command.failure_reason.value == "no_permission"
    assert command.result_call_id is None
    await db.refresh(call)
    assert call.command_id is None


async def test_two_calls_cannot_claim_one_command(
    db, manager, installation_factory, call_factory
) -> None:
    """Enforced by the partial unique index, not by this code."""
    from sqlalchemy.exc import IntegrityError

    installation = await installation_factory()
    issued = (
        await manager.post(
            f"/api/v1/devices/{installation.id}/commands",
            json={"kind": "dial", "number": "+998935554433"},
        )
    ).json()
    command_id = uuid.UUID(issued["id"])
    first = await call_factory(installation=installation)
    second = await call_factory(installation=installation)
    first.command_id = command_id
    await db.flush()
    second.command_id = command_id
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_a_command_nobody_answered_fails_with_a_reason(
    db, manager, installation_factory, device_client_factory
) -> None:
    """"It did not work" without a reason is not actionable (UC-16 AC)."""
    installation = await installation_factory()
    device = await device_client_factory(installation)
    issued = (
        await manager.post(
            f"/api/v1/devices/{installation.id}/commands",
            json={"kind": "dial", "number": "+998935554433"},
        )
    ).json()
    await device.get("/api/device/v1/commands")  # marks it sent

    command = await db.get(CommandModel, uuid.UUID(issued["id"]))
    command.sent_at = datetime.now(UTC) - timedelta(seconds=30)
    await db.flush()

    assert await CommandService(db).expire_stale() == 1
    await db.refresh(command)
    assert command.status is CommandStatus.FAILED
    assert command.failure_reason.value == "device_offline"


async def test_the_panel_can_read_the_latency_history(
    manager, installation_factory, device_client_factory
) -> None:
    """The device page shows p50/p90 per model from these rows (R3)."""
    installation = await installation_factory()
    device = await device_client_factory(installation)
    issued = (
        await manager.post(
            f"/api/v1/devices/{installation.id}/commands",
            json={"kind": "dial", "number": "+998935554433"},
        )
    ).json()
    await device.post(
        f"/api/device/v1/commands/{issued['id']}/ack", json={"status": "acknowledged"}
    )
    body = (await manager.get(f"/api/v1/devices/{installation.id}/commands")).json()
    assert body["total"] == 1
    assert body["items"][0]["latency_ms"] is not None


async def test_commands_need_a_token(client, installation_factory) -> None:
    installation = await installation_factory()
    assert (
        await client.post(
            f"/api/v1/devices/{installation.id}/commands", json={"kind": "recheck"}
        )
    ).status_code == 401
    assert (await client.get("/api/device/v1/commands")).status_code == 401


async def test_a_device_cannot_acknowledge_another_phones_command(
    manager, installation_factory, device_client_factory
) -> None:
    first = await installation_factory()
    second = await installation_factory()
    issued = (
        await manager.post(
            f"/api/v1/devices/{first.id}/commands",
            json={"kind": "dial", "number": "+998935554433"},
        )
    ).json()
    stranger = await device_client_factory(second)
    response = await stranger.post(
        f"/api/device/v1/commands/{issued['id']}/ack", json={"status": "acknowledged"}
    )
    assert response.status_code == 404
