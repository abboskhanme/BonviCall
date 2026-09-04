"""Registered numbers, their assignment history, and enrolment codes (T31, T32).

The 409 on a clashing assignment **names the current holder** — that is UC-01's
acceptance criterion, and it is the difference between an admin fixing the
problem and an admin going to look through the history to find out who has it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status

from src.core.deps import PrincipalDep, SessionDep
from src.core.permissions import Perm, require_permission
from src.modules.enrolment.schemas import EnrolmentCodeResponse
from src.modules.enrolment.service import EnrolmentService
from src.modules.numbers.schemas import (
    AssignmentListResponse,
    AssignmentResponse,
    CloseAssignmentRequest,
    CreateAssignmentRequest,
    CreateNumberRequest,
    NumberListResponse,
    NumberResponse,
    UpdateNumberRequest,
)
from src.modules.numbers.service import NumberService

router = APIRouter(prefix="/numbers", tags=["Numbers"])

#: Assignments are addressed directly once they exist, so they get their own
#: prefix rather than being nested three levels deep under a number.
assignments_router = APIRouter(prefix="/assignments", tags=["Numbers"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get(
    "",
    response_model=NumberListResponse,
    dependencies=[Depends(require_permission(Perm.NUMBERS_READ))],
)
async def list_numbers(session: SessionDep, is_active: bool | None = None) -> NumberListResponse:
    items, total = await NumberService(session).list(is_active)
    return NumberListResponse(
        items=[NumberResponse.model_validate(row) for row in items], total=total
    )


@router.post(
    "",
    response_model=NumberResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(Perm.NUMBERS_WRITE))],
)
async def create_number(
    payload: CreateNumberRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> NumberResponse:
    """The number is normalised first, so three formats are one row (N37)."""
    number = await NumberService(session).create(payload, principal.id, _client_ip(request))
    return NumberResponse.model_validate(number)


@router.get(
    "/{number_id}",
    response_model=NumberResponse,
    dependencies=[Depends(require_permission(Perm.NUMBERS_READ))],
)
async def get_number(number_id: uuid.UUID, session: SessionDep) -> NumberResponse:
    return NumberResponse.model_validate(await NumberService(session).get(number_id))


@router.patch(
    "/{number_id}",
    response_model=NumberResponse,
    dependencies=[Depends(require_permission(Perm.NUMBERS_WRITE))],
)
async def update_number(
    number_id: uuid.UUID,
    payload: UpdateNumberRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> NumberResponse:
    number = await NumberService(session).update(
        number_id, payload, principal.id, _client_ip(request)
    )
    return NumberResponse.model_validate(number)


@router.get(
    "/{number_id}/assignments",
    response_model=AssignmentListResponse,
    dependencies=[Depends(require_permission(Perm.NUMBERS_READ))],
)
async def list_assignments(
    number_id: uuid.UUID, session: SessionDep
) -> AssignmentListResponse:
    """Full history — this is where the time-boxed mapping becomes visible."""
    items, total = await NumberService(session).assignments(number_id)
    return AssignmentListResponse(
        items=[AssignmentResponse.model_validate(row) for row in items], total=total
    )


@router.post(
    "/{number_id}/assignments",
    response_model=AssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(Perm.NUMBERS_WRITE))],
)
async def create_assignment(
    number_id: uuid.UUID,
    payload: CreateAssignmentRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> AssignmentResponse:
    """409 ``number_already_assigned``, with the current holder in ``detail``."""
    assignment = await NumberService(session).assign(
        number_id, payload, principal.id, _client_ip(request)
    )
    return AssignmentResponse.model_validate(assignment)


@router.post(
    "/{number_id}/enrolment-code",
    response_model=EnrolmentCodeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(Perm.ENROLMENT_WRITE))],
)
async def issue_enrolment_code(
    number_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> EnrolmentCodeResponse:
    """Single-use, 24 h. The agent is frozen at issue."""
    code = await EnrolmentService(session).issue_code(
        number_id, principal.id, _client_ip(request)
    )
    return EnrolmentCodeResponse.model_validate(code)


@assignments_router.patch(
    "/{assignment_id}",
    response_model=AssignmentResponse,
    dependencies=[Depends(require_permission(Perm.NUMBERS_WRITE))],
)
async def close_assignment(
    assignment_id: uuid.UUID,
    payload: CloseAssignmentRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> AssignmentResponse:
    """Close a holding period. Calls already attributed keep their agent."""
    assignment = await NumberService(session).close_assignment(
        assignment_id, payload.valid_to, principal.id, _client_ip(request), payload.note
    )
    return AssignmentResponse.model_validate(assignment)
