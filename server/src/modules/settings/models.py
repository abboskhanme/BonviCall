"""Settings ORM model (SPEC §3.8).

The table is ``app_settings``, never ``settings`` (CONVENTIONS.md §10): a table
called ``settings`` collides with the SQL word people reach for and with the
module name in half the queries someone writes at 2 a.m.

Every key that exists is seeded by the migration with its documented default,
so a missing key is a bug rather than a silent ``None`` three layers down.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin


class AppSettingModel(Base, TimestampMixin):
    """One tunable value.

    No ``UUIDMixin``: the key *is* the identity, and a surrogate id would allow
    two rows to claim ``retention.audio_months``.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(
        sa.String(100),
        primary_key=True,
        doc=(
            "Dotted name, e.g. 'retention.audio_months'. Referenced by constant, never typed twice."
        ),
    )
    value: Mapped[Any] = mapped_column(
        postgresql.JSONB,
        nullable=False,
        doc="JSONB so a threshold, a list of e-mails and a holiday list are one table.",
    )
    value_type: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        doc="int | bool | string | list | time — what the panel renders as the editor.",
    )
    description_uz: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, doc="Shown next to the field on the settings screen."
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Which admin last changed it; the change itself is in audit_log.",
    )
