"""Writing the audit log (UC-24, N27).

There is exactly one way a row gets in, and it is this class. There is no way
for one to change or leave: the table carries a trigger that raises on UPDATE
and DELETE, so this is append-only in the database and not by agreement.

``detail`` is machine-readable context — before/after values, counts, the
reason for an attestation. It never carries a password, a token or an enrolment
code (N26).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.enums import ActorType, AuditAction
from src.modules.audit.models import AuditLogModel


class AuditService:
    """Appends to ``audit_log``. Never commits — the calling service owns that.

    Deliberate: an audit row and the thing it describes must land in the same
    transaction, or the log records something that did not happen.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def recorded_recently(
        self,
        action: AuditAction,
        actor_user_id: uuid.UUID | None,
        object_id: uuid.UUID | None,
        within_seconds: int,
    ) -> bool:
        """Whether this actor already logged this action for this object.

        Exists so the audio module can answer "is this a new playback or the
        same one seeking" without reading this table itself (§2). UC-24 wants
        exactly one row per playback start, and scrubbing a twenty-minute
        recording must not produce forty.
        """
        found = await self.session.scalar(
            select(AuditLogModel.id)
            .where(
                AuditLogModel.action == action,
                AuditLogModel.actor_user_id == actor_user_id,
                AuditLogModel.object_id == object_id,
                AuditLogModel.at > clock.now() - timedelta(seconds=within_seconds),
            )
            .limit(1)
        )
        return found is not None

    async def list(
        self,
        action=None,
        object_type: str | None = None,
        object_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
        limit: int = 50,
    ):
        """Newest first. Read-only — there is no update and no delete."""
        statement = select(AuditLogModel).order_by(AuditLogModel.at.desc())
        if action is not None:
            statement = statement.where(AuditLogModel.action == action)
        if object_type is not None:
            statement = statement.where(AuditLogModel.object_type == object_type)
        if object_id is not None:
            statement = statement.where(AuditLogModel.object_id == object_id)
        if actor_user_id is not None:
            statement = statement.where(AuditLogModel.actor_user_id == actor_user_id)
        rows = list((await self.session.scalars(statement.limit(limit))).all())
        return rows, len(rows)

    async def record(
        self,
        action: AuditAction,
        object_type: str,
        object_id: uuid.UUID | None = None,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_user_id: uuid.UUID | None = None,
        actor_service_token_id: uuid.UUID | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AuditLogModel:
        row = AuditLogModel(
            action=action,
            object_type=object_type,
            object_id=object_id,
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            actor_service_token_id=actor_service_token_id,
            ip=ip,
            user_agent=(user_agent or "")[:255] or None,
            detail=detail,
        )
        self.session.add(row)
        await self.session.flush()
        return row
