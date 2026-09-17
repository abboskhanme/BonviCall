"""The groups endpoints: RBAC, the tree, paging, binding and deletion."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from src.modules.surveys.models import TelegramGroupModel

pytestmark = pytest.mark.asyncio


# ── RBAC (T20's three answers) ─────────────────────────────────────────────


async def test_no_token_is_401(client: AsyncClient) -> None:
    for path in ("/api/v1/groups", "/api/v1/groups/tree"):
        assert (await client.get(path)).status_code == 401


async def test_a_salesperson_cannot_read_the_directory(sales: AsyncClient) -> None:
    """``numbers:read`` is not granted to ``sales`` — N41 promises an employee
    their own calls and their own phone's health, not a map of who else is
    enrolled. The group directory is that map."""
    assert (await sales.get("/api/v1/groups")).status_code == 403
    assert (await sales.get("/api/v1/groups/tree")).status_code == 403


async def test_a_manager_may_read_but_not_write(
    manager: AsyncClient, group_factory
) -> None:
    group = await group_factory()
    assert (await manager.get("/api/v1/groups")).status_code == 200
    response = await manager.patch(
        f"/api/v1/groups/{group.id}", json={"is_active": False}
    )
    assert response.status_code == 403


async def test_a_group_that_does_not_exist_is_404(admin: AsyncClient) -> None:
    assert (
        await admin.get(f"/api/v1/groups/{uuid.uuid4()}")
    ).status_code == 404


# ── The tree ───────────────────────────────────────────────────────────────


async def test_the_tree_counts_without_opening_a_node(
    admin: AsyncClient, agent_factory, group_factory, response_factory, survey_factory
) -> None:
    agent = await agent_factory(full_name="Dilshod")
    survey = await survey_factory(group=await group_factory(agent=agent))
    await response_factory(survey=survey, csat=5)
    await group_factory(agent=agent)
    await group_factory(agent=None)

    body = (await admin.get("/api/v1/groups/tree")).json()
    node = next(row for row in body["agents"] if row["full_name"] == "Dilshod")
    assert node["group_count"] == 2
    assert node["response_count"] == 1
    assert body["unassigned"]["group_count"] == 1


async def test_rebinding_a_group_does_not_move_its_past_ratings(
    admin: AsyncClient, agent_factory, group_factory, survey_factory, response_factory
) -> None:
    """⚠️ This is a FIX, and it is the one that made two screens disagree.

    BonviZvonki's tree groups responses by the GROUP's current ``agent_id``,
    while its ratings page groups by ``surveys.agent_id``. Re-bind a chat and
    every historical rating silently moves to the new employee on one screen
    and not on the other — two numbers for the same person, and nothing to say
    which is right.
    """
    first = await agent_factory(full_name="Birinchi")
    second = await agent_factory(full_name="Ikkinchi")
    group = await group_factory(agent=first)
    await response_factory(survey=await survey_factory(group=group, agent_id=first.id))

    moved = await admin.patch(
        f"/api/v1/groups/{group.id}", json={"agent_id": str(second.id)}
    )
    assert moved.status_code == 200

    body = (await admin.get("/api/v1/groups/tree")).json()
    nodes = {row["full_name"]: row for row in body["agents"]}
    # The rating stays with whoever earned it...
    assert nodes["Birinchi"]["response_count"] == 1
    assert nodes["Ikkinchi"]["response_count"] == 0
    # ...while the GROUP moves.
    assert nodes["Birinchi"]["group_count"] == 0
    assert nodes["Ikkinchi"]["group_count"] == 1


# ── Listing ────────────────────────────────────────────────────────────────


async def test_the_unbound_filter_is_a_real_server_side_filter(
    admin: AsyncClient, group_factory
) -> None:
    """BonviZvonki has no such parameter, FastAPI drops the unknown key
    silently, and its panel walks every page to answer this — twenty requests
    over a thousand rows for one WHERE clause."""
    await group_factory()
    await group_factory(agent=None)

    body = (await admin.get("/api/v1/groups", params={"has_agent": False})).json()
    assert len(body["items"]) == 1
    assert body["items"][0]["agent_id"] is None


async def test_paging_is_keyset_and_returns_every_row_exactly_once(
    admin: AsyncClient, group_factory
) -> None:
    for _ in range(5):
        await group_factory()

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        params: dict[str, object] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = (await admin.get("/api/v1/groups", params=params)).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 5
    assert len(set(seen)) == 5


async def test_a_percent_in_a_title_does_not_match_every_row(
    admin: AsyncClient, group_factory
) -> None:
    """⚠️ A FIX. The source escapes ILIKE metacharacters on its survey search
    and never applied it to the group search, so ``%`` removed the filter
    instead of matching itself."""
    await group_factory(title="100% Mijoz")
    await group_factory(title="Boshqa")

    body = (await admin.get("/api/v1/groups", params={"search": "100%"})).json()
    assert [item["title"] for item in body["items"]] == ["100% Mijoz"]


async def test_inactive_groups_are_hidden_until_asked_for(
    admin: AsyncClient, group_factory
) -> None:
    await group_factory(is_active=False)
    hidden = (await admin.get("/api/v1/groups")).json()
    assert hidden["items"] == []
    shown = (
        await admin.get("/api/v1/groups", params={"include_inactive": True})
    ).json()
    assert len(shown["items"]) == 1


# ── Binding ────────────────────────────────────────────────────────────────


async def test_binding_by_hand_marks_the_row_manual(
    admin: AsyncClient, agent_factory, group_factory
) -> None:
    """The badge the panel shows: automation must not touch this row again."""
    agent = await agent_factory()
    group = await group_factory(agent=None)
    body = (
        await admin.patch(
            f"/api/v1/groups/{group.id}", json={"agent_id": str(agent.id)}
        )
    ).json()
    assert body["bound_by"] == "manual"
    assert body["agent_id"] == str(agent.id)
    assert body["bound_at"] is not None


async def test_releasing_an_employee_clears_the_binding_time_with_it(
    admin: AsyncClient, group_factory, db
) -> None:
    """``bound_has_a_time`` is a CHECK: the source has rows with an agent and
    no ``bound_at`` because one write path forgot the second column."""
    group = await group_factory()
    body = (
        await admin.patch(f"/api/v1/groups/{group.id}", json={"agent_id": None})
    ).json()
    assert body["agent_id"] is None
    assert body["bound_at"] is None


async def test_an_omitted_agent_id_leaves_the_binding_alone(
    admin: AsyncClient, group_factory
) -> None:
    """"Leave the employee" and "release the employee" are different requests
    and Pydantic cannot tell them apart from the value alone."""
    group = await group_factory()
    body = (
        await admin.patch(f"/api/v1/groups/{group.id}", json={"is_active": False})
    ).json()
    assert body["agent_id"] is not None
    assert body["is_active"] is False


async def test_binding_to_an_agent_that_does_not_exist_is_404(
    admin: AsyncClient, group_factory
) -> None:
    group = await group_factory()
    response = await admin.patch(
        f"/api/v1/groups/{group.id}", json={"agent_id": str(uuid.uuid4())}
    )
    assert response.status_code == 404


async def test_a_bulk_patch_changes_every_named_group(
    admin: AsyncClient, agent_factory, group_factory
) -> None:
    agent = await agent_factory()
    groups = [await group_factory(agent=None) for _ in range(3)]
    body = (
        await admin.patch(
            "/api/v1/groups/bulk",
            json={
                "group_ids": [str(group.id) for group in groups],
                "agent_id": str(agent.id),
            },
        )
    ).json()
    assert body["updated"] == 3


async def test_bulk_is_routed_before_the_uuid_segment(admin: AsyncClient) -> None:
    """⚠️ Starlette matches in declaration order. The other way round, ``bulk``
    is parsed as a UUID and the endpoint answers 422 — which is how the source
    learned it, and why the ordering carries a comment there and here."""
    response = await admin.patch(
        "/api/v1/groups/bulk", json={"group_ids": [str(uuid.uuid4())]}
    )
    assert response.status_code != 422


async def test_a_bulk_patch_over_the_limit_is_refused_by_the_schema(
    admin: AsyncClient,
) -> None:
    response = await admin.patch(
        "/api/v1/groups/bulk",
        json={"group_ids": [str(uuid.uuid4()) for _ in range(201)]},
    )
    assert response.status_code == 422


# ── Deletion ───────────────────────────────────────────────────────────────


async def test_a_group_the_bot_is_still_in_cannot_be_deleted(
    admin: AsyncClient, group_factory
) -> None:
    """It would be re-registered on the chat's next message, so the delete
    would look like it worked and silently undo itself."""
    group = await group_factory(bot_status="member")
    response = await admin.delete(f"/api/v1/groups/{group.id}")
    assert response.status_code == 409
    assert response.json()["error"]["detail"]["reason"] == "group_still_active"


@pytest.mark.parametrize("status", ["left", "kicked"])
async def test_a_group_the_bot_has_left_can_be_deleted(
    admin: AsyncClient, group_factory, db, status: str
) -> None:
    group = await group_factory(bot_status=status)
    assert (await admin.delete(f"/api/v1/groups/{group.id}")).status_code == 204
    assert await db.get(TelegramGroupModel, group.id) is None
