"""The audit log (T54, UC-24, N27)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_audit_is_admin_only(admin, manager, sales, viewer, client) -> None:
    """A manager is one of the people this log records. That is the reason."""
    assert (await admin.get("/api/v1/audit")).status_code == 200
    for other in (manager, sales, viewer):
        assert (await other.get("/api/v1/audit")).status_code == 403
    assert (await client.get("/api/v1/audit")).status_code == 401


async def test_actions_are_recorded_and_filterable(admin) -> None:
    await admin.post("/api/v1/agents", json={"full_name": "Audited"})
    body = (await admin.get("/api/v1/audit?action=agent_created")).json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["actor_type"] == "user"
    assert row["object_type"] == "agents"
    assert row["at"]


async def test_there_is_no_route_that_changes_an_audit_row() -> None:
    """UC-24/N27: append-only through the API as well as in the database.

    The trigger makes it impossible; this makes it obvious.
    """
    from fastapi.routing import APIRoute

    from src.main import create_app

    app = create_app()
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1/audit"):
            assert route.methods <= {"GET", "HEAD", "OPTIONS"}, route.path


async def test_the_audit_detail_never_carries_a_secret(db, admin, user_factory) -> None:
    """N26. A password reset is audited; the password is not."""
    import json

    from src.core.enums import UserRole

    victim = await user_factory(UserRole.MANAGER)
    await admin.post(
        f"/api/v1/users/{victim.id}/password", json={"password": "a-secret-one-here"}
    )
    body = (await admin.get("/api/v1/audit?action=password_reset")).json()
    assert body["total"] == 1
    assert "a-secret-one-here" not in json.dumps(body)
