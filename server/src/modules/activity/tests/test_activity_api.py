"""The activity report over the wire: access, scope, arithmetic, boundaries.

The three things that can make this report lie, and therefore the three things
asserted hardest:

  · an unanswered incoming call and an unanswered outgoing call counted as the
    same thing (they are 983 and 1047 over a week of real data);
  · repeat attempts by one customer counted as several unreached customers;
  · a day boundary taken in UTC, which moves five hours of calls onto the
    wrong day and is invisible until somebody adds up a month by hand.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.core.enums import CallDirection, CallDisposition
from src.modules.agents.models import AgentModel

pytestmark = pytest.mark.asyncio

ACTIVITY = "/api/v1/activity"
MISSED = "/api/v1/activity/missed-clients"

#: A fixed instant inside the window every test asks for. Tashkent is UTC+5 and
#: has no daylight saving, so 09:00Z is 14:00 local — the middle of a working
#: day, whichever side of midnight the assertion is about.
NOON = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


def _window() -> dict[str, str]:
    """The single local day :data:`NOON` falls in."""
    return {"date_from": "2026-08-20", "date_to": "2026-08-20"}


async def _own_installation(db, installation_factory, agent_id):
    """An installation belonging to the ``sales`` fixture's own agent."""
    return await installation_factory(agent=await db.get(AgentModel, agent_id))


async def _incoming(call_factory, installation, **overrides):
    return await call_factory(
        installation=installation,
        direction=CallDirection.INCOMING,
        disposition=overrides.pop("disposition", CallDisposition.MISSED),
        **overrides,
    )


async def _outgoing(call_factory, installation, **overrides):
    return await call_factory(
        installation=installation,
        direction=CallDirection.OUTGOING,
        disposition=overrides.pop("disposition", CallDisposition.ANSWERED),
        **overrides,
    )


# ── Access ────────────────────────────────────────────────────


NIL_AGENT = "00000000-0000-0000-0000-0000000000ff"


async def test_anonymous_is_401(client) -> None:
    assert (await client.get(ACTIVITY)).status_code == 401
    assert (
        await client.get(MISSED, params={"agent_id": NIL_AGENT})
    ).status_code == 401


async def test_a_manager_may_read_the_report(manager) -> None:
    assert (await manager.get(ACTIVITY)).status_code == 200


async def test_a_salesperson_may_read_the_report(sales) -> None:
    """``calls:read:own`` passes the gate; the query narrows below."""
    assert (await sales.get(ACTIVITY)).status_code == 200


# ── Own scope ─────────────────────────────────────────────────


async def test_a_salesperson_sees_only_their_own_row(
    sales, db, call_factory, installation_factory, agent_factory
) -> None:
    mine = await _own_installation(db, installation_factory, sales.principal.agent_id)
    colleague = await installation_factory(agent=await agent_factory(full_name="Boshqa"))
    await _outgoing(call_factory, mine, started_at=NOON)
    await _outgoing(call_factory, colleague, started_at=NOON)

    body = (await sales.get(ACTIVITY, params=_window())).json()
    assert [row["agent_id"] for row in body["agents"]] == [
        str(sales.principal.agent_id)
    ]
    assert body["total"]["outbound_total"] == 1, "the colleague's call is not counted"


async def test_a_salesperson_cannot_name_a_colleague(
    sales, call_factory, installation_factory, agent_factory
) -> None:
    """⚠️ The ``agent_id`` filter is IGNORED for own-scope, never merged.

    Merging would answer with the colleague's row the moment somebody pasted an
    id into the address bar.
    """
    colleague = await agent_factory(full_name="Boshqa")
    installation = await installation_factory(agent=colleague)
    await _outgoing(call_factory, installation, started_at=NOON)

    body = (
        await sales.get(
            ACTIVITY, params={**_window(), "agent_id": str(colleague.id)}
        )
    ).json()
    assert [row["agent_id"] for row in body["agents"]] == [
        str(sales.principal.agent_id)
    ]
    assert body["total"]["outbound_total"] == 0


async def test_a_manager_sees_every_agent(
    manager, call_factory, installation_factory, agent_factory
) -> None:
    first = await installation_factory(agent=await agent_factory(full_name="Aziz"))
    second = await installation_factory(agent=await agent_factory(full_name="Dilnoza"))
    await _outgoing(call_factory, first, started_at=NOON)
    await _outgoing(call_factory, second, started_at=NOON)

    body = (await manager.get(ACTIVITY, params=_window())).json()
    assert {row["agent_name"] for row in body["agents"]} == {"Aziz", "Dilnoza"}


async def test_a_manager_may_filter_to_one_agent(
    manager, call_factory, installation_factory, agent_factory
) -> None:
    aziz = await agent_factory(full_name="Aziz")
    first = await installation_factory(agent=aziz)
    second = await installation_factory(agent=await agent_factory(full_name="Dilnoza"))
    await _outgoing(call_factory, first, started_at=NOON)
    await _outgoing(call_factory, second, started_at=NOON)

    body = (
        await manager.get(ACTIVITY, params={**_window(), "agent_id": str(aziz.id)})
    ).json()
    assert [row["agent_name"] for row in body["agents"]] == ["Aziz"]


async def test_an_employee_with_no_calls_still_appears(
    manager, installation_factory, agent_factory
) -> None:
    """An inner join hides them, and "this person did nothing" may be the most
    important finding in the report."""
    await installation_factory(agent=await agent_factory(full_name="Jim"))
    body = (await manager.get(ACTIVITY, params=_window())).json()
    assert [row["agent_name"] for row in body["agents"]] == ["Jim"]
    assert body["agents"][0]["total"] == 0


async def test_an_archived_employee_is_out_of_the_report(
    manager, installation_factory, agent_factory
) -> None:
    await installation_factory(
        agent=await agent_factory(full_name="Ketgan", archived_at=NOON)
    )
    body = (await manager.get(ACTIVITY, params=_window())).json()
    assert body["agents"] == []


# ── The arithmetic ────────────────────────────────────────────


async def test_incoming_and_outgoing_unanswered_are_never_added_together(
    manager, call_factory, installation_factory
) -> None:
    """⚠️ THE POINT OF THE REPORT. An unanswered incoming call is the company
    failing to pick up; an unanswered outgoing call is a customer who was busy.
    Measured over 7 days: 983 and 1047. One column would be twice the truth."""
    installation = await installation_factory()
    await _incoming(call_factory, installation, started_at=NOON)
    await _outgoing(
        call_factory,
        installation,
        disposition=CallDisposition.NO_ANSWER,
        started_at=NOON,
    )

    row = (await manager.get(ACTIVITY, params=_window())).json()["total"]
    assert row["missed"] == 1
    assert row["outbound_no_answer"] == 1
    assert row["total"] == 2


async def test_a_rejected_incoming_call_is_a_missed_one(
    manager, call_factory, installation_factory
) -> None:
    """The phone rang and there was no conversation — which is what this column
    is about. Counting only ``disposition = 'missed'`` would leave the rejected
    call in ``inbound_total`` and in no other column, and the row would stop
    adding up."""
    installation = await installation_factory()
    await _incoming(
        call_factory, installation, disposition=CallDisposition.REJECTED, started_at=NOON
    )

    row = (await manager.get(ACTIVITY, params=_window())).json()["total"]
    assert (row["inbound_total"], row["missed"], row["inbound_answered"]) == (1, 1, 0)


async def test_the_columns_add_up_in_both_directions(
    manager, call_factory, installation_factory
) -> None:
    """``disposition`` is NOT NULL and a CHECK pins the direction pairs, so
    these two identities are facts of the schema. BonviZvonki cannot state
    either, which is why it needs three ``unknown`` columns."""
    installation = await installation_factory()
    await _incoming(call_factory, installation, started_at=NOON)
    await _incoming(
        call_factory, installation, disposition=CallDisposition.ANSWERED, started_at=NOON
    )
    await _outgoing(call_factory, installation, started_at=NOON)
    await _outgoing(
        call_factory,
        installation,
        disposition=CallDisposition.NO_ANSWER,
        started_at=NOON,
    )

    row = (await manager.get(ACTIVITY, params=_window())).json()["total"]
    assert row["inbound_total"] == row["inbound_answered"] + row["missed"]
    assert row["outbound_total"] == row["outbound_answered"] + row["outbound_no_answer"]
    assert row["missed_rate"] == 50.0


async def test_talk_time_is_the_sum_of_durations(
    manager, call_factory, installation_factory
) -> None:
    installation = await installation_factory()
    await _outgoing(call_factory, installation, started_at=NOON, duration_sec=90)
    await _outgoing(call_factory, installation, started_at=NOON, duration_sec=30)
    row = (await manager.get(ACTIVITY, params=_window())).json()["total"]
    assert row["talk_seconds"] == 120


async def test_a_silent_window_has_no_rates_rather_than_zero(
    manager, installation_factory
) -> None:
    await installation_factory()
    row = (await manager.get(ACTIVITY, params=_window())).json()["total"]
    assert row["missed_rate"] is None
    assert row["callback_rate"] is None
    assert row["callback_median_minutes"] is None


# ── Customers, not events ─────────────────────────────────────


async def test_repeat_attempts_are_one_customer(
    manager, call_factory, installation_factory
) -> None:
    """Measured: a customer who cannot get through tries 1.8 times on average.
    Counting events counts one person's problem several times."""
    installation = await installation_factory()
    for minute in range(3):
        await _incoming(
            call_factory,
            installation,
            started_at=NOON + timedelta(minutes=minute),
            remote_number="+998901234567",
        )

    row = (await manager.get(ACTIVITY, params=_window())).json()["total"]
    assert row["missed"] == 3
    assert row["missed_clients"] == 1
    assert row["clients_unreached"] == 1


async def test_a_callback_reaches_the_customer(
    manager, call_factory, installation_factory
) -> None:
    installation = await installation_factory()
    await _incoming(
        call_factory, installation, started_at=NOON, remote_number="+998901234567"
    )
    await _outgoing(
        call_factory,
        installation,
        started_at=NOON + timedelta(minutes=10),
        remote_number="998 90 123 45 67",
    )

    body = (await manager.get(ACTIVITY, params=_window())).json()
    row = body["total"]
    assert row["missed_clients"] == 1
    assert row["clients_reached"] == 1
    assert row["clients_unreached"] == 0
    assert row["callback_rate"] == 100.0
    assert body["callback_median_minutes"] == 10.0


async def test_the_customer_trying_again_and_being_answered_counts_as_contact(
    manager, call_factory, installation_factory
) -> None:
    """Leaving this out reports the commonest real case — "they rang again and
    we spoke" — as "never reached"."""
    installation = await installation_factory()
    await _incoming(
        call_factory, installation, started_at=NOON, remote_number="+998901234567"
    )
    await _incoming(
        call_factory,
        installation,
        disposition=CallDisposition.ANSWERED,
        started_at=NOON + timedelta(minutes=5),
        remote_number="+998901234567",
    )

    row = (await manager.get(ACTIVITY, params=_window())).json()["total"]
    assert row["clients_reached"] == 1
    assert row["clients_unreached"] == 0


async def test_the_clock_starts_at_the_last_missed_attempt(
    manager, call_factory, installation_factory
) -> None:
    """A customer rang at 09:00 and again at 18:00 and was called back at 09:20.
    Measured from the first attempt they read as "reached"; they are not."""
    installation = await installation_factory()
    morning = NOON
    await _incoming(
        call_factory, installation, started_at=morning, remote_number="+998901234567"
    )
    await _outgoing(
        call_factory,
        installation,
        started_at=morning + timedelta(minutes=20),
        remote_number="+998901234567",
    )
    await _incoming(
        call_factory,
        installation,
        started_at=morning + timedelta(hours=2),
        remote_number="+998901234567",
    )

    row = (await manager.get(ACTIVITY, params=_window())).json()["total"]
    assert row["clients_unreached"] == 1


async def test_a_callback_outside_the_window_does_not_count(
    manager, call_factory, installation_factory
) -> None:
    """Without the 24-hour bound any later call counts, the measure sits near
    100 % and measures nothing."""
    installation = await installation_factory()
    await _incoming(
        call_factory, installation, started_at=NOON, remote_number="+998901234567"
    )
    await _outgoing(
        call_factory,
        installation,
        started_at=NOON + timedelta(hours=30),
        remote_number="+998901234567",
    )

    body = (
        await manager.get(
            ACTIVITY, params={"date_from": "2026-08-20", "date_to": "2026-08-22"}
        )
    ).json()
    assert body["total"]["clients_unreached"] == 1
    assert body["callback_window_hours"] == 24


async def test_a_missed_call_with_no_usable_number_is_not_held_against_anyone(
    manager, call_factory, installation_factory
) -> None:
    """You cannot call back a number you do not have. It still shows in the
    volume column — measured at BonviZvonki, 8 of 971 over 7 days."""
    installation = await installation_factory()
    await _incoming(
        call_factory, installation, started_at=NOON, remote_number=None
    )
    await _incoming(call_factory, installation, started_at=NOON, remote_number="700")

    row = (await manager.get(ACTIVITY, params=_window())).json()["total"]
    assert row["missed"] == 2
    assert row["missed_addressable"] == 0
    assert row["missed_open"] == 0
    assert row["missed_clients"] == 0


async def test_one_customer_calling_two_employees_is_one_person_in_the_total(
    manager, call_factory, installation_factory, agent_factory
) -> None:
    """⚠️ Per employee two rows — each is answerable for their own phone —
    but company-wide ONE person. Summing the rows inflated the headline by 4 %
    at BonviZvonki (151 against 145 over two days)."""
    first = await installation_factory(agent=await agent_factory(full_name="Aziz"))
    second = await installation_factory(agent=await agent_factory(full_name="Dilnoza"))
    await _incoming(
        call_factory, first, started_at=NOON, remote_number="+998901234567"
    )
    await _incoming(
        call_factory, second, started_at=NOON, remote_number="+998901234567"
    )

    body = (await manager.get(ACTIVITY, params=_window())).json()
    assert sum(row["missed_clients"] for row in body["agents"]) == 2
    assert body["total"]["missed_clients"] == 1
    assert body["total"]["clients_unreached"] == 1


# ── Windows and boundaries ────────────────────────────────────


async def test_the_day_boundary_is_tashkent_midnight(
    manager, call_factory, installation_factory
) -> None:
    """UTC+5: 18:59Z is still the 10th locally, 19:00Z is already the 11th.

    Bucketing in UTC moves five hours of calls onto the previous day and
    nothing on screen says so.
    """
    installation = await installation_factory()
    await _outgoing(
        call_factory,
        installation,
        started_at=datetime(2026, 8, 10, 18, 59, tzinfo=UTC),
    )
    await _outgoing(
        call_factory,
        installation,
        started_at=datetime(2026, 8, 10, 19, 0, tzinfo=UTC),
    )

    body = (
        await manager.get(
            ACTIVITY, params={"date_from": "2026-08-11", "date_to": "2026-08-11"}
        )
    ).json()
    assert body["total"]["outbound_total"] == 1
    assert body["days_series"] == [
        {
            "day": "2026-08-11",
            "inbound": 0,
            "inbound_answered": 0,
            "missed": 0,
            "outbound": 1,
            "outbound_no_answer": 0,
        }
    ]


async def test_date_to_includes_the_whole_of_that_day(
    manager, call_factory, installation_factory
) -> None:
    """"Up to the 16th" that stops at midnight loses the whole of the 16th."""
    installation = await installation_factory()
    await _outgoing(
        call_factory,
        installation,
        # 23:30 local on the 16th.
        started_at=datetime(2026, 8, 16, 18, 30, tzinfo=UTC),
    )
    body = (
        await manager.get(
            ACTIVITY, params={"date_from": "2026-08-10", "date_to": "2026-08-16"}
        )
    ).json()
    assert body["days"] == 7
    assert body["total"]["outbound_total"] == 1


async def test_every_day_of_the_window_is_a_bar_including_empty_ones(
    manager, installation_factory
) -> None:
    await installation_factory()
    body = (
        await manager.get(
            ACTIVITY, params={"date_from": "2026-08-14", "date_to": "2026-08-20"}
        )
    ).json()
    assert [day["day"] for day in body["days_series"]] == [
        f"2026-08-{day}" for day in range(14, 21)
    ]


async def test_the_hourly_cut_covers_all_twenty_four_hours_in_local_time(
    manager, call_factory, installation_factory
) -> None:
    """Limiting it to working hours once broke the totals: the hourly sum said
    3135 and the card said 3143, and eight calls looked lost."""
    installation = await installation_factory()
    # 07:00 local == 02:00Z.
    await _incoming(
        call_factory,
        installation,
        started_at=datetime(2026, 8, 20, 2, 0, tzinfo=UTC),
    )
    body = (await manager.get(ACTIVITY, params=_window())).json()
    hours = body["hours_series"]
    assert [hour["hour"] for hour in hours] == list(range(24))
    assert hours[7]["missed"] == 1
    assert hours[7]["missed_rate"] == 100.0
    assert sum(hour["missed"] for hour in hours) == body["total"]["missed"]


async def test_a_backwards_range_is_refused(manager) -> None:
    response = await manager.get(
        ACTIVITY, params={"date_from": "2026-08-20", "date_to": "2026-08-10"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["detail"] == {"field": "date_from"}


async def test_an_absurd_range_is_refused(manager) -> None:
    response = await manager.get(
        ACTIVITY, params={"date_from": "2020-01-01", "date_to": "2026-08-20"}
    )
    assert response.status_code == 400


async def test_days_is_bounded(manager) -> None:
    assert (await manager.get(ACTIVITY, params={"days": 0})).status_code == 422
    assert (await manager.get(ACTIVITY, params={"days": 400})).status_code == 422


# ── The detail list ───────────────────────────────────────────


async def test_the_detail_proves_the_summary(
    manager, call_factory, installation_factory, agent_factory
) -> None:
    """⚠️ Row count == customers, attempts == missed calls. If the detail does
    not reconcile, the tool built to prove a number destroys trust in it."""
    agent = await agent_factory(full_name="Aziz")
    installation = await installation_factory(agent=agent)
    for minute in range(2):
        await _incoming(
            call_factory,
            installation,
            started_at=NOON + timedelta(minutes=minute),
            remote_number="+998901234567",
        )
    await _incoming(
        call_factory,
        installation,
        started_at=NOON,
        remote_number="+998907654321",
        contact_name="Nodira",
    )

    summary = (await manager.get(ACTIVITY, params=_window())).json()["total"]
    detail = (
        await manager.get(MISSED, params={**_window(), "agent_id": str(agent.id)})
    ).json()

    assert len(detail["clients"]) == summary["missed_clients"] == 2
    assert sum(row["attempts"] for row in detail["clients"]) == summary["missed"] == 3
    assert detail["unreached"] == summary["clients_unreached"] == 2
    assert detail["agent_name"] == "Aziz"


async def test_the_detail_names_who_made_contact_and_which_way(
    manager, call_factory, installation_factory, agent_factory
) -> None:
    """A colleague returning the call is a perfectly good answer — measured,
    9 % of the time — and the list says so by name."""
    agent = await agent_factory(full_name="Aziz")
    colleague = await agent_factory(full_name="Dilnoza")
    mine = await installation_factory(agent=agent)
    theirs = await installation_factory(agent=colleague)
    await _incoming(
        call_factory, mine, started_at=NOON, remote_number="+998901234567"
    )
    await _outgoing(
        call_factory,
        theirs,
        started_at=NOON + timedelta(minutes=6),
        remote_number="+998901234567",
    )

    detail = (
        await manager.get(MISSED, params={**_window(), "agent_id": str(agent.id)})
    ).json()
    row = detail["clients"][0]
    assert row["contacted_by"] == "Dilnoza"
    assert row["contact_inbound"] is False
    assert row["minutes_to_contact"] == 6.0
    assert row["phone_key"] == "901234567"
    assert detail["unreached"] == 0


async def test_unreached_customers_sort_first(
    manager, call_factory, installation_factory, agent_factory
) -> None:
    """The list is a work list: what still needs doing is at the top."""
    agent = await agent_factory(full_name="Aziz")
    installation = await installation_factory(agent=agent)
    await _incoming(
        call_factory, installation, started_at=NOON, remote_number="+998901111111"
    )
    await _outgoing(
        call_factory,
        installation,
        started_at=NOON + timedelta(minutes=3),
        remote_number="+998901111111",
    )
    await _incoming(
        call_factory,
        installation,
        started_at=NOON + timedelta(minutes=1),
        remote_number="+998902222222",
    )

    clients = (
        await manager.get(MISSED, params={**_window(), "agent_id": str(agent.id)})
    ).json()["clients"]
    assert [row["contacted_at"] is None for row in clients] == [True, False]


async def test_a_salesperson_may_open_their_own_detail(
    sales, db, call_factory, installation_factory
) -> None:
    installation = await _own_installation(
        db, installation_factory, sales.principal.agent_id
    )
    await _incoming(call_factory, installation, started_at=NOON)
    response = await sales.get(
        MISSED, params={**_window(), "agent_id": str(sales.principal.agent_id)}
    )
    assert response.status_code == 200
    assert len(response.json()["clients"]) == 1


async def test_a_salesperson_asking_for_a_colleague_gets_404_not_403(
    sales, agent_factory
) -> None:
    """⚠️ 403 would confirm that this agent exists and spoke to that number.
    BonviZvonki answers 403 here (``ForbiddenError``); SPEC §4.1 rule 2 says
    404, and an unknown agent answers the same."""
    colleague = await agent_factory(full_name="Boshqa")
    response = await sales.get(
        MISSED, params={**_window(), "agent_id": str(colleague.id)}
    )
    assert response.status_code == 404


async def test_an_archived_agent_has_no_detail_either(
    manager, call_factory, installation_factory, agent_factory
) -> None:
    """The summary leaves archived employees out, so the detail must too — or a
    hand-typed URL opens a list for somebody the report does not contain."""
    agent = await agent_factory(full_name="Ketgan", archived_at=NOON)
    installation = await installation_factory(agent=agent)
    await _incoming(call_factory, installation, started_at=NOON)

    response = await manager.get(MISSED, params={**_window(), "agent_id": str(agent.id)})
    assert response.status_code == 404


async def test_an_unknown_agent_is_404(manager) -> None:
    response = await manager.get(
        MISSED,
        params={**_window(), "agent_id": "00000000-0000-0000-0000-0000000000ff"},
    )
    assert response.status_code == 404


async def test_the_detail_uses_the_same_window_as_the_summary(
    manager, call_factory, installation_factory, agent_factory
) -> None:
    """"9 in the table, 8 in the list" is the worst outcome for a tool whose
    whole job is to prove a number."""
    agent = await agent_factory(full_name="Aziz")
    installation = await installation_factory(agent=agent)
    await _incoming(
        call_factory,
        installation,
        # 23:30 local on the 19th — outside a window that starts on the 20th.
        started_at=datetime(2026, 8, 19, 18, 30, tzinfo=UTC),
        remote_number="+998901111111",
    )
    await _incoming(
        call_factory, installation, started_at=NOON, remote_number="+998902222222"
    )

    detail = (
        await manager.get(MISSED, params={**_window(), "agent_id": str(agent.id)})
    ).json()
    assert [row["phone_key"] for row in detail["clients"]] == ["902222222"]
    assert detail["date_from"] == "2026-08-20" and detail["date_to"] == "2026-08-20"
