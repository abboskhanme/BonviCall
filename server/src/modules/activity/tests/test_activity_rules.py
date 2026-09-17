"""The report's arithmetic and its window — no database, no session, no clock.

``rules.py`` imports nothing from the project, which is what makes these run in
milliseconds and what makes the numbers on the screen checkable without a
container. Every case below is one of the mistakes BonviZvonki measured and
fixed; a regression here is a manager reading a wrong figure out loud.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from src.core.clock import TASHKENT
from src.modules.activity.rules import (
    MAX_WINDOW_DAYS,
    ActivityHour,
    AgentActivity,
    MissedClient,
    WindowInvalid,
    activity_window,
    day_span,
    sum_rows,
)

TODAY = date(2026, 8, 20)


def _agent(**overrides) -> AgentActivity:
    row = AgentActivity(agent_id=uuid4(), agent_name="Test")
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


# ── The window ────────────────────────────────────────────────


def test_days_window_covers_whole_local_days() -> None:
    """A rolling "now minus 7x24 hours" makes the first bar read 97 % low."""
    window = activity_window(
        days=7, date_from=None, date_to=None, today=TODAY, zone=TASHKENT
    )
    assert window.date_from == date(2026, 8, 14)
    assert window.date_to == TODAY
    assert window.days == 7
    assert window.since == datetime(2026, 8, 14, tzinfo=TASHKENT)
    # Exclusive, and therefore local midnight AFTER the last day.
    assert window.until == datetime(2026, 8, 21, tzinfo=TASHKENT)


def test_one_day_window_is_one_day() -> None:
    """Off by one here is the bug that labelled a 1-day window "2 kun"."""
    window = activity_window(
        days=1, date_from=None, date_to=None, today=TODAY, zone=TASHKENT
    )
    assert (window.date_from, window.date_to, window.days) == (TODAY, TODAY, 1)


def test_the_upper_bound_is_tashkent_midnight_not_utc_midnight() -> None:
    """UTC+5: 19:00 UTC is already tomorrow in Tashkent.

    Bucketing in UTC moves the day boundary to 05:00 local and files
    after-midnight calls under the previous day, so every label is wrong.
    """
    window = activity_window(
        days=1,
        date_from=date(2026, 8, 11),
        date_to=date(2026, 8, 11),
        today=TODAY,
        zone=TASHKENT,
    )
    assert window.since.astimezone(UTC) == datetime(2026, 8, 10, 19, 0, tzinfo=UTC)
    assert window.until.astimezone(UTC) == datetime(2026, 8, 11, 19, 0, tzinfo=UTC)


def test_date_to_is_inclusive() -> None:
    """"Up to the 16th" includes the whole of the 16th.

    BonviZvonki needed ``_inclusive_end`` to shift a midnight ``date_to``,
    because its filter was ``started_at <= date_to``; here the bound is a
    calendar date and the exclusive instant is derived from it.
    """
    window = activity_window(
        days=7,
        date_from=date(2026, 8, 10),
        date_to=date(2026, 8, 16),
        today=TODAY,
        zone=TASHKENT,
    )
    assert window.days == 7
    assert window.until == datetime(2026, 8, 17, tzinfo=TASHKENT)


def test_an_explicit_range_is_never_rebuilt_from_a_day_count() -> None:
    """Their measured bug: converting a range to ``days`` and back moved the
    start forward by up to 24 hours and silently dropped 853 calls."""
    window = activity_window(
        days=30,
        date_from=date(2026, 8, 10),
        date_to=date(2026, 8, 16),
        today=TODAY,
        zone=TASHKENT,
    )
    assert (window.date_from, window.date_to) == (date(2026, 8, 10), date(2026, 8, 16))


def test_date_from_alone_runs_up_to_today() -> None:
    window = activity_window(
        days=7, date_from=date(2026, 8, 18), date_to=None, today=TODAY, zone=TASHKENT
    )
    assert (window.date_from, window.date_to, window.days) == (
        date(2026, 8, 18),
        TODAY,
        3,
    )


def test_date_to_alone_counts_back_from_it() -> None:
    """Theirs ignored a lone ``date_to`` and returned the last N days ending
    today — a different period from the one asked for, with no sign of it."""
    window = activity_window(
        days=3, date_from=None, date_to=date(2026, 8, 10), today=TODAY, zone=TASHKENT
    )
    assert (window.date_from, window.date_to, window.days) == (
        date(2026, 8, 8),
        date(2026, 8, 10),
        3,
    )


def test_a_backwards_range_is_refused() -> None:
    """A reversed range would quietly report a different period's data."""
    with pytest.raises(WindowInvalid) as raised:
        activity_window(
            days=7,
            date_from=date(2026, 8, 16),
            date_to=date(2026, 8, 10),
            today=TODAY,
            zone=TASHKENT,
        )
    assert raised.value.field_name == "date_from"


def test_an_absurd_range_is_refused() -> None:
    """``days`` is capped by the query parameter; the explicit pair needs its
    own bound or one pasted URL asks for a decade of daily bars."""
    with pytest.raises(WindowInvalid):
        activity_window(
            days=7,
            date_from=TODAY - timedelta(days=MAX_WINDOW_DAYS),
            date_to=TODAY,
            today=TODAY,
            zone=TASHKENT,
        )


def test_every_day_in_the_window_is_present_including_empty_ones() -> None:
    """Trimming empty days makes weekends vanish and the line continuous."""
    span = day_span(date(2026, 8, 14), date(2026, 8, 20))
    assert len(span) == 7
    assert span[0] == date(2026, 8, 14) and span[-1] == date(2026, 8, 20)


# ── Per-agent arithmetic ──────────────────────────────────────


def test_missed_rate_divides_by_incoming_calls() -> None:
    row = _agent(inbound_total=10, inbound_answered=7, missed=3)
    assert row.missed_rate == 30.0


def test_rates_are_none_rather_than_zero_when_there_is_nothing_to_divide() -> None:
    """"No incoming calls" and "none missed out of many" are different answers;
    the panel renders the first as an em dash and must be able to tell."""
    row = _agent()
    assert row.missed_rate is None
    assert row.callback_rate is None


def test_callback_rate_is_per_customer_not_per_event() -> None:
    """A customer who rang four times and was answered on the fourth WAS
    reached. Counting events would report "3 missed, 75 %" for a customer the
    company actually served."""
    row = _agent(missed=4, missed_clients=1, clients_reached=1)
    assert row.callback_rate == 100.0
    assert row.clients_unreached == 0


def test_clients_unreached_is_the_headline() -> None:
    row = _agent(missed_clients=9, clients_reached=6)
    assert row.clients_unreached == 3


def test_missed_open_divides_addressable_events_not_all_of_them() -> None:
    """A missed call with no number cannot be returned, so it must not land in
    the "not called back" list — measured, 8 of 971 over 7 days."""
    row = _agent(missed=20, missed_addressable=12, missed_called_back=5)
    assert row.missed_open == 7


def test_missed_open_never_goes_negative() -> None:
    """Closed events can exceed addressable ones at a window edge."""
    row = _agent(missed_addressable=3, missed_called_back=5)
    assert row.missed_open == 0


def test_total_is_both_directions() -> None:
    assert _agent(outbound_total=4, inbound_total=6).total == 10


# ── The company row ───────────────────────────────────────────


def test_volume_columns_are_summed() -> None:
    rows = [
        _agent(outbound_total=3, inbound_total=2, missed=1, talk_seconds=60),
        _agent(outbound_total=4, inbound_total=5, missed=2, talk_seconds=90),
    ]
    total = sum_rows(rows)
    assert (total.outbound_total, total.inbound_total, total.missed) == (7, 7, 3)
    assert total.talk_seconds == 150
    assert total.agent_id == UUID(int=0) and total.agent_name == ""


def test_customer_counts_are_not_summed() -> None:
    """One customer can call two employees: two correct rows, one person.

    Summing inflated the headline by 4 % at BonviZvonki (151 against 145), so
    ``sum_rows`` leaves these at zero and the caller overwrites them from a
    de-duplicated query. A zero here is an obvious bug; a plausible wrong
    number is not.
    """
    rows = [_agent(missed_clients=5, clients_reached=3) for _ in range(2)]
    total = sum_rows(rows)
    assert total.missed_clients == 0
    assert total.clients_reached == 0


# ── The hourly cut and the detail row ─────────────────────────


def test_hourly_rate_divides_by_incoming_calls_in_that_hour() -> None:
    hour = ActivityHour(hour=12, inbound=20, inbound_answered=13, missed=7)
    assert hour.missed_rate == 35.0


def test_a_silent_hour_has_no_rate() -> None:
    assert ActivityHour(hour=3).missed_rate is None


def test_minutes_to_contact_runs_from_the_last_missed_attempt() -> None:
    """Measuring from the FIRST attempt would call a customer "reached" while
    their later attempt was still unanswered."""
    last = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    client = MissedClient(
        phone_key="901234567",
        contact_name=None,
        attempts=3,
        first_missed_at=last - timedelta(hours=2),
        last_missed_at=last,
        contacted_at=last + timedelta(minutes=12, seconds=30),
        contacted_by="Aziz",
        contact_inbound=False,
    )
    assert client.minutes_to_contact == 12.5


def test_an_uncontacted_customer_has_no_delay() -> None:
    now = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    client = MissedClient(
        phone_key="901234567",
        contact_name=None,
        attempts=1,
        first_missed_at=now,
        last_missed_at=now,
        contacted_at=None,
        contacted_by=None,
        contact_inbound=None,
    )
    assert client.minutes_to_contact is None
