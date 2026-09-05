"""Add ``installations.push_token`` — the FCM registration token (T55, §4.6).

A separate revision rather than an edit to 001, even though 001's pre-release
licence would still allow the edit. The licence exists so that "add two values
to an enum that shipped an hour ago" does not become noise in a history people
read; it is not a reason to make a *column* appear retroactively. Editing 001
would leave every database already at head 001 silently without the column —
``upgrade head`` is a no-op for them — while the model expects it, and the
first symptom would be an ``UndefinedColumn`` at runtime on somebody else's
machine. Now that the app is being installed on real handsets, that is a worse
trade than one small file.

**The column holds a credential** (N26): possessing it lets anyone wake the
handset through Google's infrastructure. It is never logged, never returned on
a panel DTO, and never leaves the server. See ``core/push.py`` for why the
send interface cannot carry a payload either.

Nullable with no default and no backfill: a phone has no token until its app
reports one, and ``NULL`` is the honest way to say "we have no address for this
phone", which is exactly what :meth:`CommandService.deliver` branches on.

Revision ID: 002
Revises: 001
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "installations",
        # No ``comment=``: nothing else in this schema carries a database
        # comment, and one column that does makes ``alembic check`` demand a
        # revision to remove it on every run. The reasoning lives in the model's
        # ``doc=`` and in this file's docstring, which is where people read it.
        sa.Column("push_token", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("installations", "push_token")
