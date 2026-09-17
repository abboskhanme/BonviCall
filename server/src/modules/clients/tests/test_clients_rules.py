"""Every function in ``clients/rules.py`` — no session, no clock.

The load-bearing one is :func:`test_a_bounded_window_agrees_with_the_activity_report`.
``client_window`` and ``activity.rules.activity_window`` are two functions that
convert an Asia/Tashkent calendar range into the same half-open instants, and
two implementations of one rule are how a rule quietly becomes two. They differ
only in what an ABSENT bound means, so this asserts the overlap.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.core.clock import TASHKENT
from src.modules.activity.rules import activity_window
from src.modules.clients.rules import (
    MAX_WINDOW_DAYS,
    ClientFilter,
    ClientRow,
    ClientScope,
    CursorInvalid,
    DirectoryCursor,
    WindowInvalid,
    client_window,
    escape_like,
    is_client_key,
    search_digits,
)

# ── The window ────────────────────────────────────────────────


def test_a_bounded_window_agrees_with_the_activity_report() -> None:
    """One rule, two call sites — asserted rather than hoped for.

    If the directory and the activity report resolved a period differently, the
    same seven days would produce two different sets of numbers in two sections
    of the same panel, and nobody would be able to say which was right.
    """
    mine = client_window(
        date_from=date(2026, 8, 10), date_to=date(2026, 8, 16), zone=TASHKENT
    )
    theirs = activity_window(
        days=7,
        date_from=date(2026, 8, 10),
        date_to=date(2026, 8, 16),
        today=date(2026, 8, 20),
        zone=TASHKENT,
    )
    assert (mine.since, mine.until) == (theirs.since, theirs.until)
    assert (mine.date_from, mine.date_to) == (theirs.date_from, theirs.date_to)


def test_the_upper_bound_is_the_midnight_after_date_to() -> None:
    """"Up to the 16th" includes the whole of the 16th, by construction.

    The source needs an ``_inclusive_end`` helper for this, because its filter
    is ``started_at <= date_to`` and a bare date meant midnight — which lost a
    whole day's work with nothing in the response to say so.
    """
    window = client_window(
        date_from=date(2026, 8, 16), date_to=date(2026, 8, 16), zone=TASHKENT
    )
    assert window.since == datetime(2026, 8, 16, 0, 0, tzinfo=TASHKENT)
    assert window.until == datetime(2026, 8, 17, 0, 0, tzinfo=TASHKENT)


def test_no_bounds_means_everything() -> None:
    """The directory's default. Its first question is *who are our customers*,
    and a window that silently defaulted to a week would answer another one."""
    window = client_window(date_from=None, date_to=None, zone=TASHKENT)
    assert (window.since, window.until) == (None, None)
    assert window.bounded is False


def test_one_bound_alone_is_honoured() -> None:
    since_only = client_window(date_from=date(2026, 8, 10), date_to=None, zone=TASHKENT)
    assert since_only.since is not None and since_only.until is None
    assert since_only.bounded is True

    until_only = client_window(date_from=None, date_to=date(2026, 8, 16), zone=TASHKENT)
    assert until_only.since is None and until_only.until is not None


def test_a_backwards_range_is_refused() -> None:
    with pytest.raises(WindowInvalid) as caught:
        client_window(
            date_from=date(2026, 8, 16), date_to=date(2026, 8, 10), zone=TASHKENT
        )
    assert caught.value.field_name == "date_from"


def test_a_range_past_the_ceiling_is_refused() -> None:
    """One pasted URL must not ask for a decade."""
    start = date(2020, 1, 1)
    with pytest.raises(WindowInvalid):
        client_window(
            date_from=start,
            date_to=date(2026, 1, 1),
            zone=TASHKENT,
        )
    # A whole calendar year and a leap day is still allowed.
    ok = client_window(date_from=date(2024, 1, 1), date_to=date(2024, 12, 31), zone=TASHKENT)
    assert (ok.date_to - ok.date_from).days + 1 <= MAX_WINDOW_DAYS
    assert start < date(2026, 1, 1)


# ── The filter ────────────────────────────────────────────────


def test_widening_changes_the_scope_and_nothing_else() -> None:
    """⚠️ The agent list is what keeps a salesperson inside their own
    customers. Widening the CUT must never widen that."""
    import uuid

    mine = uuid.uuid4()
    filters = ClientFilter(
        window=client_window(date_from=None, date_to=None, zone=TASHKENT),
        agent_ids=[mine],
        scope=ClientScope.CLIENTS,
        search="Aziz",
    )
    wide = filters.widened()
    assert wide.scope is ClientScope.ALL
    assert wide.agent_ids == [mine]
    assert wide.window is filters.window
    assert wide.search == "Aziz"


# ── The key ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("901112233", True),
        (" 901112233 ", True),
        ("undefined", False),
        ("", False),
        ("90-111", False),
    ],
)
def test_is_client_key(raw: str, expected: bool) -> None:
    assert is_client_key(raw) is expected


# ── Searching ─────────────────────────────────────────────────


def test_a_percent_sign_is_searched_for_literally() -> None:
    """Unescaped, a single ``%`` matches everything and switches the search
    off — which reads as "the filter is broken"."""
    assert escape_like("50%") == "50\\%"
    assert escape_like("a_b") == "a\\_b"
    assert escape_like("back\\slash") == "back\\\\slash"


def test_only_the_digits_of_a_number_are_compared() -> None:
    assert search_digits("+998 90 123-45-67") == "998901234567"
    assert search_digits("Aziz") == ""


# ── The cursor ────────────────────────────────────────────────


def test_a_cursor_round_trips() -> None:
    cursor = DirectoryCursor(sort_value=datetime(2026, 8, 16, 9, 0), key="901112233")
    decoded = DirectoryCursor.decode(cursor.encode())
    assert decoded.key == "901112233"
    assert decoded.sort_value == "2026-08-16T09:00:00"


def test_a_null_sort_value_round_trips() -> None:
    """The NULL tail is a real page: every unscored customer lives there."""
    decoded = DirectoryCursor.decode(
        DirectoryCursor(sort_value=None, key="901112233").encode()
    )
    assert decoded.sort_value is None


def test_an_integer_sort_value_round_trips() -> None:
    decoded = DirectoryCursor.decode(DirectoryCursor(sort_value=12, key="9").encode())
    assert decoded.sort_value == 12


@pytest.mark.parametrize("raw", ["not-base64!!", "", "eyJ4IjoxfQ", "eyJrIjpbMSwyXX0"])
def test_a_tampered_cursor_is_refused(raw: str) -> None:
    """Refused, never answered by silently restarting from page one: that is
    how a reader ends up paging the same rows forever."""
    with pytest.raises(CursorInvalid):
        DirectoryCursor.decode(raw)


# ── The row's derived figures ─────────────────────────────────


def _row(**overrides) -> ClientRow:
    values = {
        "phone_key": "901112233",
        "name": None,
        "phone": None,
        "code": None,
        "calls_total": 0,
        "inbound": 0,
        "outbound": 0,
        "missed": 0,
        "talk_seconds": 0,
        "first_call_at": None,
        "last_call_at": None,
        "agent_count": 0,
        "main_agent_id": None,
        "main_agent_name": None,
        "avg_score": None,
        "scored": 0,
    }
    values.update(overrides)
    return ClientRow(**values)


def test_missed_rate_is_none_without_incoming_calls() -> None:
    """None rather than zero: "they never called" and "they called ten times
    and we answered every one" are different answers, and the panel renders the
    first as a dash."""
    assert _row(inbound=0, missed=0).missed_rate is None


def test_missed_rate_is_a_percentage_of_incoming() -> None:
    assert _row(inbound=8, missed=2).missed_rate == 25.0
    assert _row(inbound=3, missed=1).missed_rate == 33.3
