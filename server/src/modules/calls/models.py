"""Call ORM model (SPEC §3.5).

~15,000 rows a month, designed and indexed for 500,000 (UC-19).

Three timestamps are kept and never merged (N36, CONVENTIONS.md §6):
``started_at``/``answered_at``/``ended_at`` are the device's, reconciled
against its own call log; ``device_epoch_ms`` + ``device_timezone`` are the raw
evidence for skew; ``received_at`` is ours and is **authoritative for ordering
and cursors**. Attribution uses ``started_at`` and ordering uses
``received_at`` because they answer two different questions (D-08).

Calls are never deleted and never soft-deleted (UC-26). ``DELETE`` returns 405
for every role including ``admin``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UUIDMixin, phone_key_computed
from src.core.enums import (
    AppVariant,
    AudioMissingReason,
    CallDirection,
    CallDisposition,
    CallSource,
    CallType,
    pg_enum,
)


class CallModel(Base, UUIDMixin, TimestampMixin):
    """One call on a registered number."""

    __tablename__ = "calls"

    seq: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.Identity(always=True),
        nullable=False,
        unique=True,
        doc=(
            "Monotonic insert counter — the export cursor (SPEC §4.9). "
            "GENERATED ALWAYS, so an explicit value is an error rather than a "
            "silent hole in someone's export. The export still applies a "
            "10-second settling window: under concurrency a lower seq can "
            "commit after a higher one."
        ),
    )
    client_call_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        nullable=False,
        unique=True,
        doc=(
            "The idempotency key: a UUIDv5 the device derives from call-log "
            "facts that survive a reinstall (D-05). Upsert on this; a replay "
            "returns the same id. Duplicate rate must be 0 (N2)."
        ),
    )
    installation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("installations.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Which installation delivered it.",
    )
    number_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("registered_numbers.id", ondelete="RESTRICT"),
        nullable=False,
        doc=(
            "Resolved from the installation, never from the payload: the device "
            "does not get to say "
            "which number it is."
        ),
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Resolved at ingest from the assignment covering started_at, then frozen.",
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("number_assignments.id", ondelete="SET NULL"),
        nullable=True,
        doc=(
            "Which assignment produced the attribution. Frozen so history does "
            "not silently move when an admin edits an assignment; the "
            "reattribute_calls job re-stamps it and writes an audit row."
        ),
    )
    direction: Mapped[CallDirection] = mapped_column(
        pg_enum(CallDirection, "call_direction"), nullable=False, doc="incoming | outgoing."
    )
    disposition: Mapped[CallDisposition] = mapped_column(
        pg_enum(CallDisposition, "call_disposition"),
        nullable=False,
        doc="UC-11's five classes are direction x disposition; a CHECK enforces the pairs.",
    )
    remote_number: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        doc=(
            "As the device saw it, normalised where possible. An unparseable "
            "number is stored raw with a NULL key rather than rejected: losing "
            "a call because its number was odd is the worse failure."
        ),
    )
    remote_number_key: Mapped[str | None] = mapped_column(
        sa.CHAR(9),
        phone_key_computed("remote_number"),
        nullable=True,
        doc=(
            "Generated last-9 key. **NULL for short numbers on purpose**: a "
            "4-digit extension used as a key matches the tail of every long "
            "number, which is how BonviZvonki marked strangers as colleagues."
        ),
    )
    contact_name: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        doc="Resolved on-device from the employee's contacts. Decoration, never identity (L3).",
    )
    call_type: Mapped[CallType] = mapped_column(
        pg_enum(CallType, "call_type"),
        nullable=False,
        server_default=CallType.UNKNOWN.value,
        doc=(
            "internal | external | unknown. Empty directory yields unknown, never external (UC-25)."
        ),
    )
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        doc="Device time, call-log reconciled. Attribution and business dates use this (D-08).",
    )
    answered_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc=(
            "NULL means there was never a conversation (UC-09). A CHECK ties it to the disposition."
        ),
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc="Device time; bounds the audio harvest window.",
    )
    duration_sec: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
        doc=(
            "Whole seconds from the call log's DURATION, truncated not rounded. Never a float "
            "(§10)."
        ),
    )
    ring_sec: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc="Ring time, where known.",
    )
    device_epoch_ms: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        doc="Raw device clock at call start — the evidence for skew (N36).",
    )
    device_timezone: Mapped[str] = mapped_column(
        sa.String(64), nullable=False, doc="IANA name as the handset reported it."
    )
    clock_skew_sec: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
        doc=(
            "received_at - device_epoch_ms at receipt, corrected for transit. "
            "Never used to rewrite started_at: a corrected timestamp would "
            "break the call-log reconciliation everything else depends on."
        ),
    )
    received_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="Server receipt. **Authoritative for ordering, cursors and retention** (N36).",
    )
    sim_subscription_id: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc="The registered subscription only — Guard 1 already refused the rest.",
    )
    sim_slot: Mapped[int | None] = mapped_column(
        sa.SmallInteger,
        nullable=True,
        doc="Physical slot.",
    )
    source: Mapped[CallSource] = mapped_column(
        pg_enum(CallSource, "call_source"),
        nullable=False,
        doc="live_capture | call_log_recovery (the UC-13 sweep after the app was dead).",
    )
    reconciled_with_call_log: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
        doc="False means the 15-minute reconciliation window expired first (D-05 rule 2).",
    )
    command_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey(
            "commands.id", ondelete="SET NULL", use_alter=True, name="fk_calls_command"
        ),
        nullable=True,
        doc=(
            "Click-to-call linkage (UC-16). Circular with commands.result_call_id, "
            "so this constraint is added once both tables exist. A failed command "
            "is never linked to a call — the partial unique index plus a service "
            "check enforce it."
        ),
    )
    has_audio: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
        doc="Denormalised so the gap report's partial index can exist (UC-23).",
    )
    audio_missing_reason: Mapped[AudioMissingReason | None] = mapped_column(
        pg_enum(AudioMissingReason, "audio_missing_reason"),
        nullable=True,
        doc=(
            "Closed enum, never free text. A CHECK makes 'always present when "
            "audio is absent' true "
            "(N5)."
        ),
    )
    audio_duration_mismatch: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
        doc=(
            "Set at commit when the file's duration differs from duration_sec by more than 2 s "
            "(UC-14)."
        ),
    )
    note: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, doc="Free text, editable with calls:note only."
    )
    app_version: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        doc="Denormalised: per-version capture rate must survive an upgrade.",
    )
    app_variant: Mapped[AppVariant] = mapped_column(
        pg_enum(AppVariant, "app_variant"),
        nullable=False,
        doc="Denormalised for the same reason (D-06).",
    )

    __table_args__ = (
        # N5: a call without audio ALWAYS carries a reason, and a call with
        # audio never carries one. A constraint rather than a convention,
        # because "100 % of calls" is the acceptance criterion.
        sa.CheckConstraint(
            "(has_audio AND audio_missing_reason IS NULL)"
            " OR (NOT has_audio AND audio_missing_reason IS NOT NULL)",
            name="audio_reason_present",
        ),
        # UC-11: the invalid direction/disposition pairs must be
        # unrepresentable rather than merely unused.
        sa.CheckConstraint(
            "(direction = 'incoming' AND disposition IN ('answered','missed','rejected'))"
            " OR (direction = 'outgoing' AND disposition IN ('answered','no_answer'))",
            name="direction_disposition",
        ),
        # UC-09: "answered" and "there is an answered_at" are the same fact.
        sa.CheckConstraint(
            "(disposition = 'answered') = (answered_at IS NOT NULL)",
            name="answered_has_timestamp",
        ),
        # UC-09/UC-11: zero calls classified as answered that the call log
        # shows with duration 0, and no duration on a call nobody answered.
        sa.CheckConstraint(
            "(disposition = 'answered' AND duration_sec > 0)"
            " OR (disposition <> 'answered' AND duration_sec = 0)",
            name="answered_has_duration",
        ),
        sa.Index("ix_calls_cursor", sa.text("received_at DESC"), sa.text("id DESC")),
        sa.Index("ix_calls_agent", "agent_id", sa.text("started_at DESC")),
        sa.Index("ix_calls_started", sa.text("started_at DESC"), sa.text("id DESC")),
        sa.Index("ix_calls_number", "number_id", sa.text("started_at DESC")),
        sa.Index("ix_calls_install", "installation_id", sa.text("started_at DESC")),
        sa.Index(
            "ix_calls_remote",
            "remote_number_key",
            postgresql_where=sa.text("remote_number_key IS NOT NULL"),
        ),
        sa.Index(
            "ix_calls_no_audio",
            sa.text("started_at DESC"),
            postgresql_where=sa.text("has_audio = false"),
        ),
        sa.Index("ix_calls_type", "call_type", sa.text("started_at DESC")),
        sa.Index(
            "uq_calls_command",
            "command_id",
            unique=True,
            postgresql_where=sa.text("command_id IS NOT NULL"),
        ),
    )
