"""Audio wire schemas (SPEC §4.5, §4.8)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.core.enums import AudioCodec, AudioContainer, CaptureRoute, UploadStatus


class OpenUploadIn(BaseModel):
    """``POST /calls/{client_call_id}/audio/session`` — step 1 of three."""

    bytes_total: int = Field(gt=0, description="Declared file size.")
    sha256: str = Field(min_length=64, max_length=64)
    codec: AudioCodec
    container: AudioContainer
    sample_rate_hz: int | None = Field(default=None, gt=0)
    channels: int | None = Field(default=None, ge=1, le=2)
    bitrate_bps: int | None = Field(default=None, gt=0)
    duration_ms: int | None = Field(default=None, ge=0)
    capture_route: CaptureRoute
    capture_route_detail: str | None = Field(
        default=None,
        max_length=64,
        description="The folder *name* only, never a path from the phone (§8).",
    )
    recorded_at: datetime = Field(
        description=(
            "When the file was written. Checked against the call's window — a "
            "recording that does not overlap is refused and never stored (N28)."
        )
    )


class OpenUploadOut(BaseModel):
    """``201``, or the **existing** open session — that is the resume path."""

    upload_id: uuid.UUID
    chunk_size: int = Field(description="The client always obeys this value.")
    received_bytes: int = Field(
        description="Resume from here. After an app restart this is not zero."
    )
    expires_at: datetime


class ChunkAcceptedOut(BaseModel):
    """``200`` for an accepted chunk."""

    received_bytes: int


class UploadStatusOut(BaseModel):
    """``GET /audio/{upload_id}`` — the probe (step 4)."""

    upload_id: uuid.UUID
    status: UploadStatus
    received_bytes: int
    bytes_total: int
    expires_at: datetime


class CommitOut(BaseModel):
    """``200``, and **idempotent**: committing twice returns the same body.

    Only after this response does the device delete its local file (N11).
    """

    audio_id: uuid.UUID
    sha256: str
    bytes: int
    stored: bool
    duration_mismatch: bool = Field(
        description="The file's length differs from the call log's by > 2 s (UC-14)."
    )


class CallAudioResponse(BaseModel):
    """Audio metadata for the panel's call detail page."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    call_id: uuid.UUID
    bytes: int
    sha256: str
    codec: AudioCodec
    container: AudioContainer
    duration_ms: int | None
    capture_route: CaptureRoute
    capture_route_detail: str | None
    recorded_at: datetime | None
    uploaded_at: datetime | None
    deleted_at: datetime | None
    deleted_reason: str | None
