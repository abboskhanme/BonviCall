"""Pure audio rules — no session, no framework (§2).

The attribution window is the whole of the server-side privacy boundary, so it
lives where it can be tested without a database and read without a fixture.
"""

from __future__ import annotations

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
