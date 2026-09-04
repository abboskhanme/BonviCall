"""The permission registry (T18, N23, CONVENTIONS.md §11, SPEC §4.1).

Three things are fixed here and are not open to a module to change:

1. **This file is in ``core/``.** BonviZvonki keeps ``ROLE_PERMISSIONS`` in
   ``modules/users/domain/entities.py`` and imports it from ``core/deps.py``,
   so ``core`` depends on a module and the arrows point both ways. Ours point
   one way.
2. **Permissions are constants, never string literals at a call site.**
   A typo in ``require_permission("call:read")`` fails closed and silently,
   forever. :func:`require_permission` refuses an unknown permission at import
   time instead, so the typo is a startup error.
3. **Every constant for UC-01…UC-29 is declared up front.** Module tasks
   reference constants; they never add one. A new constant after Phase 1 is a
   review failure unless this list is amended in the same pull request.

Scope is narrowed by the *query*, not by a second check: ``calls:read:own``
gets a salesperson through :func:`require_any_permission`, and
``CallService.list()`` adds ``WHERE agent_id = principal.agent_id``. A row that
exists but belongs to another agent is a **404**, never a 403 — 403 would
confirm that a colleague spoke to that number (SPEC §4.1 rule 2).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum

from src.core.deps import Principal, PrincipalDep
from src.core.errors import ForbiddenError


class Role(StrEnum):
    """Every principal the server authorises.

    ``service`` is here but is **not** a ``user_role`` in the database
    (``core.enums.UserRole``): a machine has no password, no session and no
    navigation, so it is a ``service_tokens`` row (SPEC §3.2). A test asserts
    the four user roles are a subset of these five.
    """

    ADMIN = "admin"
    MANAGER = "manager"
    SALES = "sales"
    VIEWER = "viewer"
    SERVICE = "service"


class Perm:
    """Every permission in the product. ``<resource>:<action>[:own]`` (§12)."""

    USERS_READ = "users:read"
    USERS_WRITE = "users:write"

    AGENTS_READ = "agents:read"
    AGENTS_WRITE = "agents:write"
    AGENTS_ARCHIVE = "agents:archive"

    NUMBERS_READ = "numbers:read"
    NUMBERS_WRITE = "numbers:write"

    ENROLMENT_READ = "enrolment:read"
    ENROLMENT_WRITE = "enrolment:write"
    ENROLMENT_ATTEST = "enrolment:attest"

    INSTALLATIONS_READ = "installations:read"
    INSTALLATIONS_REVOKE = "installations:revoke"

    DEVICES_READ = "devices:read"
    DEVICES_READ_OWN = "devices:read:own"

    CALLS_READ = "calls:read"
    CALLS_READ_OWN = "calls:read:own"
    CALLS_NOTE = "calls:note"

    AUDIO_PLAY = "audio:play"
    AUDIO_PLAY_OWN = "audio:play:own"
    AUDIO_DOWNLOAD = "audio:download"

    COMMANDS_DIAL = "commands:dial"

    ALERTS_READ = "alerts:read"
    ALERTS_ACK = "alerts:ack"

    REPORTS_READ = "reports:read"
    REPORTS_EXPORT = "reports:export"

    AUDIT_READ = "audit:read"

    SETTINGS_READ = "settings:read"
    SETTINGS_WRITE = "settings:write"

    APPVERSIONS_READ = "appversions:read"
    APPVERSIONS_WRITE = "appversions:write"

    MONITOR_READ = "monitor:read"

    EXPORT_READ = "export:read"
    EXPORT_AUDIO = "export:audio"

    CALLBACK_REPORT = "callback:report"

    @classmethod
    def all(cls) -> frozenset[str]:
        """Every declared permission string."""
        return frozenset(
            value
            for name, value in vars(cls).items()
            if name.isupper() and isinstance(value, str)
        )


ALL_PERMISSIONS: frozenset[str] = Perm.all()


ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    # An admin holds everything. Stated as the explicit set rather than
    # ALL_PERMISSIONS so that adding a permission is a visible decision here
    # and not an automatic grant.
    Role.ADMIN: frozenset(
        {
            Perm.USERS_READ,
            Perm.USERS_WRITE,
            Perm.AGENTS_READ,
            Perm.AGENTS_WRITE,
            Perm.AGENTS_ARCHIVE,
            Perm.NUMBERS_READ,
            Perm.NUMBERS_WRITE,
            Perm.ENROLMENT_READ,
            Perm.ENROLMENT_WRITE,
            Perm.ENROLMENT_ATTEST,
            Perm.INSTALLATIONS_READ,
            Perm.INSTALLATIONS_REVOKE,
            Perm.DEVICES_READ,
            Perm.CALLS_READ,
            Perm.CALLS_NOTE,
            Perm.AUDIO_PLAY,
            Perm.AUDIO_DOWNLOAD,
            Perm.COMMANDS_DIAL,
            Perm.ALERTS_READ,
            Perm.ALERTS_ACK,
            Perm.REPORTS_READ,
            Perm.REPORTS_EXPORT,
            Perm.AUDIT_READ,
            Perm.SETTINGS_READ,
            Perm.SETTINGS_WRITE,
            Perm.APPVERSIONS_READ,
            Perm.APPVERSIONS_WRITE,
            Perm.MONITOR_READ,
            Perm.EXPORT_READ,
            Perm.EXPORT_AUDIO,
            # Not granted: *:*:own — an admin sees everything, so an own-scope
            # permission would only make the query narrower than intended.
            # Not granted: callback:report — that is a machine reporting an
            # inbound caller id, and a human never does it.
        }
    ),
    Role.MANAGER: frozenset(
        {
            Perm.AGENTS_READ,
            Perm.NUMBERS_READ,
            Perm.ENROLMENT_READ,
            Perm.INSTALLATIONS_READ,
            Perm.DEVICES_READ,
            Perm.CALLS_READ,
            Perm.CALLS_NOTE,
            Perm.AUDIO_PLAY,
            Perm.AUDIO_DOWNLOAD,
            Perm.COMMANDS_DIAL,
            Perm.ALERTS_READ,
            Perm.REPORTS_READ,
            Perm.REPORTS_EXPORT,
            Perm.SETTINGS_READ,
            Perm.APPVERSIONS_READ,
            Perm.MONITOR_READ,
            # Not granted: agents:write / numbers:write / enrolment:write —
            # the rollout is the admin's job; a manager reviews calls.
            # Not granted: installations:revoke — revoking wipes an employee's
            # local audio (UC-08); it needs the accountable role.
            # Not granted: alerts:ack — UC-06/UC-18 require that an alert
            # cannot be cleared by whoever it is inconvenient for.
            # Not granted: audit:read — the audit log records who listened to
            # which call, and a manager is one of the people it records.
        }
    ),
    Role.SALES: frozenset(
        {
            Perm.DEVICES_READ_OWN,
            Perm.CALLS_READ_OWN,
            Perm.AUDIO_PLAY_OWN,
            # Nothing else. N41's transparency is "see your own calls and your
            # own phone's health", not a read-only panel: a salesperson who can
            # list agents or numbers can work out who else is enrolled.
            # Not granted: audio:download — playing is transparency, taking a
            # copy of a customer conversation off the system is not.
            # Not granted: reports:* — every report is fleet-wide by shape.
        }
    ),
    Role.VIEWER: frozenset(
        {
            Perm.MONITOR_READ,
            # The sales-room TV and nothing else. The board's own DTO masks the
            # remote number server-side (SPEC §4.1 rule 3); masking in CSS is
            # not masking, and this role is what a visitor walking past reads.
        }
    ),
    Role.SERVICE: frozenset(
        {
            Perm.EXPORT_READ,
            Perm.EXPORT_AUDIO,
            Perm.CALLBACK_REPORT,
            # Cannot read users, cannot read the audit log, cannot write
            # anything (UC-29). Token scopes are checked in addition to this.
        }
    ),
}


def permissions_for(role: str) -> frozenset[str]:
    """The permission set of ``role``; empty for a role we do not know.

    Empty rather than an exception: an unknown role must fail closed, and a
    principal that can do nothing is a 403 rather than a 500.
    """
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return frozenset()


#: Routes that answer without a token. SPEC §4.1 rule 5 lists five; SPEC §4.2
#: then makes ``enrolment/redeem`` public as well — it is the code-redemption
#: call and by construction cannot carry a token. Six is the reconciled list
#: and T20's harness asserts against this constant, not against a count.
#: Every entry is (method, path). Anything not here must be protected.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/healthz"),
        ("GET", "/readyz"),
        ("POST", "/api/v1/auth/login"),
        ("GET", "/i/{code}"),
        # SPEC §4.1 rule 5 names "the install landing page and the APK
        # download" as one public pair; §8.1 gives the per-agent link its own
        # path so the download is a funnel signal. Both halves are here.
        ("GET", "/i/{code}/apk"),
        ("GET", "/api/v1/app/download/{version_code}"),
        ("POST", "/api/device/v1/enrolment/redeem"),
    }
)


def require_permission(permission: str) -> Callable[..., Awaitable[Principal]]:
    """Router dependency: the caller must hold ``permission``, else 403.

    ``require_permission(Perm.CALLS_READ)`` — never a bare string. An unknown
    permission raises here, at import time, so a typo is a server that refuses
    to start rather than an endpoint that quietly refuses everybody.
    """
    _assert_declared(permission)

    async def dependency(principal: PrincipalDep) -> Principal:
        if not principal.has(permission):
            raise ForbiddenError()
        return principal

    return dependency


def require_any_permission(*permissions: str) -> Callable[..., Awaitable[Principal]]:
    """Router dependency: the caller must hold at least one of ``permissions``.

    This is how own-scope works:
    ``require_any_permission(Perm.CALLS_READ, Perm.CALLS_READ_OWN)`` lets a
    salesperson through and the service query narrows on ``agent_id``. Adding a
    second dependency to check ownership would put a business rule in a router.
    """
    if not permissions:
        raise ValueError("require_any_permission needs at least one permission")
    for permission in permissions:
        _assert_declared(permission)

    async def dependency(principal: PrincipalDep) -> Principal:
        if not principal.has_any(*permissions):
            raise ForbiddenError()
        return principal

    return dependency


def _assert_declared(permission: str) -> None:
    if permission not in ALL_PERMISSIONS:
        raise ValueError(
            f"{permission!r} is not declared in core.permissions.Perm. "
            "Permissions are declared up front (T18); add it there, with the "
            "role grants, in the same change."
        )


__all__ = [
    "ALL_PERMISSIONS",
    "PUBLIC_ROUTES",
    "ROLE_PERMISSIONS",
    "Perm",
    "Role",
    "permissions_for",
    "require_any_permission",
    "require_permission",
]
