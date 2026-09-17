"""The rules engine: R1, R2, R3, the two sections, and the two exclusions.

Ported in intent from BonviZvonki ``modules/sales/tests/test_compliance.py``
(1,600 lines), rewritten in this repository's style and names. Each test below
pins one decision that was argued out against real data — the measurements are
in ``rules.py`` and ``service.py`` beside the code, and these are what stop any
of them coming back.

The three things that can make this report lie, and therefore the three things
asserted hardest:

  · a conversation counted for the WRONG DAY, because a call is an instant in
    UTC and a sale is a bare local date (five hours' difference, invisible
    until somebody adds up a month by hand);
  · a customer identified by their phone number instead of their SAP code, so
    a conversation from their second number disappears;
  · "could not be checked" quietly counted as "clean".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from src.core.enums import CallType
from src.modules.sales.models import SaleModel
from src.modules.sales.rules import (
    ClientKind,
    ReviewState,
    SkipReason,
    Verdict,
)
from src.modules.sales.service import (
    ComplianceService,
    SalesScope,
    refresh_sale_attribution,
)
from src.modules.sales.tests.conftest import SALE_DAY

pytestmark = pytest.mark.asyncio

#: 09:00 UTC is 14:00 in Tashkent — the middle of a working day, whichever side
#: of midnight the assertion is about.
NOON = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


async def _scope(db, **overrides):
    """The filter every surface shares, resolved from the seeded settings."""
    return await SalesScope(db).resolve(**overrides)


async def _rows(db, **overrides):
    page = await ComplianceService(db).page(
        await _scope(db, review=ReviewState.ALL.value, **overrides), limit=200
    )
    return page.items


async def _one(db, **overrides):
    items = await _rows(db, **overrides)
    assert len(items) == 1, [row.external_id for row in items]
    return items[0]


async def _call(call_factory, installation, partner, *, at, **overrides):
    """A conversation with ``partner`` — matched on the last-9 key (N37)."""
    return await call_factory(
        installation=installation,
        remote_number=partner.phone,
        started_at=at,
        **overrides,
    )


@pytest_asyncio.fixture
async def installation(installation_factory, agent_factory):
    """One handset belonging to one employee — the source of every call below."""
    return await installation_factory(agent=await agent_factory(full_name="Aziz"))


# ══════════════════════════════════════════════════════════════
#  R1 — was there a conversation inside the window?
# ══════════════════════════════════════════════════════════════


async def test_a_conversation_on_the_sale_day_justifies_it(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """The nearest possible case. A sale has no clock, so a conversation on its
    own day is taken to have happened BEFORE it."""
    partner = await partner_factory()
    await sale_factory(partner=partner)
    await _call(call_factory, installation, partner, at=NOON)

    row = await _one(db)
    assert row.verdict.verdict == Verdict.OK.value
    assert row.verdict.days_before == 0
    assert row.verdict.broken_rules == []


@pytest.mark.parametrize(
    ("days_before", "expected"),
    [(0, Verdict.OK), (3, Verdict.OK), (4, Verdict.SUSPICIOUS), (9, Verdict.SUSPICIOUS)],
)
async def test_the_window_boundary_is_locked(
    db, partner_factory, sale_factory, call_factory, installation, days_before, expected
) -> None:
    """⚠️ THE BOUNDARY IS PINNED: with a 3-day window a conversation 3 days
    before the sale is INSIDE it and one 4 days before is not. The default is
    3, so the window is the sale day plus three, i.e. four calendar days.
    """
    partner = await partner_factory()
    await sale_factory(partner=partner)
    await _call(call_factory, installation, partner, at=NOON - timedelta(days=days_before))

    row = await _one(db)
    assert row.verdict.verdict == expected.value
    assert row.verdict.days_before == days_before, "the evidence is shown either way"


async def test_a_conversation_after_the_sale_cannot_justify_it(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """An agreement cannot be reached after the goods have gone.

    ``calls_total`` still counts it — R3 is the harshest signal and is stated
    in its most cautious form — so the verdict is R1 alone.
    """
    partner = await partner_factory()
    await sale_factory(partner=partner)
    await _call(call_factory, installation, partner, at=NOON + timedelta(days=1))

    row = await _one(db)
    assert row.verdict.verdict == Verdict.SUSPICIOUS.value
    assert "R1" in row.verdict.broken_rules
    assert "R3" not in row.verdict.broken_rules
    assert row.verdict.calls_total == 1
    assert row.verdict.last_call_at is None, "it is not evidence FOR the sale"


async def test_an_internal_call_does_not_justify_a_sale(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """A colleague-to-colleague call is not an agreement with a customer.

    ⚠️ ``unknown`` IS counted, and that is the deliberate difference from
    BonviZvonki. ``unknown`` is what an empty line directory produces (UC-25),
    which is the state of a fleet nobody has configured — excluding it would
    make this module answer "nothing was ever discussed" on day one.
    """
    partner = await partner_factory()
    await sale_factory(partner=partner)
    await _call(
        call_factory, installation, partner, at=NOON, call_type=CallType.INTERNAL
    )

    row = await _one(db)
    assert row.verdict.verdict == Verdict.SUSPICIOUS.value
    assert row.verdict.calls_total == 0


async def test_a_conversation_late_in_the_local_evening_stays_on_its_own_day(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """⚠️ THE FIVE-HOUR TRAP. 21:00 Tashkent on the sale day is 16:00 UTC, and
    23:00 Tashkent is 18:00 UTC — both still the sale day locally. Compared in
    UTC the boundary moves and an evening conversation lands on the next day,
    outside the window, with nothing on the screen to say so.
    """
    partner = await partner_factory()
    await sale_factory(partner=partner, occurred_on=SALE_DAY)
    # 23:30 local on the sale day.
    await _call(
        call_factory,
        installation,
        partner,
        at=datetime(2026, 8, 20, 18, 30, tzinfo=UTC),
    )

    row = await _one(db)
    assert row.verdict.verdict == Verdict.OK.value
    assert row.verdict.days_before == 0


async def test_a_conversation_just_after_local_midnight_is_the_next_day(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """The other side of the same boundary: 00:30 local on the day AFTER the
    sale is 19:30 UTC on the sale day. Compared in UTC it would wrongly count."""
    partner = await partner_factory()
    await sale_factory(partner=partner, occurred_on=SALE_DAY)
    await _call(
        call_factory,
        installation,
        partner,
        at=datetime(2026, 8, 20, 19, 30, tzinfo=UTC),
    )

    row = await _one(db)
    assert row.verdict.verdict == Verdict.SUSPICIOUS.value
    assert row.verdict.last_call_at is None


# ══════════════════════════════════════════════════════════════
#  R2 — was there a conversation since the previous sale?
# ══════════════════════════════════════════════════════════════


async def test_a_conversation_between_two_sales_satisfies_r2(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """call -> sale -> call -> sale is the correct sequence."""
    partner = await partner_factory()
    first = await sale_factory(
        partner=partner, external_id="OP-A", occurred_on=SALE_DAY - timedelta(days=10)
    )
    await _call(call_factory, installation, partner, at=NOON - timedelta(days=10))
    await sale_factory(partner=partner, external_id="OP-B", occurred_on=SALE_DAY)
    await _call(call_factory, installation, partner, at=NOON - timedelta(days=1))

    rows = {row.external_id: row for row in await _rows(db)}
    assert rows["OP-B"].verdict.verdict == Verdict.OK.value
    assert rows["OP-B"].verdict.previous_sale_on == first.occurred_on
    assert rows["OP-B"].verdict.calls_between == 1


async def test_no_conversation_since_the_previous_sale_breaks_r2(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """⚠️ A conversation on the PREVIOUS SALE'S OWN DAY is not in the gap: it
    may have justified THAT sale, and one conversation must not justify two.
    """
    partner = await partner_factory()
    await sale_factory(
        partner=partner, external_id="OP-A", occurred_on=SALE_DAY - timedelta(days=10)
    )
    # On the previous sale's own day — justifies the first, not the second.
    await _call(call_factory, installation, partner, at=NOON - timedelta(days=10))
    await sale_factory(partner=partner, external_id="OP-B", occurred_on=SALE_DAY)

    rows = {row.external_id: row for row in await _rows(db)}
    assert rows["OP-A"].verdict.verdict == Verdict.OK.value
    assert rows["OP-B"].verdict.verdict == Verdict.SUSPICIOUS.value
    assert "R2" in rows["OP-B"].verdict.broken_rules
    assert rows["OP-B"].verdict.calls_between == 0


async def test_r2_is_silent_on_a_first_sale(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """There is nothing to compare against, so the rule does not fire."""
    partner = await partner_factory()
    await sale_factory(partner=partner)
    await _call(call_factory, installation, partner, at=NOON)

    row = await _one(db)
    assert row.verdict.previous_sale_on is None
    assert "R2" not in row.verdict.broken_rules


async def test_two_sales_on_one_day_do_not_make_each_other_suspicious(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """⚠️ WITHOUT ``DISTINCT`` BEFORE ``lag``, the second sale of a day treats
    its own twin as "the previous sale"; the gap between them is empty and R2
    breaks automatically — every second sale becomes suspicious for no reason.
    """
    partner = await partner_factory()
    await _call(call_factory, installation, partner, at=NOON)
    await sale_factory(partner=partner, external_id="OP-A", occurred_on=SALE_DAY)
    await sale_factory(partner=partner, external_id="OP-B", occurred_on=SALE_DAY)

    rows = await _rows(db)
    assert {row.verdict.verdict for row in rows} == {Verdict.OK.value}
    assert {row.verdict.previous_sale_on for row in rows} == {None}


async def test_the_previous_sale_is_found_outside_the_period(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """⚠️ Computed over the FILTERED set, every sale at the start of a period
    would look like a first sale and R2 would switch itself off silently."""
    partner = await partner_factory()
    await sale_factory(
        partner=partner, external_id="OP-OLD", occurred_on=SALE_DAY - timedelta(days=30)
    )
    await sale_factory(partner=partner, external_id="OP-NEW", occurred_on=SALE_DAY)
    await _call(call_factory, installation, partner, at=NOON)

    # The period covers only the newer sale.
    rows = await _rows(db, since=SALE_DAY, until=SALE_DAY)
    assert len(rows) == 1
    assert rows[0].verdict.previous_sale_on == SALE_DAY - timedelta(days=30)


async def test_the_previous_sale_is_keyed_on_the_code_not_the_number(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """A FIX against BonviZvonki, which partitions by the copied phone key.

    Two customers behind one switchboard number keep separate histories here;
    keyed on the number, the second customer's first sale would inherit the
    first customer's date and R2 would fire against a sale that never happened.
    """
    shared = "+998901234567"
    left = await partner_factory(code="К00100", phone=shared)
    right = await partner_factory(code="К00200", phone=shared)
    await sale_factory(
        partner=left, external_id="OP-L", occurred_on=SALE_DAY - timedelta(days=5)
    )
    await sale_factory(partner=right, external_id="OP-R", occurred_on=SALE_DAY)
    await _call(call_factory, installation, left, at=NOON)

    rows = {row.external_id: row for row in await _rows(db)}
    assert rows["OP-R"].verdict.previous_sale_on is None, "a different customer"


# ══════════════════════════════════════════════════════════════
#  R3 — never spoken to at all
# ══════════════════════════════════════════════════════════════


async def test_a_customer_never_spoken_to_breaks_every_rule(
    db, partner_factory, sale_factory
) -> None:
    """The harshest signal: a phone number, a sale, and no conversation ever."""
    partner = await partner_factory()
    await sale_factory(partner=partner)

    row = await _one(db)
    assert row.verdict.verdict == Verdict.SUSPICIOUS.value
    assert row.verdict.broken_rules == ["R1", "R3"], "always in this order"
    assert row.verdict.calls_total == 0


# ══════════════════════════════════════════════════════════════
#  The third class — not checkable is NOT clean
# ══════════════════════════════════════════════════════════════


async def test_a_customer_with_no_usable_number_cannot_be_checked(
    db, partner_factory, sale_factory
) -> None:
    """Blaming somebody for a gap in SAP's own export would be the false signal
    this product exists to prevent."""
    partner = await partner_factory(phone="(99) 999-99-99")
    assert partner.phone_key is None, "a fabricated number never gets a key"
    await sale_factory(partner=partner)

    row = await _one(db)
    assert row.verdict.verdict == Verdict.NOT_CHECKABLE.value
    assert row.verdict.skip_reason == SkipReason.NO_PHONE.value
    assert row.verdict.broken_rules == [], "no rule is claimed against it"


async def test_a_code_missing_from_the_catalogue_still_appears(
    db, sale_factory
) -> None:
    """⚠️ An INNER join would make it drop out of the list SILENTLY. It is
    ``not_checkable``, and ``partner_excluded`` is false because there is no
    catalogue row to carry the flag."""
    await sale_factory(partner_code="К09999")

    row = await _one(db)
    assert row.verdict.verdict == Verdict.NOT_CHECKABLE.value
    assert row.verdict.skip_reason == SkipReason.NO_PHONE.value
    assert row.partner_excluded is False


async def test_an_inactive_contractor_is_not_matched(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """The manager's decision: an inactive contractor does not count."""
    partner = await partner_factory(is_active=False)
    await sale_factory(partner=partner)
    await _call(call_factory, installation, partner, at=NOON)

    row = await _one(db)
    assert row.verdict.verdict == Verdict.NOT_CHECKABLE.value


# ══════════════════════════════════════════════════════════════
#  Only sales are checked
# ══════════════════════════════════════════════════════════════


async def test_payments_and_returns_are_stored_and_never_checked(
    db, partner_factory, sale_factory
) -> None:
    """They belong on the customer's timeline; they are not agreements."""
    partner = await partner_factory()
    await sale_factory(partner=partner, external_id="OP-PAY", op_type="payment_in")
    await sale_factory(partner=partner, external_id="OP-OTHER", op_type="other")

    assert await _rows(db) == []
    stored = (await db.execute(select(SaleModel.external_id))).scalars().all()
    assert set(stored) == {"OP-PAY", "OP-OTHER"}, "nothing was dropped"


# ══════════════════════════════════════════════════════════════
#  Two sections: regular customers and walk-ins
# ══════════════════════════════════════════════════════════════


async def test_a_shared_code_is_absent_from_the_regular_list(
    db, partner_factory, sale_factory
) -> None:
    """Measured: 718 sales and $531,432 under ``К00001`` alone. Counted as
    ``not_checkable`` among regular customers, they wrote "could not be
    checked" into an employee's column for what was a KIND OF WORK."""
    partner = await partner_factory(code="К00001")
    await sale_factory(partner=partner)

    assert await _rows(db) == []


async def test_the_same_sale_appears_in_the_walk_in_section(
    db, partner_factory, sale_factory
) -> None:
    """The sale is not lost — it moves to the section whose question it can
    actually answer."""
    partner = await partner_factory(code="К00001")
    await sale_factory(partner=partner)

    row = await _one(db, client_kind=ClientKind.WALK_IN.value)
    assert row.verdict.verdict == Verdict.NOT_CHECKABLE.value
    assert row.verdict.skip_reason == SkipReason.GENERIC_CODE.value


async def test_the_shared_code_marker_follows_the_setting_not_a_constant(
    db, partner_factory, sale_factory, set_sales_setting
) -> None:
    """A FIX against BonviZvonki, which tests the built-in constant here while
    splitting the sections on the setting. A deployment that adds a shared code
    got rows excluded from the regular list AND scored by the rules in the
    walk-in one — where the rules are meant not to apply at all.
    """
    await set_sales_setting("sales.walk_in_codes", "К07777")
    partner = await partner_factory(code="К07777")
    await sale_factory(partner=partner)

    row = await _one(db, client_kind=ClientKind.WALK_IN.value)
    assert row.verdict.skip_reason == SkipReason.GENERIC_CODE.value
    assert row.verdict.verdict == Verdict.NOT_CHECKABLE.value


async def test_a_walk_in_ticket_over_the_limit_is_flagged(
    db, partner_factory, sale_factory
) -> None:
    """The walk-in section's whole measure: the rules cannot apply, so the
    question becomes "is any single ticket unusually large"."""
    partner = await partner_factory(code="К00001")
    await sale_factory(partner=partner, external_id="OP-BIG", amount_usd=Decimal("5000"))
    await sale_factory(partner=partner, external_id="OP-SMALL", amount_usd=Decimal("10"))

    rows = {
        row.external_id: row
        for row in await _rows(db, client_kind=ClientKind.WALK_IN.value)
    }
    assert rows["OP-BIG"].over_limit is True
    assert rows["OP-SMALL"].over_limit is False


async def test_a_sale_of_unknown_value_is_not_over_the_limit(
    db, partner_factory, sale_factory
) -> None:
    """⚠️ Putting it on the "over the limit" list would be an accusation built
    on a gap in SAP's export."""
    partner = await partner_factory(code="К00001")
    await sale_factory(partner=partner, amount_usd=None)

    row = await _one(db, client_kind=ClientKind.WALK_IN.value)
    assert row.over_limit is False


async def test_a_large_sale_to_a_regular_customer_is_never_over_the_limit(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """There is no notion of a limit there — it would fill the screen with
    false warnings."""
    partner = await partner_factory()
    await sale_factory(partner=partner, amount_usd=Decimal("999999"))
    await _call(call_factory, installation, partner, at=NOON)

    row = await _one(db)
    assert row.over_limit is False


# ══════════════════════════════════════════════════════════════
#  Out of scope — one section, two sources
# ══════════════════════════════════════════════════════════════


async def test_an_excluded_branch_is_in_neither_the_list_nor_the_counts(
    db, partner_factory, sale_factory, sale_branch_factory, call_factory, installation
) -> None:
    partner = await partner_factory()
    await sale_branch_factory("Логистика", excluded_at=datetime.now(UTC))
    await sale_factory(partner=partner, external_id="OP-OUT", branch="Логистика")
    await sale_factory(partner=partner, external_id="OP-IN", branch="Бухоро")
    await _call(call_factory, installation, partner, at=NOON)

    assert [row.external_id for row in await _rows(db)] == ["OP-IN"]
    summary = await ComplianceService(db).summary(await _scope(db))
    assert summary.total == 1


async def test_a_branch_with_no_name_stays_in_the_main_list(
    db, partner_factory, sale_factory, sale_branch_factory
) -> None:
    """⚠️ In SQL ``NULL NOT IN (…)`` is NULL, not true, so a sale with no branch
    would drop SILENTLY out of the main list the moment anything was excluded.
    SAP does produce them."""
    partner = await partner_factory()
    await sale_branch_factory("Логистика", excluded_at=datetime.now(UTC))
    await sale_factory(partner=partner, external_id="OP-NOBRANCH", branch=None)

    assert [row.external_id for row in await _rows(db)] == ["OP-NOBRANCH"]


async def test_the_out_of_scope_section_shows_exactly_the_excluded(
    db, partner_factory, sale_factory, sale_branch_factory
) -> None:
    partner = await partner_factory()
    await sale_branch_factory("Логистика", excluded_at=datetime.now(UTC))
    await sale_factory(partner=partner, external_id="OP-OUT", branch="Логистика")
    await sale_factory(partner=partner, external_id="OP-IN", branch="Бухоро")

    rows = await _rows(db, out_of_scope=True)
    assert [row.external_id for row in rows] == ["OP-OUT"]


async def test_the_out_of_scope_section_is_empty_when_nobody_is_excluded(
    db, partner_factory, sale_factory
) -> None:
    """"Nobody excluded" must mean an EMPTY section, never "everything"."""
    partner = await partner_factory()
    await sale_factory(partner=partner)

    assert await _rows(db, out_of_scope=True) == []


async def test_an_excluded_customer_leaves_the_main_list(
    db, partner_factory, sale_factory
) -> None:
    """Measured: 25 such contractors, 127 sales in three weeks, 102 of them
    permanently suspicious and burying the real defects."""
    partner = await partner_factory(excluded_at=datetime.now(UTC))
    await sale_factory(partner=partner)

    assert await _rows(db) == []
    assert len(await _rows(db, out_of_scope=True)) == 1


async def test_an_excluded_customer_leaves_the_walk_in_section_too(
    db, partner_factory, sale_factory
) -> None:
    """⚠️ THE ONE DIFFERENCE FROM A BRANCH. A branch measures "who sold" and is
    irrelevant under a shared code; a customer measures "who bought", and an
    excluded customer must not be under control ANYWHERE — or "I excluded them"
    is a half-done action."""
    partner = await partner_factory(code="К00001", excluded_at=datetime.now(UTC))
    await sale_factory(partner=partner)

    assert await _rows(db, client_kind=ClientKind.WALK_IN.value) == []


async def test_an_excluded_branch_does_not_reach_the_walk_in_section(
    db, partner_factory, sale_factory, sale_branch_factory
) -> None:
    """The mirror of the test above. Cut here as well, an excluded branch's
    shared-code sales would be visible in NO section at all (measured: 47)."""
    partner = await partner_factory(code="К00001")
    await sale_branch_factory("Логистика", excluded_at=datetime.now(UTC))
    await sale_factory(partner=partner, branch="Логистика")

    assert len(await _rows(db, client_kind=ClientKind.WALK_IN.value)) == 1
    assert await _rows(db, client_kind=ClientKind.WALK_IN.value, out_of_scope=True) == []


async def test_putting_a_customer_back_restores_the_history_with_no_re_import(
    db, partner_factory, sale_factory
) -> None:
    """⚠️ THE CENTRAL PROOF: the sale was never deleted."""
    partner = await partner_factory(excluded_at=datetime.now(UTC))
    await sale_factory(partner=partner, external_id="OP-BACK")
    assert await _rows(db) == []

    partner.excluded_at = None
    await db.flush()

    assert [row.external_id for row in await _rows(db)] == ["OP-BACK"]


async def test_a_row_carries_its_customer_exclusion_state(
    db, partner_factory, sale_factory
) -> None:
    """``partner_excluded`` is for the BUTTON: without it the card would open
    saying "Exclude" even for a customer already excluded, and there would be
    no way back from the screen."""
    partner = await partner_factory(excluded_at=datetime.now(UTC))
    await sale_factory(partner=partner)

    row = await _one(db, out_of_scope=True)
    assert row.partner_excluded is True


# ══════════════════════════════════════════════════════════════
#  The review queue
# ══════════════════════════════════════════════════════════════


async def test_a_decided_sale_leaves_the_default_queue(
    db, partner_factory, sale_factory, sale_review_factory
) -> None:
    """Otherwise the manager sees the rows they have already dealt with again
    every day and the queue never ends."""
    partner = await partner_factory()
    sale = await sale_factory(partner=partner)
    await sale_review_factory(sale.id, status="justified")

    page = await ComplianceService(db).page(
        await _scope(db, review=ReviewState.NEW.value), limit=50
    )
    assert page.items == []

    page = await ComplianceService(db).page(
        await _scope(db, review=ReviewState.JUSTIFIED.value), limit=50
    )
    assert len(page.items) == 1
    assert page.items[0].review is not None
    assert page.items[0].review.status == "justified"


# ══════════════════════════════════════════════════════════════
#  The report
# ══════════════════════════════════════════════════════════════


async def test_all_three_classes_are_counted(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """One card must not hide another: "how many could not be checked" is the
    measure of SAP's own data quality."""
    clean = await partner_factory(code="К00011")
    dirty = await partner_factory(code="К00022")
    blind = await partner_factory(code="К00033", phone="(99) 999-99-99")
    await sale_factory(partner=clean, external_id="OP-1")
    await sale_factory(partner=dirty, external_id="OP-2")
    await sale_factory(partner=blind, external_id="OP-3")
    await _call(call_factory, installation, clean, at=NOON)

    summary = await ComplianceService(db).summary(await _scope(db))
    assert (summary.total, summary.ok, summary.suspicious, summary.not_checkable) == (
        3,
        1,
        1,
        1,
    )
    assert summary.window_days == 3
    assert summary.new == 1, "suspicious and not yet decided"


async def test_the_report_ignores_the_verdict_filter(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """⚠️ With the report following the list's filter, choosing "suspicious"
    would drop two of the three cards to zero."""
    clean = await partner_factory(code="К00011")
    dirty = await partner_factory(code="К00022")
    await sale_factory(partner=clean, external_id="OP-1")
    await sale_factory(partner=dirty, external_id="OP-2")
    await _call(call_factory, installation, clean, at=NOON)

    summary = await ComplianceService(db).summary(
        await _scope(db, verdict=Verdict.SUSPICIOUS.value)
    )
    assert (summary.ok, summary.suspicious) == (1, 1)


async def test_sales_with_no_employee_are_their_own_row_in_the_cut(
    db, partner_factory, sale_factory
) -> None:
    """They must not vanish quietly: a branch linked to nobody is exactly what
    the map screen exists to surface."""
    partner = await partner_factory()
    await sale_factory(partner=partner)

    summary = await ComplianceService(db).summary(await _scope(db))
    assert [row.agent_id for row in summary.agents] == [None]
    assert summary.agents[0].sales == 1


# ══════════════════════════════════════════════════════════════
#  Attribution — whoever spoke outranks the branch
# ══════════════════════════════════════════════════════════════


async def test_the_employee_who_spoke_outranks_the_branch(
    db,
    partner_factory,
    sale_factory,
    sale_branch_factory,
    call_factory,
    installation_factory,
    agent_factory,
) -> None:
    """⚠️ A branch is a PLACE. Measured: 20 of 34 branches are linked to nobody,
    and 1,100 sales would have had no employee at all."""
    branch_agent = await agent_factory(full_name="Filial xodimi")
    talker = await agent_factory(full_name="Gaplashgan")
    partner = await partner_factory()
    await sale_branch_factory("Бухоро", agent_id=branch_agent.id)
    await sale_factory(partner=partner, branch="Бухоро", agent_id=branch_agent.id)
    await _call(
        call_factory,
        await installation_factory(agent=talker),
        partner,
        at=NOON,
    )

    changed = await refresh_sale_attribution(db, window_days=3)
    assert changed == 1
    row = await _one(db)
    assert row.agent_name == "Gaplashgan"


async def test_a_sale_nobody_spoke_about_falls_back_to_the_branch(
    db, partner_factory, sale_factory, sale_branch_factory, agent_factory
) -> None:
    """The clean rule ("if nobody spoke, the sale belongs to nobody") dropped
    coverage from 3,367 sales to 2,849 and emptied part of every report."""
    branch_agent = await agent_factory(full_name="Filial xodimi")
    partner = await partner_factory()
    await sale_branch_factory("Бухоро", agent_id=branch_agent.id)
    await sale_factory(partner=partner, branch="Бухоро", agent_id=branch_agent.id)

    await refresh_sale_attribution(db, window_days=3)
    row = await _one(db)
    assert row.agent_name == "Filial xodimi"


async def test_the_attribution_clears_itself_when_the_call_goes_away(
    db, partner_factory, sale_factory, call_factory, installation
) -> None:
    """⚠️ IN BOTH DIRECTIONS. Write-only, and a deleted call would leave the old
    employee sitting on the sale for ever."""
    partner = await partner_factory()
    sale = await sale_factory(partner=partner)
    call = await _call(call_factory, installation, partner, at=NOON)

    await refresh_sale_attribution(db, window_days=3)
    await db.refresh(sale)
    assert sale.attributed_call_id == call.id

    await db.delete(call)
    await db.flush()
    await refresh_sale_attribution(db, window_days=3)
    await db.refresh(sale)
    assert sale.attributed_call_id is None
    assert sale.call_agent_id is None


async def test_the_attributed_call_is_the_one_nearest_the_sale(
    db,
    partner_factory,
    sale_factory,
    call_factory,
    installation_factory,
    agent_factory,
) -> None:
    """Whoever closed the sale is usually the last to have spoken. Measured:
    294 such cases in a 3-day window."""
    early = await installation_factory(agent=await agent_factory(full_name="Birinchi"))
    late = await installation_factory(agent=await agent_factory(full_name="Oxirgi"))
    partner = await partner_factory()
    await sale_factory(partner=partner)
    await _call(call_factory, early, partner, at=NOON - timedelta(days=2))
    latest = await _call(call_factory, late, partner, at=NOON)

    await refresh_sale_attribution(db, window_days=3)
    row = await _one(db)
    assert row.agent_name == "Oxirgi"
    assert row.verdict.last_call_id == latest.id, "and the panel can open it"
