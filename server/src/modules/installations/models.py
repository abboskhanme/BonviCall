"""Installation ORM model (SPEC §3.4).

An installation is the binding between a handset and a **registered number**.
The number is the identity anchor, not the device, which is why exactly one
installation may be ``active`` per number — enforced by a partial unique index,
because "the app is on two phones" doubles every call and is a data-integrity
failure, not a UI problem.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UUIDMixin
from src.core.enums import (
    AppVariant,
    FunnelStage,
    InstallationStatus,
    VerificationMethod,
    pg_enum,
)


class InstallationModel(Base, UUIDMixin, TimestampMixin):
    """One app installation. The app carries this id in ``X-Installation-Id``."""

    __tablename__ = "installations"

    number_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("registered_numbers.id", ondelete="RESTRICT"),
        nullable=False,
        doc="The registered line. Calls are resolved from here, never from the payload.",
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Frozen at bind time so the funnel and every alert can name a person.",
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("devices.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Which handset.",
    )
    status: Mapped[InstallationStatus] = mapped_column(
        pg_enum(InstallationStatus, "installation_status"),
        nullable=False,
        server_default=InstallationStatus.PENDING.value,
        doc="pending until verified; replaced on rebinding; revoked by an admin.",
    )
    verification_method: Mapped[VerificationMethod | None] = mapped_column(
        pg_enum(VerificationMethod, "verification_method"),
        nullable=True,
        doc="NULL until verified. admin_attested is weaker and is shown as such.",
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="When the number was proven."
    )
    attested_by: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Set only when verification_method='admin_attested' (T142).",
    )
    attest_reason: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        doc=(
            "Required when attested. An unexplained attestation is "
            "indistinguishable from a mistake six months later."
        ),
    )
    bound_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc="When the code was redeemed. The attribution fallback for an out-of-range call.",
    )
    replaced_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Superseded by a newer installation (UC-07)."
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Admin revoked it (UC-08)."
    )
    revoke_confirmed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc="The phone came back and confirmed the local wipe. NULL means it never did.",
    )
    revoke_pending_records: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True, doc="Records still queued at last contact (UC-08)."
    )
    revoke_pending_bytes: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True, doc="Audio bytes still queued at last contact."
    )
    credential_hash: Mapped[str] = mapped_column(
        sa.CHAR(64), nullable=False, doc="sha256 of the installation secret (N24)."
    )
    device_fingerprint_hash: Mapped[str] = mapped_column(
        sa.CHAR(64),
        nullable=False,
        doc=(
            "Token binding. A token copied to another phone is refused on first "
            "use and raises credential_replay. Honest limit: this raises the "
            "cost of theft, it does not defeat root on the handset."
        ),
    )
    token_version: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("1"),
        doc="Incremented on revoke or replay — every issued token dies at once.",
    )
    refresh_token_hash: Mapped[str | None] = mapped_column(
        sa.CHAR(64), nullable=True, doc="Current refresh token; reuse means credential_replay."
    )
    app_version: Mapped[str | None] = mapped_column(
        sa.String(20),
        nullable=True,
        doc="Last reported.",
    )
    app_variant: Mapped[AppVariant | None] = mapped_column(
        pg_enum(AppVariant, "app_variant"), nullable=True, doc="legacy28 | modern34 (D-06)."
    )
    sim_subscription_id: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc=(
            "The registered subscription as the OS numbers it. Guard 1 of the "
            "privacy boundary matches every call against this (§7.4)."
        ),
    )
    sim_slot: Mapped[int | None] = mapped_column(
        sa.SmallInteger,
        nullable=True,
        doc="Physical slot.",
    )
    funnel_stage: Mapped[FunnelStage] = mapped_column(
        pg_enum(FunnelStage, "funnel_stage"),
        nullable=False,
        server_default=FunnelStage.INVITED.value,
        doc="Persisted so the rollout list is one query, not a per-row computation.",
    )
    funnel_changed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="Time-in-stage is what an admin actually watches during a rollout.",
    )

    __table_args__ = (
        sa.Index(
            "uq_installation_active_per_number",
            "number_id",
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
        ),
        sa.Index("ix_installations_agent", "agent_id", "status"),
        sa.Index("ix_installations_stage", "funnel_stage", sa.text("funnel_changed_at DESC")),
        sa.CheckConstraint(
            "verification_method <> 'admin_attested' OR attest_reason IS NOT NULL",
            name="attestation_needs_reason",
        ),
    )
