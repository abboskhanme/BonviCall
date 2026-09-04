"""Command wire schemas (UC-16, SPEC §3.8, §4.6)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.core.enums import CommandFailureReason, CommandKind, CommandStatus


class CreateCommandRequest(BaseModel):
    """``POST /api/v1/devices/{installation_id}/commands``."""

    kind: CommandKind
    number: str | None = Field(
        default=None,
        max_length=32,
        description="For kind='dial'. Named, not a free-form payload map (§8).",
    )
    reason: str | None = Field(default=None, max_length=255)


class CommandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    installation_id: uuid.UUID
    kind: CommandKind
    status: CommandStatus
    failure_reason: CommandFailureReason | None
    created_at: datetime
    sent_at: datetime | None
    acked_at: datetime | None
    expires_at: datetime
    result_call_id: uuid.UUID | None
    latency_ms: int | None = Field(
        description=(
            "acked_at - created_at, stored so UC-16's five-second bar is "
            "**measured** rather than assumed. R3 flags that bar as possibly "
            "unachievable on doze-restricted OEMs; this column is what turns "
            "that into a conversation with evidence."
        )
    )


class CommandListResponse(BaseModel):
    items: list[CommandResponse]
    total: int


class DeviceCommandOut(BaseModel):
    """A pending command, as the app collects it."""

    command_id: uuid.UUID
    kind: CommandKind
    number: str | None = None
    issued_at: datetime
    expires_at: datetime


class DeviceCommandListOut(BaseModel):
    commands: list[DeviceCommandOut]
    server_time: datetime


class DeviceAckIn(BaseModel):
    """``POST /api/device/v1/commands/{id}/ack``."""

    status: str = Field(pattern="^(acknowledged|failed)$")
    failure_reason: CommandFailureReason | None = None
    at: datetime | None = None
    result_client_call_id: uuid.UUID | None = Field(
        default=None, description="The call the dial produced, if it produced one."
    )
