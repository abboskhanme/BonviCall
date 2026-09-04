"""Device health, and the scope rule the list had to learn (UC-17).

SPEC §5.2 gated the list on ``devices:read`` and the detail on
``devices:read | devices:read:own``, which gave a salesperson a page they could
open and no list that led to it. The rule that settles it is the project's own:
scope is narrowed by the query, not by the permission.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.modules.devices.models import DeviceHealthModel

pytestmark = pytest.mark.asyncio


async def _health(db, installation, **overrides) -> DeviceHealthModel:
    row = DeviceHealthModel(
        installation_id=installation.id,
        last_heartbeat_at=overrides.pop("last_heartbeat_at", datetime.now(UTC)),
        battery_level=overrides.pop("battery_level", 71),
        queue_records=overrides.pop("queue_records", 0),
        queue_bytes=overrides.pop("queue_bytes", 0),
        clock_skew_sec=overrides.pop("clock_skew_sec", -3),
        service_running=overrides.pop("service_running", True),
        **overrides,
    )
    db.add(row)
    await db.flush()
    return row


async def test_a_manager_sees_every_device(db, manager, installation_factory) -> None:
    await _health(db, await installation_factory())
    await _health(db, await installation_factory())
    body = (await manager.get("/api/v1/devices")).json()
    assert body["total"] == 2


async def test_a_salesperson_sees_only_their_own_phone(
    db, sales, installation_factory, agent_factory
) -> None:
    """A one-row list that answers the question they actually have."""
    from src.modules.agents.models import AgentModel

    own_agent = await db.get(AgentModel, sales.principal.agent_id)
    mine = await installation_factory(agent=own_agent)
    await _health(db, mine)
    await _health(db, await installation_factory())

    body = (await sales.get("/api/v1/devices")).json()
    assert body["total"] == 1
    assert body["items"][0]["installation_id"] == str(mine.id)


async def test_another_agents_device_is_404_for_a_salesperson(
    db, sales, installation_factory
) -> None:
    theirs = await installation_factory()
    await _health(db, theirs)
    assert (await sales.get(f"/api/v1/devices/{theirs.id}")).status_code == 404


async def test_a_salesperson_can_open_their_own_device_page(
    db, sales, installation_factory, agent_factory
) -> None:
    from src.modules.agents.models import AgentModel

    own_agent = await db.get(AgentModel, sales.principal.agent_id)
    mine = await installation_factory(agent=own_agent)
    await _health(db, mine)
    response = await sales.get(f"/api/v1/devices/{mine.id}")
    assert response.status_code == 200
    assert response.json()["installation_id"] == str(mine.id)


async def test_is_online_is_derived_from_the_last_heartbeat(
    db, manager, installation_factory
) -> None:
    """UC-17: five missed two-minute beats is OFFLINE within ten minutes.

    Derived and never stored — storing it would need a job to keep it false,
    and it would be wrong between runs.
    """
    fresh = await installation_factory()
    await _health(db, fresh, last_heartbeat_at=datetime.now(UTC))
    stale = await installation_factory()
    await _health(db, stale, last_heartbeat_at=datetime.now(UTC) - timedelta(minutes=30))

    body = (await manager.get("/api/v1/devices")).json()
    items = {item["installation_id"]: item for item in body["items"]}
    assert items[str(fresh.id)]["is_online"] is True
    assert items[str(stale.id)]["is_online"] is False


async def test_a_device_that_never_reported_is_offline(
    db, manager, installation_factory
) -> None:
    installation = await installation_factory()
    await _health(db, installation, last_heartbeat_at=None)
    body = (await manager.get("/api/v1/devices")).json()
    assert body["items"][0]["is_online"] is False


async def test_every_uc17_field_is_present(db, manager, installation_factory) -> None:
    """The panel renders these; a missing one is a blank cell nobody notices."""
    installation = await installation_factory()
    await _health(db, installation)
    item = (await manager.get("/api/v1/devices")).json()["items"][0]
    for field in (
        "agent_id", "manufacturer", "model", "android_release", "app_version",
        "app_variant", "last_heartbeat_at", "is_online", "battery_level",
        "battery_optimisation_exempt", "queue_records", "queue_bytes",
        "clock_skew_sec", "recording_route", "recording_route_ok",
        "service_running", "ws_connected",
    ):
        assert field in item, field


async def test_a_viewer_cannot_read_device_health(db, viewer, installation_factory) -> None:
    await _health(db, await installation_factory())
    assert (await viewer.get("/api/v1/devices")).status_code == 403


async def test_without_a_token_it_is_401(client) -> None:
    assert (await client.get("/api/v1/devices")).status_code == 401


async def test_an_unknown_device_is_404(manager) -> None:
    assert (await manager.get(f"/api/v1/devices/{uuid.uuid4()}")).status_code == 404
