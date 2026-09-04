"""Device health for the panel (UC-17, T36's read half).

**The list narrows by scope, exactly as ``/calls`` does.** SPEC §5.2 gated the
list on ``devices:read`` and the detail on ``devices:read | devices:read:own``,
which left a ``sales`` user with a page they could open and no list that led to
it. The project's own rule settles it: scope is narrowed by the *query*, not by
the permission. A salesperson gets a one-row list — their own phone's health,
which answers the question they actually have ("is my phone still reporting?").
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from src.core.deps import PrincipalDep, SessionDep
from src.core.permissions import Perm, require_any_permission
from src.modules.devices.schemas import DeviceHealthListResponse, DeviceHealthResponse
from src.modules.devices.service import DeviceService

router = APIRouter(prefix="/devices", tags=["Devices"])

_read_any = require_any_permission(Perm.DEVICES_READ, Perm.DEVICES_READ_OWN)


@router.get("", response_model=DeviceHealthListResponse, dependencies=[Depends(_read_any)])
async def list_devices(
    principal: PrincipalDep, session: SessionDep
) -> DeviceHealthListResponse:
    """Every device the caller may see, most recently heard from first."""
    rows = await DeviceService(session).list(principal)
    return DeviceHealthListResponse(
        items=[DeviceHealthResponse.model_validate(row) for row in rows],
        total=len(rows),
    )


@router.get(
    "/{installation_id}",
    response_model=DeviceHealthResponse,
    dependencies=[Depends(_read_any)],
)
async def get_device(
    installation_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> DeviceHealthResponse:
    """One device. Another agent's phone is 404, like every other scoped read."""
    row = await DeviceService(session).get(principal, installation_id)
    return DeviceHealthResponse.model_validate(row)
