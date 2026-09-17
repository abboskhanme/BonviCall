"""Create the sales-control schema.

═══ What this does, and what it deliberately does not ═════════════════════
Five new tables and seven new ``app_settings`` rows. **No ``ALTER TABLE`` on
anything that exists, no enum touched, no data rewritten.** Deploying this to a
running system adds tables nothing reads yet and a feature flag that is off, so
the day it ships it changes no behaviour at all.

``sales.digest_enabled`` is seeded **false** for the same reason
``analysis.enabled`` and ``enrolment.callback_enabled`` are: the digest is the
one thing in this module that would leave the machine, and nothing may start
doing that because a migration ran. In this repository it could not anyway —
the only transport implementation writes a log line
(``modules/sales/telegram.py``) — but the switch is the rollback either way,
and a feature that arrives already on is a feature nobody chose.

═══ The generated phone key ═══════════════════════════════════════════════
``sale_partners.phone_key`` is ``GENERATED ALWAYS … STORED`` and its expression
is the one ``core.phone.phone_key_sql`` produces — character for character the
expression revision 001 put on ``calls.remote_number_key``. That is the whole
point: the sales key and the calls key are the two sides of one join, and if
they ever disagreed the join would return nothing, with no error and no clue
(CONVENTIONS.md §7).

It is generated from ``matchable_phone`` rather than from ``phone``, because
three refusals stand between what SAP wrote and what we are willing to match on
— a foreign number whose last nine digits coincidentally look Uzbek, a
fabricated one, and one that is not a number at all. Those live in
``rules.matchable_phone`` (108 of 3,531 contractors measured) and must not be
taught to ``core/phone.py``, which is shared with the handset.

═══ No PostgreSQL enum types ══════════════════════════════════════════════
``sales.op_type`` is a ``VARCHAR`` with no constraint at all: that vocabulary is
SAP's, not ours, and a type they add tomorrow must not need a migration — it
lands in ``other`` and is counted separately in the import report.
``sale_reviews.status`` and ``.reason`` ARE ours and closed, so they get a
CHECK; the precedent for the shape is ``call_analysis_state.failure_stage``
(revision 010) and the survey tables (revision 015). This revision therefore
declares no ``PG_ENUMS`` block and
``test_migration_enum_table_matches_core_enums`` is unaffected.

═══ Why the settings seed IMPORTS the walk-in codes ═══════════════════════
A migration is normally self-contained — revision 010 writes its settings out
literally so a reviewer reads them in the diff. Revision 012 already made the
exception for the rubric, and the same two reasons hold here. The codes are
SAP's own Cyrillic identifiers (``К00001`` — the ``К`` is U+041A, not a Latin
``K``), and a second copy of that list is a list that silently becomes the
wrong one the first time somebody edits the real one. The seed is the default
FLOOR; ``rules.parse_partner_codes`` falls back to the same constant when the
row is unreadable, so a seeded database and an unseeded one behave identically.

Revision ID: 014
Revises: 013
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from src.modules.sales.rules import (
    DEFAULT_WALK_IN_LIMIT_USD,
    DEFAULT_WINDOW_DAYS,
    GENERIC_PARTNER_CODES,
)

revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The last-9 key, produced by ``core.phone.phone_key_sql`` over
#: ``matchable_phone``. Written out rather than imported so that this revision
#: keeps its meaning after the application's helper has moved on — exactly as
#: revision 001 writes out the same expression for ``calls.remote_number_key``.
#: A test compares the two.
_PHONE_KEY = (
    "CASE WHEN (length(regexp_replace(matchable_phone, '[^0-9]', '', 'g')) >= 9) "
    "THEN right(regexp_replace(matchable_phone, '[^0-9]', '', 'g'), 9) END"
)


#: §3.8's shape: every key with its documented default.
SETTINGS_SEED: tuple[tuple[str, object, str], ...] = (
    # R1's window, in whole Asia/Tashkent days: the sale day plus the N before
    # it. Three, because a sale is agreed within a few days of the conversation
    # that produced it; a much wider window makes every sale look justified.
    ("sales.window_days", DEFAULT_WINDOW_DAYS, "int"),
    # The shared codes walk-in buyers are booked under. Under one of these the
    # question "was this customer spoken to?" has no meaning — one code, a
    # hundred people — so they are answered with a ticket limit instead.
    ("sales.walk_in_codes", ",".join(sorted(GENERIC_PARTNER_CODES)), "string"),
    # Whole dollars: ``value_type`` decides which editor the panel renders and
    # it has no float.
    ("sales.walk_in_limit_usd", DEFAULT_WALK_IN_LIMIT_USD, "int"),
    # Our own departments' SAP codes. EMPTY by default, and empty is a real
    # answer: the list only ever FILLS the out-of-scope flag at the start of an
    # import, and a non-empty default would take a real customer out of sales
    # control on day one without anybody deciding it.
    ("sales.internal_codes", "", "string"),
    # OFF. See the note at the top of this file.
    ("sales.digest_enabled", False, "bool"),
    ("sales.digest_chat_id", "", "string"),
    # 0 — every sale is in the message. A threshold above zero never hides a
    # sale of UNKNOWN value: "I do not know" is not "small".
    ("sales.digest_min_amount_usd", 0, "int"),
)

_settings_table = sa.table(
    "app_settings",
    sa.column("key", sa.String),
    sa.column("value", postgresql.JSONB),
    sa.column("value_type", sa.String),
)


def upgrade() -> None:
    # ── The SAP contractor catalogue ──────────────────────────
    op.create_table(
        "sale_partners",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("group_name", sa.String(length=64), nullable=True),
        sa.Column("branch", sa.String(length=128), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("matchable_phone", sa.String(length=64), nullable=True),
        sa.Column(
            "phone_key",
            sa.CHAR(length=9),
            sa.Computed(_PHONE_KEY, persisted=True),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("telegram_link", sa.String(length=255), nullable=True),
        sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_partners")),
    )
    # The SAP code is the idempotency key a re-import upserts on. A unique
    # INDEX rather than a UNIQUE CONSTRAINT, because that is what
    # ``mapped_column(unique=True, index=True)`` puts in ``Base.metadata`` —
    # writing the constraint out as well leaves a permanent ``alembic check``
    # diff on a schema that is otherwise correct (the lesson of revision 013).
    op.create_index(op.f("ix_sale_partners_code"), "sale_partners", ["code"], unique=True)
    # Control applies to `Клиенты` only; the other groups are filtered out.
    op.create_index(op.f("ix_sale_partners_group_name"), "sale_partners", ["group_name"])
    # Every read of the catalogue filters on it — which is what makes marking a
    # contractor inactive enough, and deleting the row unnecessary.
    op.create_index(op.f("ix_sale_partners_is_active"), "sale_partners", ["is_active"])
    # The join to ``calls.remote_number_key``. Partial, like ``ix_calls_remote``:
    # a contractor with no usable number is not a row anything ever looks up.
    op.create_index(
        "ix_sale_partners_phone_key",
        "sale_partners",
        ["phone_key"],
        postgresql_where=sa.text("phone_key IS NOT NULL"),
    )

    # ── The operations register ───────────────────────────────
    op.create_table(
        "sales",
        sa.Column("external_id", sa.String(length=32), nullable=False),
        sa.Column("doc_number", sa.String(length=32), nullable=True),
        sa.Column("op_type", sa.String(length=32), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("branch", sa.String(length=128), nullable=True),
        sa.Column("direction", sa.String(length=64), nullable=True),
        sa.Column("partner_code", sa.String(length=16), nullable=False),
        sa.Column("partner_name", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=3), nullable=True),
        sa.Column("currency", sa.String(length=8), server_default="USD", nullable=False),
        sa.Column("amount_usd", sa.Numeric(precision=18, scale=3), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("attributed_call_id", sa.UUID(), nullable=True),
        sa.Column("call_agent_id", sa.UUID(), nullable=True),
        sa.Column("source_file", sa.String(length=255), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        # SET NULL on all three: a sale is a fact in SAP and must survive an
        # employee being removed from our roster. Calls are never deleted in
        # this product (UC-26), so the third is belt to braces.
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], name=op.f("fk_sales_agent_id_agents"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["attributed_call_id"], ["calls.id"], name=op.f("fk_sales_attributed_call_id_calls"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["call_agent_id"], ["agents.id"], name=op.f("fk_sales_call_agent_id_agents"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales")),
    )
    op.create_index(op.f("ix_sales_external_id"), "sales", ["external_id"], unique=True)
    op.create_index(op.f("ix_sales_occurred_on"), "sales", ["occurred_on"])
    op.create_index(op.f("ix_sales_branch"), "sales", ["branch"])
    op.create_index(op.f("ix_sales_partner_code"), "sales", ["partner_code"])
    op.create_index(op.f("ix_sales_agent_id"), "sales", ["agent_id"])
    op.create_index(op.f("ix_sales_attributed_call_id"), "sales", ["attributed_call_id"])
    op.create_index(op.f("ix_sales_call_agent_id"), "sales", ["call_agent_id"])
    # The digest's replay guard reads max() of this.
    op.create_index(op.f("ix_sales_imported_at"), "sales", ["imported_at"])
    # The evidence join and the previous-sale window function both walk "this
    # customer's sales in date order"; without this they walk the register.
    op.create_index("ix_sales_partner_day", "sales", ["partner_code", "occurred_on"])
    # Every control query opens with ``op_type = 'sale'`` and then a date range.
    op.create_index("ix_sales_type_day", "sales", ["op_type", "occurred_on"])

    # ── The manager's decision ────────────────────────────────
    op.create_table(
        "sale_reviews",
        sa.Column("sale_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        # Our own closed vocabulary, so the invalid values are unrepresentable
        # rather than merely unused.
        sa.CheckConstraint("status IN ('justified', 'confirmed')", name=op.f("ck_sale_reviews_review_status_known")),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN ('walk_in', 'telegram', 'visit', 'contract', 'other')",
            name=op.f("ck_sale_reviews_review_reason_known"),
        ),
        # A reason explains a JUSTIFICATION; a confirmed suspicion has a note.
        sa.CheckConstraint("reason IS NULL OR status = 'justified'", name=op.f("ck_sale_reviews_reason_only_when_justified")),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], name=op.f("fk_sale_reviews_sale_id_sales"), ondelete="CASCADE"),
        # NULLABLE and SET NULL: the decision must outlive the account, because
        # "who has the most unjustified sales" is read off these rows.
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name=op.f("fk_sale_reviews_reviewed_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_reviews")),
    )
    # ONE decision per sale — a second row would show the sale twice.
    op.create_index(op.f("ix_sale_reviews_sale_id"), "sale_reviews", ["sale_id"], unique=True)
    op.create_index(op.f("ix_sale_reviews_status"), "sale_reviews", ["status"])
    op.create_index(op.f("ix_sale_reviews_reviewed_by"), "sale_reviews", ["reviewed_by"])

    # ── SAP branch -> our employee ────────────────────────────
    #
    # No surrogate id: the primary key is the branch NAME, because rows are
    # looked up by the SAP name and referenced from nowhere else.
    # ``app_settings`` already keys on its natural string.
    op.create_table(
        "sale_branches",
        sa.Column("branch", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("matched_automatically", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], name=op.f("fk_sale_branches_agent_id_agents"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("branch", name=op.f("pk_sale_branches")),
    )
    op.create_index(op.f("ix_sale_branches_agent_id"), "sale_branches", ["agent_id"])

    # ── The daily message log ─────────────────────────────────
    op.create_table(
        "sale_digests",
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("covered_on", sa.Date(), nullable=True),
        sa.Column("watermark", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chat_id", sa.String(length=32), nullable=True),
        sa.Column("ok", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_digests")),
    )
    # The replay guard reads ``kind = 'daily' AND ok`` and takes max(watermark).
    op.create_index(op.f("ix_sale_digests_kind"), "sale_digests", ["kind"])
    op.create_index(op.f("ix_sale_digests_ok"), "sale_digests", ["ok"])

    op.bulk_insert(
        _settings_table,
        [
            {"key": key, "value": value, "value_type": value_type}
            for key, value, value_type in SETTINGS_SEED
        ],
    )


def downgrade() -> None:
    """Drop the five tables and remove the seeded settings.

    Nothing outside this revision references them: ``sales`` points OUT (at
    ``agents``, ``calls`` and ``users``) and nothing points back, which is what
    makes the whole module removable in one step. The ``calls`` rows a sale was
    attributed to are untouched — the attribution lives on the sale.
    """
    op.execute(
        sa.delete(_settings_table).where(
            _settings_table.c.key.in_([key for key, _, _ in SETTINGS_SEED])
        )
    )
    op.drop_index(op.f("ix_sale_digests_ok"), table_name="sale_digests")
    op.drop_index(op.f("ix_sale_digests_kind"), table_name="sale_digests")
    op.drop_table("sale_digests")

    op.drop_index(op.f("ix_sale_branches_agent_id"), table_name="sale_branches")
    op.drop_table("sale_branches")

    op.drop_index(op.f("ix_sale_reviews_reviewed_by"), table_name="sale_reviews")
    op.drop_index(op.f("ix_sale_reviews_status"), table_name="sale_reviews")
    op.drop_index(op.f("ix_sale_reviews_sale_id"), table_name="sale_reviews")
    op.drop_table("sale_reviews")

    op.drop_index("ix_sales_type_day", table_name="sales")
    op.drop_index("ix_sales_partner_day", table_name="sales")
    op.drop_index(op.f("ix_sales_imported_at"), table_name="sales")
    op.drop_index(op.f("ix_sales_call_agent_id"), table_name="sales")
    op.drop_index(op.f("ix_sales_attributed_call_id"), table_name="sales")
    op.drop_index(op.f("ix_sales_agent_id"), table_name="sales")
    op.drop_index(op.f("ix_sales_partner_code"), table_name="sales")
    op.drop_index(op.f("ix_sales_branch"), table_name="sales")
    op.drop_index(op.f("ix_sales_occurred_on"), table_name="sales")
    op.drop_index(op.f("ix_sales_external_id"), table_name="sales")
    op.drop_table("sales")

    op.drop_index("ix_sale_partners_phone_key", table_name="sale_partners")
    op.drop_index(op.f("ix_sale_partners_is_active"), table_name="sale_partners")
    op.drop_index(op.f("ix_sale_partners_group_name"), table_name="sale_partners")
    op.drop_index(op.f("ix_sale_partners_code"), table_name="sale_partners")
    op.drop_table("sale_partners")
