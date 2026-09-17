"""Every function in ``analytics/rules.py`` (CONVENTIONS.md §13).

No database, no session, no application — which is the point of a ``rules.py``:
the window arithmetic is where this feature is most likely to be quietly wrong,
and these run in milliseconds.

The cases are BonviZvonki's own, ported from
``analytics/tests/test_bucket_starts.py`` and ``test_overview_math.py``: each
one is a defect that reached a screen there.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.core.clock import TASHKENT
from src.modules.analytics import rules


class TestWindowStart:
    def test_last_seven_days_includes_today(self) -> None:
        """Seven calendar days, not 168 hours — what a person means by "7 kun"."""
        assert rules.window_start(7, date(2026, 9, 17)) == date(2026, 9, 11)

    def test_one_day_is_today_alone(self) -> None:
        assert rules.window_start(1, date(2026, 9, 17)) == date(2026, 9, 17)

    def test_a_window_spans_a_month_boundary(self) -> None:
        assert rules.window_start(30, date(2026, 9, 17)) == date(2026, 8, 19)

    def test_zero_days_is_refused(self) -> None:
        """A window of no days would silently report the whole table."""
        with pytest.raises(ValueError):
            rules.window_start(0, date(2026, 9, 17))


class TestDayBounds:
    def test_bounds_are_tashkent_midnight_and_half_open(self) -> None:
        lower, upper = rules.day_bounds(date(2026, 9, 1), date(2026, 9, 30), TASHKENT)
        assert (lower.hour, lower.minute, lower.second) == (0, 0, 0)
        assert lower.utcoffset().total_seconds() == 5 * 3600
        # The upper bound is the first instant of the day AFTER date_to, so a
        # call at 23:59:59 on the 30th is in and one at 00:00:00 on the 1st is
        # not. Their ``_inclusive_end`` pushed the bound to .999999 instead,
        # and a call in that last microsecond fell through.
        assert upper.date() == date(2026, 10, 1)
        assert (upper.hour, upper.minute, upper.second) == (0, 0, 0)

    def test_a_single_day_is_twenty_four_hours(self) -> None:
        lower, upper = rules.day_bounds(date(2026, 9, 17), date(2026, 9, 17), TASHKENT)
        assert (upper - lower).total_seconds() == 24 * 3600


class TestPreviousWindow:
    def test_the_previous_window_is_the_same_length(self) -> None:
        """Defect 2: a one-hour window was compared against a whole day."""
        date_from, date_to = rules.previous_window(date(2026, 9, 11), date(2026, 9, 17))
        assert (date_from, date_to) == (date(2026, 9, 4), date(2026, 9, 10))
        assert (date_to - date_from).days == (date(2026, 9, 17) - date(2026, 9, 11)).days

    def test_the_two_windows_do_not_overlap(self) -> None:
        """A shared boundary day would count its calls in both periods."""
        _, previous_to = rules.previous_window(date(2026, 9, 11), date(2026, 9, 17))
        assert previous_to < date(2026, 9, 11)

    def test_a_one_day_window_compares_against_yesterday(self) -> None:
        assert rules.previous_window(date(2026, 9, 17), date(2026, 9, 17)) == (
            date(2026, 9, 16),
            date(2026, 9, 16),
        )


class TestDeltaPercent:
    def test_a_rise_is_positive_to_one_place(self) -> None:
        assert rules.delta_percent(120, 100) == Decimal("20.0")

    def test_a_fall_is_negative(self) -> None:
        assert rules.delta_percent(75, 100) == Decimal("-25.0")

    def test_up_from_nothing_is_not_a_percentage(self) -> None:
        """Otherwise a quiet week renders as "+∞ %"."""
        assert rules.delta_percent(12, 0) is None

    def test_a_missing_side_has_no_delta(self) -> None:
        assert rules.delta_percent(None, 100) is None
        assert rules.delta_percent(100, None) is None

    def test_the_result_carries_one_decimal_place(self) -> None:
        assert rules.delta_percent(Decimal("100.125"), 100) == Decimal("0.1")
        assert str(rules.delta_percent(120, 100)) == "20.0"


class TestRatioPercent:
    def test_a_block_against_its_maximum(self) -> None:
        assert rules.ratio_percent(Decimal("18.5"), 25) == Decimal("74.0")

    def test_a_maximum_of_zero_has_no_percentage(self) -> None:
        """Rather than a division error inside a read endpoint."""
        assert rules.ratio_percent(Decimal("3"), 0) is None


class TestRounding:
    def test_an_average_duration_rounds_rather_than_truncates(self) -> None:
        """Measured: ``int(695.53)`` biased every duration downward."""
        assert rules.round_half_up(Decimal("695.53")) == 696
        assert rules.round_half_up(Decimal("695.49")) == 695
        assert rules.round_half_up(Decimal("0.5")) == 1

    def test_nothing_stays_nothing(self) -> None:
        assert rules.round_half_up(None) is None
        assert rules.to_one_place(None) is None

    def test_a_score_keeps_one_decimal_and_halves_go_up(self) -> None:
        assert rules.to_one_place(Decimal("78.349")) == Decimal("78.3")
        # Banker's rounding would answer 78.2 here. Half-up is the rule the
        # validator already scores with, in the employee's favour.
        assert rules.to_one_place(Decimal("78.25")) == Decimal("78.3")


class TestBucketStarts:
    def test_daily_buckets_cover_every_day_inclusive(self) -> None:
        starts = rules.bucket_starts(date(2026, 9, 14), date(2026, 9, 17), "day")
        assert starts == [
            date(2026, 9, 14),
            date(2026, 9, 15),
            date(2026, 9, 16),
            date(2026, 9, 17),
        ]

    def test_weekly_buckets_start_on_monday(self) -> None:
        """PostgreSQL's ISO week starts on Monday; a Sunday key would miss."""
        starts = rules.bucket_starts(date(2026, 9, 17), date(2026, 9, 28), "week")
        assert starts is not None
        assert all(start.weekday() == 0 for start in starts)
        # 17 September 2026 is a Thursday: its week began on the 14th.
        assert starts[0] == date(2026, 9, 14)

    def test_monthly_buckets_start_on_the_first(self) -> None:
        starts = rules.bucket_starts(date(2026, 1, 15), date(2026, 4, 2), "month")
        assert starts == [
            date(2026, 1, 1),
            date(2026, 2, 1),
            date(2026, 3, 1),
            date(2026, 4, 1),
        ]

    def test_february_does_not_trap_the_month_walker(self) -> None:
        starts = rules.bucket_starts(date(2024, 1, 31), date(2024, 3, 1), "month")
        assert starts == [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]

    def test_a_backwards_window_has_no_buckets(self) -> None:
        assert rules.bucket_starts(date(2026, 9, 17), date(2026, 9, 1), "day") == []

    def test_an_unknown_bucket_is_refused(self) -> None:
        assert rules.bucket_starts(date(2026, 9, 1), date(2026, 9, 2), "hour") is None

    def test_too_many_points_is_refused_rather_than_filled(self) -> None:
        """Past the ceiling a line chart is unreadable; the caller stops filling."""
        long_window = rules.bucket_starts(
            date(2020, 1, 1), date(2026, 1, 1), "day"
        )
        assert long_window is None
        assert (
            len(rules.bucket_starts(date(2026, 1, 1), date(2026, 12, 31), "day") or [])
            == 365
        )
