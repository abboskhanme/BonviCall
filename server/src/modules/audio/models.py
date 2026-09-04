"""Audio ORM models (SPEC §3.6, §3.11).

``storage_key`` is a path **relative to the storage root**, never a URL, so the
whole tree can be moved — or swapped for S3 — without a data migration. Nothing
outside this module may open an audio file by path; that is the seam D-01
depends on.

Deletion keeps the row: the retention job sets ``deleted_at`` and
``deleted_reason`` and removes the blob, so "there was a recording and it
expired" stays answerable and playback returns 410 rather than a 500 (UC-26).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UUIDMixin
from src.core.enums import (
    AudioCodec,
    AudioContainer,
    CaptureRoute,
    UploadStatus,
    pg_enum,
)

#: ``call_audio.deleted_reason`` — a closed pair, kept as VARCHAR per SPEC §3.6.
DELETED_REASON_RETENTION = "retention"
DELETED_REASON_REVOCATION = "revocation"


class CallAudioModel(Base, UUIDMixin, TimestampMixin):
    """One stored recording, at most one per call."""

    __tablename__ = "call_audio"

    call_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        doc="One recording per call, enforced here rather than assumed.",
    )
    storage_key: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        doc="Path inside the storage root: calls/<yyyy>/<mm>/<dd>/<call_id>.<ext>.",
    )
    bytes: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        doc="File size, for the storage report.",
    )
    sha256: Mapped[str] = mapped_column(
        sa.CHAR(64),
        nullable=False,
        doc=(
            "Whole-file checksum. The device deletes its local copy only after we confirm it (N11)."
        ),
    )
    codec: Mapped[AudioCodec] = mapped_column(
        pg_enum(AudioCodec, "audio_codec"),
        nullable=False,
        doc=(
            "opus, or the declared aac_lc fallback — which is counted, because a fleet quietly on "
            "the fallback is a fact M0 should have caught."
        ),
    )
    container: Mapped[AudioContainer] = mapped_column(
        pg_enum(AudioContainer, "audio_container"),
        nullable=False,
        doc="ogg | mp4, pairs with the codec.",
    )
    sample_rate_hz: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc="Target 16 kHz (N17).",
    )
    channels: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True, doc="Target mono.")
    bitrate_bps: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc="Target <= 24 kbps.",
    )
    duration_ms: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc="Compared with calls.duration_sec; a gap > 2 s flags the call.",
    )
    capture_route: Mapped[CaptureRoute] = mapped_column(
        pg_enum(CaptureRoute, "capture_route"),
        nullable=False,
        doc="Which strategy produced it. The M0 baseline and the panel both read this.",
    )
    capture_route_detail: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        doc=(
            "The folder *name* only, e.g. 'Recordings/Call' — never a full path "
            "from the employee's phone."
        ),
    )
    recorded_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc="Device time the file was written; checked against the call window.",
    )
    uploaded_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Server time of the commit."
    )
    upload_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), nullable=True, doc="Which upload session produced it."
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc="Blob removed; the row stays so 410 is answerable.",
    )
    deleted_reason: Mapped[str | None] = mapped_column(
        sa.String(16), nullable=True, doc="retention | revocation."
    )

    __table_args__ = (
        sa.CheckConstraint(
            "deleted_reason IS NULL OR deleted_reason IN ('retention', 'revocation')",
            name="deleted_reason_known",
        ),
        sa.Index(
            "ix_call_audio_live",
            "deleted_at",
            postgresql_where=sa.text("deleted_at IS NULL"),
        ),
        sa.Index("ix_call_audio_route", "capture_route"),
    )


class AudioUploadSessionModel(Base, UUIDMixin, TimestampMixin):
    """Resumable upload state (SPEC §4.5).

    Keyed on ``client_call_id``, not on the server id, so a device can start
    uploading before it has seen a response. Re-opening returns the existing
    session with its true ``received_bytes`` — that is the resume path after an
    app restart, and it is why the unique index is partial on ``status='open'``.
    """

    __tablename__ = "audio_upload_sessions"

    installation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("installations.id", ondelete="CASCADE"),
        nullable=False,
        doc="Whose upload.",
    )
    client_call_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), nullable=False, doc="The device's own key for the call."
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=True,
        doc="Resolved at session creation. Metadata lands before audio, always (R7).",
    )
    bytes_total: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        doc="Declared file size.",
    )
    chunk_size: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, doc="Server-chosen; the client always obeys it."
    )
    received_bytes: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        server_default=sa.text("0"),
        doc="The resume offset. A mismatched chunk offset is a 409 carrying this value.",
    )
    sha256_expected: Mapped[str] = mapped_column(
        sa.CHAR(64), nullable=False, doc="Verified at commit before anything is stored."
    )
    codec: Mapped[AudioCodec] = mapped_column(
        pg_enum(AudioCodec, "audio_codec"),
        nullable=False,
        doc="Declared codec.",
    )
    container: Mapped[AudioContainer] = mapped_column(
        pg_enum(AudioContainer, "audio_container"), nullable=False, doc="Declared container."
    )
    duration_ms: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True, doc="Declared duration; checked against the call window."
    )
    capture_route: Mapped[CaptureRoute] = mapped_column(
        pg_enum(CaptureRoute, "capture_route"),
        nullable=False,
        doc="Which strategy produced the file.",
    )
    recorded_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc=(
            "Must overlap [started_at - 5 s, ended_at + 120 s] or the session is refused (N28, "
            "T44)."
        ),
    )
    part_path: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, doc="Relative path of the .part file the sweeper deletes."
    )
    status: Mapped[UploadStatus] = mapped_column(
        pg_enum(UploadStatus, "upload_status"),
        nullable=False,
        server_default=UploadStatus.OPEN.value,
        doc="open | committed | expired | aborted.",
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        doc="created + upload.session_ttl_days. Past it the call's reason becomes upload_expired.",
    )
    last_chunk_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Progress marker for the sweeper."
    )

    __table_args__ = (
        sa.Index(
            "uq_audio_sessions_open",
            "installation_id",
            "client_call_id",
            unique=True,
            postgresql_where=sa.text("status = 'open'"),
        ),
        sa.Index("ix_audio_sessions_sweep", "status", "expires_at"),
    )


class StorageUsageDailyModel(Base, TimestampMixin):
    """Daily storage totals (N18).

    No ``UUIDMixin``: one row per day, so the date is the key. Written by the
    nightly job so the panel can show "GB now + 30-day growth" without a ``du``
    over 200 GB.
    """

    __tablename__ = "storage_usage_daily"

    period_date: Mapped[date] = mapped_column(
        sa.Date, primary_key=True, doc="Asia/Tashkent calendar date."
    )
    audio_bytes_total: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        server_default=sa.text("0"),
        doc="Total stored at the end of the day.",
    )
    audio_files: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0"), doc="File count."
    )
    bytes_added: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        server_default=sa.text("0"),
        doc="Growth, for the 250 GB projection.",
    )
    bytes_deleted: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        server_default=sa.text("0"),
        doc="Removed by retention that day.",
    )
