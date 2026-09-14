"""Pure audio rules — no session, no framework (§2).

The attribution window is the whole of the server-side privacy boundary, so it
lives where it can be tested without a database and read without a fixture.

The filename rule lives here for the same reason: it is the one thing the
single download and the archive must agree on, and agreeing is only checkable
if both call the same function.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from datetime import datetime, timedelta

#: The OEM recorder flushes late, so the file's timestamp trails the call.
#: These are CallSentry's measured values and they come straight from
#: ``docs/S1-RECORDING.md``. Widening them is a one-line diff a reviewer sees —
#: and widening them widens the window in which a **private** recording could
#: be mistaken for a work call, which is why they are constants and not config.
PRE_BUFFER_SECONDS = 5
POST_BUFFER_SECONDS = 120

#: A duration this far from the call log's is worth flagging (UC-14). Not an
#: error: a two-second difference is normal, a two-minute one means the file
#: belongs to a different call.
DURATION_MISMATCH_SECONDS = 2


def attribution_window(
    started_at: datetime, ended_at: datetime | None, duration_sec: int
) -> tuple[datetime, datetime]:
    """``[started_at - 5 s, ended_at + 120 s]`` — the only window audio may match.

    ``ended_at`` is optional because a call-log-recovered record may not have
    one; the duration reconstructs it. A call with neither cannot be matched,
    and the caller refuses rather than guessing.
    """
    end = ended_at or (started_at + timedelta(seconds=max(duration_sec, 0)))
    return (
        started_at - timedelta(seconds=PRE_BUFFER_SECONDS),
        end + timedelta(seconds=POST_BUFFER_SECONDS),
    )


def is_attributable(
    recorded_at: datetime | None,
    started_at: datetime,
    ended_at: datetime | None,
    duration_sec: int,
) -> bool:
    """Whether a recording may be attached to this call (N28, T44).

    **Fail closed.** A recording with no timestamp is not attributable: the
    shared OEM folder holds the employee's private calls, and "we could not
    tell" must never resolve to "attach it". The device-side guard is the
    primary defence; this is the backstop for a tampered app.
    """
    if recorded_at is None:
        return False
    window_start, window_end = attribution_window(started_at, ended_at, duration_sec)
    return window_start <= recorded_at <= window_end


def duration_mismatch(duration_ms: int | None, duration_sec: int) -> bool:
    """True when the file's length disagrees with the call log's (UC-14)."""
    if duration_ms is None:
        return False
    return abs(duration_ms / 1000 - duration_sec) > DURATION_MISMATCH_SECONDS


def parse_range_header(value: str | None, size: int) -> tuple[int, int] | None:
    """``bytes=1000-2000`` -> ``(1000, 2000)`` inclusive, or ``None`` (N43).

    Returns ``None`` when there is no Range header, which means "send the whole
    body with 200". Raises ``ValueError`` for a range outside the file, which
    the router turns into 416 with ``Content-Range: bytes */total`` — a player
    that gets a 200 instead cannot seek.
    """
    if not value:
        return None
    if not value.startswith("bytes="):
        raise ValueError("only byte ranges are supported")
    spec = value[len("bytes=") :].split(",", 1)[0].strip()
    start_text, _, end_text = spec.partition("-")

    if not start_text:
        # A suffix range: "bytes=-500" means the last 500 bytes.
        length = int(end_text)
        if length <= 0:
            raise ValueError("empty suffix range")
        return max(size - length, 0), size - 1

    start = int(start_text)
    end = int(end_text) if end_text else size - 1
    if start >= size or start < 0 or end < start:
        raise ValueError("range outside the file")
    return start, min(end, size - 1)


# --- The name of a downloaded recording (SPEC §4.8) -------------------------
#
# SPEC §4.8 fixes one shape, ``<agent>_<yyyymmdd-hhmm>.<ext>``, and the archive
# adds the customer's number to it. It is written once, here, because the two
# call sites are in different modules: the ``?download=true`` header in
# ``audio/service.py`` and every entry of the archive. They were allowed to
# disagree before and they did — the single download shipped as
# ``20260913-0855.opus``, with no agent in it at all, so a recording saved to
# somebody's desktop said nothing about whose call it was.

#: ``20260913-0855``. The **caller** decides the timezone by passing an aware
#: datetime already converted; this function only formats what it is given.
STAMP_FORMAT = "%Y%m%d-%H%M"

#: The two separators every filesystem reads as "another directory", plus the
#: seven characters Windows refuses outright. A separator is not a cosmetic
#: problem in an archive: an extractor that honours a ``/`` in an entry name
#: writes outside the folder the user chose.
FORBIDDEN_CHARACTERS = '\\/:*?"<>|'

#: Said in English because it is a filename, not a message a user is shown —
#: Uzbek lives in ``core/messages_uz.py`` and nowhere else (§14). Both are
#: honest about what is missing rather than silently dropping a part of the
#: name, which would make two different calls produce the same filename.
UNKNOWN_AGENT = "unknown-agent"
UNKNOWN_NUMBER = "unknown-number"

#: ``agents.full_name`` is ``String(255)``, and a filesystem component is
#: capped at 255 **bytes** — a Cyrillic name at full length is 510 of them, so
#: the whole entry would be unextractable. Truncating the one unbounded part
#: keeps every name well under the limit.
MAX_AGENT_CHARACTERS = 60

#: A name may not end in a dot on Windows, so an extension is never empty.
FALLBACK_EXTENSION = "bin"

_WHITESPACE = re.compile(r"\s+")


def _sanitise(value: str) -> str:
    """Drop what a filesystem refuses; keep everything else as it is.

    Uzbek letters are **not** touched: ``Qo'chqorov`` and ``Toʻlqin`` stay
    spelled the way the admin typed them. That is safe because the archive
    writes its entry names as UTF-8 with the language-encoding flag set, and
    both are legal on every filesystem this product reaches.
    """
    cleaned = "".join(
        " " if character in FORBIDDEN_CHARACTERS or character < " " or character == "\x7f"
        else character
        for character in value
    )
    # Collapse afterwards, not before: a stripped separator leaves a gap, and
    # "Aziz  Karimov" with two spaces is a different filename from the one the
    # next person will search for.
    return _WHITESPACE.sub(" ", cleaned).strip()


def _agent_part(agent_name: str | None) -> str:
    """The agent's name, short enough and starting with a real character.

    Leading dots are stripped as well as the forbidden characters. Dropping the
    separators already makes traversal impossible — ``../../etc`` arrives here
    as ``.. .. etc``, which no extractor can read as a path — but a name that
    still *begins* with a dot is hidden on every Unix filesystem, and a part
    that is nothing but dots is not a legal component at all. Neither is worth
    leaving to the extractor's judgement.
    """
    cleaned = _sanitise(agent_name or "")[:MAX_AGENT_CHARACTERS]
    # ``lstrip(". ")`` and not ``lstrip(".")``: the dots arrive in groups with
    # the space a stripped separator left behind — ``../../etc`` reaches here
    # as ``.. .. etc``, and removing only the first group leaves a name that
    # still starts with a dot.
    return cleaned.lstrip(". ").strip() or UNKNOWN_AGENT


def _number_part(remote_number: str | None) -> str:
    """The customer's number, digits-and-separators, with no leading ``+``.

    ``calls.remote_number`` is nullable — a withheld caller id, or a row
    recovered from the call log that never carried one — and an empty gap in
    the middle of a filename reads as a bug. It says so instead.
    """
    cleaned = _sanitise(remote_number or "").lstrip("+").replace(" ", "")
    return cleaned or UNKNOWN_NUMBER


def _extension_part(extension: str) -> str:
    return _sanitise(extension).lstrip(".").replace(" ", "").lower() or FALLBACK_EXTENSION


def _stem(agent_name: str | None, started_at: datetime) -> str:
    return f"{_agent_part(agent_name)}_{started_at.strftime(STAMP_FORMAT)}"


def recording_filename(
    agent_name: str | None, started_at: datetime, extension: str
) -> str:
    """``Aziz Karimov_20260913-0855.opus`` — SPEC §4.8's download name."""
    return f"{_stem(agent_name, started_at)}.{_extension_part(extension)}"


def archive_entry_filename(
    agent_name: str | None,
    started_at: datetime,
    extension: str,
    remote_number: str | None,
) -> str:
    """``Aziz Karimov_20260913-0855_998901112233.opus`` — one archive entry.

    The same rule as :func:`recording_filename` plus the customer's number,
    which is what the person opening the folder sorts and searches by.
    """
    return (
        f"{_stem(agent_name, started_at)}_{_number_part(remote_number)}"
        f".{_extension_part(extension)}"
    )


def unique_filename(name: str, taken: Collection[str]) -> str:
    """``x.opus`` while it is free, then ``x (2).opus``, ``x (3).opus``.

    Two calls by one agent, in one minute, to one number collide — a redial
    after a dropped line does exactly that. A ZIP may hold two entries with the
    same name, and what happens then is decided by the extractor: most write
    the first and then overwrite it with the second, so the archive silently
    contains one recording where the manifest promises two. Counting up is the
    convention every desktop already uses for the same situation.

    Compared case-insensitively, because Windows and macOS resolve two names
    that differ only in case to one file.
    """
    existing = {entry.casefold() for entry in taken}
    if name.casefold() not in existing:
        return name
    stem, dot, extension = name.rpartition(".")
    if not dot:
        stem, extension = name, ""
    index = 2
    while f"{stem} ({index}){dot}{extension}".casefold() in existing:
        index += 1
    return f"{stem} ({index}){dot}{extension}"
