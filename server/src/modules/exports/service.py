"""The service export (T51, UC-29, SPEC §4.9).

Holds the §2.1 cross-module read exception. Everything below is a **column
projection**: no ORM entity is loaded, so no foreign entity can leak past this
module, and 50,000 rows do not have to be materialised as objects to be
serialised.

The cursor is ``seq`` with a **ten-second settling window**. ``seq`` comes from
a sequence, and under concurrency a lower ``seq`` can commit after a higher one
— so a naive ``WHERE seq > cursor`` skips that row forever. Excluding anything
received in the last ten seconds is what makes UC-29's "two consecutive full
passes return identical row sets" true rather than nearly true.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.enums import CallDisposition
from src.modules.agents.models import AgentModel
from src.modules.audio.models import CallAudioModel
from src.modules.calls.models import CallModel
from src.modules.exports.schemas import (
    BONVIZVONKI_DIRECTION,
    ExportAgentDetailOut,
    ExportAgentOut,
    ExportCallOut,
    ExportNumberPeriodOut,
)
from src.modules.numbers.models import NumberAssignmentModel, RegisteredNumberModel

#: SPEC §3.12. Ten seconds is longer than any transaction this system runs.
SETTLING_WINDOW_SECONDS = 10

MAX_EXPORT_LIMIT = 500

AUDIO_REF = "/api/service/v1/export/calls/{call_id}/audio"


class ExportService:
    """Read-only. Owns no table and writes nothing (§2.1 rule 2)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def calls(self, since: int = 0, limit: int = MAX_EXPORT_LIMIT):
        """A page of calls after ``since``, ordered by ``seq``."""
        cutoff = clock.now() - timedelta(seconds=SETTLING_WINDOW_SECONDS)
        statement = (
            select(
                CallModel.id,
                CallModel.seq,
                CallModel.agent_id,
                AgentModel.full_name,
                RegisteredNumberModel.e164,
                RegisteredNumberModel.phone_key,
                CallModel.remote_number,
                CallModel.remote_number_key,
                CallModel.direction,
                CallModel.disposition,
                CallModel.call_type,
                CallModel.started_at,
                CallModel.answered_at,
                CallModel.ended_at,
                CallModel.duration_sec,
                CallModel.received_at,
                CallModel.has_audio,
                CallModel.audio_missing_reason,
                CallModel.app_variant,
                CallAudioModel.sha256,
                CallAudioModel.duration_ms,
                CallAudioModel.capture_route,
                CallAudioModel.deleted_at,
            )
            .join(AgentModel, AgentModel.id == CallModel.agent_id)
            .join(
                RegisteredNumberModel, RegisteredNumberModel.id == CallModel.number_id
            )
            .outerjoin(CallAudioModel, CallAudioModel.call_id == CallModel.id)
            .where(CallModel.seq > since, CallModel.received_at <= cutoff)
            .order_by(CallModel.seq.asc())
            .limit(min(limit, MAX_EXPORT_LIMIT))
        )
        rows = (await self.session.execute(statement)).all()
        items = [
            ExportCallOut(
                id=row.id,
                seq=row.seq,
                agent=ExportAgentOut(id=row.agent_id, full_name=row.full_name),
                agent_number_e164=row.e164,
                agent_number_key=row.phone_key,
                remote_number_e164=row.remote_number,
                remote_number_key=row.remote_number_key,
                direction=row.direction,
                bonvizvonki_direction=BONVIZVONKI_DIRECTION[row.direction],
                disposition=row.disposition,
                answered=row.disposition is CallDisposition.ANSWERED,
                call_type=row.call_type,
                started_at=row.started_at,
                answered_at=row.answered_at,
                ended_at=row.ended_at,
                duration_sec=row.duration_sec,
                received_at=row.received_at,
                has_audio=row.has_audio,
                audio_missing_reason=row.audio_missing_reason,
                # NULL once retention removed the blob: the reference must not
                # point at a file that is gone (UC-26).
                audio_ref=(
                    AUDIO_REF.format(call_id=row.id)
                    if row.has_audio and row.deleted_at is None
                    else None
                ),
                audio_sha256=row.sha256 if row.deleted_at is None else None,
                audio_duration_ms=row.duration_ms,
                capture_route=row.capture_route,
                app_variant=row.app_variant,
            )
            for row in rows
        ]
        next_since = items[-1].seq if items else since
        return items, next_since

    async def agents(self) -> list[ExportAgentDetailOut]:
        """Agents with their number history (SPEC §4.9)."""
        agent_rows = (
            await self.session.execute(
                select(AgentModel.id, AgentModel.full_name, AgentModel.is_active)
                .where(AgentModel.archived_at.is_(None))
                .order_by(AgentModel.full_name)
            )
        ).all()
        history_rows = (
            await self.session.execute(
                select(
                    NumberAssignmentModel.agent_id,
                    RegisteredNumberModel.e164,
                    RegisteredNumberModel.phone_key,
                    NumberAssignmentModel.valid_from,
                    NumberAssignmentModel.valid_to,
                )
                .join(
                    RegisteredNumberModel,
                    RegisteredNumberModel.id == NumberAssignmentModel.number_id,
                )
                .order_by(NumberAssignmentModel.valid_from.asc())
            )
        ).all()
        by_agent: dict[uuid.UUID, list[ExportNumberPeriodOut]] = {}
        for row in history_rows:
            by_agent.setdefault(row.agent_id, []).append(
                ExportNumberPeriodOut(
                    e164=row.e164,
                    key=row.phone_key,
                    valid_from=row.valid_from,
                    valid_to=row.valid_to,
                )
            )
        return [
            ExportAgentDetailOut(
                id=row.id,
                full_name=row.full_name,
                is_active=row.is_active,
                numbers=by_agent.get(row.id, []),
            )
            for row in agent_rows
        ]
