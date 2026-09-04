"""Session and machine-token ORM models (SPEC §3.2).

Both tables store a **hash**, never the token. A database dump, a backup tape
or a support screenshot therefore cannot be replayed against the API.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UUIDMixin


class RefreshTokenModel(Base, UUIDMixin, TimestampMixin):
    """One panel session, rotated on every refresh.

    Reuse of an already-rotated token revokes the whole chain for that user and
    raises ``credential_replay`` — N24's rule applied to the panel as well as
    to the app, because a stolen refresh token looks exactly like a slow client
    until you check whether the old one comes back.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        doc="Whose session this is. CASCADE: a deleted user has no sessions.",
    )
    token_hash: Mapped[str] = mapped_column(
        sa.CHAR(64),
        nullable=False,
        unique=True,
        doc="sha256 of the opaque 32-byte token. The token itself is never stored.",
    )
    issued_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="When this link of the chain was minted.",
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, doc="Absolute expiry, 90 days."
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc="Set on logout, on rotation, or on chain revocation after a replay.",
    )
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
        doc="The next link. Walking this chain is how a replay is proven.",
    )
    ip: Mapped[str | None] = mapped_column(
        postgresql.INET, nullable=True, doc="Where the session was opened from."
    )
    user_agent: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True, doc="Browser string, truncated."
    )

    __table_args__ = (
        sa.Index("ix_refresh_tokens_user", "user_id", "issued_at"),
        sa.Index(
            "ix_refresh_tokens_live",
            "user_id",
            postgresql_where=sa.text("revoked_at IS NULL"),
        ),
    )


class ServiceTokenModel(Base, UUIDMixin, TimestampMixin):
    """A machine principal (UC-29): the export consumer, the callback receiver.

    A service token can never be exchanged for a user session and never appears
    in ``users`` — a machine has no password, no session and no navigation.
    """

    __tablename__ = "service_tokens"

    name: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        unique=True,
        doc="Which machine holds it, so revoking the right one is possible.",
    )
    token_hash: Mapped[str] = mapped_column(
        sa.CHAR(64), nullable=False, unique=True, doc="sha256 of the issued token."
    )
    scopes: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(sa.Text),
        nullable=False,
        server_default=sa.text("'{}'::text[]"),
        doc=(
            "Only 'export:read', 'export:audio' and 'callback:report' are "
            "accepted. Checked in addition to the permission, so a token "
            "scoped to callbacks cannot read the export even if the role could."
        ),
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.true(), doc="Revocation switch."
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Optional hard expiry."
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc="Last accepted request. A token nobody uses is a token to revoke.",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Which admin issued it.",
    )
