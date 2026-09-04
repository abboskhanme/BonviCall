"""Command collection and acknowledgement (UC-16, SPEC §4.6).

The socket and the FCM wake-up are the *transport*; this is the fallback and
the lifecycle. A phone that polls here after a wake-up gets the same answer it
would have got on the socket, which is why the lifecycle could be built and
tested before the socket exists.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from src.api.device.deps import ActiveInstallationDep
from src.core import clock
from src.core.deps import SessionDep
from src.modules.commands.schemas import (
    DeviceAckIn,
    DeviceCommandListOut,
    DeviceCommandOut,
)
from src.modules.commands.service import CommandService

router = APIRouter(prefix="/commands", tags=["Device commands"])


@router.get("", response_model=DeviceCommandListOut)
async def pending_commands(
    installation: ActiveInstallationDep, session: SessionDep
) -> DeviceCommandListOut:
    """Anything the phone should act on now. Expired commands are not returned."""
    commands = await CommandService(session).pending_for(installation)
    return DeviceCommandListOut(
        commands=[
            DeviceCommandOut(
                command_id=command.id,
                kind=command.kind,
                number=(command.payload or {}).get("number"),
                issued_at=command.created_at,
                expires_at=command.expires_at,
            )
            for command in commands
        ],
        server_time=clock.now(),
    )


@router.post("/{command_id}/ack", response_model=DeviceCommandListOut)
async def acknowledge(
    command_id: uuid.UUID,
    payload: DeviceAckIn,
    installation: ActiveInstallationDep,
    session: SessionDep,
) -> DeviceCommandListOut:
    """Record the outcome and the latency.

    Returns whatever else is pending, so an app that just acknowledged a dial
    does not need a second round trip to find the next command.
    """
    service = CommandService(session)
    await service.acknowledge(installation, command_id, payload)
    commands = await service.pending_for(installation)
    return DeviceCommandListOut(
        commands=[
            DeviceCommandOut(
                command_id=command.id,
                kind=command.kind,
                number=(command.payload or {}).get("number"),
                issued_at=command.created_at,
                expires_at=command.expires_at,
            )
            for command in commands
        ],
        server_time=clock.now(),
    )
