"""Every function in ``enrolment/rules.py`` (CONVENTIONS.md §13)."""

from __future__ import annotations

import pytest

from src.modules.enrolment.rules import (
    CODE_ALPHABET,
    CODE_LENGTH,
    display_number,
    msisdn_matches,
    normalise_code,
)


def test_the_alphabet_excludes_the_glyphs_people_confuse() -> None:
    """The code is read aloud and typed by a salesperson (UC-01)."""
    for character in "ILOU":
        assert character not in CODE_ALPHABET
    assert len(CODE_ALPHABET) == 32
    assert CODE_LENGTH == 8


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("k7m4pq2x", "K7M4PQ2X"),
        ("K7M4-PQ2X", "K7M4PQ2X"),
        ("K7M4 PQ2X", "K7M4PQ2X"),
        ("KIM4PQ2X", "K1M4PQ2X"),
        ("KLM4PQ2X", "K1M4PQ2X"),
        ("K7MOPQ2X", "K7M0PQ2X"),
        ("K7M4PQ2U", "K7M4PQ2V"),
    ],
)
def test_confusable_characters_are_folded(typed: str, expected: str) -> None:
    """An agent reading a code off a screen types l for 1 and O for 0.

    Those characters are not in the alphabet, so folding them is unambiguous
    and turns a support call into a successful enrolment.
    """
    assert normalise_code(typed) == expected


@pytest.mark.parametrize(
    "line1",
    [None, "", "   ", "1234567", "12345678"],
)
def test_an_absent_or_short_msisdn_is_never_a_match(line1) -> None:
    """UC-04, non-negotiable: "I don't know" is not "yes".

    Treating it as a match would attribute a phone to a number it does not
    hold, and on most Uzbek SIMs the empty answer is the normal one.
    """
    assert msisdn_matches(line1, "901112233") is False


@pytest.mark.parametrize(
    "line1",
    ["+998901112233", "998901112233", "901112233", "+998 90 111-22-33"],
)
def test_any_format_of_the_right_number_matches(line1: str) -> None:
    assert msisdn_matches(line1, "901112233") is True


def test_a_different_number_does_not_match() -> None:
    assert msisdn_matches("+998935554433", "901112233") is False


def test_display_number_groups_for_reading_aloud() -> None:
    assert display_number("+998901112233") == "+998 90 111-22-33"
    assert display_number("garbage") == "garbage"
