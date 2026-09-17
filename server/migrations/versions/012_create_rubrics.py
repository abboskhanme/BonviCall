"""Create the ``rubrics`` table and seed it with the rubric pinned in code.

═══ What this does, and what it deliberately does not ═════════════════════
One new table and one row. **No ``ALTER TABLE`` on anything that exists, no
enum touched, no data rewritten** — deploying this to a running system adds a
table holding the rubric that system is already scoring with, and changes no
behaviour on the day it ships.

SPEC-ANALYTICS §2.5 pinned the rubric in code for phase 1 and said phase 2
would read the active row instead. This is that revision: ``RubricService``
reads the active row, and falls back to ``rubric_default.DEFAULT_RUBRIC`` when
the table is empty. Both halves of that sentence matter — the seed below is the
same constant, so a seeded database and an unseeded one produce the same score
under the same ``"v1"``.

═══ Why the seed IMPORTS the rubric instead of copying it ═════════════════
A migration is normally self-contained: revision 010 writes its settings keys
out literally so a reviewer reads them in the diff, and so a later change to the
application cannot rewrite history. Two rules outweigh that here.

1. **Language.** The rubric's labels and descriptions are Uzbek, and Uzbek text
   in a ``.py`` file is legal in exactly six files (CONVENTIONS.md §14);
   ``rubric_default.py`` is one of them and a migration is not.
2. **One copy.** 220 lines of criteria duplicated here is a second rubric that
   silently becomes the wrong one the first time somebody edits the real one.

The trade-off is stated so nobody has to rediscover it: **changing
``DEFAULT_RUBRIC`` means bumping ``DEFAULT_RUBRIC_VERSION`` in the same commit**
(§2.5). The seed writes ``version=DEFAULT_RUBRIC_VERSION``, so after a bump a
fresh database seeds "v2" while a database migrated last month keeps its "v1" —
the two never both claim to be v1 while holding different criteria. A score's
``rubric_version`` therefore still resolves to the criteria that produced it.

``created_by`` is NULL: nobody published this one, the deployment did.

Revision ID: 012
Revises: 011
Create Date: 2026-09-17
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from src.modules.analysis.rubric_default import DEFAULT_RUBRIC, DEFAULT_RUBRIC_VERSION

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_rubrics_table = sa.table(
    "rubrics",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("version", sa.Integer),
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
    sa.column("is_active", sa.Boolean),
    sa.column("blocks", postgresql.JSONB),
    sa.column("red_flags", postgresql.JSONB),
    sa.column("extra_rules", sa.Text),
    sa.column("created_by", postgresql.UUID(as_uuid=True)),
)


#: The one row this revision seeds. A module constant rather than a literal
#: inside ``upgrade()`` so a test can assert its shape without a database —
#: ``test_rubric.py::test_the_migration_seeds_the_rubric_as_json_arrays``.
SEED_ROWS: list[dict[str, object]] = [
    {
        # Written here rather than left to the ORM default: ``bulk_insert``
        # issues plain SQL and never runs a Python-side column default, which
        # would leave the primary key NULL.
        "id": uuid.uuid4(),
        "version": DEFAULT_RUBRIC_VERSION,
        "name": DEFAULT_RUBRIC["name"],
        "description": DEFAULT_RUBRIC["description"],
        "is_active": True,
        # Handed over as Python lists. The columns are declared JSONB, so
        # SQLAlchemy serialises them once; passing ``json.dumps(...)`` instead
        # stores the whole rubric as a JSON *string* —
        # ``jsonb_array_length(blocks)`` then fails with "cannot get array
        # length of a scalar", and the first symptom would have been a rubric
        # page with no blocks on it.
        "blocks": DEFAULT_RUBRIC["blocks"],
        "red_flags": DEFAULT_RUBRIC["red_flags"],
        # No instructions: that text is something a person writes.
        "extra_rules": None,
        # Nobody published this one, the deployment did.
        "created_by": None,
    }
]


def upgrade() -> None:
    op.create_table(
        "rubrics",
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("blocks", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("red_flags", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("extra_rules", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_rubrics_created_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rubrics")),
        sa.UniqueConstraint("version", name=op.f("uq_rubrics_version")),
    )
    # "Exactly one active rubric" is a database fact, not a habit. Partial, so
    # historical versions may be as many as they like: two `is_active = true`
    # rows made `scalar_one_or_none()` raise MultipleResultsFound in
    # BonviZvonki, which stopped ALL scoring with a 500.
    op.create_index(
        "ix_rubrics_single_active",
        "rubrics",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.bulk_insert(_rubrics_table, SEED_ROWS)


def downgrade() -> None:
    """Drop the table. Nothing else needs undoing.

    A score's ``rubric_version`` survives this: it is a string on
    ``call_scores`` and not a foreign key, deliberately, so the analysis output
    of a downgraded database still says which criteria produced it — and
    ``RubricService.active()`` falls back to the pinned default, so scoring
    keeps working with the table gone.
    """
    op.drop_index("ix_rubrics_single_active", table_name="rubrics")
    op.drop_table("rubrics")
