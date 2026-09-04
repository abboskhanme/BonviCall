"""The application itself: health, route protection, and the contract export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute

from src.api import DEVICE_API_PREFIX, PANEL_API_PREFIX, SERVICE_API_PREFIX
from src.contract_export import CONTRACT_DIR, build_documents
from src.core.permissions import PUBLIC_ROUTES
from src.main import create_app

DOCS_ROUTES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


#: A WebSocket route has no HTTP method, but the protection rule applies to it
#: exactly the same way — arguably more, since the device socket is the one
#: channel that reaches into an employee's personally owned phone. Giving it a
#: pseudo-method keeps it inside the same harness instead of beside it.
WEBSOCKET_METHOD = "WEBSOCKET"


def _api_routes(app) -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path not in DOCS_ROUTES
    ]


def _methods_of(route) -> set[str]:
    if isinstance(route, APIWebSocketRoute):
        return {WEBSOCKET_METHOD}
    return route.methods - {"HEAD", "OPTIONS"}


def _protected_routes(app) -> list:
    """Every route the protection rule applies to, HTTP **and** WebSocket.

    ``APIWebSocketRoute`` is not an ``APIRoute``, so a socket added to the app
    was invisible to the check below until this existed. An endpoint that can
    dial a customer from someone's own handset is not the one to leave outside
    the harness.
    """
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute | APIWebSocketRoute)
        and route.path not in DOCS_ROUTES
    ]


def test_the_three_surfaces_are_mounted() -> None:
    """Three prefixes, three audiences; they never share a router (SPEC §4)."""
    app = create_app()
    prefixes = {DEVICE_API_PREFIX, PANEL_API_PREFIX, SERVICE_API_PREFIX}
    assert len(prefixes) == 3
    assert PANEL_API_PREFIX == "/api/v1"
    assert DEVICE_API_PREFIX.startswith("/api/device/")
    assert SERVICE_API_PREFIX.startswith("/api/service/")
    # Each surface owns its own paths and nothing overlaps: a device route can
    # never be reached through the panel prefix, whatever a router is renamed to.
    paths = {route.path for route in _api_routes(app)}
    device = {path for path in paths if path.startswith(DEVICE_API_PREFIX)}
    service_paths = {path for path in paths if path.startswith(SERVICE_API_PREFIX)}
    panel_paths = {
        path
        for path in paths
        if path.startswith(PANEL_API_PREFIX) and path not in device | service_paths
    }
    assert device and service_paths and panel_paths
    assert device.isdisjoint(panel_paths) and device.isdisjoint(service_paths)


#: Routes that need a caller but no particular permission (SPEC §4.7).
#: Each one is here because *any* authenticated user may call it; a route that
#: is not here and holds no ``require_*`` dependency is a hole.
AUTHENTICATED_ONLY_ROUTES = {
    ("GET", "/api/v1/auth/me"),
    ("POST", "/api/v1/auth/password"),
    # UC-26/T45: DELETE is 405 for every role including admin. A permission
    # check here would make the answer depend on who is asking, and it does
    # not — the operation does not exist for anybody.
    ("DELETE", "/api/v1/calls/{call_id}"),
    ("DELETE", "/api/v1/calls/{call_id}/audio"),
}

#: Routes authenticated by a credential that is not an access token, and the
#: guard that does it. The refresh cookie and the device's own refresh token
#: are the whole point of those two calls — there is no access token to check,
#: because the reason to call them is that it expired.
ALTERNATIVE_CREDENTIAL_ROUTES = {
    ("POST", "/api/v1/auth/refresh"): "require_refresh_token",
    ("POST", "/api/v1/auth/logout"): "require_refresh_token",
    ("POST", "/api/device/v1/auth/refresh"): "body:refresh_token",
}


def _dependency_names(dependant, seen=None) -> set[str]:
    """Every callable in a route's dependency tree, by qualified name."""
    seen = seen if seen is not None else set()
    for sub in dependant.dependencies:
        name = getattr(sub.call, "__qualname__", "") or getattr(sub.call, "__name__", "")
        seen.add(name)
        _dependency_names(sub, seen)
    return seen


def test_every_registered_route_is_protected_or_declared_public() -> None:
    """N23: no endpoint is unprotected, and the exceptions are a list, not a habit.

    This is T20's harness in embryo. It walks the whole dependency tree rather
    than the top level, because a permission dependency pulls the principal in
    beneath itself — checking only the top level would pass a route that
    resolves nobody.

    It fails the moment a module adds a route that neither resolves a principal
    nor appears in one of the three lists above. **Do not weaken it to let a
    route through.**
    """
    app = create_app()
    unprotected: list[str] = []
    unchecked: list[str] = []
    for route in _protected_routes(app):
        for method in sorted(_methods_of(route)):
            key = (method, route.path)
            if key in PUBLIC_ROUTES or key in ALTERNATIVE_CREDENTIAL_ROUTES:
                continue
            names = _dependency_names(route.dependant)
            if "get_current_principal" not in names:
                unprotected.append(f"{method} {route.path}")
                continue
            if not any(name.startswith("require_") for name in names):
                if key not in AUTHENTICATED_ONLY_ROUTES:
                    unchecked.append(f"{method} {route.path}")

    assert unprotected == [], (
        f"resolves no principal and is not declared public: {unprotected}. "
        "Add a require_permission(Perm.X) dependency, or declare the route "
        "public in core.permissions.PUBLIC_ROUTES with a reason."
    )
    assert unchecked == [], (
        f"authenticated but checks no permission: {unchecked}. Add a "
        "require_permission/require_any_permission dependency, or list the "
        "route in AUTHENTICATED_ONLY_ROUTES with a reason."
    )


def test_alternative_credential_routes_still_have_a_guard() -> None:
    """The three routes with no access token are guarded by something else."""
    app = create_app()
    for route in _api_routes(app):
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            expected = ALTERNATIVE_CREDENTIAL_ROUTES.get((method, route.path))
            if expected is None or expected.startswith("body:"):
                continue
            assert expected in _dependency_names(route.dependant), route.path


def test_public_routes_that_exist_are_actually_public() -> None:
    """A route in PUBLIC_ROUTES must genuinely resolve no principal.

    The list is a declaration; this is the check that it is not also a lie.
    Entries for routes that do not exist yet are ignored — they are Phase 5's.
    """
    app = create_app()
    registered = {
        (method, route.path)
        for route in _api_routes(app)
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    for method, path in sorted(PUBLIC_ROUTES & registered):
        route = next(
            r for r in _api_routes(app) if r.path == path and method in r.methods
        )
        assert "get_current_principal" not in _dependency_names(route.dependant), (
            f"{method} {path} is in PUBLIC_ROUTES but requires a principal"
        )


@pytest.mark.asyncio
async def test_healthz_is_public_and_touches_nothing(client) -> None:
    """A slow database must not restart the process."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz_reports_each_dependency(client, monkeypatch, tmp_path) -> None:
    from src.core import config

    settings = config.get_settings()
    monkeypatch.setattr(settings, "audio_storage_path", tmp_path / "audio")
    response = await client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "database": True, "storage": True}


@pytest.mark.asyncio
async def test_readyz_is_503_when_storage_is_unwritable(
    client, monkeypatch, tmp_path
) -> None:
    """Accepting uploads we cannot store is worse than reporting unready."""
    from src.core import config

    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    settings = config.get_settings()
    monkeypatch.setattr(settings, "audio_storage_path", blocked / "audio")
    response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["storage"] is False


@pytest.mark.asyncio
async def test_every_response_carries_a_request_id(client) -> None:
    response = await client.get("/healthz")
    assert response.headers["X-Request-Id"]


def test_contract_documents_are_committed_and_current() -> None:
    """``make contract && git diff --exit-code contract/`` is the CI gate (§1).

    This test is the same check, run locally, so a wire change that was not
    regenerated fails before the pull request rather than in CI.
    """
    for stem, document in build_documents().items():
        path = CONTRACT_DIR / f"{stem}.json"
        assert path.exists(), f"missing contract artefact: {path.name}"
        committed = json.loads(path.read_text(encoding="utf-8"))
        assert committed == document, (
            f"{path.name} is stale. Run `make contract` and commit the diff."
        )


def test_the_error_code_catalogue_is_part_of_the_contract() -> None:
    """§9: codes are stable machine contract and are present in contract/."""
    from src.core.errors import ErrorCode

    catalogue = json.loads(
        (CONTRACT_DIR / "error-codes.json").read_text(encoding="utf-8")
    )
    assert set(catalogue["codes"]) == ErrorCode.all_codes()


def test_the_phone_vector_file_is_shared_with_the_android_suite() -> None:
    """§7: one file, read by pytest and by JUnit — that is what stops drift."""
    path = Path(CONTRACT_DIR) / "phone-vectors.json"
    vectors = json.loads(path.read_text(encoding="utf-8"))
    assert vectors["phone_key_digits"] == 9
