"""Enrolment codes, attempts and the callback receivers (T32, T34, T141)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request

from src.core import clock
from src.core.deps import PrincipalDep, SessionDep
from src.core.permissions import Perm, require_permission
from src.modules.enrolment.schemas import (
    EnrolmentAttemptListResponse,
    EnrolmentAttemptResponse,
    EnrolmentCodeListResponse,
    EnrolmentCodeResponse,
)
from src.modules.enrolment.service import EnrolmentService

router = APIRouter(prefix="/enrolment", tags=["Enrolment"])
codes_router = APIRouter(prefix="/enrolment-codes", tags=["Enrolment"])


@codes_router.get(
    "",
    response_model=EnrolmentCodeListResponse,
    dependencies=[Depends(require_permission(Perm.ENROLMENT_READ))],
)
async def list_codes(
    session: SessionDep, number_id: uuid.UUID | None = None, active_only: bool = False
) -> EnrolmentCodeListResponse:
    items, total = await EnrolmentService(session).list_codes(number_id, active_only)
    return EnrolmentCodeListResponse(
        items=[EnrolmentCodeResponse.model_validate(row) for row in items], total=total
    )


@codes_router.post(
    "/{code_id}/revoke",
    response_model=EnrolmentCodeResponse,
    dependencies=[Depends(require_permission(Perm.ENROLMENT_WRITE))],
)
async def revoke_code(
    code_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> EnrolmentCodeResponse:
    code = await EnrolmentService(session).revoke_code(
        code_id, principal.id, request.client.host if request.client else None
    )
    return EnrolmentCodeResponse.model_validate(code)


@router.get(
    "/attempts",
    response_model=EnrolmentAttemptListResponse,
    dependencies=[Depends(require_permission(Perm.ENROLMENT_READ))],
)
async def list_attempts(
    session: SessionDep,
    number_id: uuid.UUID | None = None,
    installation_id: uuid.UUID | None = None,
) -> EnrolmentAttemptListResponse:
    """Where UC-01's failures appear, with timestamps.

    A stalled enrolment must be an event, not silence — this is the list an
    admin watches during a rollout.
    """
    items, total = await EnrolmentService(session).list_attempts(number_id, installation_id)
    return EnrolmentAttemptListResponse(
        items=[EnrolmentAttemptResponse.model_validate(row) for row in items], total=total
    )


@router.get(
    "/receiver-status",
    dependencies=[Depends(require_permission(Perm.ENROLMENT_READ))],
)
async def receiver_status(session: SessionDep) -> dict[str, str | bool]:
    """The banner at the top of the rollout page.

    If every receiver is down nobody can enrol, and the page says so **before**
    anyone tries. Absence of enrolment must be an event, not a quiet stall.
    """
    service = EnrolmentService(session)
    receiver = await service.usable_receiver()
    return {
        "enrolment_possible": receiver is not None,
        "receiver_name": receiver.name if receiver else "",
        "receiver_msisdn": receiver.msisdn if receiver else "",
        "status": (
            service.status_for(receiver.last_heartbeat_at, clock.now()).value
            if receiver
            else "down"
        ),
    }
