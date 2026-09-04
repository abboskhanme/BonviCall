"""Panel login, rotation and replay (SPEC §4.2, §4.7, N24)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from conftest import TEST_PASSWORD
from src.core.enums import UserRole
from src.modules.auth.models import RefreshTokenModel

pytestmark = pytest.mark.asyncio

LOGIN = "/api/v1/auth/login"


async def test_login_returns_a_token_and_the_permission_list(client, user_factory) -> None:
    """The panel's ``can()`` reads this list; it never holds its own matrix."""
    user = await user_factory(UserRole.MANAGER, password=TEST_PASSWORD)
    response = await client.post(
        LOGIN, json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["role"] == "manager"
    assert "calls:read" in body["permissions"]
    assert "audit:read" not in body["permissions"]


async def test_the_refresh_token_is_an_httponly_cookie_not_a_body_field(
    client, user_factory
) -> None:
    """A token in the response body is a token in the JavaScript heap."""
    user = await user_factory(UserRole.ADMIN, password=TEST_PASSWORD)
    response = await client.post(
        LOGIN, json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert "refresh_token" not in response.json()
    cookie = response.headers["set-cookie"]
    assert "bonvicall_refresh=" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/api/v1/auth" in cookie


async def test_a_wrong_password_and_an_unknown_email_look_identical(
    client, user_factory
) -> None:
    """Otherwise the login form is an account enumerator."""
    user = await user_factory(UserRole.ADMIN, password=TEST_PASSWORD)
    wrong_password = await client.post(
        LOGIN, json={"email": user.email, "password": "not-the-password"}
    )
    unknown_email = await client.post(
        LOGIN, json={"email": "nobody@bonvi.uz", "password": TEST_PASSWORD}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json() | {
        "error": wrong_password.json()["error"]
    }
    assert wrong_password.json()["error"]["code"] == "unauthorized"


async def test_a_deactivated_account_cannot_log_in(client, user_factory) -> None:
    user = await user_factory(
        UserRole.MANAGER, password=TEST_PASSWORD, is_active=False
    )
    response = await client.post(
        LOGIN, json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 401


async def test_a_corrupt_password_hash_is_a_401_not_a_500(client, user_factory) -> None:
    """One bad row took down every login in BonviZvonki. Not here."""
    user = await user_factory(UserRole.ADMIN)  # placeholder, not a real argon2 hash
    response = await client.post(
        LOGIN, json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 401


async def test_a_real_token_reaches_a_protected_route(client, user_factory) -> None:
    """End to end: login, then use the token the resolver has to verify."""
    user = await user_factory(UserRole.MANAGER, password=TEST_PASSWORD)
    token = (
        await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})
    ).json()["access_token"]
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == user.email


async def test_a_garbage_token_is_401(client) -> None:
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


async def test_refresh_rotates_the_token(client, user_factory) -> None:
    user = await user_factory(UserRole.ADMIN, password=TEST_PASSWORD)
    await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})
    first_cookie = client.cookies.get("bonvicall_refresh")

    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    assert client.cookies.get("bonvicall_refresh") != first_cookie


async def test_reusing_a_rotated_token_revokes_the_whole_chain(
    db, client, user_factory
) -> None:
    """N24 applied to the panel: a replay is theft until proven otherwise."""
    user = await user_factory(UserRole.ADMIN, password=TEST_PASSWORD)
    await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})
    spent = client.cookies.get("bonvicall_refresh")
    await client.post("/api/v1/auth/refresh")

    client.cookies.set("bonvicall_refresh", spent)
    replay = await client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "refresh_reused"

    live = await db.scalar(
        sa.select(sa.func.count())
        .select_from(RefreshTokenModel)
        .where(
            RefreshTokenModel.user_id == user.id, RefreshTokenModel.revoked_at.is_(None)
        )
    )
    assert live == 0, "every session in the chain is revoked"


async def test_refresh_without_the_cookie_is_401(client) -> None:
    """The route is guarded by the cookie, not by an access token."""
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_logout_is_idempotent(client, user_factory) -> None:
    user = await user_factory(UserRole.ADMIN, password=TEST_PASSWORD)
    await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})
    token = client.cookies.get("bonvicall_refresh")
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    client.cookies.set("bonvicall_refresh", token)
    assert (await client.post("/api/v1/auth/logout")).status_code == 204


async def test_changing_your_own_password_revokes_other_sessions(
    db, client, user_factory
) -> None:
    user = await user_factory(UserRole.MANAGER, password=TEST_PASSWORD)
    login = await client.post(
        LOGIN, json={"email": user.email, "password": TEST_PASSWORD}
    )
    token = login.json()["access_token"]

    response = await client.post(
        "/api/v1/auth/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": TEST_PASSWORD, "new_password": "a-longer-new-one"},
    )
    assert response.status_code == 200
    live = await db.scalar(
        sa.select(sa.func.count())
        .select_from(RefreshTokenModel)
        .where(
            RefreshTokenModel.user_id == user.id, RefreshTokenModel.revoked_at.is_(None)
        )
    )
    assert live == 0


async def test_a_short_password_is_refused_by_the_schema(client, user_factory) -> None:
    user = await user_factory(UserRole.MANAGER, password=TEST_PASSWORD)
    token = (
        await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})
    ).json()["access_token"]
    response = await client.post(
        "/api/v1/auth/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": TEST_PASSWORD, "new_password": "short"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_me_without_a_token_is_401(client) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_a_service_token_is_not_a_user_session(service_token) -> None:
    """UC-29: a machine cannot read /users and cannot be exchanged for a login."""
    assert (await service_token.get("/api/v1/users")).status_code == 403
