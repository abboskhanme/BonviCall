"""Panel login, rotation and replay (SPEC §4.2, §4.7, N24)."""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa

from conftest import TEST_PASSWORD
from src.core.enums import UserRole
from src.modules.auth.models import RefreshTokenModel
from src.modules.auth.service import REFRESH_REPLAY_GRACE

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
    """N24 applied to the panel: a replay is theft until proven otherwise.

    **Load-bearing.** The grace window added on 2026-09-13 forgives a replay
    that arrives within twenty seconds of the rotation, so this test ages the
    spent row past it — otherwise it would pass by taking the forgiving branch
    and would stop testing the rule it is named after.
    """
    user = await user_factory(UserRole.ADMIN, password=TEST_PASSWORD)
    await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})
    spent = client.cookies.get("bonvicall_refresh")
    await client.post("/api/v1/auth/refresh")
    await _age_spent_tokens(db, user.id, REFRESH_REPLAY_GRACE + timedelta(seconds=1))

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


# --- The replay that is not theft (2026-09-13) ------------------------------


async def _age_spent_tokens(db, user_id, by: timedelta) -> None:
    """Move every revocation of this user's tokens back in time.

    The alternative is freezing the clock, and this project has already been
    bitten by a frozen clock that never reached the service under test
    (`docs/STATUS.md`). Ageing the rows reaches it by definition.
    """
    await db.execute(
        sa.update(RefreshTokenModel)
        .where(
            RefreshTokenModel.user_id == user_id,
            RefreshTokenModel.revoked_at.is_not(None),
        )
        .values(revoked_at=RefreshTokenModel.revoked_at - by)
    )
    await db.flush()


async def test_two_tabs_refreshing_at_once_do_not_end_the_session(
    db, client, user_factory
) -> None:
    """The bug this window exists for, reproduced.

    The panel serialises its own refreshes, but that guard is a variable inside
    ONE tab while the cookie is shared by all of them. Two tabs whose access
    tokens expire in the same second both send the same token; the first
    rotates it and the second looks like a replay. It was never theft, and
    treating it as theft logged people out several times an hour — fifty-five
    sessions issued and fifty-five revoked in twelve hours.
    """
    user = await user_factory(UserRole.ADMIN, password=TEST_PASSWORD)
    await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})
    shared = client.cookies.get("bonvicall_refresh")

    first = await client.post("/api/v1/auth/refresh")
    client.cookies.set("bonvicall_refresh", shared)
    second = await client.post("/api/v1/auth/refresh")

    assert first.status_code == 200
    assert second.status_code == 200, "the second tab keeps working"
    live = await db.scalar(
        sa.select(sa.func.count())
        .select_from(RefreshTokenModel)
        .where(
            RefreshTokenModel.user_id == user.id, RefreshTokenModel.revoked_at.is_(None)
        )
    )
    assert live == 1, "one live session, not zero and not two"


async def test_the_forgiven_replay_still_hands_back_a_usable_session(
    client, user_factory
) -> None:
    """Forgiving it is only useful if what comes back works."""
    user = await user_factory(UserRole.ADMIN, password=TEST_PASSWORD)
    await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})
    shared = client.cookies.get("bonvicall_refresh")
    await client.post("/api/v1/auth/refresh")

    client.cookies.set("bonvicall_refresh", shared)
    token = (await client.post("/api/v1/auth/refresh")).json()["access_token"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == user.email


async def test_a_logged_out_token_is_never_forgiven(db, client, user_factory) -> None:
    """A token revoked by logout has no successor, so there is nothing to hand
    back and nothing that could be a race — the old rule applies in full."""
    user = await user_factory(UserRole.ADMIN, password=TEST_PASSWORD)
    await client.post(LOGIN, json={"email": user.email, "password": TEST_PASSWORD})
    spent = client.cookies.get("bonvicall_refresh")
    await client.post("/api/v1/auth/logout")

    client.cookies.set("bonvicall_refresh", spent)
    replay = await client.post("/api/v1/auth/refresh")

    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "refresh_reused"


# --- The login identifier ---------------------------------------------------


async def test_a_login_that_is_not_an_e_mail_address_still_works(
    client, db, user_factory
) -> None:
    """``LoginRequest.email`` is an identifier, not an address.

    ``users.email`` is CITEXT with no format constraint, and the account an
    operator uses on a laptop is ``admin`` (`scripts/dev_admin.py`). Validating
    the format at the schema refused it before any lookup ran — while adding
    nothing, because a well-formed address belonging to nobody fails at the
    same place with the same 401.
    """
    user = await user_factory(UserRole.ADMIN, password=TEST_PASSWORD)
    user.email = "admin"
    await db.flush()

    response = await client.post(
        LOGIN, json={"email": "admin", "password": TEST_PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_an_unknown_login_is_401_and_not_422(client) -> None:
    """The shape of a wrong login must not say whether the account exists.

    A 422 for "that is not an e-mail" and a 401 for "wrong password" are two
    different answers to the same question, and the difference is readable by
    anyone with curl.
    """
    response = await client.post(LOGIN, json={"email": "nobody", "password": "x"})

    assert response.status_code == 401
