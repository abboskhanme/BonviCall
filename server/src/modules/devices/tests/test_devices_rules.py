"""Every function in ``devices/rules.py`` (CONVENTIONS.md §13).

The working-hours maths is the one that matters: UC-27 alerts on four *working*
hours of silence, and getting that wrong either wakes an admin at 03:00 or
misses a phone that died on Friday afternoon.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.modules.devices.rules import (
    REQUIRED_CAPABILITIES,
    WorkingCalendar,
    alert_for_transition,
    is_capturing,
    is_online,
    parse_hour,
    working_seconds_between,
)

# Monday 2026-09-07, 08:00–20:00, Mon–Sat.
CALENDAR = WorkingCalendar(start_hour=8, end_hour=20, workdays=(1, 2, 3, 4, 5, 6))
MONDAY_09 = datetime(2026, 9, 7, 9, tzinfo=UTC)


def test_parse_hour_reads_the_setting() -> None:
    assert parse_hour("08:00") == 8
    assert parse_hour("20:00") == 20


def test_working_seconds_inside_one_day() -> None:
    assert working_seconds_between(MONDAY_09, MONDAY_09 + timedelta(hours=3), CALENDAR) == 3 * 3600


def test_the_night_does_not_count() -> None:
    """A phone that stops reporting at 02:00 is asleep, not broken."""
    friday_19 = datetime(2026, 9, 11, 19, tzinfo=UTC)
    saturday_09 = datetime(2026, 9, 12, 9, tzinfo=UTC)
    # 19:00→20:00 on Friday plus 08:00→09:00 on Saturday: two hours, not fourteen.
    assert working_seconds_between(friday_19, saturday_09, CALENDAR) == 2 * 3600


def test_sunday_does_not_count() -> None:
    saturday_19 = datetime(2026, 9, 12, 19, tzinfo=UTC)
    monday_09 = datetime(2026, 9, 14, 9, tzinfo=UTC)
    # 19:00→20:00 Saturday, all of Sunday skipped, 08:00→09:00 Monday.
    assert working_seconds_between(saturday_19, monday_09, CALENDAR) == 2 * 3600


def test_a_holiday_does_not_count() -> None:
    """Correcting the calendar is a settings change, not a code change."""
    calendar = WorkingCalendar(
        start_hour=8, end_hour=20, workdays=(1, 2, 3, 4, 5, 6),
        holidays=frozenset({date(2026, 9, 8)}),
    )
    monday_19 = datetime(2026, 9, 7, 19, tzinfo=UTC)
    wednesday_09 = datetime(2026, 9, 9, 9, tzinfo=UTC)
    assert working_seconds_between(monday_19, wednesday_09, calendar) == 2 * 3600


def test_time_before_the_start_of_the_window_does_not_count() -> None:
    assert working_seconds_between(
        datetime(2026, 9, 7, 3, tzinfo=UTC), datetime(2026, 9, 7, 9, tzinfo=UTC), CALENDAR
    ) == 3600


def test_a_reversed_interval_is_zero_not_negative() -> None:
    assert working_seconds_between(MONDAY_09, MONDAY_09 - timedelta(hours=5), CALENDAR) == 0


def test_online_is_the_heartbeat_window() -> None:
    """UC-17: five missed two-minute beats is OFFLINE within ten minutes."""
    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    assert is_online(now - timedelta(minutes=4), now, 10) is True
    assert is_online(now - timedelta(minutes=11), now, 10) is False


def test_a_device_that_never_reported_is_offline_not_unknown() -> None:
    """"We have never heard from this phone" is exactly what to chase."""
    assert is_online(None, datetime(2026, 9, 7, 12, tzinfo=UTC), 10) is False


@pytest.mark.parametrize(
    ("capability", "state", "expected"),
    [
        ("microphone", "denied", "permission_lost_microphone"),
        ("phone_state", "denied_permanently", "permission_lost_phone_state"),
        ("call_log", "granted_not_working", "permission_lost_call_log"),
        ("battery_exemption", "denied", "battery_optimisation_reenabled"),
        ("oem_recorder", "denied", "recording_route_lost"),
        ("contacts", "denied", "capture_disabled"),
    ],
)
def test_a_broken_capability_names_its_alert(capability, state, expected) -> None:
    """UC-18's six causes each produce a distinct alert."""
    assert alert_for_transition(capability, state) == expected


def test_granted_not_working_still_raises() -> None:
    """The OEM permission-manager case: retrying the dialog never fixes it,
    so a green tick would be a lie."""
    assert alert_for_transition("microphone", "granted_not_working") is not None


def test_recovering_raises_nothing() -> None:
    """An agent fixing a permission must not generate the alert they cleared."""
    assert alert_for_transition("microphone", "granted_working") is None
    assert alert_for_transition("contacts", "not_applicable") is None


def _all_working() -> dict[str, str]:
    return {name: "granted_working" for name in REQUIRED_CAPABILITIES}


def test_capturing_needs_everything(monkeypatch) -> None:
    """UC-03's never-false-ready rule."""
    assert is_capturing(_all_working(), verified=True, service_running=True) is True


def test_capturing_is_false_when_any_required_capability_is_broken() -> None:
    for name in sorted(REQUIRED_CAPABILITIES):
        states = _all_working()
        states[name] = "denied"
        assert is_capturing(states, verified=True, service_running=True) is False, name


def test_capturing_is_false_when_unverified_or_service_dead() -> None:
    assert is_capturing(_all_working(), verified=False, service_running=True) is False
    assert is_capturing(_all_working(), verified=True, service_running=False) is False


def test_contacts_is_not_required() -> None:
    """It degrades ``contact_name`` and nothing else; E2 marks it skippable."""
    assert "contacts" not in REQUIRED_CAPABILITIES
    states = _all_working() | {"contacts": "denied"}
    assert is_capturing(states, verified=True, service_running=True) is True
