"""Every function in ``audio/rules.py`` (CONVENTIONS.md §13).

The attribution window is the server's half of the privacy boundary, so it is
tested here without a database: a fixture cannot hide what a constant does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.modules.audio.rules import (
    POST_BUFFER_SECONDS,
    PRE_BUFFER_SECONDS,
    attribution_window,
    duration_mismatch,
    is_attributable,
    parse_range_header,
)

STARTED = datetime(2026, 9, 4, 13, 59, 2, tzinfo=UTC)
ENDED = STARTED + timedelta(seconds=513)


def test_the_buffers_are_the_measured_values_from_s1() -> None:
    """Widening these widens the window in which a **private** recording could
    be mistaken for a work call. They are constants for that reason."""
    assert PRE_BUFFER_SECONDS == 5
    assert POST_BUFFER_SECONDS == 120


def test_the_window_brackets_the_call() -> None:
    start, end = attribution_window(STARTED, ENDED, 513)
    assert start == STARTED - timedelta(seconds=5)
    assert end == ENDED + timedelta(seconds=120)


def test_the_window_is_reconstructed_when_the_call_has_no_end() -> None:
    """A call-log-recovered record may have only a duration."""
    start, end = attribution_window(STARTED, None, 513)
    assert end == STARTED + timedelta(seconds=513 + 120)


def test_a_recording_inside_the_window_is_attributable() -> None:
    """The OEM writer flushes late, which is what the post-buffer is for."""
    assert is_attributable(ENDED + timedelta(seconds=90), STARTED, ENDED, 513) is True
    assert is_attributable(STARTED - timedelta(seconds=3), STARTED, ENDED, 513) is True


@pytest.mark.parametrize(
    "recorded_at",
    [
        STARTED - timedelta(seconds=30),
        ENDED + timedelta(seconds=300),
        STARTED - timedelta(hours=2),
    ],
)
def test_a_recording_outside_the_window_is_not(recorded_at) -> None:
    """This is the private call in the shared folder. It is never attached."""
    assert is_attributable(recorded_at, STARTED, ENDED, 513) is False


def test_no_timestamp_fails_closed() -> None:
    """"We could not tell" must never resolve to "attach it"."""
    assert is_attributable(None, STARTED, ENDED, 513) is False


def test_duration_mismatch_tolerates_two_seconds() -> None:
    """UC-14: a two-second difference is normal, two minutes is another call."""
    assert duration_mismatch(513_000, 513) is False
    assert duration_mismatch(514_500, 513) is False
    assert duration_mismatch(400_000, 513) is True
    assert duration_mismatch(None, 513) is False


# --- Range parsing (N43) ----------------------------------------------------


def test_no_range_header_means_the_whole_body() -> None:
    assert parse_range_header(None, 1000) is None


def test_a_closed_range_is_inclusive() -> None:
    """HTTP Range is inclusive; converting conventions is how a player ends up
    one byte short of the last frame."""
    assert parse_range_header("bytes=0-99", 1000) == (0, 99)
    assert parse_range_header("bytes=1000-2000", 5000) == (1000, 2000)


def test_an_open_ended_range_runs_to_the_end() -> None:
    assert parse_range_header("bytes=900-", 1000) == (900, 999)


def test_a_range_past_the_end_is_clamped() -> None:
    assert parse_range_header("bytes=0-99999", 1000) == (0, 999)


def test_a_suffix_range_takes_the_last_bytes() -> None:
    """``bytes=-500`` is how a player reads a trailing index."""
    assert parse_range_header("bytes=-500", 1000) == (500, 999)
    assert parse_range_header("bytes=-5000", 1000) == (0, 999)


@pytest.mark.parametrize("value", ["bytes=1000-", "bytes=2000-3000", "bytes=99-50"])
def test_an_unsatisfiable_range_raises(value: str) -> None:
    """The router turns this into 416 with ``Content-Range: bytes */total``;
    a 200 instead would leave the player unable to seek."""
    with pytest.raises(ValueError):
        parse_range_header(value, 1000)


def test_a_non_byte_unit_is_refused() -> None:
    with pytest.raises(ValueError):
        parse_range_header("items=0-10", 1000)
