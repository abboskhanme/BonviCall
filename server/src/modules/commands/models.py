"""Command ORM model (SPEC §3.8, §4.6).

``latency_ms`` is stored on every acknowledgement so UC-16's five-second bar is
**measured** rather than assumed. RISKS R3 flags that bar as possibly
unachievable on doze-restricted OEMs; this column is what turns that into a
conversation with evidence instead of a quiet miss.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UUIDMixin
from src.core.enums import (
    CommandFailureReason,
    CommandKind,
    CommandStatus,
    pg_enum,
)


class CommandModel(Base, UUIDMixin, TimestampMixin):
    """One instruction sent to one installation."""

    __tablename__ = "commands"

    installation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("installations.id", ondelete="CASCADE"),
        nullable=False,
        doc="Which phone.",
    )
    kind: Mapped[CommandKind] = mapped_column(
        pg_enum(CommandKind, "command_kind"),
        nullable=False,
        doc="dial | config | logout | ping | recheck.",
    )
    payload: Mapped[dict | None] = mapped_column(
        postgresql.JSONB,
        nullable=True,
        doc="Kind-specific body, e.g. the number to dial. Never sent through FCM.",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="NULL for system-issued commands.",
    )
    status: Mapped[CommandStatus] = mapped_column(
        pg_enum(CommandStatus, "command_status"),
        nullable=False,
        server_default=CommandStatus.PENDING.value,
        doc="pending | sent | acknowledged | failed | expired.",
    )
    failure_reason: Mapped[CommandFailureReason | None] = mapped_column(
        pg_enum(CommandFailureReason, "command_failure_reason"),
        nullable=True,
        doc="Why it did not happen — UC-16 requires the panel to say which.",
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Handed to the socket or to FCM."
    )
    acked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Device acknowledgement."
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        doc=(
            "created + 120 s for dial, + 24 h otherwise. The app also discards "
            "an expired command on arrival, so a phone that wakes after three "
            "minutes never dials (UC-16)."
        ),
    )
    result_call_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("calls.id", ondelete="SET NULL"),
        nullable=True,
        doc="The call the dial produced, once it arrives.",
    )
    latency_ms: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc="acked_at - created_at. The device page shows p50/p90 per model (R3).",
    )

    __table_args__ = (
        sa.Index(
            "ix_commands_installation",
            "installation_id",
            "status",
            sa.text("created_at DESC"),
        ),
        sa.Index("ix_commands_expiry", "status", "expires_at"),
    )
