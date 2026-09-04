"""Request-scoped dependencies: the session, the caller, the request id.

The *shape* of a caller lives here; **what a caller may do** lives in
``core/permissions.py``. The arrow points one way — ``permissions`` imports
``deps``, never the reverse — which is how BonviZvonki's ``core`` ended up
importing a module (CONVENTIONS.md §11 item 1).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from src.core.database import session_scope
from src.core.errors import UnauthorizedError

#: Header name for the client-supplied correlation id (SPEC §4.0).
REQUEST_ID_HEADER = "X-Request-Id"


@dataclass(frozen=True)
class Principal:
    """Whoever is making this request, already authenticated.

    One type covers all three surfaces because authorisation asks the same
    question of each: which permissions does this caller hold. What differs is
    how the token was verified, and that is the authenticating module's job.

    :param kind: ``user`` (panel login), ``service`` (machine token, UC-29) or
        ``device`` (an installation-bound app token, N24).
    :param role: ``admin`` / ``manager`` / ``sales`` / ``service``.
        Do not branch on this outside ``core/permissions.py`` — ask for a
        permission instead (§2, §11).
    :param agent_id: set for a ``sales`` user only. It is what own-scope
        narrowing filters on, so a ``sales`` user without one can see nothing
        (SPEC §3.2 enforces the link with a CHECK).
    :param installation_id: set for a device principal; the row its token is
        bound to (N24).
    """

    kind: str
    id: uuid.UUID
    role: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    agent_id: uuid.UUID | None = None
    installation_id: uuid.UUID | None = None
    display_name: str = ""

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def has_any(self, *permissions: str) -> bool:
        return any(p in self.permissions for p in permissions)


#: Signature of the function that turns a request into a :class:`Principal`.
#: It receives the request's own session, so authentication reads the same
#: transaction as the rest of the request — and so the test suite's session
#: override applies to it too.
#:
#: ``HTTPConnection`` rather than ``Request`` because the device realtime socket
#: authenticates on its handshake (SPEC §4.6) and must go through *this* code,
#: not a second copy of it. ``Request`` and ``WebSocket`` are both
#: ``HTTPConnection``; the resolver only ever reads headers, and a second
#: authentication path is how one of them ends up missing a check.
PrincipalResolver = Callable[[HTTPConnection, AsyncSession], Awaitable[Principal]]

_principal_resolver: PrincipalResolver | None = None


def set_principal_resolver(resolver: PrincipalResolver | None) -> None:
    """Install the function that verifies a token and builds a principal.

    ``core`` must not import an authenticating module, and the authenticating
    module must not be duplicated per surface, so it registers itself here at
    wiring time (``main.py``). Until SV-AUTH does that, every authenticated
    route answers 401 ``unauthorized``, which is the truthful answer for a
    server that cannot verify a token — not a stub that lets requests through.
    """
    global _principal_resolver
    _principal_resolver = resolver


def get_principal_resolver() -> PrincipalResolver | None:
    """The installed resolver, or ``None``. ``main.py`` logs the ``None`` case."""
    return _principal_resolver


async def get_session() -> AsyncIterator[AsyncSession]:
    """One database session per request; the service layer owns the commit."""
    async for session in session_scope():
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_principal(
    connection: HTTPConnection, session: SessionDep
) -> Principal:
    """The authenticated caller, or 401. Works for HTTP **and** the socket.

    FastAPI injects the live ``Request`` or ``WebSocket`` here; asking for
    ``HTTPConnection`` is what lets one dependency serve both, and therefore
    what lets ``tests/test_app.py`` hold the socket to the same protection rule
    as every other route.
    """
    resolver = _principal_resolver
    if resolver is None:
        raise UnauthorizedError()
    return await resolver(connection, session)


def get_request_id(request: Request) -> str:
    """The correlation id echoed in every error envelope (SPEC §4.0)."""
    return getattr(request.state, "request_id", "")


PrincipalDep = Annotated[Principal, Depends(get_current_principal)]
RequestIdDep = Annotated[str, Depends(get_request_id)]

__all__ = [
    "REQUEST_ID_HEADER",
    "Principal",
    "PrincipalDep",
    "PrincipalResolver",
    "RequestIdDep",
    "SessionDep",
    "get_current_principal",
    "get_principal_resolver",
    "get_request_id",
    "get_session",
    "set_principal_resolver",
]
