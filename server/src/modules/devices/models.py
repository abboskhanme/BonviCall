"""Handset and telemetry ORM models (SPEC §3.4, §3.7).

Deliberately **not** built: a ``device_health_history`` time series. Nothing in
UC-17…UC-27 asks for a battery chart, and a two-minute append per device is
~11k rows/device/month for a graph nobody requested. The transitions that
alerts actually need live in ``capability_transitions``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UUIDMixin
from src.core.enums import (
    AppVariant,
    Capability,
    CapabilityState,
    CaptureRoute,
    NetworkType,
    pg_enum,
)


class DeviceModel(Base, UUIDMixin, TimestampMixin):
    """A handset, as it reports itself. **No raw hardware identifier is stored.**

    The handset belongs to the employee. A durable identifier that follows a
    person between jobs is not ours to keep, so change detection is done on a
    hash of the build fingerprint instead.
    """

    __tablename__ = "devices"

    manufacturer: Mapped[str] = mapped_column(
        sa.String(64), nullable=False, doc="Build.MANUFACTURER, e.g. 'Xiaomi'."
    )
    model: Mapped[str] = mapped_column(
        sa.String(96),
        nullable=False,
        doc="Build.MODEL. The capture-rate baseline is per model (M0).",
    )
    marketing_name: Mapped[str | None] = mapped_column(
        sa.String(96), nullable=True, doc="What the owner calls it, where known."
    )
    android_release: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, doc="Build.VERSION.RELEASE, e.g. '13'."
    )
    api_level: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, doc="Build.VERSION.SDK_INT. Floor is 26 (N32)."
    )
    build_fingerprint_hash: Mapped[str] = mapped_column(
        sa.CHAR(64),
        nullable=False,
        unique=True,
        doc=(
            "sha256 of Build.FINGERPRINT. Detects 'this is a different phone' "
            "without keeping an identifier that follows the employee."
        ),
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="First contact from this build.",
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="Most recent contact from this build.",
    )

    __table_args__ = (sa.Index("ix_devices_model", "manufacturer", "model", "api_level"),)


class DeviceHealthModel(Base, TimestampMixin):
    """Current state of one installation — written, never appended (SPEC §3.7).

    No ``UUIDMixin``: the primary key is ``installation_id``, because there is
    exactly one row per installation and a surrogate key would allow two.

    ``is_online`` is **derived, not stored**:
    ``last_heartbeat_at > now() - alerts.device_offline_minutes``. Storing it
    would need a job to keep it false, and it would be wrong between runs.
    """

    __tablename__ = "device_health"

    installation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("installations.id", ondelete="CASCADE"),
        primary_key=True,
        doc="The installation this row describes. One row, forever.",
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc="Server receipt of the last heartbeat. Five missed = OFFLINE (UC-17).",
    )
    last_call_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc="Server receipt of the last call. Silence detection reads it (UC-27).",
    )
    app_version: Mapped[str | None] = mapped_column(
        sa.String(20),
        nullable=True,
        doc="e.g. '1.4.0'.",
    )
    app_variant: Mapped[AppVariant | None] = mapped_column(
        pg_enum(AppVariant, "app_variant"),
        nullable=True,
        doc="legacy28 | modern34 (D-06), so capture rate is measurable per variant.",
    )
    api_level: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc="Build.VERSION.SDK_INT.",
    )
    battery_level: Mapped[int | None] = mapped_column(
        sa.SmallInteger, nullable=True, doc="Percent 0-100, as the OS reports it."
    )
    battery_charging: Mapped[bool | None] = mapped_column(
        sa.Boolean,
        nullable=True,
        doc="Plugged in.",
    )
    battery_optimisation_exempt: Mapped[bool | None] = mapped_column(
        sa.Boolean,
        nullable=True,
        doc="isIgnoringBatteryOptimizations(). False is the usual cause of a dead service.",
    )
    power_save_mode: Mapped[bool | None] = mapped_column(
        sa.Boolean,
        nullable=True,
        doc="OS battery saver on.",
    )
    free_storage_bytes: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True, doc="Below 1 GB the app stops recording (N10)."
    )
    queue_records: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc="Metadata records waiting. Zero is what the version gate needs (§4.3).",
    )
    queue_bytes: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        nullable=True,
        doc="Audio bytes waiting.",
    )
    queue_oldest_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Age of the head of the queue."
    )
    parked_records: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True, doc="Poison-parked after 5 failed attempts (N9)."
    )
    clock_skew_sec: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc=(
            "received_at - device_epoch_ms, in whole seconds. Evidence for the "
            "panel (T87); never used to rewrite a device timestamp (N36)."
        ),
    )
    device_timezone: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True, doc="IANA name as the handset reports it."
    )
    network_type: Mapped[NetworkType | None] = mapped_column(
        pg_enum(NetworkType, "network_type"), nullable=True, doc="wifi | cellular | none."
    )
    cellular_bytes_month: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        nullable=True,
        doc="The device's own figure. Server-side counting is authoritative (N14).",
    )
    service_running: Mapped[bool | None] = mapped_column(
        sa.Boolean, nullable=True, doc="Foreground service alive (UC-05)."
    )
    capture_enabled: Mapped[bool | None] = mapped_column(
        sa.Boolean, nullable=True, doc="False raises capture_disabled (UC-18)."
    )
    recording_route: Mapped[CaptureRoute | None] = mapped_column(
        pg_enum(CaptureRoute, "capture_route"), nullable=True, doc="Which strategy is in use now."
    )
    recording_route_ok: Mapped[bool | None] = mapped_column(
        sa.Boolean,
        nullable=True,
        doc="Whether that route currently works, not whether it is configured.",
    )
    ws_connected: Mapped[bool | None] = mapped_column(
        sa.Boolean,
        nullable=True,
        doc=(
            "Socket open. Shown separately from is_online on purpose: a socket "
            "can be alive while capture is dead, and conflating the two is how "
            "a broken phone looks fine."
        ),
    )


class CapabilityStateModel(Base, UUIDMixin, TimestampMixin):
    """Current state of one capability on one installation (UC-03, §7.8)."""

    __tablename__ = "capability_states"

    installation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("installations.id", ondelete="CASCADE"),
        nullable=False,
        doc="Which installation reported it.",
    )
    capability: Mapped[Capability] = mapped_column(
        pg_enum(Capability, "capability"), nullable=False, doc="Which of the twelve."
    )
    state: Mapped[CapabilityState] = mapped_column(
        pg_enum(CapabilityState, "capability_state"),
        nullable=False,
        doc="Result of exercising it, never of reading a permission flag.",
    )
    checked_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, doc="When the device last ran the check."
    )
    changed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, doc="When the state last differed."
    )
    detail: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        doc="What the check saw, e.g. '1s test capture 32 kB'. Never free-form user text.",
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "installation_id", "capability", name="uq_capability_states_installation_capability"
        ),
    )


class CapabilityTransitionModel(Base, UUIDMixin, TimestampMixin):
    """Append-only history of capability changes — the evidence behind UC-06/UC-18."""

    __tablename__ = "capability_transitions"

    installation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("installations.id", ondelete="CASCADE"),
        nullable=False,
        doc="Which installation changed.",
    )
    capability: Mapped[Capability] = mapped_column(
        pg_enum(Capability, "capability"), nullable=False, doc="Which capability."
    )
    from_state: Mapped[CapabilityState | None] = mapped_column(
        pg_enum(CapabilityState, "capability_state"),
        nullable=True,
        doc="NULL for the first report.",
    )
    to_state: Mapped[CapabilityState] = mapped_column(
        pg_enum(CapabilityState, "capability_state"), nullable=False, doc="What it became."
    )
    at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="When the change was observed. created_at is when we stored it.",
    )
    source: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        doc="device_report | admin_recheck | inferred — how we learned of it.",
    )
    detail: Mapped[str | None] = mapped_column(sa.String(255), nullable=True, doc="Check output.")

    __table_args__ = (
        sa.CheckConstraint(
            "source IN ('device_report', 'admin_recheck', 'inferred')",
            name="source_known",
        ),
        sa.Index("ix_capability_transitions_installation", "installation_id", sa.text("at DESC")),
        sa.Index("ix_capability_transitions_capability", "capability", sa.text("at DESC")),
    )


class CallLogDeltaModel(Base, UUIDMixin, TimestampMixin):
    """The production measurement rig (N1's only post-acceptance denominator).

    The device sweeps its own call log for the registered subscription and
    reports what it counted next to what it uploaded. Without this, capture
    rate becomes unverifiable the day the acceptance window ends — there is no
    adb on a phone Bonvi does not own.
    """

    __tablename__ = "call_log_deltas"

    installation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("installations.id", ondelete="CASCADE"),
        nullable=False,
        doc="Which installation swept.",
    )
    number_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("registered_numbers.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Which registered line the sweep covered.",
    )
    period_date: Mapped[date] = mapped_column(
        sa.Date, nullable=False, doc="Asia/Tashkent calendar date (D-10)."
    )
    device_counted: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
        doc="Rows the device saw in its own call log. Monotonic within a day.",
    )
    uploaded_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0"), doc="Rows it believes it sent."
    )
    subscription_unknown_count: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
        doc=(
            "Calls the OS could not attribute to a subscription. Reported "
            "separately and **never folded into the numerator or the "
            "denominator** — that is the fail-closed rule made visible."
        ),
    )
    delta: Mapped[int] = mapped_column(
        sa.Integer,
        sa.Computed("device_counted - uploaded_count", persisted=True),
        nullable=False,
        doc="Generated. A non-zero delta still open after 24 h feeds the gap report (N3).",
    )
    first_reported_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="First sweep of the day.",
    )
    last_reported_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="Most recent sweep.",
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Set when the delta reconciled to zero."
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "installation_id", "period_date", name="uq_call_log_deltas_installation_period"
        ),
        sa.Index(
            "ix_call_log_deltas_open",
            "period_date",
            "delta",
            postgresql_where=sa.text("closed_at IS NULL"),
        ),
    )


class DataUsageDailyModel(Base, UUIDMixin, TimestampMixin):
    """Per-installation traffic, counted server-side (N14, N15).

    The device's own figure is kept in ``device_health`` for comparison, but
    the cap is enforced on this one: the number that costs an employee money
    is not a number the app gets to report.
    """

    __tablename__ = "data_usage_daily"

    installation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("installations.id", ondelete="CASCADE"),
        nullable=False,
        doc="Whose traffic.",
    )
    period_date: Mapped[date] = mapped_column(
        sa.Date, nullable=False, doc="Asia/Tashkent calendar date."
    )
    cellular_bytes: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        server_default=sa.text("0"),
        doc="Against the 1 GB monthly cap.",
    )
    wifi_bytes: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("0"), doc="Unmetered traffic."
    )
    requests: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
        doc="Request count, for rate-limit tuning.",
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "installation_id", "period_date", name="uq_data_usage_daily_installation_period"
        ),
    )
