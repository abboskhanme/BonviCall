"""Alert ORM model (SPEC §3.8, §10.3).

Two rules the schema enforces rather than documents:

* **One open alert per cause.** A phone reporting a revoked permission every
  two minutes must not produce 720 rows a day, so ``dedupe_key`` is uniquely
  indexed over the open rows and repeats bump ``occurrence_count``.
* **Nothing in the device API can touch this table.** UC-06 and UC-18 are
  explicit that the agent cannot dismiss or suppress an alert about their own
  phone, and only ``admin`` may acknowledge.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UUIDMixin
from src.core.enums import AlertKind, AlertSeverity, pg_enum


class AlertModel(Base, UUIDMixin, TimestampMixin):
    """One thing an admin needs to know about."""

    __tablename__ = "alerts"

    kind: Mapped[AlertKind] = mapped_column(
        pg_enum(AlertKind, "alert_kind"), nullable=False, doc="Closed set — see SPEC §10.3."
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        pg_enum(AlertSeverity, "alert_severity"),
        nullable=False,
        doc="critical is emailed immediately; warning only when it is new.",
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        doc="Who it is about, where it is about a person.",
    )
    installation_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("installations.id", ondelete="SET NULL"),
        nullable=True,
        doc="Which phone, where it is about a phone.",
    )
    number_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("registered_numbers.id", ondelete="SET NULL"),
        nullable=True,
        doc="Which line.",
    )
    device_model: Mapped[str | None] = mapped_column(
        sa.String(96),
        nullable=True,
        doc="For fleet-wide, per-model alerts such as capture regression.",
    )
    title_uz: Mapped[str] = mapped_column(
        sa.String(200), nullable=False, doc="Uzbek headline, composed when the alert is raised."
    )
    body_uz: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, doc="Uzbek explanation and what to do about it."
    )
    detail: Mapped[dict | None] = mapped_column(
        postgresql.JSONB, nullable=True, doc="Machine-readable context for the panel."
    )
    dedupe_key: Mapped[str] = mapped_column(
        sa.String(200),
        nullable=False,
        doc="'<kind>:<installation_id|agent_id|model|fleet>'. Uniquely indexed while open.",
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="When the cause started.",
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="Most recent occurrence.",
    )
    occurrence_count: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("1"),
        doc="Bumped instead of inserting a row.",
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="An admin saw it."
    )
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Which admin. alerts:ack is admin-only for exactly this reason.",
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="The cause went away by itself."
    )
    notified_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Email sent; stops a repeat within 24 h."
    )

    __table_args__ = (
        sa.Index(
            "uq_alerts_open",
            "dedupe_key",
            unique=True,
            postgresql_where=sa.text("acknowledged_at IS NULL AND resolved_at IS NULL"),
        ),
        sa.Index("ix_alerts_feed", "severity", sa.text("last_seen_at DESC")),
    )
