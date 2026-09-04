"""The permission registry (T18, N23, §11).

These tests are the reason the registry can be trusted by every module that
comes after: they pin the role matrix of SPEC §4.1 against the code, and they
prove that a mistyped permission is a startup failure rather than an endpoint
that quietly refuses everybody forever.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends
from httpx import ASGITransport, AsyncClient

from src.core.deps import Principal, get_current_principal
from src.core.enums import UserRole
from src.core.errors import ErrorCode
from src.core.permissions import (
    ALL_PERMISSIONS,
    PUBLIC_ROUTES,
    ROLE_PERMISSIONS,
    Perm,
    Role,
    permissions_for,
    require_any_permission,
    require_permission,
)
from src.main import create_app

#: SPEC §4.1's table, transcribed. If the code and this list disagree, one of
#: them is wrong and the test says which permission.
EXPECTED_MATRIX: dict[str, set[str]] = {
    "admin": {
        "users:read", "users:write", "agents:read", "agents:write", "agents:archive",
        "numbers:read", "numbers:write", "enrolment:read", "enrolment:write",
        "enrolment:attest", "installations:read", "installations:revoke", "devices:read",
        "calls:read", "calls:note", "audio:play", "audio:download", "commands:dial",
        "alerts:read", "alerts:ack", "reports:read", "reports:export", "audit:read",
        "settings:read", "settings:write", "appversions:read", "appversions:write",
        "export:read", "export:audio",
    },
    "manager": {
        "agents:read", "numbers:read", "enrolment:read", "installations:read",
        "devices:read", "calls:read", "calls:note", "audio:play", "audio:download",
        "commands:dial", "alerts:read", "reports:read", "reports:export",
        "settings:read", "appversions:read",
    },
    "sales": {"devices:read:own", "calls:read:own", "audio:play:own"},
    "service": {"export:read", "export:audio", "callback:report"},
}


def test_role_matrix_matches_the_spec() -> None:
    for role, expected in EXPECTED_MATRIX.items():
        assert set(ROLE_PERMISSIONS[Role(role)]) == expected, role


def test_every_declared_permission_is_granted_to_someone() -> None:
    """A permission no role holds is a permission that gates nothing."""
    granted = set().union(*(set(perms) for perms in ROLE_PERMISSIONS.values()))
    assert ALL_PERMISSIONS - granted == set()


def test_every_granted_permission_is_declared() -> None:
    """The reverse: a role cannot hold a permission the registry does not name."""
    for role, permissions in ROLE_PERMISSIONS.items():
        assert set(permissions) <= ALL_PERMISSIONS, role


def test_permission_names_follow_the_convention() -> None:
    """``<resource>:<action>[:own]`` (§12)."""
    for permission in ALL_PERMISSIONS:
        parts = permission.split(":")
        assert 2 <= len(parts) <= 3, permission
        assert all(part.islower() and part.isalpha() for part in parts), permission
        if len(parts) == 3:
            assert parts[2] == "own", permission


def test_own_scope_permissions_belong_to_sales_only() -> None:
    """Scope is narrowed by the query; ``:own`` exists so the salesperson passes."""
    own = {perm for perm in ALL_PERMISSIONS if perm.endswith(":own")}
    for role, permissions in ROLE_PERMISSIONS.items():
        held = set(permissions) & own
        assert held == (own if role is Role.SALES else set()), role


def test_service_cannot_read_users_or_the_audit_log() -> None:
    """UC-29, asserted rather than assumed."""
    service = ROLE_PERMISSIONS[Role.SERVICE]
    assert Perm.USERS_READ not in service
    assert Perm.AUDIT_READ not in service
    assert not any(perm.endswith(":write") for perm in service)


def test_the_viewer_role_is_gone() -> None:
    """Removed with the TV board it was invented for (2026-09-05).

    A role that can log in and then 403s on everything reads as a permissions
    bug to whoever holds the account, and somebody eventually "fixes" it by
    granting more than they meant to. There are three logins and one machine.
    """
    assert {role.value for role in Role} == {"admin", "manager", "sales", "service"}
    assert {role.value for role in UserRole} == {"admin", "manager", "sales"}
    assert not any(perm.startswith("monitor:") for perm in ALL_PERMISSIONS)


def test_user_roles_are_a_subset_of_the_authorised_roles() -> None:
    """``service`` is a token, not a login (SPEC §3.2); the logins are a subset."""
    assert {role.value for role in UserRole} < {role.value for role in Role}
    assert Role.SERVICE.value not in {role.value for role in UserRole}


def test_unknown_role_fails_closed() -> None:
    assert permissions_for("superuser") == frozenset()


def test_public_routes_are_the_reconciled_list() -> None:
    """SPEC §4.1 rule 5 lists five; two more earn their place.

    ``enrolment/redeem`` (SPEC §4.2) cannot carry a token by construction, and
    ``/i/{code}/apk`` is the second half of the pair rule 5 already names —
    §8.1 gives the download its own per-agent path so it is a funnel signal.
    """
    assert PUBLIC_ROUTES == {
        ("GET", "/healthz"),
        ("GET", "/readyz"),
        ("POST", "/api/v1/auth/login"),
        ("GET", "/i/{code}"),
        ("GET", "/i/{code}/apk"),
        ("GET", "/api/v1/app/download/{version_code}"),
        ("POST", "/api/device/v1/enrolment/redeem"),
    }


def test_a_mistyped_permission_is_refused_at_import_time() -> None:
    """BonviZvonki passes raw strings; a typo there fails closed and silently."""
    with pytest.raises(ValueError, match="not declared"):
        require_permission("call:read")
    with pytest.raises(ValueError, match="not declared"):
        require_any_permission(Perm.CALLS_READ, "calls:read:mine")


def test_require_any_permission_needs_at_least_one() -> None:
    with pytest.raises(ValueError):
        require_any_permission()


def _principal(*permissions: str) -> Principal:
    import uuid

    return Principal(
        kind="user", id=uuid.uuid4(), role="manager", permissions=frozenset(permissions)
    )


def _guarded_app(principal: Principal | None):
    app = create_app()
    router = APIRouter(prefix="/_probe")

    @router.get("/one", dependencies=[Depends(require_permission(Perm.CALLS_READ))])
    async def _one() -> dict:
        return {"ok": True}

    @router.get(
        "/any",
        dependencies=[
            Depends(require_any_permission(Perm.CALLS_READ, Perm.CALLS_READ_OWN))
        ],
    )
    async def _any() -> dict:
        return {"ok": True}

    app.include_router(router)
    if principal is not None:
        app.dependency_overrides[get_current_principal] = lambda: principal
    return app


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.mark.asyncio
async def test_no_principal_is_401_not_500() -> None:
    """Until SV-AUTH registers a resolver, a protected route answers 401."""
    async with _client(_guarded_app(None)) as client:
        response = await client.get("/_probe/one")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == ErrorCode.UNAUTHORIZED


@pytest.mark.asyncio
async def test_wrong_permission_is_403() -> None:
    async with _client(_guarded_app(_principal(Perm.AGENTS_READ))) as client:
        response = await client.get("/_probe/one")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == ErrorCode.FORBIDDEN


@pytest.mark.asyncio
async def test_right_permission_passes() -> None:
    async with _client(_guarded_app(_principal(Perm.CALLS_READ))) as client:
        response = await client.get("/_probe/one")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_own_scope_permission_passes_the_dependency() -> None:
    """The salesperson gets through; the *query* is what narrows (§11)."""
    async with _client(_guarded_app(_principal(Perm.CALLS_READ_OWN))) as client:
        response = await client.get("/_probe/any")
    assert response.status_code == 200
