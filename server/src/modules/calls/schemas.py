"""Call wire schemas (SPEC §4.4, §4.7).

Device schemas are ``Device<Noun>In`` / ``Device<Noun>Out`` (§12) and are part
of a contract with phones we cannot force-update: inside v1 they may only gain
**optional** fields with server-side defaults.

There is no free-form map anywhere below. A field the contract does not name
cannot leave the handset (§8 rule 5).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.enums import (
    AppVariant,
    AudioMissingReason,
    CallDirection,
    CallDisposition,
    CallSource,
    CallType,
    CaptureRoute,
)
from src.modules.calls.rules import is_valid_combination

#: SPEC §4.0: a call batch is 50 items or 256 KiB, whichever comes first.
MAX_CALL_BATCH = 50


class DeviceCallIn(BaseModel):
    """One call as the handset reports it."""

    client_call_id: uuid.UUID = Field(
        description=(
            "UUIDv5 the device derives from call-log facts that survive a "
            "reinstall (SPEC §3.10). The idempotency key: a replay returns the "
            "same server id and creates no second row."
        )
    )
    direction: CallDirection
    disposition: CallDisposition
    remote_number: str | None = Field(
        default=None,
        max_length=32,
        description="As the device saw it. NULL when the caller withheld it.",
    )
    contact_name: str | None = Field(
        default=None,
        max_length=255,
        description="Resolved on-device. Decoration, never identity (L3).",
    )
    started_at: datetime = Field(description="ISO-8601 with an explicit offset (N36).")
    answered_at: datetime | None = Field(
        default=None, description="NULL means there was never a conversation (UC-09)."
    )
    ended_at: datetime | None = None
    duration_sec: int = Field(
        default=0, ge=0, description="Whole seconds, truncated not rounded."
    )
    ring_sec: int | None = Field(default=None, ge=0)
    sim_subscription_id: int | None = Field(
        default=None,
        description="The registered subscription only — Guard 1 refused the rest.",
    )
    sim_slot: int | None = Field(default=None, ge=0, le=8)
    source: CallSource = CallSource.LIVE_CAPTURE
    reconciled_with_call_log: bool = False
    audio_expected: bool = Field(
        default=False, description="Whether the device will follow up with audio."
    )
    audio_missing_reason: AudioMissingReason | None = Field(
        default=None,
        description="From the closed enum, never free text (N5). NULL lets the server decide.",
    )
    capture_route: CaptureRoute | None = Field(
        default=None, description="Which strategy produced (or failed to produce) audio."
    )
    command_id: uuid.UUID | None = Field(
        default=None, description="Set when this call answered a click-to-call command."
    )
    device_epoch_ms: int = Field(
        description="System.currentTimeMillis() at call start — raw evidence for skew."
    )
    device_timezone: str = Field(max_length=64, description="IANA name.")
    device_rtt_ms: int | None = Field(
        default=None, ge=0, description="The client's round-trip estimate, for skew."
    )
    app_version: str | None = Field(default=None, max_length=20)
    app_variant: AppVariant | None = None


    @model_validator(mode="after")
    def _direction_matches_disposition(self) -> DeviceCallIn:
        """Refuse a combination the database would refuse anyway (UC-11).

        Without this the row reaches ``ck_calls_direction_disposition`` and the
        request 500s — which a device treats as "server broken, retry" and it
        retries the same impossible record forever. A 422 names the field and
        the item, so the app can park the record instead (N9).
        """
        if not is_valid_combination(self.direction.value, self.disposition.value):
            raise ValueError(
                f"disposition {self.disposition.value!r} is impossible for a "
                f"{self.direction.value} call"
            )
        return self


class DeviceCallBatchIn(BaseModel):
    """``POST /api/device/v1/calls``."""

    calls: list[DeviceCallIn] = Field(min_length=1, max_length=MAX_CALL_BATCH)


class DeviceCallErrorOut(BaseModel):
    """The error half of a per-item result."""

    code: str
    message: str


class DeviceCallResultOut(BaseModel):
    """One item's outcome.

    Failure is **per item, not per batch**: a batch that fails wholesale is a
    batch the device will retry forever (SPEC §4.4 rule 6).
    """

    client_call_id: uuid.UUID
    id: uuid.UUID | None = Field(
        default=None, description="The server id. Same value on every replay."
    )
    status: Literal["created", "unchanged", "updated", "failed"]
    audio_upload: Literal["required", "not_expected", "already_present"] | None = None
    error: DeviceCallErrorOut | None = None


class DeviceCallBatchOut(BaseModel):
    """``200`` for the batch, whatever happened to the individual items."""

    results: list[DeviceCallResultOut]
    server_time: datetime = Field(
        description="So the app can compute skew without an extra round trip."
    )


class CallAudioSummary(BaseModel):
    """What the call list and the detail page need to know about the audio.

    ``capture_route`` is here and not folded into "audio: yes/no" because
    ``S1-RECORDING.md`` is explicit that ``app_voice_recognition`` and
    ``app_mic`` must stay distinguishable: the per-model capture rate is the M0
    baseline, and UC-23's regression alert compares against it. Collapsing the
    routes would make "which mechanism actually works on this handset" an
    unanswerable question.
    """

    available: bool = Field(description="Playable now — stored and not yet expired.")
    capture_route: CaptureRoute | None = Field(
        default=None, description="Which strategy produced it (S1, M0, UC-23)."
    )
    capture_route_detail: str | None = Field(
        default=None, description="The folder name only, never a path from the phone."
    )
    audio_missing_reason: AudioMissingReason | None = Field(
        default=None, description="Closed enum, never free text (N5)."
    )
    duration_ms: int | None = None
    duration_mismatch: bool = Field(
        default=False, description="The file's length disagrees with the call log (UC-14)."
    )
    url: str | None = Field(
        default=None,
        description=(
            "Path to stream from, present only when the recording is available. "
            "A path and never a signed or public URL (N20): the endpoint is "
            "token-protected, and the panel reaches it through the Service "
            "Worker bridge because a plain <audio src> cannot send an "
            "Authorization header (T153, N43)."
        ),
    )
    expired_at: datetime | None = Field(
        default=None, description="Removed by retention; playback answers 410 (UC-26)."
    )


class CallResponse(BaseModel):
    """A call as the panel reads it.

    Carries the display fields, not only ids. Making the browser look up an
    agent's name per row is the N+1 problem relocated to the client, and the
    ``device_model`` filter would otherwise exist server-side for a column the
    panel cannot show.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seq: int
    agent_id: uuid.UUID
    number_id: uuid.UUID
    installation_id: uuid.UUID
    direction: CallDirection
    disposition: CallDisposition
    call_type: CallType
    remote_number: str | None
    remote_number_key: str | None
    contact_name: str | None
    started_at: datetime
    answered_at: datetime | None
    ended_at: datetime | None
    duration_sec: int
    ring_sec: int | None
    received_at: datetime = Field(description="Authoritative for ordering (N36).")
    clock_skew_sec: int
    device_timezone: str
    source: CallSource
    reconciled_with_call_log: bool
    has_audio: bool
    audio_missing_reason: AudioMissingReason | None
    audio_duration_mismatch: bool
    note: str | None
    app_version: str
    app_variant: AppVariant

    # --- Display fields, denormalised into the payload on purpose ---------
    agent_name: str = Field(description="Resolved server-side; the panel renders it.")
    number_e164: str = Field(description="The registered line the call happened on.")
    device_model: str | None = Field(
        default=None, description="'Xiaomi Redmi Note 12'. The device_model filter needs it."
    )
    audio: CallAudioSummary


class CallListResponse(BaseModel):
    """A cursor page of calls (SPEC §4.0).

    ``total`` is computed only when the caller asks: a COUNT(*) over a filtered
    500k table is affordable once per filter change and not once per page.
    """

    items: list[CallResponse]
    next_cursor: str | None
    has_more: bool
    total: int | None = None


class CallFilters(BaseModel):
    """Every filter of SPEC §4.7, and every one of them indexed.

    A filter with no index is a filter that works at 5,000 rows and stops
    working at 500,000, which is the volume UC-19 sizes for.
    """

    agent_id: list[uuid.UUID] | None = None
    number_id: list[uuid.UUID] | None = None
    installation_id: uuid.UUID | None = None
    direction: CallDirection | None = None
    disposition: CallDisposition | None = None
    call_type: CallType | None = None
    has_audio: bool | None = None
    audio_missing_reason: list[AudioMissingReason] | None = None
    capture_route: list[CaptureRoute] | None = None
    date_from: date | None = Field(
        default=None, description="Asia/Tashkent calendar date, inclusive (D-10)."
    )
    date_to: date | None = Field(
        default=None, description="Asia/Tashkent calendar date, inclusive."
    )
    remote_number: str | None = Field(
        default=None,
        max_length=32,
        description="Matched on the 9-digit key, so any format finds the same calls.",
    )
    q: str | None = Field(
        default=None, max_length=100, description="Contact name; metacharacters escaped."
    )
    min_duration_sec: int | None = Field(default=None, ge=0)
    max_duration_sec: int | None = Field(default=None, ge=0)
    device_model: str | None = Field(default=None, max_length=96)
    app_variant: AppVariant | None = None


class UpdateCallNoteRequest(BaseModel):
    """``PATCH /api/v1/calls/{id}`` — the note and nothing else."""

    note: str | None = Field(default=None, max_length=4000)
