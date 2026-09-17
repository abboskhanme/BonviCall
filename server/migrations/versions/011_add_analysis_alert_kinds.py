"""Add the two analysis alert kinds to ``alert_kind``.

═══ Why this exists ═══════════════════════════════════════════════════════
``SPEC-ANALYTICS.md`` §2.1 asks for these two values and §5 relies on them, but
revision 010 created the analysis schema without them, so until now the
analysis module had nothing honest to raise:

* ``analysis_job_failed`` — ``worker.alert_on_repeated_failure`` mapped every
  job except ``backup_verify`` onto ``retention_job_failed``. A stalled AI
  pipeline therefore raised an alert whose Uzbek text says old recordings are
  not being deleted, and an admin reading it at 22:00 would go and look at
  retention. An alert that names the wrong subsystem is worse than none,
  because it is acted on.
* ``analysis_cost_cap_reached`` — ``pipeline.run_queue`` stops when a monthly
  cap is reached and could only write a WARNING to the log. A cap that stops
  the pipeline silently is indistinguishable from a pipeline that is broken,
  and §10 task 12's controlled trial is *designed* to end on this alert.

``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction block in
PostgreSQL, hence the autocommit block. It is additive and irreversible —
PostgreSQL has no ``DROP VALUE`` — so ``downgrade`` is a documented no-op
rather than a lie that appears to work (revision 004 set that shape, revision
006 records the full reason).

No table is altered and no row is rewritten: ``alerts.kind`` simply gains two
values it can hold, and no existing row holds them.

Revision ID: 011
Revises: 010
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Written out literally rather than interpolated: the values belong in the
    # diff a reviewer reads, and ``test_migration_enum_table_matches_core_enums``
    # reads these statements to know what the database's enums hold.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE alert_kind ADD VALUE IF NOT EXISTS 'analysis_job_failed'")
        op.execute(
            "ALTER TYPE alert_kind ADD VALUE IF NOT EXISTS 'analysis_cost_cap_reached'"
        )


def downgrade() -> None:
    """No-op: PostgreSQL cannot remove an enum value.

    Removing one properly means recreating ``alert_kind`` and rewriting
    ``alerts`` together with the partial unique index on ``dedupe_key`` that
    makes "one open alert per cause" a database fact. That is a table rewrite
    to undo two values nothing holds; leaving them in place costs nothing.
    """
