"""Pure device rules — no session, no framework (§2).

Three things live here because each has a failure mode a database test hides
behind fixtures: whether a phone counts as online, how much *working* time has
passed since it last said anything, and whether a capability transition is one
an admin needs to be told about.

Working hours are the interesting one. UC-27's alert is "four working hours of
silence", not four hours: a phone that stops reporting at 02:00 is asleep, not
broken, and waking an admin for it is how alerts get muted. The calendar comes
from the ``working_hours.*`` settings the migration seeded, so correcting it is
a data change; nothing here hard-codes a day or an hour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

#: ISO weekday numbers, Monday = 1. The seeded default is Mon–Sat.
DEFAULT_WORKDAYS = (1, 2, 3, 4, 5, 6)


@dataclass(frozen=True)
class WorkingCalendar:
    """The business week, as data (SPEC §3.8).

    :param start_hour/end_hour: local hours, from ``working_hours.start``/``.end``.
    :param workdays: ISO weekday numbers that count.
    :param holidays: dates excluded entirely.
    """

    start_hour: int = 8
    end_hour: int = 20
    workdays: tuple[int, ...] = DEFAULT_WORKDAYS
    holidays: frozenset[date] = field(default_factory=frozenset)

    def is_workday(self, day: date) -> bool:
        return day.isoweekday() in self.workdays and day not in self.holidays

    def contains(self, moment: datetime) -> bool:
        """True when ``moment`` (already local) is inside working hours."""
        return self.is_workday(moment.date()) and (
            self.start_hour <= moment.hour < self.end_hour
        )


def parse_hour(value: str) -> int:
    """``"08:00"`` -> ``8``. The setting is a clock time; the maths wants an hour."""
    return int(str(value).split(":", 1)[0])


def working_seconds_between(
    start: datetime, end: datetime, calendar: WorkingCalendar
) -> int:
    """Working seconds between two **local** instants.

    Walks day by day rather than subtracting: a silence that spans a Sunday, a
    holiday and two nights is the case this exists for, and the closed-form
    version of it is where the off-by-one lives.
    """
    if end <= start:
        return 0
    total = 0
    day = start.date()
    while day <= end.date():
        if calendar.is_workday(day):
            window_start = datetime.combine(
                day, time(hour=calendar.start_hour), tzinfo=start.tzinfo
            )
            window_end = datetime.combine(
                day, time(hour=calendar.end_hour), tzinfo=start.tzinfo
            )
            overlap_start = max(window_start, start)
            overlap_end = min(window_end, end)
            if overlap_end > overlap_start:
                total += int((overlap_end - overlap_start).total_seconds())
        day += timedelta(days=1)
    return total


def is_online(last_heartbeat_at: datetime | None, now: datetime, offline_minutes: int) -> bool:
    """UC-17: five missed two-minute beats is OFFLINE within ten minutes.

    A device that has never reported is offline, not unknown: "we have never
    heard from this phone" is exactly the state an admin must chase.
    """
    if last_heartbeat_at is None:
        return False
    return (now - last_heartbeat_at) < timedelta(minutes=offline_minutes)


#: Capability states that mean the phone cannot do the thing (UC-06, UC-18).
#: ``granted_not_working`` is in the list on purpose — it is the OEM
#: permission-manager case, where retrying the system dialog never helps and a
#: green tick would be a lie.
BROKEN_STATES = frozenset({"denied", "denied_permanently", "granted_not_working"})

WORKING_STATES = frozenset({"granted_working", "not_applicable"})

#: Capability -> alert kind, for the ones UC-18 names individually. Anything
#: else raises the generic drift alert; the map is not a place to be clever.
CAPABILITY_ALERTS: dict[str, str] = {
    "microphone": "permission_lost_microphone",
    "phone_state": "permission_lost_phone_state",
    "call_log": "permission_lost_call_log",
    "battery_exemption": "battery_optimisation_reenabled",
    "oem_recorder": "recording_route_lost",
}

#: Capabilities without which ``capturing`` is a lie (UC-03, §7.8).
#: ``contacts`` is deliberately absent: it degrades ``contact_name`` and
#: nothing else, and the enrolment flow marks it optional.
REQUIRED_CAPABILITIES = frozenset(
    {
        "phone_state",
        "call_log",
        "microphone",
        "notifications",
        "call_phone",
        "foreground_service",
        "subscription_resolution",
    }
)


def alert_for_transition(capability: str, to_state: str) -> str | None:
    """The alert kind a transition should raise, or ``None`` if it is good news.

    Only *into* a broken state raises. A phone recovering is a resolution, not
    a second alert, or an agent fixing a permission would generate the alert
    they just cleared.
    """
    if to_state not in BROKEN_STATES:
        return None
    return CAPABILITY_ALERTS.get(capability, "capture_disabled")


def is_capturing(states: dict[str, str], verified: bool, service_running: bool) -> bool:
    """UC-03's never-false-ready rule.

    ``capturing`` requires *every* required capability working, a verified
    installation and a live service. The home screen and the state sent to the
    server are computed from this one function, so there is no second code path
    that could disagree.
    """
    if not verified or not service_running:
        return False
    return all(states.get(name) in WORKING_STATES for name in REQUIRED_CAPABILITIES)
