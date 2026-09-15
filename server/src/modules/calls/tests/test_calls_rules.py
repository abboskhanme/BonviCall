"""Every function in ``calls/rules.py`` (CONVENTIONS.md §13).

These run without a database on purpose: the empty-directory rule is the one
that cost BonviZvonki 82 mislabelled calls out of 98, and a rule that important
should not be reachable only through fixtures.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.modules.calls.rules import (
    CALL_CLASSES,
    STATS_DAILY_MAX_DAYS,
    VALID_DISPOSITIONS,
    LineDirectory,
    call_class,
    classify_call_type,
    clock_skew_seconds,
    custom_buckets,
    digits_of,
    resolve_audio_reason,
    stats_buckets,
)

DIRECTORY = LineDirectory(
    registered_keys=frozenset({"901112233", "935554433"}),
    exact=frozenset({"712000000"}),
    prefix=frozenset({"7871"}),
    suffix=frozenset({"700"}),
)


def test_empty_directory_never_yields_external() -> None:
    """UC-25's acceptance criterion, and the reason it exists.

    BonviZvonki defaulted an unknown number to ``external``, a classifier then
    had to guess from content, and 82 of 98 calls were mislabelled. If we do
    not know, we say ``unknown``.
    """
    empty = LineDirectory()
    for number in ("+998901112233", "+998935554433", "700", "", None):
        assert classify_call_type(number, empty) == "unknown"


def test_registered_numbers_are_internal() -> None:
    assert classify_call_type("+998 90 111-22-33", DIRECTORY) == "internal"
    assert classify_call_type("935554433", DIRECTORY) == "internal"


def test_a_stranger_is_external_once_the_directory_is_populated() -> None:
    assert classify_call_type("+998977778899", DIRECTORY) == "external"


def test_short_numbers_are_internal_extensions() -> None:
    """Fewer than six digits cannot be a customer."""
    for extension in ("700", "*700", "101", "12345"):
        assert classify_call_type(extension, DIRECTORY) == "internal"


def test_suffix_and_prefix_rules_match() -> None:
    """UC-25's ``*700`` is a suffix rule, not a wildcard search."""
    assert classify_call_type("+998712345700", DIRECTORY) == "internal"
    assert classify_call_type("787112233", DIRECTORY) == "internal"
    assert classify_call_type("+998712000000", DIRECTORY) == "internal"


def test_an_unparseable_number_is_unknown_not_external() -> None:
    assert classify_call_type(None, DIRECTORY) == "unknown"
    assert classify_call_type("", DIRECTORY) == "unknown"


@pytest.mark.parametrize(
    ("disposition", "expected"),
    [
        ("missed", "not_expected"),
        ("rejected", "not_expected"),
        ("no_answer", "not_expected"),
    ],
)
def test_unanswered_calls_never_expect_audio(disposition: str, expected: str) -> None:
    """An unanswered call in the gap report's denominator makes it meaningless."""
    assert resolve_audio_reason(disposition, audio_expected=True, client_reason=None) == expected


def test_answered_call_awaiting_audio_is_pending_upload() -> None:
    assert (
        resolve_audio_reason("answered", audio_expected=True, client_reason=None)
        == "pending_upload"
    )


def test_the_device_reason_wins_when_it_gives_one() -> None:
    """The handset knows why its own recorder failed; we do not."""
    assert (
        resolve_audio_reason("answered", audio_expected=True, client_reason="no_permission")
        == "no_permission"
    )


def test_answered_call_with_no_audio_expected_still_carries_a_reason() -> None:
    """N5: never null, never free text — the CHECK constraint depends on it."""
    assert (
        resolve_audio_reason("answered", audio_expected=False, client_reason=None)
        == "recording_route_unavailable"
    )


def test_clock_skew_is_whole_seconds_and_transit_corrected() -> None:
    received = 1_788_000_060_000
    device = 1_788_000_000_000
    assert clock_skew_seconds(received, device) == 60
    # Half the round trip belongs to the network, not to the handset's clock.
    assert clock_skew_seconds(received, device, device_rtt_ms=4000) == 58


def test_clock_skew_is_signed() -> None:
    """A phone running fast gives a negative skew; both directions are evidence."""
    assert clock_skew_seconds(1_788_000_000_000, 1_788_000_030_000) == -30


def test_digits_of_strips_everything_else() -> None:
    assert digits_of("+998 (90) 111-22-33") == "998901112233"
    assert digits_of(None) == ""


# --- The direction x disposition rule (UC-11) -------------------------------


@pytest.mark.parametrize(
    ("direction", "disposition"),
    [
        ("incoming", "answered"),
        ("incoming", "missed"),
        ("incoming", "rejected"),
        ("outgoing", "answered"),
        ("outgoing", "no_answer"),
    ],
)
def test_the_five_real_classes_are_valid(direction: str, disposition: str) -> None:
    """UC-11's five classes are direction x disposition, and only these five."""
    from src.modules.calls.rules import is_valid_combination

    assert is_valid_combination(direction, disposition) is True


@pytest.mark.parametrize(
    ("direction", "disposition"),
    [
        ("outgoing", "missed"),
        ("outgoing", "rejected"),
        ("incoming", "no_answer"),
    ],
)
def test_the_impossible_combinations_are_refused(direction: str, disposition: str) -> None:
    """"Missed" is the receiver's word and "no answer" is the caller's; a
    record that mixes them came from somewhere that does not understand the
    call it is describing."""
    from src.modules.calls.rules import is_valid_combination

    assert is_valid_combination(direction, disposition) is False


def test_an_unknown_direction_is_refused() -> None:
    from src.modules.calls.rules import is_valid_combination

    assert is_valid_combination("sideways", "answered") is False


# --- The chart's x-axis ------------------------------------------------------


def test_a_week_is_seven_days_ending_today() -> None:
    granularity, buckets = stats_buckets("week", date(2026, 9, 15))
    assert granularity == "day"
    assert buckets[0] == (date(2026, 9, 9), date(2026, 9, 9))
    assert buckets[-1] == (date(2026, 9, 15), date(2026, 9, 15))
    assert len(buckets) == 7


def test_a_month_is_thirty_rolling_days_not_the_calendar_month() -> None:
    """On the 1st a calendar month is one point, and the chart goes blank."""
    _, buckets = stats_buckets("month", date(2026, 9, 1))
    assert len(buckets) == 30
    assert buckets[0][0] == date(2026, 8, 3)
    assert buckets[-1][1] == date(2026, 9, 1)


def test_a_year_is_twelve_months_and_the_last_one_stops_today() -> None:
    granularity, buckets = stats_buckets("year", date(2026, 9, 15))
    assert granularity == "month"
    assert len(buckets) == 12
    assert buckets[0] == (date(2025, 10, 1), date(2025, 10, 31))
    # Clipped: drawing a whole September that is missing half its calls would
    # show the current month as a collapse.
    assert buckets[-1] == (date(2026, 9, 1), date(2026, 9, 15))


def test_the_year_window_survives_a_december_boundary() -> None:
    """The month arithmetic is done in whole months, not in 30-day jumps."""
    _, buckets = stats_buckets("year", date(2026, 1, 15))
    assert buckets[0][0] == date(2025, 2, 1)
    assert [start.month for start, _ in buckets] == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1]


def test_february_is_not_given_a_thirtieth_day() -> None:
    _, buckets = stats_buckets("year", date(2026, 3, 10))
    february = next(start_end for start_end in buckets if start_end[0].month == 2)
    assert february == (date(2026, 2, 1), date(2026, 2, 28))


def test_every_valid_combination_has_a_class_and_nothing_else_does() -> None:
    """The chart's five lines and the CHECK constraint are the same table."""
    for direction, dispositions in VALID_DISPOSITIONS.items():
        for disposition in dispositions:
            assert call_class(direction, disposition) is not None
    assert call_class("outgoing", "missed") is None
    assert len(set(CALL_CLASSES.values())) == 5


def test_a_short_custom_range_is_daily_and_inclusive_at_both_ends() -> None:
    granularity, buckets = custom_buckets(date(2026, 9, 1), date(2026, 9, 10))
    assert granularity == "day"
    assert len(buckets) == 10
    assert buckets[0] == (date(2026, 9, 1), date(2026, 9, 1))
    assert buckets[-1] == (date(2026, 9, 10), date(2026, 9, 10))


def test_one_day_is_a_range_of_one_bucket() -> None:
    _, buckets = custom_buckets(date(2026, 9, 15), date(2026, 9, 15))
    assert buckets == [(date(2026, 9, 15), date(2026, 9, 15))]


def test_a_long_custom_range_becomes_months_clipped_at_both_ends() -> None:
    """A part-month at either end is labelled by the range, not by the month."""
    granularity, buckets = custom_buckets(date(2026, 1, 20), date(2026, 6, 10))
    assert granularity == "month"
    assert buckets[0] == (date(2026, 1, 20), date(2026, 1, 31))
    assert buckets[-1] == (date(2026, 6, 1), date(2026, 6, 10))
    assert len(buckets) == 6


def test_the_daily_threshold_is_a_quarter() -> None:
    """Three months of daily points is readable; a year of them is a smear."""
    day_granularity, _ = custom_buckets(
        date(2026, 1, 1), date(2026, 1, 1) + timedelta(days=STATS_DAILY_MAX_DAYS - 1)
    )
    month_granularity, _ = custom_buckets(
        date(2026, 1, 1), date(2026, 1, 1) + timedelta(days=STATS_DAILY_MAX_DAYS)
    )
    assert day_granularity == "day"
    assert month_granularity == "month"
