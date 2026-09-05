"""Add ``installations.app_version_code`` — the number the gate compares (N34).

``AppInfoIn.version_code`` arrives on every enrolment and was thrown away, and
the app sends ``X-App-Version-Code`` on every request. With nowhere to keep it,
``installations._version_code`` reconstructed a code from the human version
string by concatenating its digits: ``"1.0.0"`` became ``100``, which looks
plausible, and ``"1.4.0"`` became ``140`` when the real code might be ``14``.

That is not only a gap in a report. The version gate (N34) compares this number
against ``app.min_supported_version_code``, so raising the minimum was deciding
which phones stop reporting on the basis of a guess. Nothing catches it: both
numbers are integers and the comparison always succeeds.

Nullable, no backfill. A row written before this revision has no reported code,
and ``NULL`` is the honest way to say so — the gate keeps its old fallback for
those rows and continues to fail **open**, because refusing a client we cannot
identify is the one outcome N34 forbids.

Revision ID: 003
Revises: 002
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "installations", sa.Column("app_version_code", sa.Integer(), nullable=True)
    )
    op.create_index(
        # The min-version impact query filters on it across the whole fleet,
        # and it is the query an admin runs before stranding people.
        "ix_installations_app_version_code",
        "installations",
        ["app_version_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_installations_app_version_code", table_name="installations")
    op.drop_column("installations", "app_version_code")
