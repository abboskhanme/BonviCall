"""Panel account administration (T148).

The two lockout guards are the point: a panel with no admin can only be
repaired from a shell on a host the team does not sit next to.
"""

from __future__ import annotations

import uuid

import pytest

from conftest import TEST_PASSWORD
from src.core.enums import UserRole

pytestmark = pytest.mark.asyncio


async def test_admin_creates_a_manager(admin) -> None:
    response = await admin.post(
        "/api/v1/users",
        json={
            "email": "manager@bonvi.uz",
            "full_name": "Manager",
            "role": "manager",
            "password": TEST_PASSWORD,
        },
    )
    assert response.status_code == 201
    assert response.json()["must_change_password"] is True
    assert "password" not in response.json()
    assert "password_hash" not in response.json()


async def test_a_sales_account_requires_an_agent(admin) -> None:
    """Own-scope narrowing has nothing to narrow on otherwise."""
    response = await admin.post(
        "/api/v1/users",
        json={
            "email": "orphan@bonvi.uz",
            "full_name": "Orphan",
            "role": "sales",
            "password": TEST_PASSWORD,
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "sales_user_requires_agent"


async def test_a_sales_account_with_an_agent_is_created(admin, agent_factory) -> None:
    agent = await agent_factory()
    response = await admin.post(
        "/api/v1/users",
        json={
            "email": "seller@bonvi.uz",
            "full_name": "Seller",
            "role": "sales",
            "agent_id": str(agent.id),
            "password": TEST_PASSWORD,
        },
    )
    assert response.status_code == 201
    assert response.json()["agent_id"] == str(agent.id)


async def test_a_duplicate_email_is_409_not_500(admin) -> None:
    body = {
        "email": "twice@bonvi.uz",
        "full_name": "First",
        "role": "manager",
        "password": TEST_PASSWORD,
    }
    assert (await admin.post("/api/v1/users", json=body)).status_code == 201
    assert (await admin.post("/api/v1/users", json=body)).status_code == 409


async def test_you_cannot_deactivate_yourself(admin) -> None:
    me = admin.principal.id
    response = await admin.patch(f"/api/v1/users/{me}", json={"is_active": False})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "cannot_modify_self"


async def test_the_last_active_admin_cannot_be_demoted(admin, user_factory) -> None:
    """A panel with no admin is an outage, not an inconvenience."""
    other_admin = await user_factory(UserRole.ADMIN)
    # Two admins exist (the fixture's and this one), so demoting one is allowed.
    assert (
        await admin.patch(f"/api/v1/users/{other_admin.id}", json={"role": "manager"})
    ).status_code == 200
    # Now only the caller is left, and they cannot demote themselves either.
    response = await admin.patch(
        f"/api/v1/users/{admin.principal.id}", json={"role": "manager"}
    )
    assert response.status_code == 409


async def test_deactivating_a_user_revokes_their_sessions(
    db, admin, client, user_factory
) -> None:
    import sqlalchemy as sa

    from src.modules.auth.models import RefreshTokenModel

    victim = await user_factory(UserRole.MANAGER, password=TEST_PASSWORD)
    await client.post(
        "/api/v1/auth/login", json={"email": victim.email, "password": TEST_PASSWORD}
    )
    await admin.patch(f"/api/v1/users/{victim.id}", json={"is_active": False})

    live = await db.scalar(
        sa.select(sa.func.count())
        .select_from(RefreshTokenModel)
        .where(
            RefreshTokenModel.user_id == victim.id,
            RefreshTokenModel.revoked_at.is_(None),
        )
    )
    assert live == 0


async def test_an_admin_reset_forces_a_password_change(admin, user_factory) -> None:
    victim = await user_factory(UserRole.MANAGER, password=TEST_PASSWORD)
    response = await admin.post(
        f"/api/v1/users/{victim.id}/password", json={"password": "a-brand-new-one"}
    )
    assert response.status_code == 204
    body = (await admin.get(f"/api/v1/users/{victim.id}")).json()
    assert body["must_change_password"] is True


async def test_users_is_admin_only(manager, sales, service_token) -> None:
    """``users:read`` is admin-only, so the whole screen is."""
    for http_client in (manager, sales, service_token):
        assert (await http_client.get("/api/v1/users")).status_code == 403


async def test_without_a_token_it_is_401(client) -> None:
    assert (await client.get("/api/v1/users")).status_code == 401


async def test_an_unknown_user_is_404(admin) -> None:
    assert (await admin.get(f"/api/v1/users/{uuid.uuid4()}")).status_code == 404
