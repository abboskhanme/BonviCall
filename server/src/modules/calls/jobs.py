"""On-demand recomputation owned by ``calls`` (T151).

Both jobs exist because an admin edit changes what the *past* means:
reassigning a number changes who a call belonged to, and editing the line
directory changes whether it was internal. Leaving history disagreeing with the
settings screen is how a performance report stops being trusted.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import ActorType, AlertKind, AlertSeverity, AuditAction
from src.core.logging import get_logger
from src.modules.alerts.service import AlertService
from src.modules.audit.service import AuditService
from src.modules.calls.models import CallModel
from src.modules.calls.service import CallService
from src.modules.numbers.service import NumberService

log = get_logger(__name__)


async def reclassify_calls(session: AsyncSession) -> int:
    """Recompute ``call_type`` after a directory change (UC-25)."""
    return await CallService(session).reclassify()


async def reattribute_calls(
    session: AsyncSession, number_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> int:
    """Re-stamp ``agent_id``/``assignment_id`` after an assignment edit (§10.4).

    **This is the one that makes the time-boxed mapping correctable.** It also
    writes an audit row with the before/after counts and raises an ``info``
    alert, because a silent mass re-attribution is exactly the kind of change
    that destroys trust in a performance report — somebody's numbers moved and
    nobody said so.

    Idempotent: a call already attributed to the right assignment is not
    written, so running it twice changes nothing and audits nothing the second
    time.
    """
    numbers = NumberService(session)
    calls = list(
        (
            await session.scalars(
                select(CallModel).where(CallModel.number_id == number_id)
            )
        ).all()
    )
    moved: dict[str, int] = {}
    for call in calls:
        assignment = await numbers.holder_at(number_id, call.started_at)
        if assignment is None or (
            call.agent_id == assignment.agent_id
            and call.assignment_id == assignment.id
        ):
            continue
        moved[f"{call.agent_id} -> {assignment.agent_id}"] = (
            moved.get(f"{call.agent_id} -> {assignment.agent_id}", 0) + 1
        )
        call.agent_id = assignment.agent_id
        call.assignment_id = assignment.id

    total = sum(moved.values())
    if total:
        await AuditService(session).record(
            action=AuditAction.CALLS_REATTRIBUTED,
            object_type="registered_numbers",
            object_id=number_id,
            actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
            actor_user_id=actor_id,
            detail={"calls": total, "moves": moved},
        )
        await AlertService(session).raise_alert(
            kind=AlertKind.ATTRIBUTION_OUT_OF_RANGE,
            severity=AlertSeverity.INFO,
            scope=f"reattribute:{number_id}",
            number_id=number_id,
            detail={"calls_reattributed": total},
        )
        log.info("calls_reattributed", number_id=str(number_id), calls=total)
    await session.commit()
    return total
