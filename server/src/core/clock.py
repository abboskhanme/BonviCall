r"""Time — the ONE module (CONVENTIONS.md §6, N36).

``datetime.now()`` and ``datetime.utcnow()`` are forbidden everywhere else in
``server/src``. The check is::

    grep -rn "datetime.now()\|utcnow()" server/src   # -> only this file

Why this is a whole module: **devices lie about time.** A phone's clock can be
wrong by hours, can be changed by its owner mid-call, and changes timezone when
the owner travels. Every device-originated row therefore carries three
timestamps that are never merged, and only one of them is authoritative.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

#: Business calendar and working hours (N38, silence detection T38).
#: Written once so nobody spells the zone name a second time.
TASHKENT = ZoneInfo("Asia/Tashkent")

#: Working hours, local. Silence detection and the availability target use these.
WORK_START_HOUR = 8
WORK_END_HOUR = 20


def now() -> datetime:
    """Server time, timezone-aware UTC. The only clock the server trusts."""
    return datetime.now(UTC)


def today_tashkent():
    """Today's date in Tashkent — for daily reports and the business calendar."""
    return now().astimezone(TASHKENT).date()


def is_working_hours(moment: datetime | None = None) -> bool:
    """True inside 08:00–20:00 Asia/Tashkent, Mon–Sat.

    Used by silence detection: a phone that stops reporting at 02:00 is asleep,
    not broken, and must not raise an alert.
    """
    local = (moment or now()).astimezone(TASHKENT)
    if local.weekday() == 6:  # Sunday
        return False
    return WORK_START_HOUR <= local.hour < WORK_END_HOUR


def clock_skew_sec(received_at: datetime, device_epoch_ms: int | None) -> int | None:
    """How far the device's clock is from ours, in seconds. None if not reported.

    Positive: the device is behind. Stored on ``device_health.clock_skew_sec``
    and shown in the panel (T87) so a phone with a broken clock is visible
    rather than silently producing misordered calls.

    This is *evidence*, never a correction — we do not rewrite device timestamps
    from it. Ordering uses ``received_at``.
    """
    if device_epoch_ms is None:
        return None
    device_moment = datetime.fromtimestamp(device_epoch_ms / 1000, tz=UTC)
    return int((received_at - device_moment).total_seconds())


__all__ = [
    "TASHKENT",
    "WORK_START_HOUR",
    "WORK_END_HOUR",
    "now",
    "today_tashkent",
    "is_working_hours",
    "clock_skew_sec",
]
