"""Rate limiting (SPEC §4.0).

**An honest limit, stated up front:** this is an in-process fixed-window
counter. It is correct for the release-1 deployment, which is one uvicorn
process on one host (``STACK.md``), and it is *not* correct behind more than one
worker — each would keep its own counters and the effective limit would
multiply. When the server grows a second process this moves to Redis; the call
sites do not change, which is why the check is behind a function rather than
inlined.

It is not a security control either. It raises the cost of guessing an
eight-character enrolment code and of hammering the login form; an attacker with
many source addresses is not stopped by it, and nothing in the product pretends
otherwise.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from src.core import clock
from src.core.errors import ErrorCode, RateLimitedError


@dataclass(frozen=True)
class Limit:
    """``requests`` calls per ``window_seconds``, per identity."""

    requests: int
    window_seconds: int


#: The limits SPEC §4.0 names, as constants so a call site cannot invent one.
LOGIN_PER_IP = Limit(requests=20, window_seconds=3600)
LOGIN_PER_ACCOUNT = Limit(requests=10, window_seconds=300)
ENROLMENT_REDEEM_PER_IP = Limit(requests=10, window_seconds=3600)
INSTALL_PAGE_PER_IP = Limit(requests=60, window_seconds=3600)
#: The landing page hands out a ~30 MB binary, so it is stricter than the page.
APK_DOWNLOAD_PER_IP = Limit(requests=10, window_seconds=3600)

_lock = threading.Lock()
_windows: dict[tuple[str, str], tuple[int, float]] = {}


def hit(bucket: str, identity: str | None, limit: Limit) -> None:
    """Count one request; raise 429 with ``Retry-After`` once over the limit.

    ``identity`` is whatever the limit is per — an IP, an e-mail, an
    installation id. ``None`` means we could not identify the caller, which is
    counted under one shared key rather than skipped: an unidentifiable caller
    is exactly the one worth limiting.
    """
    key = (bucket, identity or "anonymous")
    current = clock.now().timestamp()
    with _lock:
        count, window_started = _windows.get(key, (0, current))
        if current - window_started >= limit.window_seconds:
            count, window_started = 0, current
        count += 1
        _windows[key] = (count, window_started)
        retry_after = int(limit.window_seconds - (current - window_started)) + 1
    if count > limit.requests:
        raise RateLimitedError(ErrorCode.RATE_LIMITED, retry_after_sec=retry_after)


def reset() -> None:
    """Drop every counter. For tests, and for nothing else."""
    with _lock:
        _windows.clear()


__all__ = [
    "APK_DOWNLOAD_PER_IP",
    "ENROLMENT_REDEEM_PER_IP",
    "INSTALL_PAGE_PER_IP",
    "LOGIN_PER_ACCOUNT",
    "LOGIN_PER_IP",
    "Limit",
    "hit",
    "reset",
]
