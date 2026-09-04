"""Panel account administration (T148, T149's server side; SPEC §4.7).

Effectively admin-only, because ``users:read`` and ``users:write`` are
admin-only. This is the screen that creates the ``manager``, ``sales`` and
``viewer`` logins every other page is gated on — before it existed, the panel
had role-gated pages and no way to create the roles.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response, status

from src.core.deps import PrincipalDep, SessionDep
from src.core.enums import UserRole
from src.core.permissions import Perm, require_permission
from src.modules.users.schemas import (
    CreateUserRequest,
    SetPasswordRequest,
    UpdateUserRequest,
    UserListResponse,
    UserResponse,
)
from src.modules.users.service import UserService

router = APIRouter(prefix="/users", tags=["Users"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get(
    "",
    response_model=UserListResponse,
    dependencies=[Depends(require_permission(Perm.USERS_READ))],
)
async def list_users(
    session: SessionDep, role: UserRole | None = None, is_active: bool | None = None
) -> UserListResponse:
    """Panel accounts only — **not** agents. Never returns a hash or a token."""
    items, total = await UserService(session).list(role=role, is_active=is_active)
    return UserListResponse(
        items=[UserResponse.model_validate(row) for row in items], total=total
    )


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(Perm.USERS_WRITE))],
)
async def create_user(
    payload: CreateUserRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> UserResponse:
    """Create a login. ``role='sales'`` requires ``agent_id`` (409 otherwise)."""
    user = await UserService(session).create(payload, principal.id, _client_ip(request))
    return UserResponse.model_validate(user)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(require_permission(Perm.USERS_READ))],
)
async def get_user(user_id: uuid.UUID, session: SessionDep) -> UserResponse:
    return UserResponse.model_validate(await UserService(session).get(user_id))


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(require_permission(Perm.USERS_WRITE))],
)
async def update_user(
    user_id: uuid.UUID,
    payload: UpdateUserRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> UserResponse:
    """Guarded: no self-demotion, and never the last active admin."""
    user = await UserService(session).update(
        user_id, payload, principal.id, _client_ip(request)
    )
    return UserResponse.model_validate(user)


@router.post(
    "/{user_id}/password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    dependencies=[Depends(require_permission(Perm.USERS_WRITE))],
)
async def set_password(
    user_id: uuid.UUID,
    payload: SetPasswordRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> None:
    """An admin sets a password. Every session of that user dies with it."""
    await UserService(session).set_password(
        user_id, payload.password, principal.id, _client_ip(request)
    )
