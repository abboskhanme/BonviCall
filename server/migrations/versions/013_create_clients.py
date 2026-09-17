"""Create ``client_contacts`` — the phone-key dictionary behind the Clients section.

═══ What this does, and what it deliberately does not ══════════════════════
**One new table. No ``ALTER TABLE`` on anything that exists, no enum touched,
no data rewritten, no settings key added.** Deploying this to a running system
adds an empty table and changes nothing until somebody uploads a contacts file.

The ``clients`` module that names this revision owns **no table**: the customer
directory is a grouped aggregate over ``calls`` and ``agents``, recomputed per
request (``server/src/modules/clients/service.py``). That is the same decision
CONVENTIONS.md §10 records for the gap report and the capture-rate delta — a
computed result is not stored while its inputs can still arrive. So the whole
of this revision is the dictionary that gives those aggregated numbers a name.

═══ Why ``phone_key`` is a plain column here and generated on ``calls`` ════
``calls.remote_number_key`` is ``GENERATED ALWAYS AS (…) STORED`` because the
source number arrives from a handset and a value the database derives cannot be
forgotten by a new code path (SPEC §3.0). Here the source number arrives inside
an uploaded file, is normalised once by ``core.phone.phone_key`` — the same
rule, the same function that produces the generated expression — and is what
makes the row exist at all: a file row whose number yields no key is counted
and dropped, never stored. There is nothing to generate the key *from* once the
row is written.

The two sides of the join are therefore produced by one rule, which is the
property that matters (CONVENTIONS.md §7). ``CHAR(9)`` on both sides.

═══ No foreign keys ════════════════════════════════════════════════════════
The dictionary is joined to ``calls`` on a VALUE, not on an identity: a contact
exists before anybody has called the number and survives after the calls are
gone, and ``calls.remote_number_key`` is NULL for anything below nine digits by
design (N37). A foreign key would make the dictionary depend on traffic and
would make deleting a call able to fail.

═══ No PostgreSQL enum for ``kind`` ════════════════════════════════════════
``client_contacts.kind`` is ``VARCHAR(16)``, adopted from BonviZvonki with its
stated reason: adding a kind must not need an ``ALTER TYPE`` on a live
database. §10 requires a native enum for the vocabularies the DEVICE contract
depends on; this one is panel-only and never crosses the device or service
surface. The closed set is enforced at the wire boundary by
``contacts.rules.ContactKind``. This revision therefore declares no
``PG_ENUMS`` table, and ``tests/test_model_registry.py`` stays satisfied
because it compares the enum types the migrations create against
``core.enums.PG_ENUM_TYPES`` — and this revision creates none.

Revision ID: 013
Revises: 012
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "client_contacts",
        sa.Column("phone_key", sa.CHAR(length=9), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("raw_name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), server_default=sa.text("'unknown'"), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("source_file", sa.String(length=255), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_client_contacts")),
    )
    # ⚠️ ONE ROW PER NUMBER is the whole design, and this UNIQUE index is what
    # makes it true. The upstream provider this data escapes from has no such
    # constraint and duplicates on every re-import — measured, 90 contacts
    # imported twice became 270. Here the second upload overwrites.
    #
    # A unique INDEX rather than a UNIQUE CONSTRAINT, because that is what
    # ``mapped_column(unique=True, index=True)`` puts in ``Base.metadata`` —
    # one object, not two. Writing the constraint out as well produced a
    # permanent ``alembic check`` diff (a constraint to drop and an index to
    # make unique) on a schema that was otherwise correct, which is the drift
    # CONVENTIONS.md §10 has the check for.
    op.create_index(
        op.f("ix_client_contacts_phone_key"),
        "client_contacts",
        ["phone_key"],
        unique=True,
    )
    # "Which other numbers of ours carry this code" is asked once per contact
    # card, and "show me everything still without a code" is the working list
    # an admin cleans the dictionary from.
    op.create_index(op.f("ix_client_contacts_code"), "client_contacts", ["code"])
    # The list filters on it and the header counts group by it.
    op.create_index(op.f("ix_client_contacts_kind"), "client_contacts", ["kind"])


def downgrade() -> None:
    """Drop the table. Nothing else needs undoing.

    No call, no agent and no score references it: the directory joins on the
    phone key at read time, so with the table gone every customer simply falls
    back to the name the handset resolved (``calls.contact_name``) and the
    Clients page keeps working with fewer names on it.
    """
    op.drop_index(op.f("ix_client_contacts_kind"), table_name="client_contacts")
    op.drop_index(op.f("ix_client_contacts_code"), table_name="client_contacts")
    op.drop_index(op.f("ix_client_contacts_phone_key"), table_name="client_contacts")
    op.drop_table("client_contacts")
