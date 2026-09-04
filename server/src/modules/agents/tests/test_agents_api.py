"""Agents CRUD and archiving (T31)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from src.core.enums import UserRole

pytestmark = pytest.mark.asyncio


async def test_admin_creates_and_lists_an_agent(admin) -> None:
    created = await admin.post("/api/v1/agents", json={"full_name": "Aziz Karimov"})
    assert created.status_code == 201
    listed = await admin.get("/api/v1/agents")
    assert any(item["full_name"] == "Aziz Karimov" for item in listed.json()["items"])


async def test_manager_may_read_but_not_write(manager) -> None:
    assert (await manager.get("/api/v1/agents")).status_code == 200
    response = await manager.post("/api/v1/agents", json={"full_name": "Nope"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_sales_cannot_see_the_roster(sales) -> None:
    """A salesperson who can list agents can work out who else is enrolled."""
    assert (await sales.get("/api/v1/agents")).status_code == 403


async def test_without_a_token_it_is_401(client) -> None:
    assert (await client.get("/api/v1/agents")).status_code == 401


async def test_an_unknown_agent_is_404(admin) -> None:
    assert (await admin.get(f"/api/v1/agents/{uuid.uuid4()}")).status_code == 404


async def test_employee_code_is_unique_where_present(admin) -> None:
    await admin.post("/api/v1/agents", json={"full_name": "A", "employee_code": "E-1"})
    clash = await admin.post(
        "/api/v1/agents", json={"full_name": "B", "employee_code": "E-1"}
    )
    assert clash.status_code == 409
    # ...but two agents with no code are fine: it is a partial unique index.
    assert (await admin.post("/api/v1/agents", json={"full_name": "C"})).status_code == 201


async def test_archiving_is_refused_while_a_number_is_still_theirs(
    admin, agent_factory, registered_number_factory
) -> None:
    """A line nobody holds cannot attribute the calls that arrive tomorrow."""
    agent = await agent_factory()
    await registered_number_factory(agent=agent)
    response = await admin.post(f"/api/v1/agents/{agent.id}/archive")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agent_has_open_assignment"


async def test_archiving_succeeds_once_the_number_is_handed_over(
    db, admin, agent_factory, registered_number_factory, user_factory
) -> None:
    from src.modules.numbers.models import NumberAssignmentModel

    agent = await agent_factory()
    number = await registered_number_factory()
    issuer = await user_factory(UserRole.ADMIN)
    db.add(
        NumberAssignmentModel(
            number_id=number.id,
            agent_id=agent.id,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            valid_to=datetime(2026, 6, 1, tzinfo=UTC),
            created_by=issuer.id,
        )
    )
    await db.flush()

    response = await admin.post(f"/api/v1/agents/{agent.id}/archive")
    assert response.status_code == 200
    assert response.json()["archived_at"] is not None
    assert response.json()["is_active"] is False


async def test_an_archived_agent_is_hidden_unless_asked_for(admin, agent_factory) -> None:
    """Archived, never deleted: their calls are still theirs."""
    agent = await agent_factory()
    await admin.post(f"/api/v1/agents/{agent.id}/archive")
    default = (await admin.get("/api/v1/agents")).json()["items"]
    assert str(agent.id) not in {item["id"] for item in default}
    included = (await admin.get("/api/v1/agents?include_archived=true")).json()["items"]
    assert str(agent.id) in {item["id"] for item in included}


async def test_search_escapes_ilike_metacharacters(admin) -> None:
    """Searching for '%' must not match every row."""
    await admin.post("/api/v1/agents", json={"full_name": "Aziz"})
    await admin.post("/api/v1/agents", json={"full_name": "100% Bonus"})
    body = (await admin.get("/api/v1/agents?q=%25")).json()
    assert [item["full_name"] for item in body["items"]] == ["100% Bonus"]


async def test_creating_an_agent_writes_an_audit_row(db, admin) -> None:
    import sqlalchemy as sa

    from src.core.enums import AuditAction
    from src.modules.audit.models import AuditLogModel

    await admin.post("/api/v1/agents", json={"full_name": "Audited"})
    rows = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AuditLogModel)
        .where(AuditLogModel.action == AuditAction.AGENT_CREATED)
    )
    assert rows == 1


# --- The roster import (T59) ------------------------------------------------

ROSTER = """full_name,employee_code
Aziz Karimov,E-001
Bekzod Rahimov,E-002
Dilnoza Yusupova,
"""


async def test_the_import_is_a_dry_run_by_default(db, admin) -> None:
    """A roster import that half-succeeded is harder to recover from than one
    that did not run, so the diff comes first."""
    response = await admin.post("/api/v1/agents/import", json={"csv": ROSTER})
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["created"] == 3
    assert (await admin.get("/api/v1/agents")).json()["total"] == 0


async def test_applying_the_import_creates_the_roster(admin) -> None:
    await admin.post("/api/v1/agents/import", json={"csv": ROSTER, "dry_run": False})
    listed = (await admin.get("/api/v1/agents")).json()
    assert listed["total"] == 3
    assert {row["full_name"] for row in listed["items"]} == {
        "Aziz Karimov",
        "Bekzod Rahimov",
        "Dilnoza Yusupova",
    }


async def test_re_running_the_import_changes_nothing(admin) -> None:
    """It is a one-off, but somebody will run it twice."""
    await admin.post("/api/v1/agents/import", json={"csv": ROSTER, "dry_run": False})
    again = await admin.post(
        "/api/v1/agents/import", json={"csv": ROSTER, "dry_run": False}
    )
    assert again.json()["skipped"] == 3
    assert again.json()["created"] == 0
    assert (await admin.get("/api/v1/agents")).json()["total"] == 3


async def test_a_renamed_person_is_an_update_not_a_duplicate(admin) -> None:
    """Matched on the employee code, which is what that column is for."""
    await admin.post("/api/v1/agents/import", json={"csv": ROSTER, "dry_run": False})
    renamed = "full_name,employee_code\nAziz Karimov-Yusupov,E-001\n"
    body = (
        await admin.post(
            "/api/v1/agents/import", json={"csv": renamed, "dry_run": False}
        )
    ).json()
    assert body["updated"] == 1
    listed = (await admin.get("/api/v1/agents")).json()
    assert listed["total"] == 3
    assert "Aziz Karimov-Yusupov" in {row["full_name"] for row in listed["items"]}


async def test_a_nameless_row_is_an_error_not_a_silent_skip(admin) -> None:
    """A dropped salesperson is discovered when their calls belong to nobody."""
    body = (
        await admin.post(
            "/api/v1/agents/import", json={"csv": "full_name,employee_code\n,E-009\n"}
        )
    ).json()
    assert body["errors"] == 1
    assert body["rows"][0]["reason"] == "empty name"


async def test_the_applied_import_is_audited(db, admin) -> None:
    import sqlalchemy as sa

    from src.core.enums import AuditAction
    from src.modules.audit.models import AuditLogModel

    await admin.post("/api/v1/agents/import", json={"csv": ROSTER, "dry_run": False})
    rows = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AuditLogModel)
        .where(AuditLogModel.action == AuditAction.AGENTS_IMPORTED)
    )
    assert rows == 1


async def test_a_dry_run_is_not_an_event(db, admin) -> None:
    import sqlalchemy as sa

    from src.modules.audit.models import AuditLogModel

    await admin.post("/api/v1/agents/import", json={"csv": ROSTER})
    assert await db.scalar(sa.select(sa.func.count()).select_from(AuditLogModel)) == 0


async def test_only_agents_write_may_import(manager, sales) -> None:
    for http_client in (manager, sales):
        response = await http_client.post(
            "/api/v1/agents/import", json={"csv": ROSTER}
        )
        assert response.status_code == 403
