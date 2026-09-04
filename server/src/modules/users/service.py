"""User administration (T148, SPEC §4.7).

Two guards exist so that the panel cannot be locked out of itself, and both are
409s rather than 403s because the caller *does* have the permission — the
operation is what is refused:

* a user cannot deactivate or demote **themselves**;
* the **last active admin** can be neither deactivated nor demoted.

A panel with no admin can only be repaired from a shell on the server, which on
a host the team does not sit next to is an outage.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.enums import ActorType, AuditAction, UserRole
from src.core.errors import ConflictError, ErrorCode, NotFoundError
from src.core.security import hash_password
from src.modules.agents.models import AgentModel
from src.modules.audit.service import AuditService
from src.modules.auth.service import AuthService
from src.modules.users.models import UserModel
from src.modules.users.schemas import CreateUserRequest, UpdateUserRequest


class UserService:
    """Panel account CRUD. Owns its transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def list(
        self, role: UserRole | None = None, is_active: bool | None = None
    ) -> tuple[list[UserModel], int]:
        statement = select(UserModel).order_by(UserModel.full_name)
        if role is not None:
            statement = statement.where(UserModel.role == role)
        if is_active is not None:
            statement = statement.where(UserModel.is_active.is_(is_active))
        rows = list((await self.session.scalars(statement)).all())
        return rows, len(rows)

    async def get(self, user_id: uuid.UUID) -> UserModel:
        user = await self.session.get(UserModel, user_id)
        if user is None:
            raise NotFoundError()
        return user

    async def create(
        self, payload: CreateUserRequest, actor_id: uuid.UUID, ip: str | None
    ) -> UserModel:
        await self._assert_agent_link(payload.role, payload.agent_id)
        if await self._email_taken(payload.email):
            raise ConflictError(ErrorCode.CONFLICT, detail={"field": "email"})

        user = UserModel(
            email=payload.email,
            password_hash=hash_password(payload.password),
            full_name=payload.full_name,
            role=payload.role,
            agent_id=payload.agent_id,
            # An account whose password was typed by somebody else is an
            # account whose password that person still knows.
            must_change_password=True,
        )
        self.session.add(user)
        await self.session.flush()
        await self.audit.record(
            action=AuditAction.USER_CREATED,
            object_type="users",
            object_id=user.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
            detail={"role": str(payload.role)},
        )
        await self.session.commit()
        return user

    async def update(
        self,
        user_id: uuid.UUID,
        payload: UpdateUserRequest,
        actor_id: uuid.UUID,
        ip: str | None,
    ) -> UserModel:
        user = await self.get(user_id)
        changes = payload.model_dump(exclude_unset=True)

        if user.id == actor_id and (
            changes.get("is_active") is False or "role" in changes
        ):
            raise ConflictError(ErrorCode.CANNOT_MODIFY_SELF)

        losing_admin = user.role is UserRole.ADMIN and (
            changes.get("is_active") is False
            or (changes.get("role") is not None and changes["role"] is not UserRole.ADMIN)
        )
        if losing_admin and await self._active_admin_count() <= 1:
            raise ConflictError(ErrorCode.LAST_ADMIN)

        new_role = changes.get("role", user.role)
        new_agent = changes.get("agent_id", user.agent_id)
        await self._assert_agent_link(new_role, new_agent)

        for field, value in changes.items():
            setattr(user, field, value)
        if changes.get("is_active") is False:
            user.deactivated_at = clock.now()
            await self._revoke_sessions(user.id)
        await self.audit.record(
            action=(
                AuditAction.USER_DEACTIVATED
                if changes.get("is_active") is False
                else AuditAction.USER_UPDATED
            ),
            object_type="users",
            object_id=user.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
            detail={"changed": sorted(changes)},
        )
        await self.session.commit()
        return user

    async def set_password(
        self, user_id: uuid.UUID, password: str, actor_id: uuid.UUID, ip: str | None
    ) -> None:
        """An admin resets somebody's password.

        Every session of that user dies with it: a reset that leaves the old
        browser logged in has not reset anything.
        """
        user = await self.get(user_id)
        user.password_hash = hash_password(password)
        user.must_change_password = True
        user.password_changed_at = None
        await self._revoke_sessions(user.id)
        await self.audit.record(
            action=AuditAction.PASSWORD_RESET,
            object_type="users",
            object_id=user.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
        )
        await self.session.commit()

    async def _assert_agent_link(
        self, role: UserRole, agent_id: uuid.UUID | None
    ) -> None:
        if role is UserRole.SALES and agent_id is None:
            raise ConflictError(ErrorCode.SALES_USER_REQUIRES_AGENT)
        if agent_id is None:
            return
        agent = await self.session.get(AgentModel, agent_id)
        if agent is None or agent.archived_at is not None:
            raise ConflictError(
                ErrorCode.SALES_USER_REQUIRES_AGENT, detail={"agent_id": str(agent_id)}
            )

    async def _email_taken(self, email: str) -> bool:
        return (
            await self.session.scalar(
                select(func.count()).select_from(UserModel).where(UserModel.email == email)
            )
        ) > 0

    async def _active_admin_count(self) -> int:
        return await self.session.scalar(
            select(func.count())
            .select_from(UserModel)
            .where(UserModel.role == UserRole.ADMIN, UserModel.is_active.is_(True))
        )

    async def _revoke_sessions(self, user_id: uuid.UUID) -> None:
        """Sessions belong to ``auth``; this module only decides when to end them."""
        await AuthService(self.session).revoke_all_sessions(user_id)
