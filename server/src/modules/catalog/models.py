"""Reference-data ORM models (SPEC §3.8).

Four tables that describe the fleet rather than its traffic: the admin's extra
line-directory rules, the M0 model baseline, the rolling capture-rate window
that is compared against it, and the self-hosted APK channel.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UUIDMixin
from src.core.enums import AppVariant, CaptureRoute, DirectoryRuleKind, pg_enum


class LineDirectoryEntryModel(Base, UUIDMixin, TimestampMixin):
    """The admin's extras for internal/external classification (UC-25).

    The derived half of the directory — every row in ``registered_numbers`` —
    is **not** copied here. It is computed. Copying it is how BonviZvonki's
    directory starved: somebody had to maintain it, and 10 of 33 employees had
    an entry.
    """

    __tablename__ = "line_directory_entries"

    pattern: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        doc="The digits to match, e.g. '700' for the suffix rule '*700'.",
    )
    kind: Mapped[DirectoryRuleKind] = mapped_column(
        pg_enum(DirectoryRuleKind, "directory_rule_kind"),
        nullable=False,
        doc="exact | prefix | suffix.",
    )
    label: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True, doc="What this range is, for the settings screen."
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.true(),
        doc="Deactivating re-runs the reclassify job.",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Which admin added the rule.",
    )

    __table_args__ = (
        sa.UniqueConstraint("pattern", "kind", name="uq_line_directory_entries_pattern_kind"),
    )


class SupportedModelModel(Base, UUIDMixin, TimestampMixin):
    """The M0 baseline as data, not prose (T14, T128).

    Without a stored baseline, "capture is worse than it was" is an opinion.
    """

    __tablename__ = "supported_models"

    manufacturer: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        doc="Build.MANUFACTURER.",
    )
    model: Mapped[str] = mapped_column(sa.String(96), nullable=False, doc="Build.MODEL.")
    api_level: Mapped[int] = mapped_column(sa.Integer, nullable=False, doc="Build.VERSION.SDK_INT.")
    app_variant: Mapped[AppVariant] = mapped_column(
        pg_enum(AppVariant, "app_variant"), nullable=False, doc="Which flavour was measured."
    )
    capture_route: Mapped[CaptureRoute] = mapped_column(
        pg_enum(CaptureRoute, "capture_route"),
        nullable=False,
        doc="Which route worked on this handset.",
    )
    baseline_audio_capture_rate: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(5, 2),
        nullable=True,
        doc=(
            "Percent of answered calls with audio, measured by M0. NUMERIC, "
            "never float: this value is compared against a threshold on three "
            "platforms and float rounds differently on each (§10)."
        ),
    )
    baseline_sample_calls: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc="How many calls the baseline rests on — a rate over 4 calls is noise.",
    )
    measured_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="When M0 measured it."
    )
    is_supported: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.true(),
        doc="False means this handset is uncovered, visibly.",
    )
    callback_verification_ok: Mapped[bool | None] = mapped_column(
        sa.Boolean,
        nullable=True,
        doc="Whether the callback route works on this OEM. NULL = untested (R19's per-OEM half).",
    )
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True, doc="What was observed.")

    __table_args__ = (
        sa.UniqueConstraint(
            "manufacturer", "model", "api_level", "app_variant",
            name="uq_supported_models_identity",
        ),
    )


class ModelCaptureStatModel(Base, UUIDMixin, TimestampMixin):
    """The rolling window the regression alert compares against the baseline (N4).

    Computing this on the fly would be cheap at this volume. It is materialised
    anyway so that "what did the system see on the day it alerted" is still
    answerable six months later.
    """

    __tablename__ = "model_capture_stats"

    manufacturer: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        doc="Build.MANUFACTURER.",
    )
    model: Mapped[str] = mapped_column(sa.String(96), nullable=False, doc="Build.MODEL.")
    api_level: Mapped[int] = mapped_column(sa.Integer, nullable=False, doc="Build.VERSION.SDK_INT.")
    app_variant: Mapped[AppVariant] = mapped_column(
        pg_enum(AppVariant, "app_variant"),
        nullable=False,
        doc="Which flavour these calls came from.",
    )
    window_start: Mapped[date] = mapped_column(
        sa.Date,
        nullable=False,
        doc="Asia/Tashkent date, inclusive.",
    )
    window_end: Mapped[date] = mapped_column(
        sa.Date,
        nullable=False,
        doc="Asia/Tashkent date, inclusive.",
    )
    answered_calls: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
        doc="The denominator: answered calls only.",
    )
    calls_with_audio: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0"), doc="The numerator."
    )
    rate: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(5, 2), nullable=True, doc="Percent. NUMERIC, never float."
    )
    baseline_rate: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(5, 2),
        nullable=True,
        doc="What supported_models held on the day this was computed.",
    )
    delta_pp: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(5, 2), nullable=True, doc="rate - baseline_rate, in percentage points."
    )
    alert_raised: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
        doc="Whether this row triggered the alert.",
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "manufacturer", "model", "api_level", "app_variant", "window_end",
            name="uq_model_capture_stats_window",
        ),
    )


class AppVersionModel(Base, UUIDMixin, TimestampMixin):
    """The self-hosted update channel (N33, N34).

    The app is not distributed through Google Play — Play policy prohibits
    call-recording apps — so the server is the update channel, and the minimum
    supported version is what the stale-client gate reads.
    """

    __tablename__ = "app_versions"

    version: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        doc="Human version, e.g. '1.4.0'.",
    )
    version_code: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, doc="Integer the version gate compares (N34)."
    )
    variant: Mapped[AppVariant] = mapped_column(
        pg_enum(AppVariant, "app_variant"), nullable=False, doc="legacy28 | modern34."
    )
    apk_path: Mapped[str] = mapped_column(
        sa.Text, nullable=False, doc="Path inside the release store, not a URL."
    )
    apk_sha256: Mapped[str] = mapped_column(
        sa.CHAR(64), nullable=False, doc="Computed server-side at upload; shown in the panel."
    )
    size_bytes: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        doc="For the download page.",
    )
    min_api_level: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("26"), doc="N32's floor: Android 8.0."
    )
    release_notes_uz: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, doc="Uzbek, shown on the in-app update screen."
    )
    is_mandatory: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
        doc="Drives update.required in every response.",
    )
    published_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Uploaded is not published."
    )
    is_current: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
        doc="One current build per variant — partial unique index.",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Which admin uploaded it.",
    )

    __table_args__ = (
        sa.UniqueConstraint("variant", "version_code", name="uq_app_versions_variant_code"),
        sa.Index(
            "uq_app_versions_current",
            "variant",
            unique=True,
            postgresql_where=sa.text("is_current"),
        ),
    )
