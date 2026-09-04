"""Registered numbers and the time-boxed assignment chain (T31).

The 409 that names the current holder is UC-01's acceptance criterion, and the
overlap refusal is the constraint that stops two admins forking the identity
anchor.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.asyncio

MOMENT = datetime(2026, 6, 1, 9, tzinfo=UTC)


async def test_three_formats_of_one_number_are_one_row(admin) -> None:
    """N37: the uniqueness that matters is the last-9 key, not the string."""
    first = await admin.post("/api/v1/numbers", json={"e164": "+998 90 111-22-33"})
    assert first.status_code == 201
    assert first.json()["e164"] == "+998901112233"
    assert first.json()["phone_key"] == "901112233"

    for variant in ("998901112233", "901112233", "8 90 111 22 33"):
        clash = await admin.post("/api/v1/numbers", json={"e164": variant})
        assert clash.status_code == 409, variant


async def test_a_number_with_fewer_than_nine_digits_is_refused(admin) -> None:
    """It could never match a call, so storing it would create a dead line."""
    response = await admin.post("/api/v1/numbers", json={"e164": "1234567"})
    assert response.status_code == 422


async def test_assigning_a_held_number_names_the_current_holder(
    admin, agent_factory, registered_number_factory
) -> None:
    """UC-01: "already assigned" without a name sends an admin hunting."""
    holder = await agent_factory(full_name="Aziz Karimov")
    number = await registered_number_factory(agent=holder)
    newcomer = await agent_factory(full_name="Bekzod")

    response = await admin.post(
        f"/api/v1/numbers/{number.id}/assignments",
        json={"agent_id": str(newcomer.id)},
    )
    assert response.status_code == 409
    detail = response.json()["error"]["detail"]
    assert detail["agent_name"] == "Aziz Karimov"
    assert detail["agent_id"] == str(holder.id)


async def test_a_handover_is_a_close_then_an_assign(
    admin, agent_factory, registered_number_factory
) -> None:
    """The normal case: one closed period followed by an open one."""
    first = await agent_factory()
    second = await agent_factory()
    number = await registered_number_factory(agent=first)

    history = (await admin.get(f"/api/v1/numbers/{number.id}/assignments")).json()
    open_assignment = history["items"][0]

    closed = await admin.patch(
        f"/api/v1/assignments/{open_assignment['id']}",
        json={"valid_to": MOMENT.isoformat()},
    )
    assert closed.status_code == 200

    handover = await admin.post(
        f"/api/v1/numbers/{number.id}/assignments",
        json={"agent_id": str(second.id), "valid_from": MOMENT.isoformat()},
    )
    assert handover.status_code == 201

    history = (await admin.get(f"/api/v1/numbers/{number.id}/assignments")).json()
    assert history["total"] == 2


async def test_an_overlapping_period_is_refused(
    admin, agent_factory, registered_number_factory
) -> None:
    first = await agent_factory()
    second = await agent_factory()
    number = await registered_number_factory(
        agent=first, valid_from=MOMENT - timedelta(days=10)
    )
    response = await admin.post(
        f"/api/v1/numbers/{number.id}/assignments",
        json={
            "agent_id": str(second.id),
            "valid_from": (MOMENT - timedelta(days=5)).isoformat(),
            "valid_to": (MOMENT + timedelta(days=5)).isoformat(),
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "number_already_assigned"


async def test_valid_to_before_valid_from_is_refused(
    admin, agent_factory, registered_number_factory
) -> None:
    agent = await agent_factory()
    number = await registered_number_factory()
    response = await admin.post(
        f"/api/v1/numbers/{number.id}/assignments",
        json={
            "agent_id": str(agent.id),
            "valid_from": MOMENT.isoformat(),
            "valid_to": (MOMENT - timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 409


async def test_assigning_to_an_archived_agent_is_404(
    admin, agent_factory, registered_number_factory
) -> None:
    agent = await agent_factory()
    await admin.post(f"/api/v1/agents/{agent.id}/archive")
    number = await registered_number_factory()
    response = await admin.post(
        f"/api/v1/numbers/{number.id}/assignments", json={"agent_id": str(agent.id)}
    )
    assert response.status_code == 404


async def test_manager_reads_numbers_but_cannot_assign(
    manager, agent_factory, registered_number_factory
) -> None:
    number = await registered_number_factory()
    assert (await manager.get("/api/v1/numbers")).status_code == 200
    agent = await agent_factory()
    response = await manager.post(
        f"/api/v1/numbers/{number.id}/assignments", json={"agent_id": str(agent.id)}
    )
    assert response.status_code == 403


async def test_sales_cannot_see_the_number_list(sales) -> None:
    assert (await sales.get("/api/v1/numbers")).status_code == 403


async def test_without_a_token_it_is_401(client) -> None:
    assert (await client.get("/api/v1/numbers")).status_code == 401


async def test_an_agents_whole_number_history_comes_in_one_request(
    admin, agent_factory, registered_number_factory
) -> None:
    """One filtered request, not one per number: fifteen cached round trips
    are fine and three hundred are not."""
    agent = await agent_factory()
    await registered_number_factory(agent=agent, e164="+998901112201")
    second = await registered_number_factory()
    await admin.post(
        f"/api/v1/numbers/{second.id}/assignments", json={"agent_id": str(agent.id)}
    )
    other = await agent_factory()
    await registered_number_factory(agent=other)

    body = (await admin.get(f"/api/v1/assignments?agent_id={agent.id}")).json()
    assert body["total"] == 2
    assert all(item["agent_id"] == str(agent.id) for item in body["items"])
