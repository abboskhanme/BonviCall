"""Add ``installations.previous_refresh_token_hash`` — reuse detection (N24).

Refresh tokens rotate: each use mints a new one and the old becomes spent.
Presenting a spent one is the classic signal that a token was copied — but
until now the server could only *refuse* it, never act on it, because a spent
hash matched no row and there was no installation whose credentials to kill.

That left the worst version of the failure: a thief who used the stolen token
**first** kept a working pair, the real handset was refused with
``refresh_reused``, and nothing on the server could tell the two apart or say
that anything had happened.

Keeping the previous hash makes the reuse *attributable*. The revision adds one
nullable column and nothing else; there is no backfill, because a token issued
before this has no predecessor to record and ``NULL`` says exactly that.

A separate revision, not an edit to 001: there are databases at head, so a
column added to the baseline would never reach them while the model expected it
(the reasoning is in 002, and it is now the rule).

Revision ID: 005
Revises: 004
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "installations",
        sa.Column("previous_refresh_token_hash", sa.CHAR(64), nullable=True),
    )
    op.create_index(
        # Reuse is looked up by this hash on a refresh that missed, so it is a
        # lookup on the failure path — rare, and the one time latency matters
        # least. Indexed anyway: without it the check is a sequential scan of
        # every installation on every refused refresh, which is a free way for
        # anyone holding one spent token to make the server work.
        "ix_installations_previous_refresh",
        "installations",
        ["previous_refresh_token_hash"],
        postgresql_where=sa.text("previous_refresh_token_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_installations_previous_refresh", table_name="installations")
    op.drop_column("installations", "previous_refresh_token_hash")
