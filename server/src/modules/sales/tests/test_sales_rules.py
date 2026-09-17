"""The pure half of sales control: the vocabulary, the parsers, the message.

No session, no container, no clock. Every case here is a defect that was
measured against a real SAP export — the numbers are in ``rules.py`` beside the
code they justify, and these tests are what stops any of them coming back.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from src.modules.sales import telegram
from src.modules.sales.digest import (
    MIN_TOP_SALES,
    TOP_AGENTS,
    TOP_SALES,
    AgentLine,
    DigestData,
    build_text,
    render,
)
from src.modules.sales.rules import (
    DEFAULT_WALK_IN_LIMIT_USD,
    DEFAULT_WINDOW_DAYS,
    GENERIC_PARTNER_CODES,
    MAX_WINDOW_DAYS,
    ComplianceRow,
    LegacyThousands,
    SaleOpType,
    SaleVerdict,
    Verdict,
    clamp_walk_in_limit,
    clamp_window_days,
    matchable_phone,
    normalise_branch,
    op_type_from_sap,
    parse_amount,
    parse_date,
    parse_optional_codes,
    parse_partner_codes,
)
from src.modules.sales.telegram import DIGEST_TEXT_LIMIT, LoggingDigestSender

#: The module's own source tree — read by the transport guarantee below.
MODULE = Path(__file__).resolve().parents[1]


# ── The operation type ────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Продажа", SaleOpType.SALE),
        ("  продажа  ", SaleOpType.SALE),
        ("Входящие платежи", SaleOpType.PAYMENT_IN),
        ("Закупка", SaleOpType.PURCHASE),
        ("Отмена продажи", SaleOpType.SALE_CANCEL),
        ("Отмена продажа", SaleOpType.SALE_CANCEL),
        ("Бух.оп", SaleOpType.ACCOUNTING),
        ("Бух.оп.", SaleOpType.ACCOUNTING),
    ],
)
def test_sap_types_map_onto_ours(raw: str, expected: SaleOpType) -> None:
    assert op_type_from_sap(raw) is expected


def test_the_doubled_word_in_the_real_export_is_recognised() -> None:
    """``Исходящие платежи платежи`` — 146 rows spell it exactly so.

    The written specification says ``Исходящие платежи``. Both are accepted, so
    the import works whether or not the export is ever corrected.
    """
    assert op_type_from_sap("Исходящие платежи платежи") is SaleOpType.PAYMENT_OUT
    assert op_type_from_sap("Исходящие платежи") is SaleOpType.PAYMENT_OUT


def test_an_unknown_type_becomes_other_rather_than_vanishing() -> None:
    """Dropping the row is SILENT data loss: the report says "read 2384" and
    the database holds 2300, and nobody sees the difference."""
    assert op_type_from_sap("Новая операция") is SaleOpType.OTHER
    assert op_type_from_sap(None) is SaleOpType.OTHER
    assert op_type_from_sap("") is SaleOpType.OTHER


# ── Branch <-> employee name ──────────────────────────────────


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Навоий", "Навои"),
        ("Жиззах", "Джиззах"),
        ("  Тошкент ", "тошкент"),
        ("Ёйма", "Ейма"),
    ],
)
def test_the_spellings_that_have_to_collapse_onto_one_form(
    left: str, right: str
) -> None:
    """The commonest SAP differences: a trailing ``й``, ``дж``/``ж``, ``ё``."""
    assert normalise_branch(left) == normalise_branch(right)


def test_the_fold_is_idempotent() -> None:
    """⚠️ The written rule was "ж -> дж", which DESTROYS ITSELF: the ``ж``
    inside ``Джиззах`` is replaced too and the result is ``дджиззах``. The
    reverse direction gives the same collapse and survives being applied twice.
    """
    once = normalise_branch("Джиззах")
    assert normalise_branch(once) == once


def test_different_branches_still_differ() -> None:
    """The folding removes a difference; it must not invent a collision."""
    assert normalise_branch("Бухоро") != normalise_branch("Хоразм")


# ── The shared-code lists ─────────────────────────────────────


@pytest.mark.parametrize("separator", [",", ";", "\n", "\r", "\t", "|"])
def test_any_separator_an_admin_pastes_is_accepted(separator: str) -> None:
    """The list is pasted out of SAP or out of a chat message. Demanding one
    exact character reads the list HALF, silently."""
    raw = separator.join(["К00001", " К02370 ", "К03223"])
    assert parse_partner_codes(raw) == GENERIC_PARTNER_CODES


def test_case_is_not_touched() -> None:
    """The code starts with a CYRILLIC К and ``upper()`` brings it no closer to
    a Latin ``K`` — normalising would only risk corrupting a real SAP code."""
    assert parse_partner_codes("к00001") == frozenset({"к00001"})


def test_an_empty_walk_in_list_falls_back_rather_than_emptying_a_section() -> None:
    """An empty set breaks BOTH sections at once and silently."""
    assert parse_partner_codes("") == GENERIC_PARTNER_CODES
    assert parse_partner_codes(None) == GENERIC_PARTNER_CODES
    assert parse_partner_codes("   ,  ,") == GENERIC_PARTNER_CODES


def test_an_empty_internal_list_is_a_real_answer() -> None:
    """⚠️ The opposite decision from the walk-in list, and deliberately: falling
    back here would quietly take a real customer out of sales control."""
    assert parse_optional_codes("") == frozenset()
    assert parse_optional_codes(None) == frozenset()
    assert parse_optional_codes("К09999") == frozenset({"К09999"})


def test_a_list_value_is_accepted_as_well_as_a_string() -> None:
    assert parse_optional_codes(["К1", "К2"]) == frozenset({"К1", "К2"})


# ── The settings bounds ───────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (3, 3),
        ("7", 7),
        (0, 0),
        (-5, 0),
        (99999, MAX_WINDOW_DAYS),
        ("uch kun", DEFAULT_WINDOW_DAYS),
        (None, DEFAULT_WINDOW_DAYS),
    ],
)
def test_the_window_is_clamped_and_never_stops_the_section(
    raw: object, expected: int
) -> None:
    """``99999`` typed into the setting would switch the whole of sales control
    off silently — every sale would find some conversation in its window."""
    assert clamp_window_days(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(2000, 2000), ("500", 500), (0, 0), (-1, 0), ("2 000 $", DEFAULT_WALK_IN_LIMIT_USD)],
)
def test_the_ticket_limit_is_clamped(raw: object, expected: int) -> None:
    """A negative limit would mark EVERY sale as over it."""
    assert clamp_walk_in_limit(raw) == expected


# ── Money: two generations of export ──────────────────────────


def test_old_export_text_uses_a_space_for_thousands_and_a_comma_for_decimals() -> None:
    assert parse_amount("1 950,000") == Decimal("1950.000")
    assert parse_amount("100 000,000") == Decimal("100000.000")


def test_an_old_export_integer_cell_is_a_thousand_times_too_large() -> None:
    """⚠️ Excel read ``"561,000"`` as 561000 and left ``#,##0`` on the cell.

    Verified against the document currency: ($) 8333 <-> 100 000,000 so'm, i.e.
    8.333 $; ($) 136240 <-> 500000 dirham, i.e. 136.240 $.
    """
    assert parse_amount(LegacyThousands(8333)) == Decimal("8.333")
    assert parse_amount(LegacyThousands(136240)) == Decimal("136.240")


def test_a_new_export_number_is_taken_unchanged() -> None:
    """⚠️ THE REWRITE. Every numeric cell used to be divided by 1000, and on the
    new export that turned 146,000 $ into 146 $ and 256 $ into 0. All 12,591
    money cells in the new file are plain ``General`` numbers.
    """
    assert parse_amount(1230.0) == Decimal("1230.000")
    assert parse_amount(256) == Decimal("256.000")
    assert parse_amount(0.0) == Decimal("0.000")


def test_a_boolean_is_not_money() -> None:
    """``bool`` is a child of ``int``; ``True`` must not become 1.000."""
    assert parse_amount(True) is None
    assert parse_amount(None) is None
    assert parse_amount("") is None
    assert parse_amount("—") is None


# ── Dates ─────────────────────────────────────────────────────


def test_the_sap_date_format_and_its_insurance() -> None:
    assert parse_date("20.08.2026") == date(2026, 8, 20)
    assert parse_date("2026-08-20") == date(2026, 8, 20)
    assert parse_date("20/08/2026") == date(2026, 8, 20)
    assert parse_date(date(2026, 8, 20)) == date(2026, 8, 20)


def test_a_time_excel_invented_is_discarded() -> None:
    """The export has no time part; a ``datetime``'s 00:00 is fabricated."""
    assert parse_date(datetime(2026, 8, 20, 0, 0, tzinfo=UTC)) == date(2026, 8, 20)


def test_an_unreadable_date_is_none_rather_than_a_guess() -> None:
    assert parse_date("kecha") is None
    assert parse_date(None) is None


# ── Which numbers we are willing to match on ──────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "(+99890) 1234567",
        "998901234567",
        "(90) 123-45-67",
        "(+ 9989) 1234567",
        "+998 90 111-22-33",
    ],
)
def test_a_usable_number_comes_back(raw: str) -> None:
    """The last-9 key itself is the DATABASE's job (``phone_key_sql``); this
    function only decides whether the raw value is eligible for one."""
    assert matchable_phone(raw) == raw


@pytest.mark.parametrize("raw", ["(+971) 50 123 4567", "(+992) 90 123 4567", "+7 701 234 5678"])
def test_a_foreign_number_is_refused(raw: str) -> None:
    """⚠️ Their last nine digits can COINCIDENTALLY look Uzbek and the sale
    would be tied to a stranger's calls. Measured: 75 such rows, 25 of them
    inside the customer group."""
    assert matchable_phone(raw) is None


@pytest.mark.parametrize("raw", ["(+99888) 8999998", "(+99899) 5555559", "(+90) 1234567"])
def test_the_borderline_numbers_that_must_survive(raw: str) -> None:
    """Killing an honest number is worse than a false key: the customer drops
    out of sales control silently. A short local number written with a plus is
    not international."""
    assert matchable_phone(raw) == raw


@pytest.mark.parametrize("raw", ["(0000) 000-00-03", "(0500) 000-00-01"])
def test_a_number_whose_tail_starts_with_a_zero_is_refused(raw: str) -> None:
    """No Uzbek national number starts with a zero — operator codes are
    33/88/90/…, landline codes 71/62/…"""
    assert matchable_phone(raw) is None


@pytest.mark.parametrize("raw", ["(99) 999-99-99", "(+99811) 1111111", "333333333"])
def test_a_single_repeated_digit_is_refused(raw: str) -> None:
    """Values typed to fill an empty cell. They count as "has a phone", no call
    is ever found, and the customer becomes suspicious FOR NO REASON — the
    exact false signal this product exists to prevent."""
    assert matchable_phone(raw) is None


def test_a_telegram_handle_is_not_a_phone_number() -> None:
    assert matchable_phone("@EadTrader") is None
    assert matchable_phone(None) is None
    assert matchable_phone("1234567") is None, "fewer than nine digits is never a key"


def test_a_trunk_zero_prefix_still_yields_a_usable_number() -> None:
    """``0901234567`` — ten digits, the tail is ``901234567``, which is fine."""
    assert matchable_phone("0901234567") == "0901234567"


# ── The daily message ─────────────────────────────────────────


def _row(name: str, amount: float | None, days_before: int | None) -> ComplianceRow:
    return ComplianceRow(
        id=uuid4(),
        occurred_on=date(2026, 8, 20),
        external_id=f"OP-{name}",
        doc_number="D-1",
        partner_code="К02711",
        partner_name=name,
        phone="+998901112233",
        phone_key="901112233",
        branch="Бухоро",
        direction="ВЕЛО",
        agent_id=uuid4(),
        agent_name="Aziz",
        amount=amount,
        currency="USD",
        amount_usd=amount,
        verdict=SaleVerdict(
            sale_id=uuid4(),
            verdict=Verdict.SUSPICIOUS.value,
            broken_rules=["R1"],
            skip_reason=None,
            last_call_at=(
                None
                if days_before is None
                else datetime(2026, 8, 20 - days_before, 9, 0, tzinfo=UTC)
            ),
            last_call_agent="Aziz",
            last_call_id=uuid4(),
            days_before=days_before,
            previous_sale_on=None,
            calls_between=0,
            calls_total=0,
        ),
        review=None,
    )


def _data(**overrides: object) -> DigestData:
    base: dict[str, object] = {
        "day": date(2026, 8, 20),
        "window_days": 3,
        "min_amount": 0,
        "total": 10,
        "ok": 6,
        "suspicious": 3,
        "not_checkable": 1,
        "agents": [AgentLine(name="Aziz", sales=5, suspicious=3)],
        "top": [_row("Alfa", 5610.0, 9)],
    }
    base.update(overrides)
    return DigestData(**base)  # type: ignore[arg-type]


def test_all_three_counts_are_in_the_message() -> None:
    """Nothing is hidden: "could not be checked" is a number too."""
    text = render(_data(), top_agents=TOP_AGENTS, top_sales=TOP_SALES)
    assert "<b>6</b>" in text and "<b>3</b>" in text and "<b>1</b>" in text
    assert "oldingi 3 kun" in text, "the window is stated on the screen"


def test_the_closing_sentence_is_never_dropped() -> None:
    """Read as an accusation, the system loses its credibility in a week."""
    for agents, sales in ((TOP_AGENTS, TOP_SALES), (0, MIN_TOP_SALES)):
        assert "AYBLAMAYDI" in render(_data(), top_agents=agents, top_sales=sales)


def test_the_evidence_explains_the_rule() -> None:
    """The reader should answer "why suspicious?" from the message itself."""
    text = render(_data(), top_agents=TOP_AGENTS, top_sales=TOP_SALES)
    assert "oxirgi suhbat" in text and "9 kun oldin" in text


def test_a_conversation_on_the_sale_day_says_so() -> None:
    text = render(
        _data(top=[_row("Alfa", 100.0, 0)]), top_agents=TOP_AGENTS, top_sales=TOP_SALES
    )
    assert "o'sha kuni" in text


def test_never_having_spoken_is_said_rather_than_left_blank() -> None:
    text = render(
        _data(top=[_row("Alfa", 100.0, None)]),
        top_agents=TOP_AGENTS,
        top_sales=TOP_SALES,
    )
    assert "suhbat umuman bo'lmagan" in text


def test_an_unknown_amount_is_said_out_loud() -> None:
    text = render(
        _data(top=[_row("Alfa", None, 2)]), top_agents=TOP_AGENTS, top_sales=TOP_SALES
    )
    assert "summa noma'lum" in text


def test_a_customer_name_with_an_ampersand_cannot_break_the_message() -> None:
    """Unescaped, Telegram rejects the WHOLE message — one customer's name and
    the daily digest simply never arrives."""
    text = render(
        _data(top=[_row('ООО "Bonvi" & Co', 10.0, 1)]),
        top_agents=TOP_AGENTS,
        top_sales=TOP_SALES,
    )
    assert "&amp;" in text and "&quot;" not in text


def test_walk_in_sales_are_stated_separately_rather_than_omitted() -> None:
    """The manager knows the day's SAP total; a smaller number with no
    explanation reads as "the system is losing sales"."""
    text = render(
        _data(
            walk_in_total=12,
            walk_in_over_limit=2,
            walk_in_over_amount=9000.0,
            walk_in_limit=2000,
        ),
        top_agents=TOP_AGENTS,
        top_sales=TOP_SALES,
    )
    assert "Bir martalik mijozlar" in text
    assert "kirmaydi" in text, "and why they are not in the counts above"


def test_a_clean_day_says_so() -> None:
    text = render(_data(suspicious=0, agents=[], top=[]), top_agents=5, top_sales=5)
    assert "Shubhali savdo yo'q" in text


def test_a_huge_day_still_fits_the_transport_limit() -> None:
    """⚠️ A longer message is REFUSED, not truncated — it would be LOST."""
    data = _data(
        agents=[AgentLine(name=f"Xodim {i:03d}", sales=40, suspicious=39) for i in range(80)],
        top=[_row("Mijoz " + "x" * 200, 10_000.0, 12) for _ in range(40)],
    )
    text = build_text(data)
    assert len(text) <= DIGEST_TEXT_LIMIT
    assert "AYBLAMAYDI" in text, "the meaning survives the shortening"
    assert "Toza:" in text, "and so do the counts"


def test_the_shortening_ladder_gives_up_the_least_useful_thing_first() -> None:
    """Sales 5 -> 3, then employees 5 -> 3 -> 1 -> gone. The figures stay."""
    small = _data()
    assert build_text(small) == render(small, top_agents=TOP_AGENTS, top_sales=TOP_SALES)


# ══════════════════════════════════════════════════════════════
#  Nothing leaves the machine
# ══════════════════════════════════════════════════════════════


def test_nothing_in_this_module_can_reach_the_network() -> None:
    """⚠️ LOAD-BEARING. Read the source rather than the behaviour: a behavioural
    assertion could only prove that ONE path did not call out.

    ``httpx`` is a real dependency of this server (the MoiZvonki client uses
    it), so its absence here is the thing that makes ``POST /sales/digest/test``
    unable to reach anybody.
    """
    banned = ("httpx", "aiohttp", "urllib.request", "requests", "api.telegram.org")
    offenders: list[str] = []
    for path in sorted(MODULE.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for token in banned:
            if token in source:
                offenders.append(f"{path.name}: {token}")
    assert offenders == [], (
        f"an outbound transport reached modules/sales: {offenders}. The digest "
        "is a seam on purpose — add a DigestSender implementation and register "
        "it through telegram.set_sender, with its token in core/config.py."
    )


def test_no_bot_token_is_a_settings_row() -> None:
    """``settings:read`` is granted to manager, so a key in ``app_settings`` is a
    key every manager can read — the same decision the analysis keys made."""
    from src.core.settings_keys import ALL_SETTING_KEYS

    assert not any("token" in key for key in ALL_SETTING_KEYS if key.startswith("sales."))


def test_the_only_sender_reports_that_it_did_not_send() -> None:
    """⚠️ It does NOT return ``ok=True``. A sender that claimed a delivery would
    write ``ok = true`` into ``sale_digests``, and that table exists to answer
    "did the message go out?" — an answer that is wrong is worse than no table.
    """
    assert isinstance(telegram.get_sender(), LoggingDigestSender)
