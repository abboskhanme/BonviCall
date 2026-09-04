"""Enrolment and number-verification ORM models (SPEC §3.4, §9).

The callback route (SPEC §9.2) is load-bearing: SMS was removed from scope, so
when a SIM does not report its own MSISDN — the common case on Uzbek networks —
this is the only remaining proof that a handset holds the registered number.
That is why the receiver's health is a product state with its own table and its
own critical alert, and not an operational detail.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UUIDMixin, phone_key_computed
from src.core.enums import (
    EnrolmentAttemptKind,
    EnrolmentOutcome,
    ReceiverKind,
    ReceiverStatus,
    VerificationMethod,
    VerificationState,
    pg_enum,
)


class EnrolmentCodeModel(Base, UUIDMixin, TimestampMixin):
    """A single-use code, valid 24 hours (UC-01).

    Crockford base32 without ``I L O U``: the code is read aloud over the phone
    and typed by a salesperson, and the ambiguous glyphs are where that fails.
    """

    __tablename__ = "enrolment_codes"

    code: Mapped[str] = mapped_column(
        sa.CHAR(8), nullable=False, unique=True, doc="The 8-character code itself."
    )
    number_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("registered_numbers.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Which line the code enrols.",
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Frozen at issue, so the landing page can greet the right person.",
    )
    issued_by: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Which admin issued it.",
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        doc="Issue + enrolment.code_ttl_hours. Past this: 410, not 404.",
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="First redemption. A second one is 409."
    )
    redeemed_by_installation_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("installations.id", ondelete="SET NULL", use_alter=True,
                      name="fk_enrolment_codes_installation"),
        nullable=True,
        doc="Which installation used it — the 409 names the device model.",
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc="Admin revoked it, or five failed attempts did.",
    )
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Which admin revoked it; NULL when the rate limiter did.",
    )
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
        doc="Five attempts auto-revoke the code and raise an alert (SPEC §4.0).",
    )

    __table_args__ = (
        sa.Index(
            "ix_codes_number_active",
            "number_id",
            postgresql_where=sa.text("redeemed_at IS NULL AND revoked_at IS NULL"),
        ),
    )


class EnrolmentAttemptModel(Base, UUIDMixin, TimestampMixin):
    """Append-only record of every enrolment step — the funnel's evidence base.

    A stalled enrolment must be an **event**, not silence: a rollout that has
    quietly stopped looks exactly like one that is working until go-live.
    """

    __tablename__ = "enrolment_attempts"

    kind: Mapped[EnrolmentAttemptKind] = mapped_column(
        pg_enum(EnrolmentAttemptKind, "enrolment_attempt_kind"),
        nullable=False,
        doc="Which step. 'step_timing' carries the durations that make N40 measurable.",
    )
    outcome: Mapped[EnrolmentOutcome] = mapped_column(
        pg_enum(EnrolmentOutcome, "enrolment_outcome"),
        nullable=False,
        doc="How it ended. Closed set — the panel groups on it.",
    )
    code_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("enrolment_codes.id", ondelete="SET NULL"),
        nullable=True,
        doc="Which code, where one was involved.",
    )
    number_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("registered_numbers.id", ondelete="SET NULL"),
        nullable=True,
        doc="Which line.",
    )
    installation_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("installations.id", ondelete="SET NULL"),
        nullable=True,
        doc="Which installation, once one exists.",
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        doc="Who was enrolling.",
    )
    step: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True, doc="'E1'…'E6' or 'landing' (SPEC §8)."
    )
    duration_ms: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True, doc="For kind='step_timing': how long that screen took."
    )
    detail: Mapped[dict | None] = mapped_column(
        postgresql.JSONB,
        nullable=True,
        doc="Machine-readable context. Never a code or a token (N26).",
    )
    remote_ip: Mapped[str | None] = mapped_column(postgresql.INET, nullable=True, doc="Where from.")
    app_version: Mapped[str | None] = mapped_column(
        sa.String(20),
        nullable=True,
        doc="Reported version.",
    )
    device_model: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True, doc="So per-model enrolment friction is visible."
    )

    __table_args__ = (
        sa.Index("ix_enrolment_attempts_number", "number_id", sa.text("created_at DESC")),
        sa.Index(
            "ix_enrolment_attempts_installation",
            "installation_id",
            sa.text("created_at DESC"),
        ),
        sa.Index("ix_enrolment_attempts_kind", "kind", "outcome", sa.text("created_at DESC")),
    )


class NumberVerificationModel(Base, UUIDMixin, TimestampMixin):
    """One attempt to prove the handset holds the registered number (UC-04)."""

    __tablename__ = "number_verifications"

    installation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("installations.id", ondelete="CASCADE"),
        nullable=False,
        doc="Which installation is proving itself.",
    )
    number_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("registered_numbers.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Which line it claims.",
    )
    method: Mapped[VerificationMethod] = mapped_column(
        pg_enum(VerificationMethod, "verification_method"), nullable=False, doc="Which route."
    )
    state: Mapped[VerificationState] = mapped_column(
        pg_enum(VerificationState, "verification_state"),
        nullable=False,
        server_default=VerificationState.PENDING.value,
        doc="pending | matched | failed | expired | attested.",
    )
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="Challenge start.",
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        doc="started_at + enrolment.callback_window_seconds (5 min).",
    )
    matched_event_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey(
            "callback_events.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_number_verifications_matched_event",
        ),
        nullable=True,
        doc=(
            "The inbound call that proved it. Circular with callback_events by "
            "design — each side records the match it made — so this constraint "
            "is added after both tables exist."
        ),
    )
    failure_outcome: Mapped[EnrolmentOutcome | None] = mapped_column(
        pg_enum(EnrolmentOutcome, "enrolment_outcome"),
        nullable=True,
        doc="no_caller_id is R19 happening, and is why admin attestation exists.",
    )
    attested_by: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="For method='admin_attested' only.",
    )
    attest_reason: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True, doc="Mandatory when attested."
    )

    __table_args__ = (
        sa.Index(
            "ix_number_verifications_pending",
            "number_id",
            postgresql_where=sa.text("state = 'pending'"),
        ),
        sa.Index(
            "ix_number_verifications_installation",
            "installation_id",
            sa.text("started_at DESC"),
        ),
    )


class CallbackReceiverModel(Base, UUIDMixin, TimestampMixin):
    """The office line that observes inbound caller id (SPEC §9.4).

    If every receiver is ``down`` nobody can enrol, so this is monitored like a
    product state: 3 minutes silent is ``degraded``, 5 minutes is ``down`` plus
    a **critical** alert, and screen E5 refuses to start a challenge rather
    than letting an agent dial into nothing.
    """

    __tablename__ = "callback_receivers"

    name: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        doc="Which box, for the alert text.",
    )
    msisdn: Mapped[str] = mapped_column(
        sa.String(20), nullable=False, doc="E.164 the agent dials. Shown in large type on E5."
    )
    kind: Mapped[ReceiverKind] = mapped_column(
        pg_enum(ReceiverKind, "receiver_kind"),
        nullable=False,
        doc="gsm_gateway | android_receiver.",
    )
    token_hash: Mapped[str] = mapped_column(
        sa.CHAR(64),
        nullable=False,
        doc="sha256 of its service token, scoped to callback:report only.",
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.true(),
        doc="Matching accepts any active receiver.",
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Every 60 s. Absence is the whole signal."
    )
    status: Mapped[ReceiverStatus] = mapped_column(
        pg_enum(ReceiverStatus, "receiver_status"),
        nullable=False,
        server_default=ReceiverStatus.DOWN.value,
        doc="Starts down: a receiver that has never checked in is not up.",
    )
    status_changed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="For the alert body.",
    )
    note: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        doc="Where it physically is.",
    )


class CallbackEventModel(Base, UUIDMixin, TimestampMixin):
    """Every inbound call a receiver saw (SPEC §3.4).

    Retention is 90 days: these are inbound call records of employees' work
    numbers and have no value once the enrolment is done.
    """

    __tablename__ = "callback_events"

    receiver_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("callback_receivers.id", ondelete="CASCADE"),
        nullable=False,
        doc="Which receiver reported it.",
    )
    caller_e164: Mapped[str | None] = mapped_column(
        sa.String(20), nullable=True, doc="NULL when the network withheld the caller id."
    )
    caller_key: Mapped[str | None] = mapped_column(
        sa.CHAR(9),
        phone_key_computed("caller_e164"),
        nullable=True,
        doc="Generated last-9 key — what the matcher joins on (N37).",
    )
    cli_presented: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
        doc=(
            "False means the operator suppressed the number. Crossed with "
            "registered_numbers.operator this is the per-operator table R19 needs."
        ),
    )
    received_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="Server receipt — authoritative for matching, not the receiver's clock.",
    )
    receiver_epoch_ms: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True, doc="The receiver's raw clock, kept as evidence (N36)."
    )
    matched_verification_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey(
            "number_verifications.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_callback_events_matched_verification",
        ),
        nullable=True,
        doc="Which challenge this satisfied, if any.",
    )
    unmatched_reason: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        doc="Why it matched nothing. An unmatched event is stored and ignored, never dropped.",
    )

    __table_args__ = (
        sa.Index("ix_callback_events_caller", "caller_key", sa.text("received_at DESC")),
        sa.Index("ix_callback_events_receiver", "receiver_id", sa.text("received_at DESC")),
    )
