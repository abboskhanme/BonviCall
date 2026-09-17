"""The activity report's own wire types.

Defined here and not imported from ``calls``: §2.1 rule 3 says what crosses
back out of a read-only module is that module's own schema, never a foreign
entity.

Ported from BonviZvonki ``modules/analytics/presentation/router.py``
(``AgentActivityRow``, ``ActivityDayRow``, ``ActivityHourRow``,
``ActivityResponse``, ``MissedClientRow``, ``MissedClientsResponse``). Field
descriptions are English because they become the OpenAPI document and
therefore the panel's generated types (CONVENTIONS.md §14); theirs are Uzbek.

Dropped against theirs, and why: ``unknown``, ``unknown_in``, ``unknown_out``
and ``inbound_known``. They exist because ``calls.answered`` is a nullable
boolean there; ``calls.disposition`` is NOT NULL here with a CHECK on the
direction/disposition pairs, so those four fields would be zero or duplicated
by construction (``rules.py``).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class AgentActivityRow(BaseModel):
    """One employee over the window. The company total uses the same shape."""

    agent_id: uuid.UUID
    agent_name: str

    outbound_total: int = Field(description="Calls the employee made to customers.")
    outbound_answered: int
    outbound_no_answer: int = Field(
        description=(
            "The customer did not pick up. NOT a missed call and never added to "
            "one: measured over 7 days, 983 incoming unanswered against 1047 "
            "outgoing, so combining them doubles the figure and blames the "
            "employee for it."
        )
    )

    inbound_total: int = Field(description="Calls customers made to the employee.")
    inbound_answered: int
    missed: int = Field(
        description=(
            "INCOMING and not answered — the company's responsibility, and the "
            "point of this report. `rejected` counts here with `missed`: the "
            "phone rang and there was no conversation."
        )
    )

    missed_called_back: int = Field(description="Missed EVENTS followed by contact.")
    missed_addressable: int = Field(
        description=(
            "Missed events carrying a usable number. `missed_open` divides by "
            "this, because a number nobody has cannot be called back."
        )
    )
    missed_open: int

    missed_clients: int = Field(
        description=(
            "Distinct customers who could not get through; repeat attempts count "
            "once. Measured: 1.8 attempts per customer on average."
        )
    )
    clients_reached: int
    clients_unreached: int = Field(
        description="THE HEADLINE: lost business, counted in people rather than calls."
    )

    missed_rate: float | None = Field(
        description="Missed as a percent of incoming. Null when there were none."
    )
    callback_rate: float | None = Field(
        description="Reached as a percent of unreached customers, per CUSTOMER."
    )
    callback_median_minutes: float | None = Field(
        description=(
            "How long this employee keeps a customer waiting (median minutes). "
            "A different question from the rate: 100 % returned three hours "
            "later is a good rate and a bad service."
        )
    )

    total: int
    talk_seconds: int


class ActivityDayRow(BaseModel):
    """One local day's volume. Empty days are present, never trimmed."""

    day: date
    inbound: int
    inbound_answered: int
    missed: int
    outbound: int
    outbound_no_answer: int


class ActivityHourRow(BaseModel):
    """One hour of the LOCAL day, summed across the window.

    Asia/Tashkent, never UTC: "customers cannot get through at lunchtime" is
    visible at 12:00 and becomes a meaningless 07:00 in UTC. Identical shape to
    the daily row, because one chart draws both cuts.
    """

    hour: int
    inbound: int
    inbound_answered: int
    missed: int
    outbound: int
    outbound_no_answer: int
    missed_rate: float | None


class ActivityResponse(BaseModel):
    """The whole report: window, chart series, per-agent rows and the total."""

    days: int = Field(description="Calendar days covered, Asia/Tashkent.")
    date_from: date
    date_to: date = Field(description="Inclusive: the last day the window covers.")
    callback_window_hours: int = Field(
        description="A later call counts as a callback only inside this many hours."
    )
    callback_median_minutes: float | None = Field(
        description=(
            "Company-wide median minutes to contact. Computed over calls, never "
            "as an average of the agents' medians — a median of medians ignores "
            "volume."
        )
    )
    days_series: list[ActivityDayRow]
    hours_series: list[ActivityHourRow]
    agents: list[AgentActivityRow]
    total: AgentActivityRow = Field(
        description=(
            "The company row. Its customer counts are computed separately, not "
            "summed: one customer who called two employees is one person."
        )
    )


class MissedClientRow(BaseModel):
    """One unreached customer — the detail that proves the number.

    A row reading "15 missed, 100 % called back" looks wrong until this list
    shows the 15 events came from 9 customers and every one was spoken to.
    """

    phone_key: str = Field(
        description="The last-9 matching key (`calls.remote_number_key`, N37)."
    )
    contact_name: str | None = Field(
        description=(
            "Resolved on the handset from the employee's own contacts. "
            "Decoration, never identity — there is no customer catalogue."
        )
    )
    attempts: int
    first_missed_at: datetime
    last_missed_at: datetime
    contacted_at: datetime | None = Field(description="Null — still not contacted.")
    contacted_by: str | None = Field(
        description="Who spoke to them. May be a different employee."
    )
    contact_inbound: bool | None = Field(
        description=(
            "True — the customer tried again and was answered; false — somebody "
            "called them back."
        )
    )
    minutes_to_contact: float | None


class MissedClientsResponse(BaseModel):
    agent_id: uuid.UUID
    agent_name: str
    date_from: date
    date_to: date
    callback_window_hours: int
    clients: list[MissedClientRow]
    unreached: int
