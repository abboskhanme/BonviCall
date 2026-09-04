"""Agents (T31, SPEC §3.3).

An agent is never deleted. They are archived, because their calls are still
theirs and a performance history that loses a person is worthless — the lesson
is written into BonviZvonki's own model file. Archiving is refused while the
agent still holds an open number assignment: a line nobody holds cannot
attribute the calls that arrive on it tomorrow.
"""

from __future__ import annotations

import csv
import io
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.enums import ActorType, AuditAction
from src.core.errors import ConflictError, ErrorCode, NotFoundError
from src.core.sqltext import escape_like
from src.modules.agents.models import AgentModel
from src.modules.agents.schemas import (
    CreateAgentRequest,
    ImportAgentsResponse,
    ImportRowResult,
    UpdateAgentRequest,
)
from src.modules.audit.service import AuditService
from src.modules.numbers.service import NumberService


class AgentService:
    """Agent CRUD and archiving. Owns the transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def list(
        self, include_archived: bool = False, query: str | None = None
    ) -> tuple[list[AgentModel], int]:
        statement = select(AgentModel).order_by(AgentModel.full_name)
        if not include_archived:
            statement = statement.where(AgentModel.archived_at.is_(None))
        if query:
            statement = statement.where(
                AgentModel.full_name.ilike(f"%{escape_like(query)}%")
            )
        rows = list((await self.session.scalars(statement)).all())
        return rows, len(rows)

    async def get(self, agent_id: uuid.UUID) -> AgentModel:
        agent = await self.session.get(AgentModel, agent_id)
        if agent is None:
            raise NotFoundError()
        return agent

    async def create(
        self, payload: CreateAgentRequest, actor_id: uuid.UUID, ip: str | None
    ) -> AgentModel:
        if payload.employee_code and await self._code_taken(payload.employee_code):
            raise ConflictError(ErrorCode.CONFLICT, detail={"field": "employee_code"})
        agent = AgentModel(**payload.model_dump(exclude_none=True))
        self.session.add(agent)
        await self.session.flush()
        await self.audit.record(
            action=AuditAction.AGENT_CREATED,
            object_type="agents",
            object_id=agent.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
        )
        await self.session.commit()
        return agent

    async def update(
        self,
        agent_id: uuid.UUID,
        payload: UpdateAgentRequest,
        actor_id: uuid.UUID,
        ip: str | None,
    ) -> AgentModel:
        agent = await self.get(agent_id)
        changes = payload.model_dump(exclude_unset=True)
        code = changes.get("employee_code")
        if code and code != agent.employee_code and await self._code_taken(code):
            raise ConflictError(ErrorCode.CONFLICT, detail={"field": "employee_code"})
        for field, value in changes.items():
            setattr(agent, field, value)
        await self.audit.record(
            action=AuditAction.AGENT_UPDATED,
            object_type="agents",
            object_id=agent.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
            detail={"changed": sorted(changes)},
        )
        await self.session.commit()
        return agent

    async def archive(
        self, agent_id: uuid.UUID, actor_id: uuid.UUID, ip: str | None
    ) -> AgentModel:
        """Remove from the system. Refused while a number is still theirs."""
        agent = await self.get(agent_id)
        open_assignments = await NumberService(self.session).count_open_assignments(
            agent_id
        )
        if open_assignments:
            raise ConflictError(
                ErrorCode.AGENT_HAS_OPEN_ASSIGNMENT,
                detail={"open_assignments": open_assignments},
            )
        agent.archived_at = clock.now()
        agent.is_active = False
        await self.audit.record(
            action=AuditAction.AGENT_ARCHIVED,
            object_type="agents",
            object_id=agent.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
        )
        await self.session.commit()
        return agent

    async def import_roster(
        self, csv_text: str, dry_run: bool, actor_id: uuid.UUID, ip: str | None
    ):
        """Import ~33 people from pasted CSV, dry-run first (T59).

        Matching is on ``employee_code`` where there is one and on the exact
        name otherwise. A row with neither a name nor a usable code is an error
        rather than a silent skip: a roster import that quietly dropped a
        salesperson is discovered when their calls are attributed to nobody.
        """
        rows: list[ImportRowResult] = []
        created = updated = skipped = errors = 0

        reader = csv.reader(io.StringIO(csv_text.strip()))
        for index, raw in enumerate(reader, start=1):
            if not raw or not any(field.strip() for field in raw):
                continue
            if index == 1 and raw[0].strip().lower() in ("full_name", "name", "fio"):
                continue  # a header row, which every spreadsheet export has

            full_name = raw[0].strip()
            code = raw[1].strip() if len(raw) > 1 and raw[1].strip() else None
            if not full_name:
                errors += 1
                rows.append(
                    ImportRowResult(
                        line=index, full_name="", employee_code=code,
                        action="error", reason="empty name",
                    )
                )
                continue

            existing = None
            if code:
                existing = await self.session.scalar(
                    select(AgentModel).where(AgentModel.employee_code == code)
                )
            if existing is None:
                existing = await self.session.scalar(
                    select(AgentModel).where(AgentModel.full_name == full_name)
                )

            if existing is None:
                created += 1
                action = "create"
                if not dry_run:
                    self.session.add(
                        AgentModel(full_name=full_name, employee_code=code)
                    )
            elif existing.full_name != full_name or existing.employee_code != code:
                updated += 1
                action = "update"
                if not dry_run:
                    existing.full_name = full_name
                    existing.employee_code = code or existing.employee_code
            else:
                skipped += 1
                action = "skip"

            rows.append(
                ImportRowResult(
                    line=index, full_name=full_name, employee_code=code, action=action
                )
            )

        if dry_run:
            # Nothing was written, so nothing is committed and nothing is
            # audited: a preview is not an event.
            await self.session.rollback()
        else:
            await self.audit.record(
                action=AuditAction.AGENTS_IMPORTED,
                object_type="agents",
                actor_type=ActorType.USER,
                actor_user_id=actor_id,
                ip=ip,
                detail={"created": created, "updated": updated, "skipped": skipped},
            )
            await self.session.commit()

        return ImportAgentsResponse(
            dry_run=dry_run,
            created=created,
            updated=updated,
            skipped=skipped,
            errors=errors,
            rows=rows,
        )

    async def _code_taken(self, employee_code: str) -> bool:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(AgentModel)
                .where(AgentModel.employee_code == employee_code)
            )
        ) > 0
