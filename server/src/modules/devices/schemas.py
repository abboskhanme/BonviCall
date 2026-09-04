"""Device health and telemetry wire schemas (UC-17, SPEC §3.7, §4.4, §4.7)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from src.core.enums import (
    AppVariant,
    AudioMissingReason,
    Capability,
    CapabilityState,
    CaptureRoute,
    InstallationStatus,
    NetworkType,
)


class DeviceHealthResponse(BaseModel):
    """Every UC-17 field, plus the identity the panel needs to name a person."""

    model_config = ConfigDict(from_attributes=True)

    installation_id: uuid.UUID
    agent_id: uuid.UUID
    number_id: uuid.UUID
    installation_status: InstallationStatus
    manufacturer: str | None
    model: str | None
    android_release: str | None
    api_level: int | None
    app_version: str | None
    app_variant: AppVariant | None

    never_reported: bool = Field(
        description=(
            "Bound and never sent a heartbeat. Kept distinct from "
            "``is_online: false`` because the next action differs: never "
            "started is a person waiting for help right now; worked once and "
            "stopped is a phone in a lift or a battery manager to argue with."
        )
    )
    last_heartbeat_at: datetime | None
    last_call_at: datetime | None
    is_online: bool = Field(
        description=(
            "Derived, never stored: last_heartbeat_at is inside the "
            "alerts.device_offline_minutes window. Storing it would need a job "
            "to keep it false, and it would be wrong between runs."
        )
    )
    ws_connected: bool | None = Field(
        default=None,
        description=(
            "Shown separately from is_online on purpose: a socket can be alive "
            "while capture is dead, and conflating the two is how a broken "
            "phone looks fine."
        ),
    )

    battery_level: int | None
    battery_charging: bool | None
    battery_optimisation_exempt: bool | None
    power_save_mode: bool | None
    free_storage_bytes: int | None
    queue_records: int | None
    queue_bytes: int | None
    queue_oldest_at: datetime | None
    parked_records: int | None
    clock_skew_sec: int | None
    device_timezone: str | None
    network_type: NetworkType | None
    cellular_bytes_month: int | None
    service_running: bool | None
    capture_enabled: bool | None
    recording_route: CaptureRoute | None
    recording_route_ok: bool | None
    updated_at: datetime | None


class DeviceHealthListResponse(BaseModel):
    items: list[DeviceHealthResponse]
    total: int


class CapabilityStateResponse(BaseModel):
    """One capability's current state, as the panel's matrix renders it."""

    model_config = ConfigDict(from_attributes=True)

    capability: Capability
    state: CapabilityState
    checked_at: datetime
    changed_at: datetime
    detail: str | None


class DeviceDetailResponse(DeviceHealthResponse):
    """Device health plus its capability matrix (UC-17's device page)."""

    capabilities: list[CapabilityStateResponse] = Field(
        default_factory=list,
        description="Empty for a phone that has never reported — not missing.",
    )
    capturing: bool = Field(
        default=False,
        description=(
            "UC-03's never-false-ready rule: every required capability working, "
            "a verified installation and a live service. One function computes "
            "it, so the phone and the panel cannot disagree."
        ),
    )


# --- Device ingest ----------------------------------------------------------


class DeviceHeartbeatIn(BaseModel):
    """``POST /api/device/v1/heartbeat`` — every 120 s while the service lives."""

    device_epoch_ms: int = Field(description="Raw device clock; the skew evidence (N36).")
    device_timezone: str = Field(max_length=64)
    device_rtt_ms: int | None = Field(default=None, ge=0)
    app_version: str | None = Field(default=None, max_length=20)
    app_variant: AppVariant | None = None
    api_level: int | None = Field(default=None, ge=21, le=99)
    battery_level: int | None = Field(default=None, ge=0, le=100)
    battery_charging: bool | None = None
    battery_optimisation_exempt: bool | None = Field(
        default=None,
        description="isIgnoringBatteryOptimizations(). False is the usual cause of a dead service.",
    )
    power_save_mode: bool | None = None
    free_storage_bytes: int | None = Field(default=None, ge=0)
    queue_records: int | None = Field(
        default=None,
        ge=0,
        description="Zero is what the stale-version gate waits for (SPEC §4.3).",
    )
    queue_bytes: int | None = Field(default=None, ge=0)
    queue_oldest_at: datetime | None = None
    parked_records: int | None = Field(default=None, ge=0)
    network_type: NetworkType | None = None
    cellular_bytes_month: int | None = Field(default=None, ge=0)
    service_running: bool | None = None
    capture_enabled: bool | None = None
    recording_route: CaptureRoute | None = None
    recording_route_ok: bool | None = None
    ws_connected: bool | None = None
    pending_commands_seen: int | None = Field(default=None, ge=0)


class UpdateBlockOut(BaseModel):
    """Carried on every device response (SPEC §4.3).

    The app keeps capturing and draining while ``required`` is true; it blocks
    only new enrolment actions. Refusing an old version must never destroy data.
    """

    required: bool
    min_version_code: int
    latest_version: str | None = None
    latest_version_code: int | None = None
    apk_url: str | None = None
    message_uz: str | None = None


class DeviceHeartbeatOut(BaseModel):
    """``server_time`` lets the app compute skew without an extra round trip."""

    server_time: datetime
    clock_skew_sec: int
    config_hash: str | None = Field(
        default=None, description="The app re-fetches config only when this changes."
    )
    pending_command_count: int = 0
    update: UpdateBlockOut


class DeviceCapabilityIn(BaseModel):
    """One capability report. The result of *exercising* it, never a flag read."""

    capability: Capability
    state: CapabilityState
    checked_at: datetime
    detail: str | None = Field(
        default=None,
        max_length=255,
        description="What the check saw, e.g. '1s test capture 32 kB'.",
    )


class DeviceCapabilityBatchIn(BaseModel):
    """``POST /api/device/v1/capabilities``."""

    capabilities: list[DeviceCapabilityIn] = Field(min_length=1, max_length=32)


class DeviceCapabilityBatchOut(BaseModel):
    """Alerts are raised inside this request, so the 10-minute bound of UC-06
    is a device-reporting-interval question and not a server-latency one."""

    accepted: int
    transitions: int
    alerts_raised: int
    server_time: datetime


class DeviceCallLogDeltaIn(BaseModel):
    """``POST /api/device/v1/call-log-delta`` — the production rig (§4.1 B).

    Without this, capture rate becomes unverifiable the day the acceptance
    window ends: there is no adb on a phone Bonvi does not own.
    """

    period_date: date = Field(description="Asia/Tashkent calendar date.")
    device_counted: int = Field(ge=0, description="Rows the device saw in its own log.")
    uploaded_count: int = Field(ge=0)
    subscription_unknown_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Calls the OS could not attribute to a subscription. Reported "
            "separately and never folded into either side of the rate — that is "
            "the fail-closed rule made visible."
        ),
    )
    swept_at: datetime | None = None


class DeviceCallLogDeltaOut(BaseModel):
    period_date: date
    device_counted: int
    uploaded_count: int
    delta: int
    server_time: datetime


class DeviceEventDetailIn(BaseModel):
    """The **only** context a device event may carry (§8 rule 5, §15).

    Every field is named here, and that is the whole point: the wire schema is
    the allow-list, so a field the contract does not name cannot leave the
    phone. An open map — even one whose *values* are typed — leaves the *keys*
    unconstrained, and the handset belongs to the employee.

    ``CONVENTIONS.md`` §8 enforces the same boundary on the Android side with a
    type signature (``OemHarvestStrategy.locate(Decision.Capture, …)``) so that
    it cannot be widened in one line. This is the other end of the same pipe,
    and adding a field here shows up as a diff in ``contract/``.

    All optional: one event kind uses two of these, another uses none.
    """

    model_config = ConfigDict(extra="forbid")

    # queue_full, storage_low (N8, N10)
    queue_records: int | None = Field(default=None, ge=0)
    queue_bytes: int | None = Field(default=None, ge=0)
    free_storage_bytes: int | None = Field(default=None, ge=0)

    # poisoned_record (N9)
    client_call_id: uuid.UUID | None = Field(
        default=None, description="Which queued record was parked."
    )
    attempts: int | None = Field(default=None, ge=0)

    # recording_route_lost, oem_recorder_missing (S1, UC-18)
    capture_route: CaptureRoute | None = None

    # attribution_discarded (N28) — a rising count means the harvest window is
    # mistuned, which is the difference between a bug and a privacy incident.
    discarded_count: int | None = Field(default=None, ge=0)
    audio_missing_reason: AudioMissingReason | None = None

    # app_updated, capture_toggled_off, revocation_completed
    from_version: str | None = Field(default=None, max_length=20)
    to_version: str | None = Field(default=None, max_length=20)
    by_user: bool | None = Field(
        default=None, description="Whether the employee did it, or the OS did."
    )
    deleted_records: int | None = Field(default=None, ge=0)
    deleted_bytes: int | None = Field(default=None, ge=0)


class DeviceEventIn(BaseModel):
    """``POST /api/device/v1/events`` — device events that are not calls."""

    kind: str = Field(
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]{2,63}$",
        description=(
            "One of the names in SPEC §4.4. Unknown names are accepted on "
            "purpose — an event we do not understand raises 'info' rather than "
            "being dropped — but the shape is constrained to a lower-case "
            "identifier: an unbounded free-text field is itself a way off the "
            "phone."
        ),
    )
    at: datetime | None = None
    detail: DeviceEventDetailIn | None = Field(
        default=None, description="Named fields only; see DeviceEventDetailIn."
    )


class DeviceEventBatchIn(BaseModel):
    events: list[DeviceEventIn] = Field(min_length=1, max_length=50)


class DeviceEventBatchOut(BaseModel):
    accepted: int
    alerts_raised: int
    server_time: datetime
