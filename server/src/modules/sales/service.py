"""Sales control — the rules engine. R1, R2, R3.

Ported from BonviZvonki ``modules/sales/application/compliance.py`` (1,513
lines) and ``application/attribution.py``. Every query, every join and every
reason for them is theirs; what changed is named at each seam below. The
vocabulary, the arithmetic and the measured numbers behind them are in
``rules.py``.

**This module writes only derived columns** (``refresh_sale_attribution``) and
the human's decision (:class:`SaleReviewService`). The verdict itself is never
stored — ``rules.py`` says why at length.

════════════════════════════════════════════════════════════════
 THE SEAMS THAT CHANGED, AND WHY
════════════════════════════════════════════════════════════════

**The phone key is a column, not an expression.** BonviZvonki matches a call's
customer with
``right(regexp_replace(coalesce(calls.client_phone,''),'\\D','','g'), 9)``,
written by hand and required to be spelled identically to the index definition
in ``bootstrap.py`` — "one character different and PostgreSQL stops recognising
the index, and every report turns into a full scan of ``calls``". BonviCall has
``calls.remote_number_key``: a STORED GENERATED column produced by
``core.phone.phone_key_sql`` and indexed by ``ix_calls_remote``. The expression,
its duplicate and the whole hazard are gone. ``sale_partners.phone_key`` is the
same mechanism over ``matchable_phone``.

**There is no ``clients`` module here, so a customer's numbers are the
catalogue's.** Theirs unions the SAP catalogue with the phone contacts an
employee typed ("К02121 Bobur aka"), and that union is worth a measured +168
sales matched in a 3-day window (2,094 -> 2,262) at no loss. BonviCall has no
contact catalogue yet — :func:`partner_phones` is the seam where it arrives,
and it is deliberately ONE function so the union lands in one place.

**Day boundaries are half-open instants.** Theirs casts every call's
``started_at`` to a local date and compares dates. Here a sale's day is turned
into the pair of Asia/Tashkent midnights that bound it, so the comparison is
``started_at >= midnight AND started_at < next_midnight`` — the form the rest
of this repo uses, and the form that can use ``ix_calls_started`` instead of
forcing a functional scan. The local date is still computed, but only once per
row, on the aggregate, for the "9 days before" label a human reads.

**"A customer is a code" is now true everywhere.** Their previous-sale window
function partitions by the sale's copied ``phone_key``; ours partitions by
``partner_code``. See :func:`_previous_sale_cte` for what that fixes.

**The employee who spoke is found through a call id.** Theirs stores only
``call_agent_id``; ours stores ``attributed_call_id`` beside it and writes both
from the same subquery, so the row can be opened as a recording and the two
cannot disagree.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
    CTE,
    Integer,
    Select,
    and_,
    case,
    cast,
    distinct,
    false,
    func,
    literal,
    nullslast,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from src.core.clock import TASHKENT
from src.core.enums import CallType
from src.core.errors import ErrorCode, NotFoundError, ValidationError
from src.core.pagination import Cursor, Page, apply_keyset
from src.core.settings_keys import SettingKey
from src.modules.agents.models import AgentModel
from src.modules.calls.models import CallModel
from src.modules.sales.models import (
    SaleBranchModel,
    SaleModel,
    SalePartnerModel,
    SaleReviewModel,
)
from src.modules.sales.rules import (
    DEFAULT_WALK_IN_LIMIT_USD,
    DEFAULT_WINDOW_DAYS,
    GENERIC_PARTNER_CODES,
    AgentBreakdown,
    ClientKind,
    ComplianceRow,
    ComplianceSummary,
    ReviewState,
    Rule,
    SaleOpType,
    SaleReview,
    SaleReviewReason,
    SaleReviewStatus,
    SaleVerdict,
    SkipReason,
    Verdict,
    clamp_walk_in_limit,
    clamp_window_days,
    parse_optional_codes,
    parse_partner_codes,
)
from src.modules.settings.service import SettingsService
from src.modules.users.models import UserModel

# ══════════════════════════════════════════════════════════════
#  SQL fragments
# ══════════════════════════════════════════════════════════════


def day_start(day: ColumnElement | date) -> ColumnElement:
    """The Asia/Tashkent midnight that OPENS ``day``, as an instant.

    ⚠️ THE CONVERSION MUST HAPPEN ON THE SALE SIDE, not the call side. A sale
    carries a bare date; a call carries an instant in UTC. Turning the date
    into the two instants that bound it leaves ``calls.started_at`` untouched
    in the predicate, so ``ix_calls_started`` is usable — whereas casting every
    call to a local date, as BonviZvonki does, forbids the index and scans.

    In UTC the local day opens at 19:00 the previous evening (Tashkent is
    UTC+5, and has no daylight saving), so comparing raw is wrong by five hours
    in a way nobody notices until a month is added up by hand.
    """
    return cast(
        func.timezone(TASHKENT.key, cast(day, sa.TIMESTAMP)),
        sa.DateTime(timezone=True),
    )


def _local_date(instant: ColumnElement) -> ColumnElement:
    """A stored instant as its Asia/Tashkent calendar date.

    Used ONLY for the "N days before" label, on one aggregated value per row —
    never inside a join predicate, for the reason in :func:`day_start`.
    """
    return cast(func.timezone(TASHKENT.key, instant), sa.Date)


def partner_phones(name: str = "partner_phones") -> Any:
    """Every number that identifies a customer: ``(code, phone_key)``.

    ⚠️ A CUSTOMER IS A CODE, NOT A NUMBER. One customer can hold several
    numbers: one written on the SAP card, another in an employee's handset. A
    sale matched on the SAP number alone LOSES the conversation that came from
    the second one.

    ⚠️ THE SECOND SOURCE IS NOT PORTED YET, AND THIS IS THE SEAM. BonviZvonki
    unions this with ``client_contacts`` — the "К02121 Bobur aka" entries an
    employee typed into their phone, with the code checked against SAP so a
    mistyped one cannot enlarge the list. Measured (29.08.2026): sales with a
    conversation found in a 3-day window rose from 2,094 to 2,262 — +168, with
    nothing lost. BonviCall has no contact catalogue; ``modules/clients`` is
    being ported separately. When it lands, its ``UNION`` belongs HERE and
    nowhere else: this function is called from four places (the evidence, the
    "has a number at all" test, the attribution refresh and the timeline) and
    two of them would otherwise disagree about what a customer's numbers are.

    ⚠️ An INACTIVE contractor is not counted (the manager's decision).

    ``name`` is a parameter because one statement uses this subquery twice and
    two identically named subqueries collide in SQL.
    """
    return (
        select(
            SalePartnerModel.code.label("code"),
            SalePartnerModel.phone_key.label("phone_key"),
        )
        .where(
            SalePartnerModel.phone_key.is_not(None),
            SalePartnerModel.is_active.is_(True),
        )
        .subquery(name)
    )


def effective_agent() -> ColumnElement:
    """A sale's REAL employee: whoever spoke, else whoever holds the branch.

    ⚠️ ONE EXPRESSION FOR THE WHOLE PRODUCT. Written twice, the employee in the
    list and the employee in the report would differ and nobody would notice.

    WHY THE BRANCH IS NOT ENOUGH: SAP has no salesperson's name, only
    ``Подразделение``, and a branch is a PLACE. Measured: 20 of 34 branches are
    linked to no employee, because there is no person called "Логистика" or
    "Мастона ёйма" — they are departments and shops. 1,100 sales would have had
    no employee at all.

    WHY THE BRANCH IS STILL THE FALLBACK: the clean rule ("if nobody spoke, the
    sale belongs to nobody") dropped coverage from 3,367 sales to 2,849 and
    emptied part of every report. With the fallback, attributed sales rise from
    3,367 to 3,781.
    """
    return func.coalesce(SaleModel.call_agent_id, SaleModel.agent_id)


#: Which calls can count as a conversation with a customer.
#
# ⚠️ BonviZvonki filters ``call_type = 'sales'``, a value its number routing
# computes reliably. BonviCall's vocabulary is ``internal | external |
# unknown``, and ``unknown`` is what an EMPTY LINE DIRECTORY produces (UC-25) —
# which is the state of a fleet nobody has configured yet. Excluding it would
# make this whole module return "nothing was ever discussed" on day one, which
# is the silent-empty-answer failure the repo keeps legislating against. So the
# test is the conservative one: an INTERNAL call (colleague to colleague) is
# never an agreement with a customer and can never justify a sale; anything
# else may.
CUSTOMER_CALL = CallModel.call_type != CallType.INTERNAL


def _ilike_escape(text: str) -> str:
    """Turn ``ILIKE`` metacharacters into ordinary ones."""
    for sign in ("\\", "%", "_"):
        text = text.replace(sign, f"\\{sign}")
    return text


def _previous_sale_cte() -> CTE:
    """Each customer's PREVIOUS sale date, over the whole history.

    ⚠️ WHY ``DISTINCT`` BEFORE ``lag``. Two sales to one customer on one day is
    normal. Walking ``lag`` straight down the rows makes the second sale treat
    its OWN SAME-DAY TWIN as "the previous sale"; the gap between them is then
    empty and R2 breaks automatically — every second sale becomes suspicious
    for no reason. Dates are made distinct first, then the previous one taken.

    ⚠️ WHY IT IS OUTSIDE THE FILTER. The user may ask for "the last 7 days"
    while the previous sale lies outside that window. Computed over the
    filtered set, every sale at the start of a period would look like a FIRST
    sale and R2 would switch itself off for it, silently.

    ⚠️ PARTITIONED BY ``partner_code``, NOT BY THE PHONE KEY — this is a fix.
    Theirs partitions by the sale's copied ``phone_key`` and drops rows where it
    is NULL, which has two consequences nobody could see: a customer whose
    number is known only through a contact (not the SAP card) gets NO
    previous-sale row at all, so R2 never fires for them; and two different
    customers who share a switchboard number have their sale histories merged
    into one. Everything else in this module already says a customer is a code.
    """
    days = (
        select(SaleModel.partner_code, SaleModel.occurred_on)
        .where(SaleModel.op_type == SaleOpType.SALE.value)
        .distinct()
        .subquery("sale_days")
    )
    return select(
        days.c.partner_code,
        days.c.occurred_on,
        func.lag(days.c.occurred_on)
        .over(partition_by=days.c.partner_code, order_by=days.c.occurred_on)
        .label("previous_sale_on"),
    ).cte("previous_sale")


# ══════════════════════════════════════════════════════════════
#  The filter every surface shares
# ══════════════════════════════════════════════════════════════


@dataclass(slots=True)
class ComplianceFilter:
    """ONE filter for the list, the report, the timeline and the digest.

    ⚠️ All of them must see the same window: if the report says "41 suspicious"
    and the list holds a different number of rows, the reader does not know
    which to believe, and the tool built to prove a number is what destroys
    trust in it.
    """

    since: date | None = None
    """Inclusive. A calendar date, never an instant: ``sales.occurred_on`` is a
    ``Date`` because SAP gives no clock."""
    until: date | None = None
    """Inclusive, and inclusivity is structural here — the column being
    compared is itself a calendar date. The half-open pair lives on the CALL
    side, where the values are instants (:func:`day_start`)."""

    agent_ids: list[uuid.UUID] | None = None
    branches: list[str] | None = None
    verdict: str | None = None
    review: str | None = None
    rule: str | None = None
    search: str | None = None

    window_days: int = DEFAULT_WINDOW_DAYS
    """From the settings (:meth:`SalesScope.resolve`), never hard-coded."""

    client_kind: str = ClientKind.REGULAR.value
    """Which section: regular customers or walk-ins. See ``rules.ClientKind``."""

    over_limit: bool | None = None
    """Only meaningful in the walk-in section: ``True`` — over the ticket
    limit, ``False`` — under it, ``None`` — everything."""

    walk_in_codes: frozenset[str] = GENERIC_PARTNER_CODES
    walk_in_limit: int = DEFAULT_WALK_IN_LIMIT_USD

    out_of_scope: bool = False
    """THE "OUT OF SCOPE" SECTION — one section, TWO sources.

    ``False`` (default) — the MAIN list: a sale shows if its branch is in scope
    AND its customer is in scope.
    ``True`` — only the excluded: branch OR customer out of scope.

    ⚠️ Sales are never deleted, only separated by the query. The manager's
    request was exactly that: "take them out, but do not lose them — give them
    their own section". Deleting would be irreversible, and putting a customer
    back would restore the history only by re-importing every SAP file, which
    for old periods is not possible at all.

    ⚠️ The ``client_kind`` split applies here TOO: a walk-in buyer has their own
    section and their own question (the ticket limit). Otherwise one sale would
    appear in two lists and the totals would exceed reality.

    (BonviZvonki calls this parameter ``excluded_branches``, a name left over
    from when only branches could be excluded. Nothing here is bound by their
    URLs, so it is named for what it means.)
    """

    excluded_branch_names: frozenset[str] = frozenset()
    """Branches out of scope, read from ``sale_branches`` on every request."""

    excluded_partner_codes: frozenset[str] = frozenset()
    """Customers out of scope, read from ``sale_partners`` on every request.

    ⚠️ ONE DIFFERENCE FROM BRANCHES, and it is deliberate: excluding a CUSTOMER
    also affects the WALK-IN section; excluding a branch does not. The reason is
    in the question each answers — a branch measures "who sold", which is
    irrelevant under a shared code, while a customer measures "who bought", and
    an excluded customer must not be under control ANYWHERE.
    """


class SalesScope:
    """Reads the four settings and the two exclusion lists the filter needs.

    ⚠️ ALL OF IT ON EVERY REQUEST, in one place. The alternative — letting the
    caller pass them in — means the list can be computed against one set of
    walk-in codes and the report against another; both numbers sit on one
    screen and the difference destroys confidence immediately.

    ⚠️ THE EXCLUSIONS COME FROM THE FLAG, NOT FROM A SETTING.
    ``sales.internal_codes`` only ever FILLS the flag, once, at the start of an
    import (:meth:`SalesImportService.apply_internal_codes`). The query always
    reads the flag, or the button on the screen ("put back") and the list in
    the settings would be two contradictory sources of one fact.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = SettingsService(session)

    async def _value(self, key: str) -> Any:
        """One setting, or ``None`` when the row is missing.

        A missing row is a seeding bug, and ``SettingsService`` is right to
        raise for it — but a report section must not go dark because of one
        row, so each caller below falls back to its documented default.
        """
        try:
            return await self.settings.get(key)
        except KeyError:
            return None

    async def window_days(self) -> int:
        return clamp_window_days(await self._value(SettingKey.SALES_WINDOW_DAYS))

    async def walk_in_codes(self) -> frozenset[str]:
        """⚠️ NEVER EMPTY — ``rules.parse_partner_codes`` falls back.

        An empty set breaks both sections at once and silently: walk-in sales
        flood back into the regular list, and the walk-in section goes blank.
        """
        return parse_partner_codes(await self._value(SettingKey.SALES_WALK_IN_CODES))

    async def walk_in_limit(self) -> int:
        return clamp_walk_in_limit(await self._value(SettingKey.SALES_WALK_IN_LIMIT_USD))

    async def internal_codes(self) -> frozenset[str]:
        """⚠️ AN EMPTY SET IS A REAL ANSWER here, and the default.

        Falling back to the built-in list, the way the walk-in codes do, would
        be dangerous: it would quietly take a real customer out of control.
        """
        return parse_optional_codes(await self._value(SettingKey.SALES_INTERNAL_CODES))

    async def excluded_branches(self) -> frozenset[str]:
        """Branches out of scope. An empty set is a real answer and the default.

        The error leans the safe way: with an empty list nothing is HIDDEN, at
        worst an extra row is shown.
        """
        rows = await self.session.scalars(
            select(SaleBranchModel.branch).where(
                SaleBranchModel.excluded_at.is_not(None)
            )
        )
        return frozenset(rows)

    async def excluded_partner_codes(self) -> frozenset[str]:
        """Customers out of scope. Same shape as the branches, deliberately —
        the two merge into one section, so reading them two different ways is
        how they drift apart."""
        rows = await self.session.scalars(
            select(SalePartnerModel.code).where(
                SalePartnerModel.excluded_at.is_not(None)
            )
        )
        return frozenset(rows)

    async def resolve(self, **overrides: Any) -> ComplianceFilter:
        """A filter with every settings-derived field already filled in."""
        return ComplianceFilter(
            window_days=await self.window_days(),
            walk_in_codes=await self.walk_in_codes(),
            walk_in_limit=await self.walk_in_limit(),
            excluded_branch_names=await self.excluded_branches(),
            excluded_partner_codes=await self.excluded_partner_codes(),
            **overrides,
        )


# ══════════════════════════════════════════════════════════════
#  The rules engine
# ══════════════════════════════════════════════════════════════


class ComplianceService:
    """The rules engine. Reads ``sales``, ``sale_partners`` and ``calls``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Stage 1: the sales in scope ───────────────────────────

    def _selected(self, f: ComplianceFilter, *, partner_code: str | None = None) -> CTE:
        """The sales the filter admits, plus the previous sale and the decision.

        Only FACTS in the database are filtered here. Filtering by the VERDICT
        (``verdict``, ``rule``) happens in :meth:`_rows`, where it has been
        computed.
        """
        prev = _previous_sale_cte()
        reviewer = aliased(UserModel)

        statement = (
            select(
                SaleModel.id,
                SaleModel.external_id,
                SaleModel.doc_number,
                SaleModel.occurred_on,
                SaleModel.partner_code,
                SaleModel.partner_name,
                SaleModel.branch,
                SaleModel.direction,
                SaleModel.amount,
                SaleModel.currency,
                SaleModel.amount_usd,
                # ⚠️ WHOEVER SPOKE OUTRANKS THE BRANCH — see effective_agent().
                effective_agent().label("agent_id"),
                AgentModel.full_name.label("agent_name"),
                SalePartnerModel.phone.label("phone"),
                SalePartnerModel.phone_key.label("phone_key"),
                # ⚠️ Taken from the OUTER join above. An inner join would make a
                # sale whose code is absent from the catalogue drop out of the
                # list SILENTLY (`unknown_partner`). For a missing code
                # `NULL IS NOT NULL` is `False`, which is the honest answer:
                # there is no row to carry the exclusion flag.
                SalePartnerModel.excluded_at.is_not(None).label("partner_excluded"),
                prev.c.previous_sale_on,
                SaleReviewModel.status.label("review_status"),
                SaleReviewModel.reason.label("review_reason"),
                SaleReviewModel.note.label("review_note"),
                SaleReviewModel.reviewed_at.label("reviewed_at"),
                reviewer.full_name.label("reviewed_by"),
            )
            .select_from(SaleModel)
            # Every join is OPTIONAL: a branch with no employee, a code missing
            # from the catalogue and an unreviewed sale must all STAY in the
            # list rather than fall out of control.
            .outerjoin(AgentModel, AgentModel.id == effective_agent())
            .outerjoin(
                SalePartnerModel, SalePartnerModel.code == SaleModel.partner_code
            )
            .outerjoin(
                prev,
                and_(
                    prev.c.partner_code == SaleModel.partner_code,
                    prev.c.occurred_on == SaleModel.occurred_on,
                ),
            )
            .outerjoin(SaleReviewModel, SaleReviewModel.sale_id == SaleModel.id)
            .outerjoin(reviewer, reviewer.id == SaleReviewModel.reviewed_by)
            # ⚠️ THE RULES APPLY TO SALES ONLY. Payments, returns and accounting
            # entries stay in the database — they belong on the customer's
            # timeline — but they are never checked.
            .where(SaleModel.op_type == SaleOpType.SALE.value)
        )

        statement = self._scope_terms(statement, f)
        statement = self._section_terms(statement, f)

        if partner_code is not None:
            statement = statement.where(SaleModel.partner_code == partner_code)
        if f.since is not None:
            statement = statement.where(SaleModel.occurred_on >= f.since)
        if f.until is not None:
            statement = statement.where(SaleModel.occurred_on <= f.until)
        if f.agent_ids:
            statement = statement.where(effective_agent().in_(f.agent_ids))
        if f.branches:
            statement = statement.where(SaleModel.branch.in_(f.branches))

        text = (f.search or "").strip()
        if text:
            conditions = [
                SaleModel.partner_name.ilike(f"%{_ilike_escape(text)}%", escape="\\"),
                SaleModel.partner_code.ilike(f"%{_ilike_escape(text)}%", escape="\\"),
                SaleModel.external_id.ilike(f"%{_ilike_escape(text)}%", escape="\\"),
            ]
            digits = "".join(char for char in text if char.isdigit())
            if digits:
                # A number may be typed in any format; the key is digits only.
                # It lives on the catalogue row rather than on the sale,
                # because a customer is a code (see models.py).
                conditions.append(SalePartnerModel.phone_key.like(f"%{digits}%"))
            statement = statement.where(or_(*conditions))

        return statement.cte("selected")

    @staticmethod
    def _scope_terms(statement: Select, f: ComplianceFilter) -> Select:
        """"OUT OF SCOPE" — two sources, one section.

        Two different things are outside sales control and both for the same
        reason:

          · A BRANCH of ours that is not selling (`Маркетинг булими`,
            `Логистика`);
          · A CUSTOMER that is a contractor in SAP but not a buyer (our own
            warehouse, the call centre, internal supply).

        For both, "was the customer called before the sale?" is meaningless,
        and both sat permanently at the top of the suspicious list BURYING the
        real defects.

        ⚠️ EXCLUDING A BRANCH DOES NOT REACH THE WALK-IN SECTION — neither the
        main list nor the excluded one. That section is built on the customer
        CODE and its question is the ticket limit, so who sold is irrelevant.
        Cutting here as well would leave an excluded branch's shared-code sales
        visible in NO section at all (measured: 47 sales).

        ⚠️ EXCLUDING A CUSTOMER DOES reach it: an excluded customer must not be
        under control anywhere, or "I excluded them" is a half-done action.
        """
        names = sorted(f.excluded_branch_names)
        codes = sorted(f.excluded_partner_codes)
        walk_in = f.client_kind == ClientKind.WALK_IN.value

        by_branch = SaleModel.branch.in_(names) if names and not walk_in else None
        by_partner = SaleModel.partner_code.in_(codes) if codes else None

        if f.out_of_scope:
            outside = [term for term in (by_branch, by_partner) if term is not None]
            # The section's definition: branch excluded OR customer excluded.
            # With nobody excluded it is an EMPTY section — never "everything".
            return statement.where(or_(*outside) if outside else false())

        if by_branch is not None:
            # ⚠️ ``branch IS NULL`` IS SPELLED OUT. In SQL ``NULL NOT IN (…)``
            # is NULL — not true — so sales with no branch (they occur in SAP)
            # would drop SILENTLY out of the main list. ``partner_code`` has no
            # such problem: the column is NOT NULL.
            statement = statement.where(
                or_(SaleModel.branch.not_in(names), SaleModel.branch.is_(None))
            )
        if by_partner is not None:
            statement = statement.where(SaleModel.partner_code.not_in(codes))
        return statement

    @staticmethod
    def _section_terms(statement: Select, f: ComplianceFilter) -> Select:
        """Regular customers or walk-ins.

        ⚠️ A filter on a FACT (is the code in the list), which is why it lives
        here and not among the verdict filters. Both sections are built from
        ONE query: built separately they would drift, and one sale could then
        appear in both lists or in neither.
        """
        codes = sorted(f.walk_in_codes)
        if f.client_kind != ClientKind.WALK_IN.value:
            return statement.where(SaleModel.partner_code.not_in(codes))

        statement = statement.where(SaleModel.partner_code.in_(codes))
        if f.over_limit is True:
            statement = statement.where(SaleModel.amount_usd > f.walk_in_limit)
        elif f.over_limit is False:
            # ⚠️ ``amount_usd IS NULL`` counts as NOT over the limit. Putting a
            # sale of unknown value on the "over the limit" list would be an
            # accusation built on a gap in SAP's export.
            statement = statement.where(
                or_(
                    SaleModel.amount_usd <= f.walk_in_limit,
                    SaleModel.amount_usd.is_(None),
                )
            )
        return statement

    # ── Stage 2: the call evidence ────────────────────────────

    def _evidence(self, selected: CTE, window_days: int) -> CTE:
        """Every sale's call aggregate — in ONE pass.

        All three rules are three cuts of one question: "when was this number
        spoken to". So the calls are gathered once and separated by ``FILTER``:

          · ``last_call_at``  — the nearest conversation before the sale (R1);
          · ``calls_between`` — conversations since the previous sale (R2);
          · ``calls_total``   — the whole history (R3).

        ⚠️ MATCHED BY CODE, NOT BY NUMBER. A customer may hold several numbers
        and the one on the SAP card is only one of them (measured: 124
        contractors have a number that is present and unusable). The code is
        SAP's own reliable identifier.

        ⚠️ ONLY NON-INTERNAL CALLS — see :data:`CUSTOMER_CALL`.

        ⚠️ ``calls_total`` IS NOT BOUNDED BY THE PERIOD — conversations after
        the sale count too. R3 ("never spoken to at all") is the harshest
        signal, so it is stated in its most CAUTIOUS form: one contact anywhere
        in the history and R3 does not fire.

        ⚠️ ONE QUERY FOR THE WHOLE PAGE. A six-month export is ~17,000 sales and
        each carries three questions; a query per row would be 51,000 queries.
        """
        phones = partner_phones()

        # Only the customers we need. Without this, the whole ``calls`` table —
        # hundreds of thousands of rows — is dragged into the join on every
        # request.
        codes = select(distinct(selected.c.partner_code))
        calls = (
            select(
                phones.c.code.label("code"),
                CallModel.id.label("call_id"),
                CallModel.started_at.label("started_at"),
                CallModel.agent_id.label("agent_id"),
            )
            .join(phones, phones.c.phone_key == CallModel.remote_number_key)
            .where(CUSTOMER_CALL, phones.c.code.in_(codes))
            .subquery("customer_calls")
        )
        talker = aliased(AgentModel)

        # The sale day is inclusive: SAP gives no time, so a conversation on
        # the sale's own day is taken to have happened BEFORE it. Half-open, so
        # the predicate stays on the raw instant column.
        before = calls.c.started_at < day_start(selected.c.occurred_on + 1)
        in_window = calls.c.started_at >= day_start(
            selected.c.occurred_on - window_days
        )
        # ⚠️ A CONVERSATION ON THE PREVIOUS SALE'S OWN DAY IS NOT IN THE GAP: it
        # may have justified THAT sale, and one conversation must not justify
        # two. The current sale's own day IS in, for the reason above.
        after_previous = calls.c.started_at >= day_start(
            selected.c.previous_sale_on + 1
        )

        return (
            select(
                selected.c.id.label("sale_id"),
                func.max(calls.c.started_at).filter(before).label("last_call_at"),
                func.count(calls.c.call_id).label("calls_total"),
                func.count(calls.c.call_id)
                .filter(and_(before, in_window))
                .label("calls_in_window"),
                func.count(calls.c.call_id)
                .filter(
                    and_(
                        selected.c.previous_sale_on.is_not(None),
                        after_previous,
                        before,
                    )
                )
                .label("calls_between"),
                # WHO held the last conversation, and WHICH call it was.
                # ``max()`` cannot answer either — this is a choice by TIME, not
                # by value, and ``max`` would return an arbitrary name. So:
                # the first element of an ordered array. The casts keep the
                # element types known outside the CTE.
                cast(
                    func.array_agg(
                        aggregate_order_by(talker.full_name, calls.c.started_at.desc())
                    ).filter(before),
                    ARRAY(sa.String),
                ).label("last_call_agents"),
                cast(
                    func.array_agg(
                        aggregate_order_by(calls.c.call_id, calls.c.started_at.desc())
                    ).filter(before),
                    ARRAY(PG_UUID(as_uuid=True)),
                ).label("last_call_ids"),
            )
            .select_from(selected)
            .outerjoin(calls, calls.c.code == selected.c.partner_code)
            .outerjoin(talker, talker.id == calls.c.agent_id)
            .group_by(selected.c.id)
            .cte("evidence")
        )

    # ── Stage 3: the verdict ──────────────────────────────────

    def _rows(self, f: ComplianceFilter, selected: CTE, evidence: CTE) -> Select:
        """Apply the rules, then filter on the verdict.

        ⚠️ R1 IS DECIDED BY A COUNT, NOT BY A DATE DIFFERENCE. BonviZvonki
        writes it as ``last_call_at IS NULL OR days_before > window``, which is
        equivalent but makes the verdict depend on a ``date - date`` cast of an
        aggregate. ``_evidence`` already counts the conversations that fall
        inside the window, so the rule reads as what it means.
        ``days_before`` stays, purely as the number a human reads.
        """
        days_before = cast(
            selected.c.occurred_on - _local_date(evidence.c.last_call_at), Integer
        )

        # ── What cannot be checked ────────────────────────────
        #
        # ⚠️ AGAINST THE CONFIGURED LIST, not the built-in constant. Theirs
        # tests ``GENERIC_PARTNER_CODES`` here while the section split above
        # uses the setting, so a deployment that adds a shared code gets rows
        # that are excluded from the regular list AND scored by the rules in
        # the walk-in one — where the rules are meant not to apply at all.
        generic = selected.c.partner_code.in_(sorted(f.walk_in_codes))
        # ⚠️ "No phone" is a question about the CUSTOMER, not about the sale
        # row: neither the SAP card nor any other known number. Their earlier
        # version looked only at the number copied onto the sale, so a customer
        # SAP had recorded wrongly (`К02277`, phone `(+93893)…`) came out as
        # "could not be checked" — while their real number was in an employee's
        # handset and had been spoken to that very day.
        known = partner_phones("known_phones")
        no_phone = ~(
            select(known.c.code)
            .where(known.c.code == selected.c.partner_code)
            .exists()
        )
        skipped = or_(generic, no_phone)
        checkable = ~skipped

        # ── The rules ─────────────────────────────────────────
        #
        # R1: no conversation inside the window. ``last_call_at`` may itself be
        # OUTSIDE the window (it is still shown as evidence), which is why the
        # count is what decides and the date is only what explains.
        r1 = and_(checkable, evidence.c.calls_in_window == 0)
        # R2: NOT APPLIED to a first sale — there is nothing to compare against.
        r2 = and_(
            checkable,
            selected.c.previous_sale_on.is_not(None),
            evidence.c.calls_between == 0,
        )
        r3 = and_(checkable, evidence.c.calls_total == 0)

        verdict = case(
            (skipped, literal(Verdict.NOT_CHECKABLE.value)),
            (or_(r1, r2, r3), literal(Verdict.SUSPICIOUS.value)),
            else_=literal(Verdict.OK.value),
        )

        # ── Over the ticket limit ─────────────────────────────
        #
        # ⚠️ COMPUTED IN THE WALK-IN SECTION ONLY. A large sale to a regular
        # customer is a normal event, and marking it would fill the screen with
        # false warnings.
        #
        # ⚠️ ``amount_usd IS NULL`` IS NOT over the limit — see _section_terms.
        #
        # It is computed HERE, in SQL, rather than left to the client, because
        # the money is ``numeric`` and no float comparison of it ever has to
        # happen anywhere (CONVENTIONS.md §10).
        if f.client_kind == ClientKind.WALK_IN.value:
            over_limit = and_(
                selected.c.amount_usd.is_not(None),
                selected.c.amount_usd > f.walk_in_limit,
            )
        else:
            over_limit = literal(False)

        skip_reason = case(
            # Order matters: a shared code usually has no phone either, but the
            # reason is "shared code" — it is the more precise one, and the one
            # that cannot be fixed by tidying the catalogue.
            (generic, literal(SkipReason.GENERIC_CODE.value)),
            (no_phone, literal(SkipReason.NO_PHONE.value)),
        )

        statement = (
            select(
                selected.c.id,
                selected.c.external_id,
                selected.c.doc_number,
                selected.c.occurred_on,
                selected.c.partner_code,
                selected.c.partner_name,
                selected.c.phone,
                selected.c.phone_key,
                selected.c.partner_excluded,
                selected.c.branch,
                selected.c.direction,
                selected.c.agent_id,
                selected.c.agent_name,
                selected.c.amount,
                selected.c.currency,
                selected.c.amount_usd,
                selected.c.previous_sale_on,
                selected.c.review_status,
                selected.c.review_reason,
                selected.c.review_note,
                selected.c.reviewed_at,
                selected.c.reviewed_by,
                evidence.c.last_call_at,
                evidence.c.calls_between,
                evidence.c.calls_total,
                evidence.c.last_call_agents[1].label("last_call_agent"),
                evidence.c.last_call_ids[1].label("last_call_id"),
                over_limit.label("over_limit"),
                days_before.label("days_before"),
                verdict.label("verdict"),
                skip_reason.label("skip_reason"),
                r1.label("r1"),
                r2.label("r2"),
                r3.label("r3"),
            )
            .select_from(selected)
            .join(evidence, evidence.c.sale_id == selected.c.id)
        )

        if f.verdict:
            statement = statement.where(verdict == f.verdict)
        if f.rule:
            statement = statement.where(
                {Rule.R1: r1, Rule.R2: r2, Rule.R3: r3}[Rule(f.rule)]
            )

        # ⚠️ THE REVIEW FILTER IS DELIBERATELY HERE AND NOT IN ``_selected``.
        #
        # Measured (17,663 sales, ``sale_reviews`` empty): with the condition
        # pushed up, PostgreSQL judges ``LEFT JOIN … IS NULL`` extremely
        # selective (it estimates 88 rows where there are 17,663) and picks a
        # NESTED LOOP for ``evidence`` — the calls table is rescanned for EVERY
        # sale. The query went from 0.2 s to 0.8 s and grew quadratically with
        # the number of sales. Here the size of ``selected`` is estimated
        # correctly and the plan stays a HASH JOIN.
        if f.review == ReviewState.NEW.value:
            statement = statement.where(selected.c.review_status.is_(None))
        elif f.review in (ReviewState.JUSTIFIED.value, ReviewState.CONFIRMED.value):
            statement = statement.where(selected.c.review_status == f.review)
        # ``all`` and ``None`` both mean no filter, but they mean different
        # things: ``all`` is the manager's choice, ``None`` is "the parameter
        # was not given" — and then the router sends ``new``.
        return statement

    # ── The three stages, assembled ───────────────────────────

    def verdict_rows(
        self, f: ComplianceFilter, *, partner_code: str | None = None
    ) -> Select:
        """The filtered sales with their verdict — a ready expression.

        ⚠️ THE THREE STAGES ARE ALWAYS ASSEMBLED HERE AND AS THIS PAIR:
        ``_evidence`` must be built over exactly the ``_selected`` it is joined
        to, or the evidence comes from a different set of sales. These three
        lines used to be repeated at each call site, and when a new surface was
        added (the customer timeline) they drifted — one sale then carried two
        different verdicts on two screens.
        """
        selected = self._selected(f, partner_code=partner_code)
        return self._rows(f, selected, self._evidence(selected, int(f.window_days)))

    # ── The queue ─────────────────────────────────────────────

    async def page(
        self,
        f: ComplianceFilter,
        *,
        limit: int,
        cursor: Cursor | None = None,
        with_total: bool = False,
        order: str = "desc",
    ) -> Page[ComplianceRow]:
        """One page of the review queue, ordered ``occurred_on, id``.

        ⚠️ KEYSET, NOT ``OFFSET`` — and this is a change from BonviZvonki, which
        pages with ``OFFSET`` over four different sort orders. A review queue is
        exactly the list an ``OFFSET`` breaks: the manager decides on a sale on
        page 1, it leaves the default ``review=new`` set, and every later page
        shifts by one — so one sale is never seen at all. Keyset paired with
        ``id`` cannot skip or repeat a row that existed when paging started
        (``core/pagination.py``).

        The other three sort orders are not ported. ``amount`` is answered by
        :meth:`top_suspicious`, which takes a LIMIT and no cursor, so it needs
        no cursorable key; sorting a paged work queue by employee or customer
        name is not a workflow anybody described, and a sort a cursor cannot
        express is a sort that silently loses rows.
        """
        rows = self.verdict_rows(f)
        listed = rows.subquery("listed")

        total = None
        if with_total:
            total = await self.session.scalar(
                select(func.count()).select_from(listed)
            )

        statement = apply_keyset(
            select(listed),
            listed.c.occurred_on,
            listed.c.id,
            cursor,
            descending=order != "asc",
        ).limit(limit + 1)
        result = list((await self.session.execute(statement)).all())
        has_more = len(result) > limit
        result = result[:limit]
        next_cursor = (
            Cursor(result[-1].occurred_on, result[-1].id).encode()
            if has_more and result
            else None
        )
        return Page(
            items=[_to_row(row) for row in result],
            next_cursor=next_cursor,
            has_more=has_more,
            total=total,
        )

    # ── The report ────────────────────────────────────────────

    async def summary(self, f: ComplianceFilter) -> ComplianceSummary:
        """The three class counts, and the per-employee cut.

        ⚠️ THE VERDICT FILTERS (``verdict``, ``rule``, ``review``) ARE IGNORED
        HERE. All three counts have to stay on the screen: with the report
        following the list's filter, choosing "suspicious" would drop two of
        the three cards to zero and "how many could not be checked" — the
        measure of SAP's own data quality — would have no answer at all.

        The period, the employee, the branch and the search ARE kept: those
        define the window the reader is looking at.
        """
        scope = replace(f, verdict=None, rule=None, review=None)
        rows = self.verdict_rows(scope).subquery("scoped")

        def counted(condition: Any) -> Any:
            return func.count().filter(condition)

        result = (
            await self.session.execute(
                select(
                    rows.c.agent_id,
                    rows.c.agent_name,
                    func.count().label("sales"),
                    counted(rows.c.verdict == Verdict.OK.value).label("ok"),
                    counted(rows.c.verdict == Verdict.SUSPICIOUS.value).label(
                        "suspicious"
                    ),
                    counted(rows.c.verdict == Verdict.NOT_CHECKABLE.value).label(
                        "not_checkable"
                    ),
                    counted(
                        and_(
                            rows.c.verdict == Verdict.SUSPICIOUS.value,
                            rows.c.review_status.is_(None),
                        )
                    ).label("new"),
                    counted(
                        rows.c.review_status == ReviewState.JUSTIFIED.value
                    ).label("justified"),
                    counted(
                        rows.c.review_status == ReviewState.CONFIRMED.value
                    ).label("confirmed"),
                    # ⚠️ The limit is counted in the EMPLOYEE cut too: "whose
                    # walk-in tickets keep going over" is answered from this
                    # column and from nowhere else.
                    counted(rows.c.over_limit).label("over_limit"),
                    func.coalesce(
                        func.sum(rows.c.amount_usd).filter(rows.c.over_limit), 0
                    ).label("over_limit_amount"),
                )
                .group_by(rows.c.agent_id, rows.c.agent_name)
                .order_by(
                    func.count()
                    .filter(rows.c.verdict == Verdict.SUSPICIOUS.value)
                    .desc(),
                    nullslast(rows.c.agent_name.asc()),
                )
            )
        ).all()

        agents = [
            AgentBreakdown(
                agent_id=row.agent_id,
                agent_name=row.agent_name,
                sales=row.sales,
                ok=row.ok,
                suspicious=row.suspicious,
                not_checkable=row.not_checkable,
                new=row.new,
                justified=row.justified,
                confirmed=row.confirmed,
                over_limit=row.over_limit,
                over_limit_amount=_number(row.over_limit_amount) or 0.0,
            )
            for row in result
        ]
        # The totals are summed from the employee cut: they are slices of ONE
        # set, so a second query would be wasted work AND a chance for the two
        # numbers to disagree.
        return ComplianceSummary(
            total=sum(a.sales for a in agents),
            ok=sum(a.ok for a in agents),
            suspicious=sum(a.suspicious for a in agents),
            not_checkable=sum(a.not_checkable for a in agents),
            new=sum(a.new for a in agents),
            justified=sum(a.justified for a in agents),
            confirmed=sum(a.confirmed for a in agents),
            window_days=int(f.window_days),
            agents=agents,
            over_limit=sum(a.over_limit for a in agents),
            over_limit_amount=round(sum(a.over_limit_amount for a in agents), 3),
            walk_in_limit=int(f.walk_in_limit),
        )

    # ── One customer's sales ──────────────────────────────────

    async def for_partner(
        self, partner_code: str, f: ComplianceFilter, *, limit: int
    ) -> list[ComplianceRow]:
        """One customer's sales, newest first.

        ⚠️ THE PERIOD DOES NOT NARROW THE RULES. "The previous sale" (R2) and
        "the whole history" (R3) are still computed over everything
        (:func:`_previous_sale_cte`, :meth:`_evidence`) — the period decides
        only what is SHOWN. Otherwise a sale at the start of the period would
        look like a first sale, and the same sale would read suspicious in the
        control list and clean on the customer card.
        """
        listed = self.verdict_rows(f, partner_code=partner_code).subquery("client")
        result = await self.session.execute(
            select(listed)
            .order_by(listed.c.occurred_on.desc(), listed.c.external_id.desc())
            .limit(limit)
        )
        return [_to_row(row) for row in result.all()]


# ══════════════════════════════════════════════════════════════
#  The derived attribution
# ══════════════════════════════════════════════════════════════


async def refresh_sale_attribution(session: AsyncSession, *, window_days: int) -> int:
    """Write the conversation that attributed each sale. Returns rows changed.

    Whose sale is it? The manager's decision (29.08.2026): a sale is tied to a
    CUSTOMER through ``partner_code``, and to an EMPLOYEE through whoever SPOKE
    to that customer. Two questions, two answers.

    THE RULES, each chosen by measurement (see :func:`effective_agent` for why
    the branch alone is not enough):

      · **A three-day window**, the same as the rules' own. The sale day and
        the three before it.
      · **If several employees spoke, the one CLOSEST to the sale.** Whoever
        closed the sale is usually the last to have spoken. Measured: 294 such
        cases in a 3-day window.
      · **If nobody spoke, fall back to the branch** (``sales.agent_id``).

    ⚠️ IN BOTH DIRECTIONS: it writes what it finds and CLEARS what it no longer
    finds. Write-only, and a deleted contact or a deleted call would leave the
    old employee sitting on the sale for ever.

    ⚠️ TWO STATEMENTS, ONE TRUTH. The second derives ``call_agent_id`` from the
    call id the first just wrote, so the denormalised employee cannot disagree
    with the call it came from — which a second correlated subquery could.
    """
    phones = partner_phones("attribution_phones")

    # ⚠️ ``ORDER BY started_at DESC LIMIT 1`` — the conversation NEAREST the
    # sale. ``max(agent_id)`` cannot express it: that is a choice by time, not
    # by value, and ``max`` returns an arbitrary employee.
    closest = (
        select(CallModel.id)
        .join(phones, phones.c.phone_key == CallModel.remote_number_key)
        .where(
            phones.c.code == SaleModel.partner_code,
            CUSTOMER_CALL,
            CallModel.agent_id.is_not(None),
            CallModel.started_at >= day_start(SaleModel.occurred_on - window_days),
            CallModel.started_at < day_start(SaleModel.occurred_on + 1),
        )
        .order_by(CallModel.started_at.desc())
        .limit(1)
        .scalar_subquery()
    )

    result = await session.execute(
        update(SaleModel)
        .where(
            SaleModel.op_type == SaleOpType.SALE.value,
            SaleModel.attributed_call_id.is_distinct_from(closest),
        )
        .values(attributed_call_id=closest)
    )

    agent_of_call = (
        select(CallModel.agent_id)
        .where(CallModel.id == SaleModel.attributed_call_id)
        .scalar_subquery()
    )
    await session.execute(
        update(SaleModel)
        .where(SaleModel.call_agent_id.is_distinct_from(agent_of_call))
        .values(call_agent_id=agent_of_call)
    )
    return result.rowcount or 0


# ══════════════════════════════════════════════════════════════
#  The human's decision
# ══════════════════════════════════════════════════════════════


class SaleReviewService:
    """The review queue — the manager's decision.

    This is the only subjective row the database keeps. The rule's own result
    ("suspicious") is not stored, because it changes as calls synchronise
    (``rules.py``). A person's decision does not change: "they walked in", "we
    agreed it on Telegram" — those are facts, not calculations.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(
        self,
        sale_id: uuid.UUID,
        *,
        status: SaleReviewStatus,
        reason: SaleReviewReason | None,
        note: str | None,
        user_id: uuid.UUID | None,
    ) -> SaleReview:
        """Record the decision. ONE decision per sale — a repeat overwrites.

        ⚠️ CHANGING YOUR MIND IS NORMAL. A manager may mark a sale justified,
        then speak to the employee and change it to confirmed. So the table
        holds the LAST decision rather than a history, and ``sale_id`` is
        unique: a second row would show the sale twice in the list.

        Who decided and when is ALWAYS recorded — an anonymous decision cannot
        be discussed.
        """
        exists = await self.session.scalar(
            select(SaleModel.id).where(SaleModel.id == sale_id)
        )
        if exists is None:
            raise NotFoundError()

        # ⚠️ A CONFIRMED SUSPICION CARRIES NO REASON: the reason list ("walked
        # in", "Telegram"…) was built to explain a JUSTIFICATION. Refused rather
        # than silently dropped, so a panel that sends one learns about it —
        # theirs discards it, and the field then looks accepted and is not.
        if reason is not None and status is not SaleReviewStatus.JUSTIFIED:
            raise ValidationError(
                ErrorCode.VALIDATION_ERROR,
                detail={"field": "reason", "reason": "only_with_justified"},
            )
        cleaned = (note or "").strip() or None

        row = await self.session.scalar(
            select(SaleReviewModel).where(SaleReviewModel.sale_id == sale_id)
        )
        if row is None:
            row = SaleReviewModel(sale_id=sale_id)
            self.session.add(row)
        row.status = status.value
        row.reason = reason.value if reason else None
        row.note = cleaned
        row.reviewed_by = user_id
        row.reviewed_at = func.now()
        await self.session.flush()
        await self.session.refresh(row)

        name = None
        if user_id is not None:
            name = await self.session.scalar(
                select(UserModel.full_name).where(UserModel.id == user_id)
            )
        await self.session.commit()
        return SaleReview(
            status=row.status,
            reason=row.reason,
            note=row.note,
            reviewed_by=name,
            reviewed_at=row.reviewed_at,
        )


# ══════════════════════════════════════════════════════════════
#  Row -> data shape
# ══════════════════════════════════════════════════════════════


def _number(value: Any) -> float | None:
    """``Decimal`` -> ``float``. There is no ``Decimal`` in JSON.

    The value is stored as ``numeric`` and every comparison against a threshold
    happens in SQL (``over_limit``), so this conversion only ever feeds a
    display (CONVENTIONS.md §10 bans float in a COLUMN, which this is not).
    """
    return None if value is None else float(value)


def broken_rules(row: Any) -> list[str]:
    """The rules broken, ALWAYS in this order (R1, R2, R3).

    The order has to be stable: badges that move about make the list unreadable.
    """
    return [
        rule.value
        for rule, broken in ((Rule.R1, row.r1), (Rule.R2, row.r2), (Rule.R3, row.r3))
        if broken
    ]


def _to_row(row: Any) -> ComplianceRow:
    review = (
        SaleReview(
            status=row.review_status,
            reason=row.review_reason,
            note=row.review_note,
            reviewed_by=row.reviewed_by,
            reviewed_at=row.reviewed_at,
        )
        if row.review_status is not None
        else None
    )
    return ComplianceRow(
        id=row.id,
        occurred_on=row.occurred_on,
        external_id=row.external_id,
        doc_number=row.doc_number,
        partner_code=row.partner_code,
        partner_name=row.partner_name,
        phone=row.phone,
        phone_key=row.phone_key,
        branch=row.branch,
        direction=row.direction,
        agent_id=row.agent_id,
        agent_name=row.agent_name,
        amount=_number(row.amount),
        currency=row.currency,
        amount_usd=_number(row.amount_usd),
        partner_excluded=bool(row.partner_excluded),
        over_limit=bool(row.over_limit),
        verdict=SaleVerdict(
            sale_id=row.id,
            verdict=row.verdict,
            broken_rules=broken_rules(row),
            skip_reason=row.skip_reason,
            last_call_at=row.last_call_at,
            last_call_agent=row.last_call_agent,
            last_call_id=row.last_call_id,
            days_before=row.days_before,
            previous_sale_on=row.previous_sale_on,
            calls_between=row.calls_between,
            calls_total=row.calls_total,
        ),
        review=review,
    )


__all__ = [
    "ComplianceFilter",
    "ComplianceService",
    "SaleReviewService",
    "SalesScope",
    "broken_rules",
    "effective_agent",
    "partner_phones",
    "refresh_sale_attribution",
]
