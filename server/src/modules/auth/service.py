"""Authentication: panel sessions, device tokens, the principal resolver.

Three kinds of caller reach this module and none of them may be mistaken for
another, so the token's ``typ`` claim is checked, never inferred:

* a **user** — a panel login, with a rotating opaque refresh token;
* a **device** — an installation-bound token whose claims must match the
  headers the request carries (N24), so a token copied to a second phone is
  refused on first use;
* a **service** — an opaque machine token (UC-29), never a JWT, never
  exchangeable for a user session.

Refresh-token reuse is treated as theft in both directions: for a panel user the
whole chain is revoked, for an installation ``token_version`` is incremented so
every issued token dies at once.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.config import get_settings
from src.core.deps import Principal
from src.core.errors import ErrorCode, UnauthorizedError
from src.core.logging import get_logger
from src.core.permissions import Role, permissions_for
from src.core.security import (
    bearer_token,
    create_access_token,
    decode_access_token,
    hash_password,
    new_opaque_token,
    sha256_hex,
    verify_password,
)
from src.modules.auth.models import RefreshTokenModel, ServiceTokenModel
from src.modules.installations.service import InstallationService
from src.modules.users.models import UserModel

log = get_logger(__name__)

TOKEN_TYPE_USER = "user"
TOKEN_TYPE_DEVICE = "device"

#: Checked against the token's claims by ``installations`` — that is the N24
#: binding. Named here because this is where the request is read.
HEADER_INSTALLATION = "X-Installation-Id"
HEADER_FINGERPRINT = "X-Device-Fingerprint"

#: SPEC §4.2: twelve hours, not fifteen minutes. A phone can be offline for a
#: day, and N25 requires that expiry never loses data — not that the window is
#: small. The panel's window is short because a browser is always online.
DEVICE_ACCESS_TOKEN_HOURS = 12

#: Headers every device request carries (SPEC §4.2). Missing ones are a 400
#: ``header_missing``, never a 500.
HEADER_INSTALLATION = "X-Installation-Id"
HEADER_FINGERPRINT = "X-Device-Fingerprint"


@dataclass(frozen=True)
class TokenPair:
    """What a successful login or refresh hands back."""

    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    """Login, refresh, logout and password change. Owns its transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()

    # --- Panel ------------------------------------------------------------

    async def login(
        self, email: str, password: str, ip: str | None, user_agent: str | None
    ) -> tuple[UserModel, TokenPair]:
        """Verify a password and open a session.

        A wrong e-mail and a wrong password give the same answer: telling a
        caller which half was wrong turns the login form into an account
        enumerator.
        """
        user = await self.session.scalar(select(UserModel).where(UserModel.email == email))
        if user is None or not verify_password(password, user.password_hash):
            log.info("login_failed", email=email)
            raise UnauthorizedError(ErrorCode.UNAUTHORIZED)
        if not user.is_active:
            log.info("login_refused_inactive", user_id=str(user.id))
            raise UnauthorizedError(ErrorCode.UNAUTHORIZED)

        user.last_login_at = clock.now()
        pair = await self._issue_user_pair(user, ip=ip, user_agent=user_agent)
        await self.session.commit()
        log.info("login_succeeded", user_id=str(user.id), role=str(user.role))
        return user, pair

    async def refresh(
        self, raw_token: str, ip: str | None, user_agent: str | None
    ) -> tuple[UserModel, TokenPair]:
        """Rotate a panel session. Reuse of a spent token kills the chain."""
        token_hash = sha256_hex(raw_token)
        row = await self.session.scalar(
            select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash)
        )
        if row is None:
            raise UnauthorizedError(ErrorCode.UNAUTHORIZED)

        if row.revoked_at is not None:
            # The token was already spent. Either a client retried a request it
            # had already completed, or somebody else has the token; we cannot
            # tell, and only one of those is safe to allow. Kill the chain.
            await self.revoke_all_sessions(row.user_id)
            await self.session.commit()
            log.warning("refresh_reused", user_id=str(row.user_id))
            raise UnauthorizedError(ErrorCode.REFRESH_REUSED)

        if row.expires_at <= clock.now():
            raise UnauthorizedError(ErrorCode.UNAUTHORIZED)

        user = await self.session.get(UserModel, row.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError(ErrorCode.UNAUTHORIZED)

        pair, successor = await self._issue_user_pair(
            user, ip=ip, user_agent=user_agent, return_row=True
        )
        row.revoked_at = clock.now()
        row.replaced_by_id = successor.id
        await self.session.commit()
        return user, pair

    async def logout(self, raw_token: str) -> None:
        """End one session. Idempotent: logging out twice is not an error."""
        token_hash = sha256_hex(raw_token)
        await self.session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.token_hash == token_hash,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=clock.now())
        )
        await self.session.commit()

    async def change_own_password(
        self, user_id: uuid.UUID, current_password: str, new_password: str
    ) -> None:
        """Self-service change. Succeeding revokes every other session."""
        user = await self.session.get(UserModel, user_id)
        if user is None or not verify_password(current_password, user.password_hash):
            raise UnauthorizedError(ErrorCode.UNAUTHORIZED)
        user.password_hash = hash_password(new_password)
        user.password_changed_at = clock.now()
        user.must_change_password = False
        await self.revoke_all_sessions(user_id)
        await self.session.commit()
        log.info("password_changed", user_id=str(user_id))

    async def _issue_user_pair(
        self,
        user: UserModel,
        ip: str | None,
        user_agent: str | None,
        return_row: bool = False,
    ) -> TokenPair | tuple[TokenPair, RefreshTokenModel]:
        """Mint a pair. ``return_row`` also hands back the stored row, so the
        rotation can link the chain without a second lookup."""
        ttl = timedelta(minutes=self.settings.access_token_ttl_min)
        access_token, _ = create_access_token(
            subject=user.id,
            token_type=TOKEN_TYPE_USER,
            expires_in=ttl,
            claims={"role": str(user.role)},
        )
        raw_refresh = new_opaque_token()
        row = RefreshTokenModel(
            user_id=user.id,
            token_hash=sha256_hex(raw_refresh),
            expires_at=clock.now() + timedelta(days=self.settings.refresh_token_ttl_days),
            ip=ip,
            user_agent=(user_agent or "")[:255] or None,
        )
        self.session.add(row)
        await self.session.flush()
        pair = TokenPair(
            access_token=access_token,
            refresh_token=raw_refresh,
            expires_in=int(ttl.total_seconds()),
        )
        return (pair, row) if return_row else pair

    async def revoke_all_sessions(self, user_id: uuid.UUID) -> None:
        """End every live session of one user.

        Public because ``users`` calls it: an admin resetting a password, or
        deactivating an account, must not leave a browser logged in.
        """
        await self.session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.user_id == user_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=clock.now())
        )


async def resolve_principal(request: Request, session: AsyncSession) -> Principal:
    """Turn a request into a :class:`Principal`, or raise 401.

    Registered on the application in ``main.py``. ``core`` never imports this
    module — the composition root does the wiring, which is what keeps the
    dependency arrows pointing one way (CONVENTIONS.md §11).
    """
    token = bearer_token(request.headers.get("Authorization"))

    service_principal = await _service_principal(session, token)
    if service_principal is not None:
        return service_principal

    claims = decode_access_token(token)
    token_type = claims.get("typ")
    if token_type == TOKEN_TYPE_USER:
        return await _user_principal(session, claims)
    if token_type == TOKEN_TYPE_DEVICE:
        # The installation module owns the row, the binding check and the
        # token_version rule, so it builds its own principal (CONVENTIONS §2).
        return await InstallationService(session).principal_for_claims(
            claims,
            installation_header=request.headers.get(HEADER_INSTALLATION),
            fingerprint_header=request.headers.get(HEADER_FINGERPRINT),
        )
    raise UnauthorizedError()


async def _service_principal(session: AsyncSession, token: str) -> Principal | None:
    """A machine token is opaque, so it is looked up before any JWT decoding."""
    row = await session.scalar(
        select(ServiceTokenModel).where(ServiceTokenModel.token_hash == sha256_hex(token))
    )
    if row is None:
        return None
    if not row.is_active or (row.expires_at is not None and row.expires_at <= clock.now()):
        raise UnauthorizedError()
    row.last_used_at = clock.now()
    # Scopes narrow the role further: a token issued for callbacks cannot read
    # the export even though the service role could (SPEC §4.1 rule 4).
    scoped = frozenset(row.scopes or ()) & permissions_for(str(Role.SERVICE))
    return Principal(
        kind="service",
        id=row.id,
        role=str(Role.SERVICE),
        permissions=scoped,
        display_name=row.name,
    )


async def _user_principal(session: AsyncSession, claims: dict) -> Principal:
    user = await session.get(UserModel, uuid.UUID(claims["sub"]))
    if user is None or not user.is_active:
        raise UnauthorizedError()
    return Principal(
        kind="user",
        id=user.id,
        role=str(user.role),
        permissions=permissions_for(str(user.role)),
        agent_id=user.agent_id,
        display_name=user.full_name,
    )
