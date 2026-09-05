"""The service export's wire types (UC-29, SPEC §4.9).

**This is a committed contract**, versioned, and a change to it is a breaking
change for another product. Everything BonviZvonki's pipeline needs is here:
direction, both numbers in its own last-9 key form, timestamps, duration, agent
identity, internal/external, and a stable audio reference.

The types are defined **in this module** on purpose (§2.1 rule 3): what leaves
the service boundary is this module's own schema, never a foreign ORM entity.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from src.core.enums import (
    AppVariant,
    AudioMissingReason,
    CallDirection,
    CallDisposition,
    CallType,
    CaptureRoute,
)
from src.core.wire import Int64

#: Ours -> BonviZvonki's vocabulary, mapped in exactly one place (SPEC §3.1).
BONVIZVONKI_DIRECTION = {
    CallDirection.INCOMING: "inbound",
    CallDirection.OUTGOING: "outbound",
}


class ExportAgentOut(BaseModel):
    id: uuid.UUID
    full_name: str


class ExportCallOut(BaseModel):
    """One call, in the shape release 2 consumes."""

    id: uuid.UUID
    seq: Int64 = Field(description="The cursor. Monotonic, server-assigned.")
    agent: ExportAgentOut
    agent_number_e164: str
    agent_number_key: str = Field(description="Last 9 digits — their join key too (N37).")
    remote_number_e164: str | None
    remote_number_key: str | None
    direction: CallDirection
    bonvizvonki_direction: str = Field(
        description="Their vocabulary, mapped here so ours never leaks into theirs."
    )
    disposition: CallDisposition
    answered: bool
    call_type: CallType
    started_at: datetime
    answered_at: datetime | None
    ended_at: datetime | None
    duration_sec: int
    received_at: datetime
    has_audio: bool
    audio_missing_reason: AudioMissingReason | None
    audio_ref: str | None = Field(
        description="A stable reference, never a public URL (N20, §5.4)."
    )
    audio_sha256: str | None
    audio_duration_ms: int | None
    capture_route: CaptureRoute | None
    app_variant: AppVariant


class ExportCallsResponse(BaseModel):
    """``seq ASC`` with a settling window, so two full passes agree (UC-29)."""

    items: list[ExportCallOut]
    next_since: Int64
    count: int


class ExportNumberPeriodOut(BaseModel):
    """One line an agent held, and when."""

    e164: str
    key: str
    valid_from: datetime
    valid_to: datetime | None


class ExportAgentDetailOut(BaseModel):
    """An agent plus their number history.

    Needed because BonviZvonki's L3 failure was exactly this mapping arriving
    wrong — a single ``agents.phone`` column cannot express a handover.
    """

    id: uuid.UUID
    full_name: str
    is_active: bool
    numbers: list[ExportNumberPeriodOut]


class ExportAgentsResponse(BaseModel):
    items: list[ExportAgentDetailOut]
    count: int
