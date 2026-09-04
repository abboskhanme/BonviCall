"""Command wire schemas (UC-16, SPEC §3.8, §4.6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

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


# --- Realtime frames (SPEC §4.6) -------------------------------------------
# These do not appear in the OpenAPI documents: OpenAPI cannot describe a
# WebSocket. They are exported separately as ``contract/device-ws-frames.json``
# so the Kotlin side is still generated from this file and never hand-written
# (CONVENTIONS.md §1) — an unversioned socket frame on a fleet of phones we
# cannot force-update is exactly the failure the contract rule exists to stop.


class CommandFrameOut(BaseModel):
    """server → app. **Identical in shape to** :class:`DeviceCommandOut`.

    Deliberately so: the app parses one command type whether it arrived on the
    socket or was collected over REST after an FCM wake-up. Two shapes for one
    concept is how the two paths drift and only one of them gets the fix.

    The dial target is a named field, not a ``payload`` map (§8 rule 5).
    """

    type: Literal["command"] = "command"
    command_id: uuid.UUID
    kind: CommandKind
    number: str | None = None
    issued_at: datetime
    expires_at: datetime = Field(
        description="The app discards this on arrival if it has passed (UC-16)."
    )


class PingFrameOut(BaseModel):
    """server → app, every 30 s. No pong within 15 s closes the socket."""

    type: Literal["ping"] = "ping"
    at: datetime


class LogoutFrameOut(BaseModel):
    """server → app: stop using this socket, and why.

    ``replaced`` is the common one and is not an error — the app reconnected
    before the old socket's close was noticed.
    """

    type: Literal["logout"] = "logout"
    reason: Literal["revoked", "replaced", "version_unsupported"]


class AckFrameIn(BaseModel):
    """app → server: the outcome of a command, and implicitly its latency."""

    type: Literal["ack"]
    command_id: uuid.UUID
    status: Literal["acknowledged", "failed"]
    failure_reason: CommandFailureReason | None = None
    at: datetime | None = None
    result_client_call_id: uuid.UUID | None = None


class PresenceFrameIn(BaseModel):
    """app → server: still here, and this much is queued.

    Presence means **reachable**, never healthy. ``is_online`` in the panel is
    driven by ``last_heartbeat_at`` (SPEC §4.6): a socket can be alive while
    capture is dead, and conflating the two is how a broken phone looks fine.
    """

    type: Literal["presence"]
    state: Literal["online", "away"]
    queue_records: int | None = Field(default=None, ge=0)
    at: datetime | None = None


class PongFrameIn(BaseModel):
    """app → server, answering a ping."""

    type: Literal["pong"]
    at: datetime | None = None


#: Everything the app is allowed to say on the socket. A frame that is not one
#: of these is a protocol error and closes the connection — the allow-list is
#: the schema, on this channel exactly as on the REST one (§8 rule 5).
DeviceFrameIn = Annotated[
    AckFrameIn | PresenceFrameIn | PongFrameIn, Field(discriminator="type")
]

#: Parses an inbound frame, or raises ``ValidationError``. Built once: a
#: ``TypeAdapter`` per frame would rebuild the schema on every heartbeat.
DEVICE_FRAME_ADAPTER: TypeAdapter[AckFrameIn | PresenceFrameIn | PongFrameIn] = (
    TypeAdapter(DeviceFrameIn)
)
