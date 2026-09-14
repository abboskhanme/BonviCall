"""Every function in ``audio/rules.py`` (CONVENTIONS.md §13).

The attribution window is the server's half of the privacy boundary, so it is
tested here without a database: a fixture cannot hide what a constant does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.modules.audio.rules import (
    MAX_AGENT_CHARACTERS,
    POST_BUFFER_SECONDS,
    PRE_BUFFER_SECONDS,
    archive_entry_filename,
    attribution_window,
    duration_mismatch,
    is_attributable,
    parse_range_header,
    recording_filename,
    unique_filename,
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


# --- The name of a downloaded recording (SPEC §4.8) -------------------------
#
# The rule these pin is worth more than it looks. It decides what somebody
# finds on their desktop a week later, and it was wrong for the whole life of
# the product until 2026-09-13: `audio/service.py` built the name inline and
# left the agent out of it, so every downloaded recording was called
# `20260913-0855.opus` and said nothing about whose call it was.

CALL_TIME = datetime(2026, 9, 13, 8, 55, tzinfo=UTC)


def test_the_single_download_name_is_the_shape_the_spec_states() -> None:
    """SPEC §4.8: ``<agent>_<yyyymmdd-hhmm>.<ext>``, agent included."""
    assert (
        recording_filename("Aziz Karimov", CALL_TIME, "opus")
        == "Aziz Karimov_20260913-0855.opus"
    )


def test_an_archive_entry_adds_the_customers_number() -> None:
    """What the person opening the folder sorts and searches by."""
    assert (
        archive_entry_filename("Aziz Karimov", CALL_TIME, "opus", "+998 90 111 22 33")
        == "Aziz Karimov_20260913-0855_998901112233.opus"
    )


def test_a_separator_never_survives_into_an_entry_name() -> None:
    """The one that is a security bug rather than a cosmetic one.

    An extractor that honours ``/`` in an entry name writes outside the folder
    the user chose. Dropping the separators is what makes that impossible:
    ``../../etc`` arrives as ``.. .. etc``, which is a filename and not a path.
    The leading dot goes too — a name starting with one is hidden on every Unix
    filesystem, and a component of nothing but dots is not legal at all.
    """
    name = archive_entry_filename("../../etc", CALL_TIME, "opus", "90/111")

    assert "/" not in name
    assert "\\" not in name
    assert not name.startswith(".")
    assert name == "etc_20260913-0855_90111.opus"


@pytest.mark.parametrize("forbidden", list('\\/:*?"<>|'))
def test_windows_refuses_these_so_none_of_them_is_written(forbidden: str) -> None:
    assert forbidden not in recording_filename(f"A{forbidden}B", CALL_TIME, "opus")


def test_control_characters_are_dropped() -> None:
    assert "\n" not in recording_filename("Aziz\nKarimov", CALL_TIME, "opus")
    assert "\x7f" not in recording_filename("Aziz\x7fKarimov", CALL_TIME, "opus")


def test_uzbek_spelling_is_left_alone() -> None:
    """The archive writes UTF-8 entry names, so there is nothing to protect
    against — and an admin who typed ``Qo'chqorov`` gets ``Qo'chqorov``."""
    assert recording_filename("Qo'chqorov Toʻlqin", CALL_TIME, "opus").startswith(
        "Qo'chqorov Toʻlqin_"
    )


def test_a_missing_agent_or_number_says_so_rather_than_leaving_a_gap() -> None:
    """An empty part would make two different calls share one filename."""
    assert recording_filename(None, CALL_TIME, "opus") == "unknown-agent_20260913-0855.opus"
    assert recording_filename("   ", CALL_TIME, "opus").startswith("unknown-agent_")
    assert archive_entry_filename("Aziz", CALL_TIME, "opus", None).endswith(
        "_unknown-number.opus"
    )


def test_a_long_name_is_truncated_so_the_entry_stays_extractable() -> None:
    """``full_name`` is 255 characters; a filesystem component is 255 BYTES,
    and a Cyrillic name at full length is 510 of them."""
    name = recording_filename("Ж" * 200, CALL_TIME, "opus")

    assert len(name.encode()) < 255
    assert name.startswith("Ж" * MAX_AGENT_CHARACTERS)


def test_an_extension_is_never_empty_and_never_a_second_dot() -> None:
    """A name ending in a dot is refused by Windows."""
    assert recording_filename("Aziz", CALL_TIME, "").endswith(".bin")
    assert recording_filename("Aziz", CALL_TIME, ".OPUS").endswith(".opus")


def test_a_redial_in_the_same_minute_does_not_overwrite_the_first_recording() -> None:
    """Same agent, same minute, same number — a redial after a dropped line.

    Two ZIP entries may carry one name, and most extractors write the first and
    then overwrite it: the archive would silently hold one recording where the
    manifest promises two.
    """
    first = "Aziz_20260913-0855_998901112233.opus"

    assert unique_filename(first, []) == first
    assert unique_filename(first, [first]) == "Aziz_20260913-0855_998901112233 (2).opus"
    assert (
        unique_filename(first, [first, "Aziz_20260913-0855_998901112233 (2).opus"])
        == "Aziz_20260913-0855_998901112233 (3).opus"
    )


def test_a_collision_is_judged_the_way_the_filesystem_judges_it() -> None:
    """Windows and macOS resolve two names differing only in case to one file."""
    assert unique_filename("a.opus", ["A.OPUS"]) == "a (2).opus"
