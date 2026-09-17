"""Window arithmetic for the analytics reports — pure, so it can be tested
without a database (CONVENTIONS.md §2).

No session, no framework, no ``src`` import. Everything here is a function over
dates and numbers, which is what lets the boundary cases — the day a window
starts on, the period a delta is compared against, the buckets a chart draws
even where nothing happened — be pinned by a test that runs in milliseconds.

Ported from ``../BonviZvonki/services/backend/src/modules/analytics``
(``presentation/router.py::last_days_start`` and
``application/services.py::_previous_period`` / ``_bucket_starts``), with the
comments translated and the reasoning kept: every one of them records a defect
that reached a manager's screen.

**The one deliberate change is the type.** BonviZvonki works in ``datetime``
and carries a ``_inclusive_end`` helper that pushes a bare date to 23:59:59.999999
because its filter is ``started_at <= date_to``. BonviCall's house rule is
already the answer to that: a business date is an Asia/Tashkent calendar day and
the query is half-open, ``>= midnight(from)`` and ``< midnight(to + 1 day)``
(``CallService._filtered``, D-08). So these functions take ``date`` and the
inclusive-end problem cannot be expressed.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from decimal import ROUND_HALF_UP, Decimal

#: The buckets a timeseries may be grouped into. The same three PostgreSQL's
#: ``date_trunc`` is asked for, so :func:`bucket_starts` and the database
#: cannot disagree about where a period begins.
BUCKETS: tuple[str, ...] = ("day", "week", "month")

#: Upper bound on filled points. In the daily bucket this is ~1.5 years — past
#: it a line chart is unreadable and filling it is work for nothing, so the
#: caller falls back to "return the periods that have data".
MAX_BUCKETS = 550

#: One decimal place for a score or a percentage. Decimal and not float, the
#: same call ``gaps/service.py::_rate`` makes: these numbers are rendered
#: beside each other on one screen and read as exact.
ONE_PLACE = Decimal("0.1")


def window_start(days: int, today: date) -> date:
    """The first day of "the last ``days`` days", ``today`` included.

    **One definition, in one place.** BonviZvonki computed "30 days" twice —
    the analytics page as ``now - 30x24h`` (a rolling window) and the activity
    page as whole local days — and the same period showed 22,003 calls on one
    screen and 21,513 on the other. A manager read that as a fault, and they
    were right to.

    Whole calendar days, because "the last 7 days" means seven calendar days to
    a person, not 168 hours, and because that is what makes the daily chart
    line up with the number above it.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    return today - timedelta(days=days - 1)


def day_bounds(
    date_from: date, date_to: date, zone: tzinfo
) -> tuple[datetime, datetime]:
    """The half-open instant range for a calendar window in ``zone``.

    ``[midnight(date_from), midnight(date_to + 1 day))`` — inclusive at both
    ends as a *date* range, which is what somebody picking "to 16 August"
    means. Half-open in instants so a call at exactly midnight belongs to
    exactly one day and never to two.
    """
    lower = datetime.combine(date_from, time.min, tzinfo=zone)
    upper = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=zone)
    return lower, upper


def previous_window(date_from: date, date_to: date) -> tuple[date, date]:
    """The window of the same length immediately before this one.

    Two defects are fixed here rather than re-introduced:

    1. It must be **the same length**. BonviZvonki compared against whole days
       derived from ``timedelta.days``, so a one-hour window was compared with
       a twenty-four-hour one. With calendar days on both sides the two windows
       are equal by construction.
    2. It must **not overlap**. The previous window ends the day before this
       one starts; a shared boundary day would count its calls in both periods
       and show a change that did not happen.

    The *filters* are carried over by the caller with ``dataclasses.replace``,
    which is the third defect: a hand-built previous filter dropped the score
    bounds and compared a filtered period against an unfiltered one, reporting
    "+25.6 %" where nothing had moved.
    """
    span = (date_to - date_from).days + 1
    previous_to = date_from - timedelta(days=1)
    return previous_to - timedelta(days=span - 1), previous_to


def delta_percent(
    current: Decimal | int | None, previous: Decimal | int | None
) -> Decimal | None:
    """Change against the previous period, in percent, to one decimal place.

    ``None`` when either side is missing or the previous period was zero:
    "up from nothing" is not a percentage, and rendering it as one is how a
    quiet week becomes "+∞ %".
    """
    if current is None or previous is None:
        return None
    before = Decimal(previous)
    if before == 0:
        return None
    return ((Decimal(current) - before) / before * 100).quantize(
        ONE_PLACE, rounding=ROUND_HALF_UP
    )


def ratio_percent(value: Decimal | int, maximum: int) -> Decimal | None:
    """``value`` as a percentage of ``maximum``, to one decimal place.

    ``None`` for a non-positive maximum rather than a division error: a rubric
    block whose maximum we do not know has no honest percentage, and the radar
    chart leaves it out.
    """
    if maximum <= 0:
        return None
    return (Decimal(value) / Decimal(maximum) * 100).quantize(
        ONE_PLACE, rounding=ROUND_HALF_UP
    )


def round_half_up(value: Decimal | int | float | None) -> int | None:
    """Nearest whole number, halves upward.

    ``int()`` is the wrong tool and the reason is measured: it truncates, so an
    average duration of 695.53 s became 695 s and every such figure was biased
    downward.
    """
    if value is None:
        return None
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_one_place(value: Decimal | int | float | None) -> Decimal | None:
    """A score or an average, to one decimal place. ``None`` stays ``None``."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(ONE_PLACE, rounding=ROUND_HALF_UP)


def bucket_starts(date_from: date, date_to: date, bucket: str) -> list[date] | None:
    """Every period start in the window, in the order a chart draws them.

    **It must agree with PostgreSQL's ``date_trunc`` exactly**, or a filled key
    lands next to a real one instead of on top of it and the real value
    disappears:

    * ``day``   — the day itself
    * ``week``  — Monday (PostgreSQL's ISO week starts on Monday)
    * ``month`` — the first of the month

    ``None`` past :data:`MAX_BUCKETS`, or for a bucket nobody named — the
    caller then returns only the periods that have data.

    **Why fill at all.** Returning only the days that had calls makes the chart
    lie: the axis is categorical, so five points are drawn at the same spacing
    whether the window is a week or a quarter. Somebody changes the period, the
    chart does not move, and the conclusion is "the filter is broken". It was
    not — it was invisible.
    """
    if date_from > date_to:
        return []

    if bucket == "day":
        cursor = date_from
    elif bucket == "week":
        cursor = date_from - timedelta(days=date_from.weekday())
    elif bucket == "month":
        cursor = date_from.replace(day=1)
    else:
        return None

    starts: list[date] = []
    while cursor <= date_to:
        starts.append(cursor)
        if len(starts) > MAX_BUCKETS:
            return None
        if bucket == "day":
            cursor += timedelta(days=1)
        elif bucket == "week":
            cursor += timedelta(days=7)
        else:
            # Months are not a fixed number of days: step into the next one
            # through its 28th, which every month has.
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return starts


__all__ = [
    "BUCKETS",
    "MAX_BUCKETS",
    "ONE_PLACE",
    "bucket_starts",
    "day_bounds",
    "delta_percent",
    "previous_window",
    "ratio_percent",
    "round_half_up",
    "to_one_place",
    "window_start",
]
