"""Every function in ``calls/rules.py`` (CONVENTIONS.md §13).

These run without a database on purpose: the empty-directory rule is the one
that cost BonviZvonki 82 mislabelled calls out of 98, and a rule that important
should not be reachable only through fixtures.
"""

from __future__ import annotations

import pytest

from src.modules.calls.rules import (
    LineDirectory,
    classify_call_type,
    clock_skew_seconds,
    digits_of,
    resolve_audio_reason,
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
