"""Agent ORM model (SPEC §3.3).

An **agent** is a person whose calls are attributed. A **user** is a login.
They are separate chains on purpose: the normal case is a salesperson who never
opens the panel, and their calls must still be recorded and attributed.

Deliberately **no phone column.** BonviZvonki has ``agents.phone`` and cannot
express "this number moved from A to B on the 14th"; that mapping lives in
``numbers.number_assignments`` and is time-boxed.
"""

from __future__ import annotations

from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UUIDMixin

#: Avatar fallback when nobody picked a colour.
DEFAULT_AGENT_COLOR = "#6366f1"


class AgentModel(Base, UUIDMixin, TimestampMixin):
    """A salesperson."""

    __tablename__ = "agents"

    full_name: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
        index=True,
        doc="As the admin typed it. Indexed because the panel searches on it.",
    )
    employee_code: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        doc="The roster import key. Unique where present — see the partial index.",
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.true(),
        doc="False once the person has left the company. Their calls stay.",
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc=(
            "Removed from the system. A timestamp rather than a flag so the "
            "panel can answer 'when?' as well as 'whether?' (§6). An agent "
            "with calls is never deleted — the BonviZvonki lesson."
        ),
    )
    hired_at: Mapped[date | None] = mapped_column(
        sa.Date,
        nullable=True,
        doc="Asia/Tashkent calendar date; used by the roster import only.",
    )
    color: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        server_default=DEFAULT_AGENT_COLOR,
        doc="Avatar fallback in the panel; decoration, never identity.",
    )
    note: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, doc="Free text for the admin."
    )

    __table_args__ = (
        sa.Index(
            "uq_agents_employee_code",
            "employee_code",
            unique=True,
            postgresql_where=sa.text("employee_code IS NOT NULL"),
        ),
        sa.Index("ix_agents_active", "is_active", "full_name"),
    )
