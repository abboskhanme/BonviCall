"""Every function in ``rules.py``, with no session and no clock (§13).

The numbers asserted here are BonviZvonki's measured ones. Where this port
changed a number — the message TTL ceiling — the test says which behaviour it
is pinning and why, so the change cannot be undone by accident.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.modules.surveys import rules

TASHKENT = ZoneInfo("Asia/Tashkent")
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


# ── The red-flag registry ──────────────────────────────────────────────────


def test_the_registry_is_the_ten_criteria_the_source_ships() -> None:
    assert len(rules.RED_FLAGS) == 10
    assert [key for key, _ in rules.RED_FLAGS] == [
        "rude",
        "no_answer",
        "late_reply",
        "broken_promise",
        "wrong_price",
        "late_delivery",
        "wrong_order",
        "bad_quality",
        "no_document",
        "pushy",
    ]


def test_normalize_keeps_the_order_the_customer_ticked_in() -> None:
    assert rules.normalize_red_flags(["pushy", "rude", "pushy"]) == ["pushy", "rude"]


def test_normalize_refuses_an_unknown_key_rather_than_dropping_it() -> None:
    """Silently discarding it would store an answer the customer did not give."""
    with pytest.raises(rules.UnknownRedFlag) as raised:
        rules.normalize_red_flags(["rude", "invented"])
    assert raised.value.keys == ["invented"]


def test_normalize_treats_none_and_empty_alike() -> None:
    assert rules.normalize_red_flags(None) == []
    assert rules.normalize_red_flags([]) == []


# ── Tokens and the anonymous hash ──────────────────────────────────────────


def test_a_token_is_unpredictable_and_fits_the_column() -> None:
    tokens = {rules.new_token() for _ in range(200)}
    assert len(tokens) == 200
    assert all(len(token) <= rules.SURVEY_TOKEN_MAX_LEN for token in tokens)


def test_the_respondent_hash_is_stable_and_fits_the_column() -> None:
    first = rules.respondent_hash("tok", 4242)
    assert first == rules.respondent_hash("tok", 4242)
    assert len(first) == rules.RESPONDENT_HASH_LEN


def test_one_person_is_unlinkable_across_two_surveys() -> None:
    """The anonymity promise, as arithmetic.

    Different token, same human, different hash — so "what did this customer
    say last time" has no answer at all. This is the property the whole design
    exists for, and it is one assertion.
    """
    assert rules.respondent_hash("token-a", 7) != rules.respondent_hash("token-b", 7)


# ── Settings resolvers ─────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["", "abc", None, 0, -3, [], {}])
def test_a_nonsense_threshold_lands_on_the_documented_default(value: object) -> None:
    """A rating that appears after one answer is as wrong as one that never does."""
    assert rules.resolve_positive_int(value, rules.DEFAULT_MIN_RESPONSES) == 5


def test_a_usable_threshold_is_honoured() -> None:
    assert rules.resolve_positive_int(8, rules.DEFAULT_MIN_RESPONSES) == 8
    assert rules.resolve_positive_int("8", rules.DEFAULT_MIN_RESPONSES) == 8


def test_zero_ttl_means_never_delete_and_is_not_confused_with_a_bad_value() -> None:
    assert rules.resolve_message_ttl_hours(0) == 0
    assert rules.resolve_message_ttl_hours(-5) == 0
    assert rules.resolve_message_ttl_hours("rubbish") == rules.DEFAULT_MESSAGE_TTL_HOURS


def test_the_ttl_ceiling_leaves_room_inside_telegrams_48_hour_limit() -> None:
    """⚠️ This is a FIX and the assertion is the point.

    BonviZvonki clamps to exactly 48, which is the hour Telegram stops letting
    a bot delete its own message — so its documented maximum is the one value
    guaranteed to fail. 47 leaves an hour of margin.
    """
    assert rules.MESSAGE_TTL_CEILING_HOURS < rules.TELEGRAM_DELETE_LIMIT_HOURS
    assert rules.resolve_message_ttl_hours(1000) == 47
    assert rules.resolve_message_ttl_hours(48) == 47


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),
        ("HA", True),
        ("on", True),
        ("1", True),
        ("false", False),
        ("", False),
        (None, False),
        (1, True),
        (0, False),
    ],
)
def test_as_bool_never_reads_the_string_false_as_true(value: object, expected: bool) -> None:
    """``bool("false")`` is True, and this flag failing open would post to customers."""
    assert rules.as_bool(value) is expected


# ── Eligibility ────────────────────────────────────────────────────────────


def test_an_unbound_group_is_blocked_and_force_cannot_clear_it() -> None:
    block = rules.structural_block(
        agent_id_present=False, is_active=True, bot_status="member"
    )
    assert block is not None
    assert block.reason == rules.BLOCK_NOT_BOUND
    assert block.bypassable is False


@pytest.mark.parametrize("status", ["left", "kicked"])
def test_a_chat_the_bot_is_out_of_is_blocked(status: str) -> None:
    block = rules.structural_block(
        agent_id_present=True, is_active=True, bot_status=status
    )
    assert block is not None
    assert block.reason == rules.BLOCK_INACTIVE


def test_a_bound_active_group_is_not_blocked() -> None:
    assert (
        rules.structural_block(
            agent_id_present=True, is_active=True, bot_status="member"
        )
        is None
    )


def test_suppression_opens_exactly_on_the_window_boundary() -> None:
    window = rules.DEFAULT_SUPPRESSION_DAYS
    assert rules.suppression_block(NOW - timedelta(days=window), NOW, window) is None
    assert (
        rules.suppression_block(NOW - timedelta(days=window - 1), NOW, window)
        is not None
    )


def test_a_group_never_asked_is_never_suppressed() -> None:
    assert rules.suppression_block(None, NOW, 10) is None


def test_days_since_floors_at_zero_for_a_future_stamp() -> None:
    """⚠️ A FIX. ``(now - last).days`` floors toward negative infinity, so a
    stamp a second in the future — clock skew, or a concurrent transaction —
    made the source tell an admin "the last survey was created -1 days ago"."""
    assert rules.days_since(NOW + timedelta(seconds=30), NOW) == 0
    assert rules.days_remaining(NOW + timedelta(seconds=30), NOW, 10) == 10


def test_days_remaining_never_goes_negative() -> None:
    assert rules.days_remaining(NOW - timedelta(days=99), NOW, 10) == 0


# ── Automatic binding ──────────────────────────────────────────────────────


def test_a_manual_row_is_left_alone_even_when_somebody_is_recognised() -> None:
    """⚠️ The guard that stops the bot undoing an admin's correction overnight."""
    decision = rules.autobind_decision(
        bound_by="manual", current_agent_id="old", matched_agent_id="new"
    )
    assert decision.write is False
    assert decision.agent_id is None
    assert decision.reason == rules.AUTOBIND_MANUAL


def test_a_recognised_employee_is_bound() -> None:
    decision = rules.autobind_decision(
        bound_by=None, current_agent_id=None, matched_agent_id="new"
    )
    assert decision.write is True
    assert decision.agent_id == "new"


def test_recognising_nobody_keeps_the_employee_already_there() -> None:
    """Today perhaps only the customer wrote; that is not a change of employee."""
    decision = rules.autobind_decision(
        bound_by="auto", current_agent_id="old", matched_agent_id=None
    )
    assert decision.write is False
    assert decision.reason == rules.AUTOBIND_MATCHED


def test_recognising_nobody_on_an_unbound_group_says_so() -> None:
    decision = rules.autobind_decision(
        bound_by=None, current_agent_id=None, matched_agent_id=None
    )
    assert decision.reason == rules.AUTOBIND_NO_AGENT
    assert decision.write is False


# ── The rating ─────────────────────────────────────────────────────────────


def test_below_the_threshold_the_average_is_none_and_never_zero() -> None:
    """A 0.0 would be drawn as 'rated badly' by every chart on the page."""
    figure = rules.rating(total=3, average=4.5, min_responses=5)
    assert figure.average is None
    assert figure.ready is False
    assert figure.count == 3


def test_on_the_threshold_the_average_opens() -> None:
    figure = rules.rating(total=5, average=4.333333, min_responses=5)
    assert figure.ready is True
    assert figure.average == 4.33


def test_the_distribution_always_has_five_bars() -> None:
    assert rules.distribution({5: 2, 1: 1}) == {
        "1": 1,
        "2": 0,
        "3": 0,
        "4": 0,
        "5": 2,
    }


def test_the_response_rate_is_none_when_nothing_was_sent() -> None:
    """Null, not 0 %: there is no basis to compute, and 0 reads as 'nobody answered'."""
    assert rules.response_rate(sent=0, answered=0) is None


def test_the_response_rate_is_a_percentage_to_one_place() -> None:
    assert rules.response_rate(sent=3, answered=1) == 33.3


# ── Windows ────────────────────────────────────────────────────────────────


def test_the_default_window_is_whole_local_days_ending_today() -> None:
    window = rules.report_window(
        days=7, date_from=None, date_to=None, today=date(2026, 9, 17), zone=TASHKENT
    )
    assert window.date_from == date(2026, 9, 11)
    assert window.date_to == date(2026, 9, 17)
    assert window.days == 7
    assert window.since == datetime(2026, 9, 11, tzinfo=TASHKENT)
    # Exclusive: local midnight AFTER date_to, so the 17th is included whole.
    assert window.until == datetime(2026, 9, 18, tzinfo=TASHKENT)


def test_date_to_is_inclusive_by_construction() -> None:
    """⚠️ The bug this shape deletes, measured in the source: its filter is
    ``responded_at <= date_to`` over a NAIVE local midnight, which in UTC+5 is
    the previous day — one agent's rating read 3.8 on one page and 3.0 on
    another, a 0.8 gap on a five-point scale from nothing but a timezone."""
    window = rules.report_window(
        days=7,
        date_from=date(2026, 8, 10),
        date_to=date(2026, 8, 16),
        today=date(2026, 9, 17),
        zone=TASHKENT,
    )
    assert window.until == datetime(2026, 8, 17, tzinfo=TASHKENT)
    assert window.days == 7


def test_an_explicit_range_is_never_converted_back_into_a_day_count() -> None:
    window = rules.report_window(
        days=7,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 3, 31),
        today=date(2026, 9, 17),
        zone=TASHKENT,
    )
    assert window.days == 90


def test_a_backwards_range_names_the_field_at_fault() -> None:
    with pytest.raises(rules.WindowInvalid) as raised:
        rules.report_window(
            days=7,
            date_from=date(2026, 9, 17),
            date_to=date(2026, 9, 1),
            today=date(2026, 9, 17),
            zone=TASHKENT,
        )
    assert raised.value.field_name == "date_from"


def test_a_pasted_url_cannot_ask_for_five_years() -> None:
    with pytest.raises(rules.WindowInvalid):
        rules.report_window(
            days=7,
            date_from=date(2020, 1, 1),
            date_to=date(2026, 9, 17),
            today=date(2026, 9, 17),
            zone=TASHKENT,
        )


def test_the_survey_period_is_half_open_and_ends_now() -> None:
    period = rules.survey_period(NOW, 14)
    assert period.end == NOW
    assert period.start == NOW - timedelta(days=14)


def test_a_token_lives_seven_days() -> None:
    assert rules.token_expiry(NOW) == NOW + timedelta(days=7)


def test_a_zero_ttl_yields_no_delete_deadline_rather_than_now() -> None:
    """``None``, not ``now`` — otherwise "never delete" would delete everything."""
    assert rules.message_delete_deadline(NOW, 0) is None
    assert rules.message_delete_deadline(NOW, 24) == NOW - timedelta(hours=24)


# ── ILIKE escaping ─────────────────────────────────────────────────────────


def test_ilike_metacharacters_are_escaped_backslash_first() -> None:
    """Unescaped, a title containing ``%`` matches every row and the filter is gone."""
    assert rules.ilike_escape("100%") == "100\\%"
    assert rules.ilike_escape("a_b") == "a\\_b"
    assert rules.ilike_escape("c:\\x") == "c:\\\\x"
