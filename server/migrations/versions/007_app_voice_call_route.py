"""Add ``app_voice_call`` to the ``capture_route`` enum (T71b).

``MediaRecorder.AudioSource.VOICE_CALL`` is the one app-side source that
carries both parties to the conversation. Android refuses it to an ordinary app
from targetSdk 29 onwards; the ``legacy28`` flavour targets 28 precisely so it
can ask, and CallSentry — which works on this fleet's handsets — ships the same
way and probes the same source first.

Until now the app could not report it even if it got it: the route would have
had to be filed as ``app_voice_recognition``, which would make the M0 table
claim the far end was captured by a source that did not capture it.

``ALTER TYPE ... ADD VALUE`` is additive and irreversible — PostgreSQL has no
``DROP VALUE`` — so ``downgrade`` is a documented no-op rather than a lie that
appears to work.

Revision ID: 007
Revises: 006
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Written out literally rather than interpolated: the value belongs in the
    # diff a reviewer reads, and ``test_migration_enum_table_matches_core_enums``
    # reads these statements to know what the database's enums hold.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE capture_route ADD VALUE IF NOT EXISTS 'app_voice_call'")


def downgrade() -> None:
    """No-op: PostgreSQL cannot remove an enum value.

    Removing it properly means recreating the type and rewriting every column
    that uses it — ``recordings`` and ``device_health`` — to undo one additive
    value. Leaving it in place costs nothing.
    """
