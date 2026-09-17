"""Sales-control ORM models.

Ported from BonviZvonki ``modules/sales/infrastructure/models.py``. Five tables:

  · ``sale_partners`` — the SAP contractor catalogue (code -> name, phone);
  · ``sales``         — the operations register (sale, payment, return, …);
  · ``sale_reviews``  — the manager's decision (the ONLY subjective row here);
  · ``sale_branches`` — SAP branch -> our employee;
  · ``sale_digests``  — the log of daily messages that were (not) sent.

⚠️ THE RULE'S RESULT ("suspicious") IS STORED NOWHERE. It is recomputed on
every request: a call can synchronise AFTER the sale (R7 — a handset out of
coverage delivers its backlog days later) and a "suspicious" flag written at
import time would by then be a lie that nobody would remember to recompute.
``rules.py`` says it at length; this is the schema consequence.

════════════════════════════════════════════════════════════════
 WHAT CHANGED AGAINST BONVIZVONKI, AND WHY
════════════════════════════════════════════════════════════════

**The phone key is produced by the database.** ``sale_partners.phone_key`` is a
``GENERATED ALWAYS … STORED`` column built by ``core.phone.phone_key_sql`` —
the same function that produces ``calls.remote_number_key`` — so the two sides
of the join cannot drift. Theirs is a plain column written by the importer with
a second, hand-rolled last-9 implementation, and a difference of one character
between the two would make every join silently return nothing.

**The eligibility test moved into its own column.** ``phone`` is what SAP wrote,
kept for the screen; ``matchable_phone`` is the same value *only when we are
willing to match on it* (``rules.matchable_phone`` refuses foreign and fake
numbers, 108 of 3531 measured); ``phone_key`` is the database's last-9 of that.
Three columns rather than two, because the generated key cannot carry those
three refusals and ``core/phone.py`` must not learn them — it is shared with
the handset.

**``sales`` has no copy of the phone key.** Theirs copies it from the catalogue
onto every sale row, with a comment about halving the cost of the rules query.
The rules query does not use it: the evidence is gathered by partner CODE (a
customer is a code, not a number). What the copy actually fed was the
previous-sale window function and the customer card, and both are keyed on the
code here — which is *more* correct, see ``service._previous_sale_cte``.
Dropping it deletes the copy, the coalescing upsert rule that protected it, one
half of ``backfill_sale_links``, and the whole class of "the register was
imported before the catalogue, so a day of sales has no phone" bug.

**``sales.attributed_call_id`` is new.** It names the conversation that
attributed the sale, so the panel can open the recording from the row — in
BonviZvonki the evidence is a date and a name with nothing behind it, because
that product has no recordings. It is also what makes this module's read of
``calls`` legal under CONVENTIONS.md §2 (a module may import another's models
where it has a foreign key into it), and what keeps ``call_agent_id`` honest:
the two are written from one subquery in ``service.refresh_sale_attribution``
and cannot disagree.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UUIDMixin, phone_key_computed


class SalePartnerModel(Base, UUIDMixin, TimestampMixin):
    """A contractor — one row per SAP ``Код БП``.

    Two sources: the contractor catalogue (wb3) is the primary one; the balance
    report (wb1/wb2) contributes ONLY a phone number the catalogue was missing.

    The whole point of this table is :attr:`phone_key`. The sales file carries
    NO phone number, so the only route from a sale to a conversation is:
    sale -> customer code -> catalogue -> phone -> ``calls``.
    """

    __tablename__ = "sale_partners"

    code: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        unique=True,
        index=True,
        doc=(
            "`К02711` — the SAP code, with a CYRILLIC К. The idempotency key: "
            "a re-import upserts on this column."
        ),
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False, doc="As SAP has it.")
    group_name: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        index=True,
        doc=(
            "`Клиенты`, `Поставщики импорт`… Control applies to `Клиенты` only "
            "— there is no sales call to a supplier."
        ),
    )
    branch: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True, doc="The SAP branch the catalogue files them under."
    )
    phone: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        doc=(
            "RAW, for the screen. Never for matching: SAP writes ten different "
            "formats and some cells hold a Telegram handle instead."
        ),
    )
    matchable_phone: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        doc=(
            "The same number, but only when we are willing to match calls on "
            "it — NULL for a foreign or a fabricated one (rules.matchable_phone, "
            "108 of 3531 measured). It exists so the generated key below can be "
            "the one shared last-9 rule and still refuse those three cases."
        ),
    )
    phone_key: Mapped[str | None] = mapped_column(
        sa.CHAR(9),
        phone_key_computed("matchable_phone"),
        nullable=True,
        doc=(
            "GENERATED last-9 key, the join to `calls.remote_number_key`. "
            "Produced by core.phone.phone_key_sql, so this key and the calls "
            "key cannot drift; if they ever did, every join would return "
            "nothing — no error, no clue (N37)."
        ),
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.true(),
        index=True,
        doc="SAP's `Актив`. Inactive contractors are never stored — see the importer.",
    )
    telegram_link: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True, doc="SAP's `Линк` column, shown on the card."
    )
    excluded_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc=(
            "The customer is OUT OF SCOPE; NULL means in scope. SAP holds rows "
            "that are contractors but not buyers — our own departments, the "
            "warehouse, the call centre. A transfer between them is booked as a "
            "sale, and 'was the customer called first?' is meaningless for it: "
            "they sat permanently at the top of the suspicious list and BURIED "
            "the real defects (measured 31.08.2026: 25 contractors, 127 sales "
            "in three weeks, 102 of them suspicious). Their sales are NOT "
            "deleted and the import keeps taking them — only the control query "
            "separates them, so putting a customer back restores the whole "
            "history with no re-import. A timestamptz rather than a bool, like "
            "`agents.archived_at`: it answers WHEN as well as WHETHER."
        ),
    )

    __table_args__ = (
        # Partial, exactly like ``ix_calls_remote`` on the other side of this
        # join: the generated key is NULL for every contractor with no usable
        # number, and those rows are never looked up by key.
        sa.Index(
            "ix_sale_partners_phone_key",
            "phone_key",
            postgresql_where=sa.text("phone_key IS NOT NULL"),
        ),
    )


class SaleModel(Base, UUIDMixin):
    """One SAP operation.

    ⚠️ ``TimestampMixin`` IS DELIBERATELY ABSENT, and the reason is stronger
    here than in BonviZvonki. The daily digest's replay guard compares
    ``max(imported_at)`` against the watermark of the last message it sent, so
    that column must mean "a file was imported" and nothing else. ``updated_at``
    with its ``onupdate`` would also move when the attribution refresh rewrites
    ``attributed_call_id`` — and the digest would then send yesterday's message
    again, which is precisely the failure the watermark exists to prevent.
    """

    __tablename__ = "sales"

    external_id: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        unique=True,
        index=True,
        doc=(
            "SAP's `Номер операции` — the idempotency key. Measured: 2383 "
            "distinct values in 2384 rows (one duplicated pair), which is good "
            "enough to upsert on."
        ),
    )
    doc_number: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        doc=(
            "SAP's `Номер документа` — the piece of paper a manager searches "
            "for. NOT interchangeable with external_id."
        ),
    )
    op_type: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        doc=(
            "A rules.SaleOpType value. Plain text rather than a native enum: "
            "this is SAP's vocabulary, not ours, and a type they add tomorrow "
            "must not need a migration — it lands in `other` and is counted "
            "separately. Our own closed vocabularies (sale_reviews.status) do "
            "get a CHECK. Indexed as the leading column of ix_sales_type_day, "
            "because every control query starts with `op_type = 'sale'`."
        ),
    )
    occurred_on: Mapped[date] = mapped_column(
        sa.Date,
        nullable=False,
        index=True,
        doc=(
            "A DATE, WITH NO TIME. SAP's `Дата регистрации` gives no clock, "
            "which is why the whole module measures its window in whole "
            "Asia/Tashkent days and says so on the screen."
        ),
    )
    branch: Mapped[str | None] = mapped_column(
        sa.String(128),
        nullable=True,
        index=True,
        doc="SAP's `Подразделение`. A PLACE, not a person — see attributed_call_id.",
    )
    direction: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True, doc="SAP's `Направление` — the product line."
    )
    partner_code: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        index=True,
        doc="The customer. **The customer is the code**, never the phone number.",
    )
    partner_name: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        doc=(
            "A COPY taken at import time, so a report still shows the name the "
            "sale went through under after the catalogue is renamed."
        ),
    )
    amount: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(18, 3), nullable=True, doc="The amount in the document's own currency."
    )
    currency: Mapped[str] = mapped_column(
        sa.String(8), nullable=False, server_default="USD", doc="The document's currency."
    )
    amount_usd: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(18, 3),
        nullable=True,
        doc=(
            "The same amount in dollars. The file gives it away free and it "
            "answers the open question 'will we need an exchange-rate table?' "
            "with NO: measured, `Хақдор ($)` always holds the dollar "
            "equivalent whatever the document currency (8.333 $ <-> 100,000 "
            "so'm; 136.240 $ <-> 500 dirham). Numeric, never float (§10)."
        ),
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc=(
            "Derived from `branch` through sale_branches. SET NULL because the "
            "sale row must survive an employee being removed: it is a fact in "
            "SAP and does not depend on our roster."
        ),
    )
    attributed_call_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("calls.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc=(
            "The conversation that attributed this sale: the LATEST non-internal "
            "call to this customer inside the window. The panel opens the "
            "recording from here — evidence you can listen to, which "
            "BonviZvonki cannot offer. A COMPUTED column, rewritten in full by "
            "`service.refresh_sale_attribution` after every import."
        ),
    )
    call_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc=(
            "Who held that conversation — denormalised from attributed_call_id "
            "so the per-employee GROUP BY needs no join to `calls`. It OUTRANKS "
            "agent_id: a branch is a place, and 20 of 34 branches are linked to "
            "nobody, which left 1,100 sales with no employee. Written from the "
            "same subquery as attributed_call_id, so the two cannot disagree."
        ),
    )
    source_file: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True, doc="The file this row last came in on."
    )
    imported_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        index=True,
        doc=(
            "When a FILE last wrote this row. The digest's replay guard reads "
            "max() of this, so it must not move when the attribution refresh "
            "rewrites a derived column — which is why this table has no "
            "TimestampMixin."
        ),
    )

    __table_args__ = (
        # The evidence join and the previous-sale window function both walk
        # "this customer's sales, in date order"; without this they walk the
        # whole register once per report.
        sa.Index("ix_sales_partner_day", "partner_code", "occurred_on"),
        # Every control query opens with `op_type = 'sale'` and then a date
        # range, so op_type leads and carries its own index with it.
        sa.Index("ix_sales_type_day", "op_type", "occurred_on"),
    )


class SaleReviewModel(Base, UUIDMixin):
    """The manager's decision — the only subjective row in this schema.

    The queue shows undecided sales by default, so a sale with a row here drops
    out of it.
    """

    __tablename__ = "sale_reviews"

    sale_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("sales.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        doc=(
            "One decision per sale — changing your mind overwrites. A second "
            "row would make the sale appear twice in the list."
        ),
    )
    status: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        index=True,
        doc="`justified` or `confirmed` — a rules.SaleReviewStatus value.",
    )
    reason: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        doc=(
            "A rules.SaleReviewReason value, and only for `justified`: the list "
            "(walked in, Telegram, a visit…) exists to explain a JUSTIFICATION. "
            "A confirmed suspicion has the note field instead."
        ),
    )
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True, doc="Free text.")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc=(
            "NULLABLE on purpose. ON DELETE SET NULL does not work otherwise, "
            "and the DECISION must outlive the account: the 'who has the most "
            "unjustified sales' figure is read off these rows."
        ),
    )
    reviewed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="When the decision was last made. Rewritten when it changes.",
    )

    __table_args__ = (
        # Our own vocabulary, so the invalid values are unrepresentable rather
        # than merely unused. `op_type` gets no such constraint because that
        # vocabulary is SAP's and open.
        sa.CheckConstraint(
            "status IN ('justified', 'confirmed')", name="review_status_known"
        ),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN "
            "('walk_in', 'telegram', 'visit', 'contract', 'other')",
            name="review_reason_known",
        ),
        # A reason explains a justification; a confirmed suspicion has none.
        sa.CheckConstraint(
            "reason IS NULL OR status = 'justified'", name="reason_only_when_justified"
        ),
    )


class SaleBranchModel(Base, TimestampMixin):
    """SAP branch -> our employee.

    The sales file has NO salesperson's name — only ``Подразделение`` (Бухоро,
    Мастона ёйма, Логистика…). This table is the only route from a sale to a
    person by branch: the import links what it can by name similarity, and the
    manager sets the rest by hand. Measured (22.08.2026): 15 of 29 branches
    matched automatically, 19 with the manual ones = 88.4 % of sales.

    ⚠️ NO ``UUIDMixin`` — the primary key is the branch NAME itself. A surrogate
    id would be dead weight: rows are looked up by the SAP name and referenced
    from nowhere else. ``app_settings`` already keys on its natural string.
    """

    __tablename__ = "sale_branches"

    branch: Mapped[str] = mapped_column(
        sa.String(128), primary_key=True, doc="SAP's `Подразделение`, exactly as written."
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Who answers for this branch. NULL — nobody yet.",
    )
    matched_automatically: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
        doc=(
            "True — the system found it by name similarity. The import NEVER "
            "touches an existing row (ON CONFLICT DO NOTHING), so a manager's "
            "manual choice can never be quietly replaced by the next import."
        ),
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc=(
            "When a PERSON decided. NULL — nobody has touched it. ⚠️ WHY IT "
            "NEEDS ITS OWN COLUMN: `matched_automatically = False` meant two "
            "completely different things — 'a human set this' and 'it never "
            "matched'. Because the import leaves existing rows alone, the "
            "second state was PERMANENT even after a matching employee "
            "appeared. That is exactly why the `Онлайн савдо` branch sat with "
            "no employee (46 sales): the SAP import ran BEFORE the roster was "
            "loaded, and the row was never re-examined although the names were "
            "byte-for-byte identical. The rule is now: empty assigned_at means "
            "the import may TRY again; a filled one means hands off."
        ),
    )
    excluded_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc=(
            "The branch is OUT OF SCOPE; NULL means in scope. We have "
            "departments that are ours but are not sales — `Маркетинг булими`, "
            "`Логистика` — where 'speak to the customer' has no meaning, so "
            "they sat permanently suspicious and buried the real defects. Same "
            "mechanism as sale_partners.excluded_at and the two merge into one "
            "'out of scope' section. Their sales are NOT deleted."
        ),
    )


class SaleDigestModel(Base, UUIDMixin):
    """The daily message log — what was sent, when, and whether it worked.

    Two jobs, both necessary:

    1. **NO REPEATS.** A scheduler is not a guarantee: a container recreated at
       the wrong moment runs the job twice in one day, and the same message
       arriving twice in a chat is noise, and noise is what stops the message
       being read. So the guard lives HERE rather than in the schedule: the
       watermark of the last successful message is compared against
       ``max(sales.imported_at)``, and with no new import nothing is sent.

    2. **AUDIT.** This is the only action in this product that leaves the
       machine. "When, to which chat, for which day, did it go or fail" has to
       be answerable — otherwise a fault is discovered only when the manager
       says "no message today".

    ⚠️ THE MESSAGE TEXT IS NOT STORED. It is reassembled from live data every
    time (like the verdict itself), and a second copy would grow this table by
    tens of megabytes a year. The test button returns the text immediately when
    somebody needs to see it.
    """

    __tablename__ = "sale_digests"

    kind: Mapped[str] = mapped_column(
        sa.String(8),
        nullable=False,
        index=True,
        doc=(
            "`daily` — the scheduled run; `test` — somebody pressed the button. "
            "⚠️ THE REPLAY GUARD LOOKS AT `daily` ONLY. If a test message moved "
            "the watermark, the real night-time message would be skipped "
            "silently — one press of 'try it' would switch off the whole day."
        ),
    )
    covered_on: Mapped[date | None] = mapped_column(
        sa.Date,
        nullable=True,
        doc="Which DAY the message was about (the sale date, not the send date).",
    )
    watermark: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc=(
            "max(sales.imported_at) at send time. Unchanged on the next run "
            "means no new sales were imported — the message would be identical."
        ),
    )
    chat_id: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True, doc="Where it was addressed."
    )
    ok: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
        index=True,
        doc="Did the transport accept it. False while no transport is configured.",
    )
    error: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, doc="What the transport said when it refused."
    )
    sent_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="When the attempt was made.",
    )
