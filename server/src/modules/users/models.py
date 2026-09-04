"""Panel account ORM model (SPEC §3.2).

A user is a login. Creating one never creates an agent, and registering an
agent never creates a user: an admin does both, on two screens, for two
reasons. The one link that exists is ``agent_id``, which is what own-scope
narrowing filters on for a ``sales`` user — and the database insists on it,
because without it a ``sales`` login would silently see nothing or everything.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UUIDMixin
from src.core.enums import UserRole, pg_enum


class UserModel(Base, UUIDMixin, TimestampMixin):
    """A panel login."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        postgresql.CITEXT,
        nullable=False,
        unique=True,
        doc=(
            "CITEXT, not VARCHAR: 'Aziz@bonvi.uz' and 'aziz@bonvi.uz' are one "
            "account, and case-folding in application code is one forgotten "
            "call away from two."
        ),
    )
    password_hash: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
        doc="argon2id. Never returned by any endpoint, never logged (N26).",
    )
    full_name: Mapped[str] = mapped_column(sa.String(255), nullable=False, doc="Display name.")
    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"),
        nullable=False,
        doc="admin | manager | sales. 'service' is a service_tokens row, not a login.",
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.true(), doc="Can log in."
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        doc=(
            "Which salesperson this login *is*. Required when role='sales' "
            "(CHECK below); NULL for admin and manager."
        ),
    )
    must_change_password: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
        doc=(
            "Set when an admin creates the account or resets the password. The "
            "panel forces the change before anything else loads."
        ),
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Last successful self-change."
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Last successful login."
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc="Paired with is_active; who did it and when is in audit_log.",
    )

    __table_args__ = (
        sa.CheckConstraint(
            "role <> 'sales' OR agent_id IS NOT NULL",
            name="sales_user_requires_agent",
        ),
        sa.Index("ix_users_agent_id", "agent_id"),
        sa.Index(
            "ix_users_active_admin",
            "role",
            postgresql_where=sa.text("is_active AND role = 'admin'"),
        ),
    )
