"""Add ``provider`` to the ``call_source`` enum (T-MZ).

Calls that reach us from MoiZvonki's cloud rather than from one of our own
handsets. Its own value rather than reusing ``live_capture``, because the two
populations are not comparable: a provider row has no installation health
behind it, no capability history, and can never carry
``app_not_running`` as its reason for having no audio. A gap report that mixed
them would average a fleet we control with one we do not.

``ALTER TYPE ... ADD VALUE`` is additive and irreversible — PostgreSQL has no
``DROP VALUE`` — so ``downgrade`` is a documented no-op rather than a lie.

Revision ID: 008
Revises: 007
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Written out literally: the value belongs in the diff a reviewer reads,
    # and ``test_migration_enum_table_matches_core_enums`` reads these
    # statements to know what the database's enums hold.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE call_source ADD VALUE IF NOT EXISTS 'provider'")


def downgrade() -> None:
    """No-op: PostgreSQL cannot remove an enum value.

    Undoing it properly means recreating the type and rewriting ``calls``,
    which is the largest table in the product, to remove one additive value.
    """
