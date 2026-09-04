"""Click-to-call and device commands from the panel (T55, UC-16)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status

from src.core.deps import PrincipalDep, SessionDep
from src.core.enums import CommandKind
from src.core.errors import ForbiddenError
from src.core.permissions import Perm, require_any_permission, require_permission
from src.modules.commands.schemas import (
    CommandListResponse,
    CommandResponse,
    CreateCommandRequest,
)
from src.modules.commands.service import CommandService

router = APIRouter(tags=["Commands"])

#: SPEC §4.7 gates dialling on ``commands:dial`` and the rest on
#: ``settings:write``. Both reach this route, so the dependency accepts either
#: and the handler checks which one the *kind* needs — the alternative is two
#: routes doing the same thing.
_command_any = require_any_permission(Perm.COMMANDS_DIAL, Perm.SETTINGS_WRITE)


@router.post(
    "/devices/{installation_id}/commands",
    response_model=CommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(_command_any)],
)
async def issue_command(
    installation_id: uuid.UUID,
    payload: CreateCommandRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> CommandResponse:
    """202: accepted for delivery, not yet done.

    Issuing a command reaches into an employee's personally owned phone, so it
    is audited under ``command_issued`` — the only action in the product that
    acts on hardware the company does not own.
    """
    needed = (
        Perm.COMMANDS_DIAL if payload.kind is CommandKind.DIAL else Perm.SETTINGS_WRITE
    )
    if not principal.has(needed):
        raise ForbiddenError()
    command = await CommandService(session).issue(
        installation_id,
        payload,
        principal.id,
        request.client.host if request.client else None,
    )
    return CommandResponse.model_validate(command)


@router.get(
    "/devices/{installation_id}/commands",
    response_model=CommandListResponse,
    dependencies=[Depends(require_permission(Perm.DEVICES_READ))],
)
async def list_commands(
    installation_id: uuid.UUID, session: SessionDep
) -> CommandListResponse:
    """History with ``latency_ms``, which is how UC-16's bar is measured."""
    items, total = await CommandService(session).list_for(installation_id)
    return CommandListResponse(
        items=[CommandResponse.model_validate(row) for row in items], total=total
    )


@router.get(
    "/commands/{command_id}",
    response_model=CommandResponse,
    dependencies=[Depends(require_permission(Perm.DEVICES_READ))],
)
async def get_command(command_id: uuid.UUID, session: SessionDep) -> CommandResponse:
    """Status, latency and the failure reason — UC-16 requires the reason."""
    return CommandResponse.model_validate(await CommandService(session).get(command_id))
