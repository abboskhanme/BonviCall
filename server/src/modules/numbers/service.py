"""Registered numbers and the time-boxed agent mapping (T31, SPEC §3.3).

This is the identity anchor. Two rules are enforced by PostgreSQL, not here,
and the code below exists to turn their violations into a message a human can
act on:

* ``uq_registered_numbers_phone_key`` — one line is one row, whatever format it
  was typed in;
* ``number_assignment_no_overlap`` — an ``EXCLUDE USING gist`` constraint, so
  two admins clicking at the same instant cannot fork the anchor. The check
  below runs first only so the 409 can **name the current holder** (UC-01's
  acceptance criterion); the database is what makes it true.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.enums import ActorType, AuditAction
from src.core.errors import ConflictError, ErrorCode, NotFoundError
from src.core.phone import phone_key
from src.modules.agents.models import AgentModel
from src.modules.audit.service import AuditService
from src.modules.numbers.models import NumberAssignmentModel, RegisteredNumberModel
from src.modules.numbers.schemas import (
    CreateAssignmentRequest,
    CreateNumberRequest,
    UpdateNumberRequest,
)


class NumberService:
    """Number CRUD plus the assignment chain. Owns the transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def list(
        self, is_active: bool | None = None
    ) -> tuple[list[RegisteredNumberModel], int]:
        statement = select(RegisteredNumberModel).order_by(RegisteredNumberModel.e164)
        if is_active is not None:
            statement = statement.where(RegisteredNumberModel.is_active.is_(is_active))
        rows = list((await self.session.scalars(statement)).all())
        return rows, len(rows)

    async def get(self, number_id: uuid.UUID) -> RegisteredNumberModel:
        number = await self.session.get(RegisteredNumberModel, number_id)
        if number is None:
            raise NotFoundError()
        return number

    async def by_phone_key(self, key: str) -> RegisteredNumberModel | None:
        """The registered line whose normalised key is ``key``, or None.

        Added for the cloud-telephony ingest (T-MZ), which learns a line from a
        provider event and must resolve it to one of ours. Here rather than in
        that module because ``registered_numbers`` belongs to this one — a
        second module selecting from it directly is how two normalisations of
        "the same number" appear (§2).
        """
        return await self.session.scalar(
            select(RegisteredNumberModel).where(RegisteredNumberModel.phone_key == key)
        )

    async def create(
        self, payload: CreateNumberRequest, actor_id: uuid.UUID, ip: str | None
    ) -> RegisteredNumberModel:
        key = phone_key(payload.e164)
        existing = await self.session.scalar(
            select(RegisteredNumberModel).where(RegisteredNumberModel.phone_key == key)
        )
        if existing is not None:
            raise ConflictError(
                ErrorCode.CONFLICT,
                detail={"field": "e164", "existing_id": str(existing.id)},
            )
        number = RegisteredNumberModel(**payload.model_dump())
        self.session.add(number)
        await self.session.flush()
        await self.session.refresh(number)
        await self.audit.record(
            action=AuditAction.NUMBER_CREATED,
            object_type="registered_numbers",
            object_id=number.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
        )
        await self.session.commit()
        return number

    async def update(
        self,
        number_id: uuid.UUID,
        payload: UpdateNumberRequest,
        actor_id: uuid.UUID,
        ip: str | None,
    ) -> RegisteredNumberModel:
        number = await self.get(number_id)
        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            setattr(number, field, value)
        await self.audit.record(
            action=AuditAction.NUMBER_UPDATED,
            object_type="registered_numbers",
            object_id=number.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
            detail={"changed": sorted(changes)},
        )
        await self.session.commit()
        return number

    # --- Assignments ------------------------------------------------------

    async def assignments(
        self, number_id: uuid.UUID
    ) -> tuple[list[NumberAssignmentModel], int]:
        """Full history, newest first — the timeline the panel renders."""
        await self.get(number_id)
        rows = list(
            (
                await self.session.scalars(
                    select(NumberAssignmentModel)
                    .where(NumberAssignmentModel.number_id == number_id)
                    .order_by(NumberAssignmentModel.valid_from.desc())
                )
            ).all()
        )
        return rows, len(rows)

    async def assignments_for_agent(
        self, agent_id: uuid.UUID
    ) -> tuple[list[NumberAssignmentModel], int]:
        """Every period this agent held a line, newest first.

        One request instead of one per number: fifteen cached round trips are
        fine and three hundred are not, and the agent detail page is where that
        difference shows up first.
        """
        rows = list(
            (
                await self.session.scalars(
                    select(NumberAssignmentModel)
                    .where(NumberAssignmentModel.agent_id == agent_id)
                    .order_by(NumberAssignmentModel.valid_from.desc())
                )
            ).all()
        )
        return rows, len(rows)

    async def holder_at(
        self, number_id: uuid.UUID, moment: datetime
    ) -> NumberAssignmentModel | None:
        """Which assignment covers ``moment``. The attribution rule (D-08)."""
        return await self.session.scalar(
            select(NumberAssignmentModel).where(
                NumberAssignmentModel.number_id == number_id,
                NumberAssignmentModel.valid_from <= moment,
                (NumberAssignmentModel.valid_to.is_(None))
                | (NumberAssignmentModel.valid_to > moment),
            )
        )

    async def assign(
        self,
        number_id: uuid.UUID,
        payload: CreateAssignmentRequest,
        actor_id: uuid.UUID,
        ip: str | None,
    ) -> NumberAssignmentModel:
        """Give a number to an agent from a moment onwards.

        A clash returns **409 naming the current holder**, because "this number
        is already assigned" without a name sends an admin to look through the
        history to find out who. That is UC-01's acceptance criterion.
        """
        await self.get(number_id)
        agent = await self.session.get(AgentModel, payload.agent_id)
        if agent is None or agent.archived_at is not None:
            raise NotFoundError()

        valid_from = payload.valid_from or clock.now()
        if payload.valid_to is not None and payload.valid_to <= valid_from:
            raise ConflictError(ErrorCode.ASSIGNMENT_OVERLAP, detail={"field": "valid_to"})

        clash = await self._overlapping(number_id, valid_from, payload.valid_to)
        if clash is not None:
            holder = await self.session.get(AgentModel, clash.agent_id)
            raise ConflictError(
                ErrorCode.NUMBER_ALREADY_ASSIGNED,
                detail={
                    "agent_id": str(clash.agent_id),
                    "agent_name": holder.full_name if holder else None,
                    "valid_from": clash.valid_from.isoformat(),
                    "valid_to": clash.valid_to.isoformat() if clash.valid_to else None,
                },
            )

        assignment = NumberAssignmentModel(
            number_id=number_id,
            agent_id=payload.agent_id,
            valid_from=valid_from,
            valid_to=payload.valid_to,
            created_by=actor_id,
            note=payload.note,
        )
        self.session.add(assignment)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            # The exclusion constraint caught a race the check above could not:
            # two admins, same instant. Same answer, without the holder's name,
            # because the winning row was written by the other transaction.
            await self.session.rollback()
            raise ConflictError(ErrorCode.NUMBER_ALREADY_ASSIGNED) from exc

        await self.audit.record(
            action=AuditAction.ASSIGNMENT_CREATED,
            object_type="number_assignments",
            object_id=assignment.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
            detail={"number_id": str(number_id), "agent_id": str(payload.agent_id)},
        )
        await self.session.commit()
        return assignment

    async def close_assignment(
        self,
        assignment_id: uuid.UUID,
        valid_to: datetime,
        actor_id: uuid.UUID,
        ip: str | None,
        note: str | None = None,
    ) -> NumberAssignmentModel:
        """End a holding period.

        Calls already attributed keep their ``agent_id``: closing a period does
        not move history, which is the whole point of the time-boxed mapping.
        The ``reattribute_calls`` job (T151) re-stamps rows only when an
        assignment's *dates* change, and writes an audit row when it does.
        """
        assignment = await self.session.get(NumberAssignmentModel, assignment_id)
        if assignment is None:
            raise NotFoundError()
        if valid_to <= assignment.valid_from:
            raise ConflictError(ErrorCode.ASSIGNMENT_OVERLAP, detail={"field": "valid_to"})
        assignment.valid_to = valid_to
        assignment.closed_by = actor_id
        if note is not None:
            assignment.note = note
        await self.audit.record(
            action=AuditAction.ASSIGNMENT_CLOSED,
            object_type="number_assignments",
            object_id=assignment.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
            detail={"valid_to": valid_to.isoformat()},
        )
        await self.session.commit()
        return assignment

    async def _overlapping(
        self, number_id: uuid.UUID, valid_from: datetime, valid_to: datetime | None
    ) -> NumberAssignmentModel | None:
        """Any assignment whose period intersects [valid_from, valid_to)."""
        statement = select(NumberAssignmentModel).where(
            NumberAssignmentModel.number_id == number_id,
            (NumberAssignmentModel.valid_to.is_(None))
            | (NumberAssignmentModel.valid_to > valid_from),
        )
        if valid_to is not None:
            statement = statement.where(NumberAssignmentModel.valid_from < valid_to)
        return await self.session.scalar(statement.limit(1))

    async def e164_map(self, number_ids) -> dict:
        """``{id: e164}`` for a page of calls — one query, not one per row."""
        if not number_ids:
            return {}
        rows = (
            await self.session.execute(
                select(RegisteredNumberModel.id, RegisteredNumberModel.e164).where(
                    RegisteredNumberModel.id.in_(set(number_ids))
                )
            )
        ).all()
        return {row.id: row.e164 for row in rows}

    async def all_phone_keys(self) -> frozenset[str]:
        """Every registered line's last-9 key — the derived half of the
        internal/external directory (UC-25).

        A set of strings, not rows: the caller is another module and has no
        business holding this table's entities.
        """
        keys = await self.session.scalars(select(RegisteredNumberModel.phone_key))
        return frozenset(keys.all())

    async def count_open_assignments(self, agent_id: uuid.UUID) -> int:
        """How many lines this agent still holds. Archiving is refused above 0.

        A line nobody holds cannot attribute the calls that arrive on it
        tomorrow, which is why archiving waits for the handover.
        """
        return await self.session.scalar(
            select(func.count())
            .select_from(NumberAssignmentModel)
            .where(
                NumberAssignmentModel.agent_id == agent_id,
                NumberAssignmentModel.valid_to.is_(None),
            )
        )

    async def count_active(self) -> int:
        return await self.session.scalar(
            select(func.count())
            .select_from(RegisteredNumberModel)
            .where(RegisteredNumberModel.is_active.is_(True))
        )
