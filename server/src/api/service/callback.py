"""The callback receiver's endpoint (T141, T144; SPEC §9.4).

The receiver holds a ``service`` token scoped to ``callback:report`` and
nothing else. It posts every inbound call it sees, and a heartbeat every 60
seconds — a heartbeat is simply an event with no caller, so the receiver proves
it is alive by posting rather than by having seen a call.

**It does not answer the call.** Ringing is enough, so the agent is not charged
and no audio exists anywhere.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from src.core.deps import SessionDep
from src.core.errors import UnauthorizedError
from src.core.permissions import Perm, require_permission
from src.core.security import bearer_token
from src.modules.enrolment.schemas import CallbackEventIn, CallbackEventOut
from src.modules.enrolment.service import EnrolmentService

router = APIRouter(prefix="/callback-events", tags=["Callback receiver"])


@router.post(
    "",
    response_model=CallbackEventOut,
    dependencies=[Depends(require_permission(Perm.CALLBACK_REPORT))],
)
async def report_callback_event(
    payload: CallbackEventIn, request: Request, session: SessionDep
) -> CallbackEventOut:
    """Record what the receiver saw, and match it to a pending verification.

    The permission dependency proves the caller is a receiver-scoped service
    token; the lookup below proves it is *this* receiver, so two gateways
    cannot report on each other's behalf.
    """
    service = EnrolmentService(session)
    receiver = await service.receiver_by_token(
        bearer_token(request.headers.get("Authorization"))
    )
    if receiver is None:
        raise UnauthorizedError()

    stored, matched, status = await service.report_callback_event(
        receiver=receiver,
        caller_e164=payload.caller_e164,
        cli_presented=payload.cli_presented,
        receiver_epoch_ms=payload.receiver_epoch_ms,
        heartbeat=payload.heartbeat,
    )
    return CallbackEventOut(stored=stored, matched=matched, receiver_status=status)
