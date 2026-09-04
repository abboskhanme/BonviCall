"""Audit log ORM model (SPEC §3.8, UC-24, N27).

Append-only is enforced by a trigger created in the migration, not by
convention: there is no route that updates or deletes an audit row, and now no
code path can either — including a psql session.

No ``TimestampMixin`` here, and that is deliberate. The row is immutable, so an
``updated_at`` column would be a field that can only ever be a lie; ``at`` is
``created_at`` under the name SPEC gives it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, UUIDMixin
from src.core.enums import ActorType, AuditAction, pg_enum


class AuditLogModel(Base, UUIDMixin):
    """One thing that happened, and who did it."""

    __tablename__ = "audit_log"

    at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="Server time. The only timestamp this table has, by design.",
    )
    actor_type: Mapped[ActorType] = mapped_column(
        pg_enum(ActorType, "actor_type"), nullable=False, doc="user | service | device | system."
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Which login, for actor_type='user'.",
    )
    actor_service_token_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("service_tokens.id", ondelete="SET NULL"),
        nullable=True,
        doc="Which machine token, for actor_type='service' (UC-29 audits export reads).",
    )
    action: Mapped[AuditAction] = mapped_column(
        pg_enum(AuditAction, "audit_action"),
        nullable=False,
        doc="Closed set — see core.enums.AuditAction.",
    )
    object_type: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, doc="'call', 'user', 'installation'… what was acted on."
    )
    object_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        nullable=True,
        doc="Not a foreign key on purpose: the audit row must outlive whatever it describes.",
    )
    ip: Mapped[str | None] = mapped_column(
        postgresql.INET,
        nullable=True,
        doc="Where the request came from.",
    )
    user_agent: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        doc="Client string.",
    )
    detail: Mapped[dict | None] = mapped_column(
        postgresql.JSONB,
        nullable=True,
        doc="Before/after values and counts. Never a password, a token or a code (N26).",
    )

    __table_args__ = (
        sa.Index("ix_audit_log_at", sa.text("at DESC")),
        sa.Index("ix_audit_log_actor", "actor_user_id", sa.text("at DESC")),
        sa.Index("ix_audit_log_object", "object_type", "object_id", sa.text("at DESC")),
    )
