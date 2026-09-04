"""Panel authentication routes (SPEC §4.7).

``/login`` is one of the routes in ``PUBLIC_ROUTES``. ``/refresh`` and
``/logout`` carry no access token — the whole point of a refresh is that the
access token has expired — so they are guarded by the refresh cookie instead,
through :func:`require_refresh_token`. They are protected; they are just
protected by a different credential.

The refresh token is an **HttpOnly cookie**, not a response field. A token in a
response body is a token in the browser's JavaScript heap, and the panel has no
use for it there.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from src.core.config import get_settings
from src.core.deps import PrincipalDep, SessionDep
from src.core.errors import UnauthorizedError
from src.core.permissions import permissions_for
from src.modules.auth.schemas import (
    ChangePasswordRequest,
    CurrentUserResponse,
    LoginRequest,
)
from src.modules.auth.service import AuthService
from src.modules.users.models import UserModel
from src.modules.users.schemas import UserResponse

router = APIRouter(prefix="/auth", tags=["Auth"])

#: Scoped to the refresh route so it is not sent with every panel request.
REFRESH_COOKIE = "bonvicall_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def require_refresh_token(request: Request) -> str:
    """The refresh cookie, or 401. This is what protects /refresh and /logout."""
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise UnauthorizedError()
    return token


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        httponly=True,
        # HTTPS-only in production (N22). Left off in dev so a LAN demo over
        # http:// still works — the same reason the audio player keeps its
        # blob: fallback.
        secure=settings.is_production,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
    )


def _me(user: UserModel) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        agent_id=user.agent_id,
        must_change_password=user.must_change_password,
        permissions=sorted(permissions_for(str(user.role))),
    )


class LoginResponse(CurrentUserResponse):
    """The user *and* their access token, so the panel needs one round trip."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest, request: Request, response: Response, session: SessionDep
) -> LoginResponse:
    """Public. A wrong e-mail and a wrong password give the same answer."""
    user, pair = await AuthService(session).login(
        email=payload.email,
        password=payload.password,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    _set_refresh_cookie(response, pair.refresh_token)
    return LoginResponse(
        **_me(user).model_dump(),
        access_token=pair.access_token,
        expires_in=pair.expires_in,
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    raw_token: str = Depends(require_refresh_token),
) -> LoginResponse:
    """Rotate the session. Reuse of a spent token revokes the whole chain."""
    user, pair = await AuthService(session).refresh(
        raw_token,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    _set_refresh_cookie(response, pair.refresh_token)
    return LoginResponse(
        **_me(user).model_dump(),
        access_token=pair.access_token,
        expires_in=pair.expires_in,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def logout(
    response: Response,
    session: SessionDep,
    raw_token: str = Depends(require_refresh_token),
) -> None:
    """End this session. Idempotent — logging out twice is not an error."""
    await AuthService(session).logout(raw_token)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


@router.get("/me", response_model=CurrentUserResponse)
async def me(principal: PrincipalDep, session: SessionDep) -> CurrentUserResponse:
    """The caller and their resolved permissions.

    The panel's ``can()`` reads this list. It never holds a role-to-permission
    map: a second copy of the matrix is a second thing to forget to update.
    """
    user = await session.get(UserModel, principal.id)
    if user is None:
        raise UnauthorizedError()
    return _me(user)


@router.post("/password", response_model=UserResponse)
async def change_password(
    payload: ChangePasswordRequest, principal: PrincipalDep, session: SessionDep
) -> UserResponse:
    """Self-service change. Succeeding revokes every other session."""
    service = AuthService(session)
    await service.change_own_password(
        principal.id, payload.current_password, payload.new_password
    )
    user = await session.get(UserModel, principal.id)
    return UserResponse.model_validate(user)
