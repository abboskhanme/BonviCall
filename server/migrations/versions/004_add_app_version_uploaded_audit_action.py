"""Add ``app_version_uploaded`` to the ``audit_action`` enum (T58, N27).

Uploading an APK is the moment a binary enters the distribution channel: the
bytes a salesperson's phone will install arrive, are hashed, and have their
signing certificate read. Publishing is the dangerous act and already has an
action; uploading is the one that answers "where did this build come from and
who put it there", which is exactly what an append-only audit log is for.

``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction block in
PostgreSQL, hence the autocommit block. It is additive and irreversible —
PostgreSQL has no ``DROP VALUE`` — so ``downgrade`` is a documented no-op
rather than a lie that appears to work.

Revision ID: 004
Revises: 003
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_VALUE = "app_version_uploaded"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{NEW_VALUE}'")


def downgrade() -> None:
    """No-op: PostgreSQL cannot remove an enum value.

    Removing it properly means recreating the type and rewriting every column
    that uses it, which would rewrite ``audit_log`` — an append-only table
    protected by a trigger (N27). Leaving the value in place costs nothing; a
    downgrade that silently rewrote the audit log would cost the thing the log
    exists to provide.
    """
