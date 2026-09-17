"""The activity report's arithmetic and its window — pure, no database.

Ported from BonviZvonki ``modules/analytics/application/activity.py``
(the dataclasses and every ``@property`` on them) and from
``modules/analytics/presentation/router.py`` (``_activity_window``,
``_inclusive_end``, ``last_days_start``). The reasoning in the comments is
theirs, measured against real data, and is kept because re-learning it costs
another quarter of wrong numbers in front of a manager.

Nothing here imports the ORM, FastAPI or any other module: ``service.py``
issues the SQL and hands the counts in, so every rule below is exercised by
``tests/test_activity_rules.py`` with no session, no container and no clock.

════════════════════════════════════════════════════════════════
 TERMS — these distinctions are the whole point of the report
════════════════════════════════════════════════════════════════

There is no single number called "unanswered", because it would put two
completely different facts in one column:

  · INCOMING + not answered = a missed customer. They called, the company
    did not pick up. That is the COMPANY's responsibility and it is the
    headline of this report.

  · OUTGOING + not answered = the customer did not pick up. That is not the
    employee's fault (busy, phone off). Adding it to the number above
    doubles the figure and blames somebody for it.

Measured by BonviZvonki over 7 days of real data: 983 incoming unanswered
against 1047 outgoing unanswered. Reporting "2030 unanswered" would have
been twice the truth and none of the meaning.

"Called back" means an OUTGOING call to that number after the missed
incoming one. Measured: over 3 days, 307 of 404 missed incoming calls (76 %)
were returned and 97 (24 %) never were; median 12 minutes.

════════════════════════════════════════════════════════════════
 WHAT BONVIZVONKI'S ``answered IS NOT NULL`` GUARD BECAME HERE
════════════════════════════════════════════════════════════════

Their ``calls.answered`` is a nullable boolean added after the fact, so rows
written before it existed are NULL. Counting those as unanswered inflates the
headline, so their report excludes them everywhere and reports the count
separately (``unknown``, ``unknown_in``, ``unknown_out``), and every
percentage divides by ``inbound_known`` rather than ``inbound_total`` —
measured, the difference was six-fold (4.6 % against 29.0 %).

**BonviCall cannot represent that state.** ``calls.disposition`` is NOT NULL
and a CHECK constraint (``direction_disposition``) pins the pairs: incoming
is ``answered | missed | rejected``, outgoing is ``answered | no_answer``. So
``inbound_total == inbound_answered + missed`` and
``outbound_total == outbound_answered + outbound_no_answer`` are facts of the
schema rather than hopes. The three ``unknown*`` fields and the separate
``inbound_known`` denominator are therefore **dropped**, not translated: a
field that is zero by construction is a column nobody can read and a banner
nobody can ever see.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from uuid import UUID

#: Report windows, in days. The four the client's manager asks for.
PERIODS: tuple[int, ...] = (1, 7, 15, 30)

#: A return call counts as "called back" only inside this many hours.
#
# WHY THERE IS A BOUND AT ALL. Without one, any later call to that number
# counts as a callback — including one a week later for an unrelated reason.
# The measure then sits near 100 % and measures nothing.
#
# 24 hours was chosen because it was measured: over 30 days of real data 76 %
# of callbacks happen within ONE hour and the median is 6 minutes. A day is
# far wider than the working practice and still clearly different from
# "never".
CALLBACK_WINDOW_HOURS = 24

#: The hourly cut covers ALL 24 hours.
#
# It was once limited to 06:00-24:00 and that BROKE THE TOTALS: the hourly
# breakdown summed to 3135 while the card above it said 3143, so eight calls
# appeared to have been lost. In a presentation that inconsistency produces
# the worst possible question — "your numbers do not add up".
#
# It is true that a percentage over a quiet night hour is noise (one missed
# call out of two is 50 %), but that is a PRESENTATION problem and it is
# solved in the panel: below a volume threshold the rate line breaks while
# the bar still shows. Nothing is hidden; only a false percentage is not
# drawn.
WORK_HOURS = range(24)

#: The longest explicit range the report will build.
#
# ``days`` is capped at 365 by the query parameter; an explicit
# ``date_from``/``date_to`` pair needs its own bound or one pasted URL asks
# for a 1827-day line chart. A year and a leap day is more than anybody reads
# at once and is still a whole calendar year.
MAX_WINDOW_DAYS = 366


# ── The window ────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Window:
    """One report window, resolved to whole Asia/Tashkent calendar days.

    ``since``/``until`` are the half-open instants the SQL uses; ``date_from``
    and ``date_to`` are the inclusive local dates the answer is labelled with.
    """

    since: datetime
    """Inclusive lower bound, tz-aware."""
    until: datetime
    """**Exclusive** upper bound, tz-aware: local midnight after ``date_to``."""
    date_from: date
    date_to: date
    """Inclusive. The last day the reader asked for."""
    days: int


class WindowInvalid(ValueError):
    """The range cannot be built. ``field`` names which bound is at fault.

    A plain ``ValueError`` subclass rather than an ``AppError``: this module
    imports nothing from the project, and the router turns it into the 400.
    """

    def __init__(self, field_name: str) -> None:
        self.field_name = field_name
        super().__init__(field_name)


def activity_window(
    *,
    days: int,
    date_from: date | None,
    date_to: date | None,
    today: date,
    zone: tzinfo,
) -> Window:
    """The window both endpoints use. **One definition, or they disagree.**

    ⚠️ It must not be duplicated. If the report and the per-agent detail list
    resolve different windows, the detail contradicts the summary and the tool
    built to prove a number is the thing that destroys trust in it —
    "9 in the table, 8 in the list" is the worst outcome.

    Three decisions are carried over from BonviZvonki, and one is new.

    1. **An explicit range wins over ``days`` and is never converted into a
       day count.** Theirs used to be: the caller passed dates, the server
       turned them into a number of days and rebuilt the window from that.
       ``timedelta.days`` truncates, so the start slid forward by up to 24
       hours — measured, a request for "10-16 August" silently dropped 853
       calls and 137 missed ones, with nothing in the response to say so.

    2. **The window is aligned to whole local days.** A rolling "now minus
       7x24 hours" window makes the first bar of the daily chart cover part of
       a day and read 97 % low, which draws a decline that did not happen.

    3. **``date_to`` is inclusive.** Their router shifted a midnight
       ``date_to`` to the end of that day by hand (``_inclusive_end``) because
       the filter was ``started_at <= date_to``; a caller asking for "up to
       the 16th" otherwise lost the whole of the 16th. Here the bounds are
       calendar ``date`` values and ``until`` is the local midnight AFTER
       ``date_to``, so inclusivity is structural. That also deletes their
       ``_as_utc``, which existed because Pydantic parsed ``?date_from=…``
       into a NAIVE datetime that then raised ``TypeError`` against an aware
       one and answered 500.

    4. **New:** a ``date_to`` on its own is honoured, with ``days`` counting
       back from it. Theirs ignored it and quietly returned the last N days
       ending today instead — a different period from the one asked for, with
       no sign in the answer.
    """
    if date_from is None and date_to is None:
        date_to = today
        date_from = date_to - timedelta(days=days - 1)
    elif date_from is None:
        assert date_to is not None
        date_from = date_to - timedelta(days=days - 1)
    elif date_to is None:
        # "Since then" — up to and including today, never into the future.
        date_to = max(today, date_from)

    assert date_from is not None and date_to is not None
    if date_from > date_to:
        raise WindowInvalid("date_from")
    span = (date_to - date_from).days + 1
    if span > MAX_WINDOW_DAYS:
        raise WindowInvalid("date_from")

    since = datetime.combine(date_from, time.min, tzinfo=zone)
    until = datetime.combine(date_to, time.min, tzinfo=zone) + timedelta(days=1)
    return Window(
        since=since, until=until, date_from=date_from, date_to=date_to, days=span
    )


def day_span(date_from: date, date_to: date) -> list[date]:
    """Every local date in the window, inclusive, with no gaps.

    ⚠️ EMPTY DAYS ARE NOT REMOVED — none of them. Dropping them LIES: weekends
    disappear, the line becomes continuous and the chart says "the same work
    every day". Trimming the edges is worse still: pick "7 days" in the
    morning before anybody has called and today's bar vanishes, so the chart
    shows six bars while the header says seven and the two contradict each
    other. An empty day is REAL data — a day off, a day nobody worked, or a
    today that has not happened yet.
    """
    cursor = date_from
    span: list[date] = []
    while cursor <= date_to:
        span.append(cursor)
        cursor += timedelta(days=1)
    return span


# ── The rows ──────────────────────────────────────────────────


def _percent(part: int, whole: int) -> float | None:
    """``part`` as a percentage of ``whole``, one decimal. None when no whole.

    None rather than zero: "no incoming calls" and "no missed calls out of
    many" are different answers and the panel renders the first as an em dash.
    """
    if not whole:
        return None
    return round(part / whole * 100, 1)


@dataclass(slots=True)
class AgentActivity:
    """One employee's activity over the window."""

    agent_id: UUID
    agent_name: str

    outbound_total: int = 0
    """Calls the employee made to customers."""
    outbound_answered: int = 0
    outbound_no_answer: int = 0
    """The customer did not pick up. ⚠️ This is NOT a missed call."""

    inbound_total: int = 0
    """Calls customers made to the employee."""
    inbound_answered: int = 0
    missed: int = 0
    """INCOMING and not answered — the company's responsibility.

    ⚠️ ``rejected`` counts here with ``missed``. BonviCall splits what
    BonviZvonki stored as one nullable boolean into a four-value
    ``disposition``, and ``rejected`` means the phone rang and the
    conversation did not happen — which is exactly the fact this column is
    about. Counting only ``disposition = 'missed'`` would leave the rejected
    calls in ``inbound_total`` and in no other column, and the row would stop
    adding up.
    """

    missed_called_back: int = 0
    """Missed EVENTS that were followed by contact."""
    missed_addressable: int = 0
    """Missed events that carry a usable number. ``missed_open`` divides by
    this: you cannot call back a number you do not have, and putting those in
    the "not returned" list blames the employee for something impossible.
    Measured: 8 of 971 over 7 days."""

    # ── Customer level ────────────────────────────────────────
    #
    # ⚠️ THE HEADLINE NUMBER IS HERE, not at the event level.
    #
    # Why. A customer who cannot get through tries again — measured, 1.8
    # times on average. Counting events counts one person's problem several
    # times and inflates the figure.
    #
    # There is a worse case. A customer who rang four times and was answered
    # on the fourth is scored "3 missed, 75 %" at the event level — yet that
    # customer WAS reached and the company DID answer. At that point the
    # event-level percentage is simply false.
    missed_clients: int = 0
    """Distinct customers who could not get through (repeats counted once)."""
    clients_reached: int = 0
    """Of those, the ones contacted afterwards: called back, or they tried
    again and were answered."""

    talk_seconds: int = 0

    callback_median_minutes: float | None = None
    """How long THIS employee takes to call back (median).

    ⚠️ The RATE and the TIME answer different questions and both are needed:
    the rate says how many customers were called back at all, the median says
    how long they were kept waiting. An employee can return 100 % of calls
    and take three hours over each — the rate does not show that. Measured at
    BonviZvonki: one team returned 89 % with a 43-minute median, another 93 %
    with 2.5 minutes.

    Median, not mean: one evening call returned the next morning (14 hours)
    ruins a mean, while the median still describes the ordinary case.
    """

    @property
    def total(self) -> int:
        return self.outbound_total + self.inbound_total

    @property
    def missed_rate(self) -> float | None:
        """What share of incoming calls went unanswered.

        The denominator is ``inbound_total``. In BonviZvonki it had to be
        ``inbound_answered + missed`` instead, because rows with a NULL
        ``answered`` were in the total and in neither half — leaving them in
        the denominator pushed the figure down SIX-fold (4.6 % against
        29.0 %), and a low number flatters: a manager reads "4.6 % missed —
        good" and never looks again. Here the CHECK on ``calls`` makes the two
        denominators the same number, so the simpler one is the honest one.
        """
        return _percent(self.missed, self.inbound_total)

    @property
    def callback_rate(self) -> float | None:
        """What share of unreached customers were contacted afterwards.

        ⚠️ Computed per CUSTOMER, never per event — see ``missed_clients``.
        """
        return _percent(self.clients_reached, self.missed_clients)

    @property
    def clients_unreached(self) -> int:
        """⚠️ THE HEADLINE NUMBER OF THE REPORT.

        Customers who could not get through and were never contacted
        afterwards. This is lost business and it is measured in PEOPLE, not in
        calls. Measured at BonviZvonki: 54 people over 3 days.
        """
        return self.missed_clients - self.clients_reached

    @property
    def missed_open(self) -> int:
        """Missed EVENTS with no contact afterwards.

        ⚠️ Divides ``missed_addressable``, not ``missed``. Secondary to
        ``clients_unreached``, which is the number that matters.
        """
        return max(0, self.missed_addressable - self.missed_called_back)


@dataclass(slots=True)
class ActivityDay:
    """One day's volume, for the chart.

    Volume ONLY: there is deliberately no customer-level count here. It breaks
    at the day boundary — a customer who calls in the evening and is answered
    next morning would be counted on one day and reached on another — and the
    chart would then disagree with the card above it.
    """

    day: date
    inbound: int = 0
    inbound_answered: int = 0
    missed: int = 0
    outbound: int = 0
    outbound_no_answer: int = 0


@dataclass(slots=True)
class ActivityHour:
    """One hour of the day, summed across the window.

    This is the most actionable cut a manager gets: WHICH HOUR customers
    cannot get through. Measured at BonviZvonki — 35 % missed over lunch
    (12:00), 74 % at 07:00, 40 % at 19:00, against a daily average of 29 %.
    The average hid all of it and never produced the conclusion "move the
    shift".

    ⚠️ Its shape is IDENTICAL to ``ActivityDay`` on purpose — one chart draws
    both cuts and the bars must not change when the reader switches. The
    hourly query once selected only incoming rows, and the hourly totals then
    failed to match the daily ones and the card; switching cut made the
    numbers jump, which costs trust in the whole screen.
    """

    hour: int
    inbound: int = 0
    inbound_answered: int = 0
    missed: int = 0
    outbound: int = 0
    outbound_no_answer: int = 0

    @property
    def missed_rate(self) -> float | None:
        return _percent(self.missed, self.inbound)


@dataclass(slots=True)
class MissedClient:
    """One unreached customer — the DETAIL that proves the number.

    WHY THIS EXISTS. A row reading "15 missed, 100 % called back" looks wrong
    and the first question is "really?". It is right: the 15 events came from
    9 different customers and every one of them was spoken to. Without
    showing that, nobody believes the figure — least of all in front of a
    manager.

    So each customer is listed: how many times they tried, when the last
    attempt was, and who spoke to them afterwards and how long after.
    """

    phone_key: str
    """The last-9 matching key (``calls.remote_number_key``, N37)."""
    contact_name: str | None
    """As the handset resolved it from the employee's own contacts.
    Decoration, never identity (L3) — BonviCall has no customer catalogue."""
    attempts: int
    first_missed_at: datetime
    last_missed_at: datetime
    contacted_at: datetime | None
    """None — STILL not contacted."""
    contacted_by: str | None
    """Who spoke to them. May be a different employee."""
    contact_inbound: bool | None
    """True — the customer tried again and was answered; False — somebody
    called them back."""

    @property
    def minutes_to_contact(self) -> float | None:
        if self.contacted_at is None:
            return None
        return round((self.contacted_at - self.last_missed_at).total_seconds() / 60, 1)


@dataclass(slots=True)
class ActivityReport:
    window: Window
    agents: list[AgentActivity] = field(default_factory=list)

    total: AgentActivity | None = None
    """Company-wide. Its customer counts are NOT the sum of the rows —
    see :func:`sum_rows`."""

    days_series: list[ActivityDay] = field(default_factory=list)
    hours_series: list[ActivityHour] = field(default_factory=list)

    callback_median_minutes: float | None = None
    """Median time to call back across the company. Not a mean: a single
    day-long delay ruins a mean, the median still describes the usual case."""


def sum_rows(rows: list[AgentActivity]) -> AgentActivity:
    """The company row. Employee fields are blank — this is not a person.

    ⚠️ THE CUSTOMER COUNTS ARE DELIBERATELY NOT SUMMED HERE. One customer can
    call two different employees. Per employee that is correctly two rows —
    each is answerable for their own phone — but company-wide it is ONE
    person, and adding the rows inflates the headline. Measured at
    BonviZvonki: 151 instead of the real 145 over two days, 4 % over. The
    caller overwrites ``missed_clients`` and ``clients_reached`` with a
    separate, de-duplicated query; this function leaves them at zero so a
    caller that forgets shows an obvious zero rather than a plausible lie.
    """
    total = AgentActivity(agent_id=UUID(int=0), agent_name="")
    for row in rows:
        total.outbound_total += row.outbound_total
        total.outbound_answered += row.outbound_answered
        total.outbound_no_answer += row.outbound_no_answer
        total.inbound_total += row.inbound_total
        total.inbound_answered += row.inbound_answered
        total.missed += row.missed
        total.missed_called_back += row.missed_called_back
        total.missed_addressable += row.missed_addressable
        total.talk_seconds += row.talk_seconds
    return total


__all__ = [
    "CALLBACK_WINDOW_HOURS",
    "MAX_WINDOW_DAYS",
    "PERIODS",
    "WORK_HOURS",
    "ActivityDay",
    "ActivityHour",
    "ActivityReport",
    "AgentActivity",
    "MissedClient",
    "Window",
    "WindowInvalid",
    "activity_window",
    "day_span",
    "sum_rows",
]
