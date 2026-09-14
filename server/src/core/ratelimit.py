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

**Two shapes of call site, and the difference matters.**

``hit`` counts every request. It is right for the install page and the APK
download, where the request itself is the cost being limited.

:func:`check` and :func:`penalise` count only the *failures*, and that is what
``/auth/login`` and ``/enrolment/redeem`` use. The reason is the deployment,
not taste: fifteen handsets enrol from one office Wi-Fi, so they reach the
server as **one** source address, and the app re-sends a redeem it already made
(``EnrolmentService._resume_redeem`` is idempotent on purpose). Counting the
successes would have the eleventh salesperson of the day told to come back in
an hour. Counting the failures leaves the honest rollout untouched and still
stops the thing the limit exists for, because guessing a code or a password
produces nothing but failures.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from fastapi import Request

from src.core import clock
from src.core.errors import ErrorCode, RateLimitedError


@dataclass(frozen=True)
class Limit:
    """``requests`` calls per ``window_seconds``, per identity."""

    requests: int
    window_seconds: int


#: The limits SPEC §4.0 names, as constants so a call site cannot invent one.
LOGIN_PER_IP = Limit(requests=20, window_seconds=3600)
#: SPEC §4.0 words this one "per (IP, email)", and the pair is the point: keyed
#: on the address alone, anybody who knows a colleague's login could lock them
#: out of the panel from anywhere by failing ten times.
LOGIN_PER_ACCOUNT = Limit(requests=10, window_seconds=300)
#: SPEC §4.0 pairs this with "5 per code"; that half is NOT here, and should
#: not be added here. ``EnrolmentService.MAX_CODE_ATTEMPTS`` already counts
#: attempts on the code row itself and auto-revokes at five — in the database,
#: so it survives a restart and is not per-process the way this module is.
#: Two counters for one rule would only mean two places to change it.
ENROLMENT_REDEEM_PER_IP = Limit(requests=10, window_seconds=3600)
INSTALL_PAGE_PER_IP = Limit(requests=60, window_seconds=3600)
#: The landing page hands out a ~30 MB binary, so it is stricter than the page.
APK_DOWNLOAD_PER_IP = Limit(requests=10, window_seconds=3600)

_lock = threading.Lock()
_windows: dict[tuple[str, str], tuple[int, float]] = {}


def _count(bucket: str, identity: str | None, limit: Limit, *, add: int) -> tuple[int, int]:
    """Read the window, rolling it if it has expired, and add ``add`` to it.

    Returns the count as it now stands and the seconds until this window ends.
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
        count += add
        if add:
            _windows[key] = (count, window_started)
        retry_after = int(limit.window_seconds - (current - window_started)) + 1
    return count, retry_after


def hit(bucket: str, identity: str | None, limit: Limit) -> None:
    """Count one request; raise 429 with ``Retry-After`` once over the limit."""
    count, retry_after = _count(bucket, identity, limit, add=1)
    if count > limit.requests:
        raise RateLimitedError(ErrorCode.RATE_LIMITED, retry_after_sec=retry_after)


def check(bucket: str, identity: str | None, limit: Limit) -> None:
    """Refuse a caller who has already spent this window. Counts nothing.

    Called **before** the work, so an exhausted attacker is turned away rather
    than handed another guess. Pair it with :func:`penalise`; on its own it
    never fires, because nothing would ever reach the limit.
    """
    count, retry_after = _count(bucket, identity, limit, add=0)
    if count >= limit.requests:
        raise RateLimitedError(ErrorCode.RATE_LIMITED, retry_after_sec=retry_after)


def penalise(bucket: str, identity: str | None, limit: Limit) -> None:
    """Count one **failure** against the window. Raises nothing.

    Deliberately silent: the caller has already failed and is about to be told
    why, and swapping that answer for a 429 at the moment the window closes
    would tell an attacker which guess was the last one. The refusal lands on
    the *next* request, from :func:`check`.
    """
    _count(bucket, identity, limit, add=1)


def client_ip(request: Request) -> str | None:
    """The caller's address, as every limit here is keyed on.

    ``request.client.host`` is the **peer**, so behind Caddy it is Caddy — one
    address for the entire fleet, which would collapse every per-IP bucket into
    one and lock the office out on the eleventh honest request. What makes it
    the real client again is ``--proxy-headers --forwarded-allow-ips`` on
    uvicorn, set in ``docker-compose.prod.yml``; Starlette then resolves
    ``X-Forwarded-For`` for it. The header is NOT read here on purpose: trusting
    it unconditionally would let any caller pick its own bucket by sending one.
    """
    return request.client.host if request.client else None


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
    "check",
    "client_ip",
    "hit",
    "penalise",
    "reset",
]
