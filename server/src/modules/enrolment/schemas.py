"""Enrolment and verification wire schemas (SPEC §4.2, §4.7)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.core.enums import (
    AppVariant,
    EnrolmentAttemptKind,
    EnrolmentOutcome,
    InstallationStatus,
    ReceiverStatus,
    VerificationMethod,
    VerificationState,
)
from src.core.wire import Int64


class IssueCodeRequest(BaseModel):
    """``POST /api/v1/numbers/{id}/enrolment-code``."""

    note: str | None = Field(default=None, max_length=255)


class EnrolmentCodeResponse(BaseModel):
    """The code plus everything the admin has to pass on."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    number_id: uuid.UUID
    agent_id: uuid.UUID
    expires_at: datetime
    redeemed_at: datetime | None
    revoked_at: datetime | None
    attempt_count: int
    created_at: datetime


class EnrolmentCodeListResponse(BaseModel):
    items: list[EnrolmentCodeResponse]
    total: int


class EnrolmentAttemptResponse(BaseModel):
    """Where UC-01's failures appear, with timestamps."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: EnrolmentAttemptKind
    outcome: EnrolmentOutcome
    number_id: uuid.UUID | None
    installation_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    step: str | None
    duration_ms: int | None
    app_version: str | None
    device_model: str | None
    created_at: datetime


class EnrolmentAttemptListResponse(BaseModel):
    items: list[EnrolmentAttemptResponse]
    total: int


# --- Device side ------------------------------------------------------------


class DeviceInfoIn(BaseModel):
    """The handset, as it describes itself. No raw hardware identifier."""

    manufacturer: str = Field(max_length=64)
    model: str = Field(max_length=96)
    marketing_name: str | None = Field(default=None, max_length=96)
    android_release: str = Field(max_length=16)
    api_level: int = Field(ge=21, le=99)
    build_fingerprint_hash: str = Field(
        min_length=64, max_length=64, description="sha256 of Build.FINGERPRINT."
    )


class AppInfoIn(BaseModel):
    version: str = Field(max_length=20)
    version_code: int = Field(ge=1)
    variant: AppVariant


class DeviceRedeemIn(BaseModel):
    """``POST /api/device/v1/enrolment/redeem`` — public, rate-limited."""

    code: str = Field(min_length=4, max_length=16)
    device: DeviceInfoIn
    app: AppInfoIn
    device_fingerprint: str = Field(min_length=64, max_length=64)
    device_epoch_ms: Int64
    device_timezone: str = Field(max_length=64)
    sim_subscription_id: int | None = None
    sim_slot: int | None = Field(default=None, ge=0, le=8)


class RedeemAgentOut(BaseModel):
    id: uuid.UUID
    full_name: str


class RedeemNumberOut(BaseModel):
    e164: str
    display: str = Field(description="Grouped for reading aloud, e.g. +998 90 111-22-33.")


class RedeemVerificationOut(BaseModel):
    """What the app needs to run screen E5."""

    required: bool
    callback_msisdn: str | None = Field(
        default=None, description="NULL when no receiver is available."
    )
    receiver_status: ReceiverStatus | None = None
    window_seconds: int


class DeviceRedeemOut(BaseModel):
    """``201``. The provisional token is scoped — an unverified phone cannot
    upload a single call (SPEC §4.2)."""

    installation_id: uuid.UUID
    status: InstallationStatus
    provisional_token: str
    expires_in: int
    agent: RedeemAgentOut
    number: RedeemNumberOut
    verification: RedeemVerificationOut
    server_time: datetime


class DeviceMsisdnVerifyIn(BaseModel):
    """``POST /api/device/v1/enrolment/verify/msisdn`` — route 1."""

    line1_number: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "TelephonyManager.getLine1Number(). NULL, empty or fewer than nine "
            "digits is never a match (UC-04) — it is 'I don't know', not 'yes'."
        ),
    )
    subscription_id: int | None = None
    sim_slot: int | None = Field(default=None, ge=0, le=8)
    carrier_name: str | None = Field(default=None, max_length=64)


class DeviceCallbackStartOut(BaseModel):
    """``POST /api/device/v1/enrolment/verify/callback/start`` — route 2."""

    verification_id: uuid.UUID
    callback_msisdn: str
    expires_at: datetime
    poll_after_ms: int = 2000


class IssuedTokensOut(BaseModel):
    """The pair handed over once verification succeeds.

    Named rather than a map because the generated Kotlin DTO is what the app
    reads: a ``Map<String, Any>`` there makes a renamed field a runtime
    ``null`` on a fleet we cannot force-update, which is exactly what
    CONVENTIONS.md §1 generates clients to prevent.
    """

    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"


class DeviceVerificationStatusOut(BaseModel):
    """Polled every two seconds for at most five minutes."""

    state: VerificationState
    failure: EnrolmentOutcome | None = None
    tokens: IssuedTokensOut | None = Field(
        default=None, description="Present only on 'matched'; the full pair."
    )
    status: InstallationStatus | None = None


class DeviceTokenPairOut(BaseModel):
    """Issued once the installation is verified."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    installation_id: uuid.UUID
    status: InstallationStatus
    verification_method: VerificationMethod | None = None
    server_time: datetime


class DeviceRefreshIn(BaseModel):
    """``POST /api/device/v1/auth/refresh``."""

    refresh_token: str


class ReceiverStatusResponse(BaseModel):
    """The banner at the top of the rollout page (SPEC §9.4).

    **If every receiver is down, nobody in the fleet can enrol**, so this is
    the page's most important sentence and it says so before anyone tries. It
    carries a real type for the same reason: an untyped body reaches the
    contract as a free-form map, and the panel then has to parse defensively
    exactly where it can least afford to guess.
    """

    enrolment_possible: bool = Field(
        description="False means the rollout is stopped, not slow."
    )
    receiver_name: str | None = Field(
        default=None, description="Which gateway, for the admin to go and look at."
    )
    receiver_msisdn: str | None = Field(
        default=None, description="The number screen E5 shows the agent."
    )
    status: ReceiverStatus = Field(
        description="up | degraded | down. Down is 5 minutes without a heartbeat."
    )
    active_receivers: int = Field(
        default=0, description="More than one is a configuration change, not code."
    )


class CallbackEventIn(BaseModel):
    """``POST /api/service/v1/callback-events`` — from the receiver (§9.4).

    A heartbeat is an event with no caller, which is why every field below is
    optional: the receiver proves it is alive by posting, not by having seen a
    call.
    """

    caller_e164: str | None = Field(default=None, max_length=32)
    cli_presented: bool = Field(
        default=False,
        description="False means the operator suppressed the number — that is R19.",
    )
    receiver_epoch_ms: Int64 | None = None
    heartbeat: bool = Field(default=False, description="True for a keepalive with no call.")


class CallbackEventOut(BaseModel):
    """What the receiver learns: whether its report matched anything."""

    stored: bool
    matched: bool
    receiver_status: ReceiverStatus
