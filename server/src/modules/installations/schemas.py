"""Installation wire schemas (SPEC §3.4, §4.7)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.core.enums import (
    AppVariant,
    FunnelStage,
    InstallationStatus,
    VerificationMethod,
)
from src.core.wire import Int64


class InstallationResponse(BaseModel):
    """One installation, as the panel reads it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number_id: uuid.UUID
    agent_id: uuid.UUID
    device_id: uuid.UUID
    status: InstallationStatus
    verification_method: VerificationMethod | None
    verified_at: datetime | None
    attest_reason: str | None
    bound_at: datetime | None
    replaced_at: datetime | None
    revoked_at: datetime | None
    revoke_confirmed_at: datetime | None
    revoke_pending_records: int | None
    revoke_pending_bytes: Int64 | None
    app_version: str | None
    app_variant: AppVariant | None
    sim_subscription_id: int | None
    sim_slot: int | None
    funnel_stage: FunnelStage
    funnel_changed_at: datetime
    created_at: datetime


class InstallationListResponse(BaseModel):
    items: list[InstallationResponse]
    total: int


class AttestRequest(BaseModel):
    """``POST /api/v1/installations/{id}/attest`` (T142).

    Attestation is deliberately weaker evidence than a proven binding, and the
    reason is mandatory: an unexplained attestation is indistinguishable from a
    mistake six months later.
    """

    reason: str = Field(min_length=3, max_length=255)


class RevokeRequest(BaseModel):
    """``POST /api/v1/installations/{id}/revoke`` (UC-08)."""

    reason: str | None = Field(default=None, max_length=255)


class RevokeResponse(BaseModel):
    """What was still queued when contact was lost.

    Bonvi does not own the handset, so a revoke that claims a completed wipe
    would be lying. ``revoke_confirmed_at`` stays NULL until the phone comes
    back and says the local audio is gone.
    """

    installation_id: uuid.UUID
    status: InstallationStatus
    revoked_at: datetime
    pending_records: int | None
    pending_bytes: Int64 | None
    confirmed: bool
