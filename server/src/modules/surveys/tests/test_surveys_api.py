"""Dispatching surveys, the transport seam, and the ratings page."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient

from src.core import clock
from src.core.settings_keys import SettingKey
from src.modules.surveys import transport
from src.modules.surveys.models import SurveyModel
from src.modules.surveys.rules import RED_FLAGS

pytestmark = pytest.mark.asyncio


# ── The feature flag ───────────────────────────────────────────────────────


async def test_the_feature_is_off_until_somebody_turns_it_on(
    admin: AsyncClient, group_factory
) -> None:
    """⚠️ Seeded false. Deploying this must be a no-op on a running system:
    it writes into chats real customers are sitting in."""
    group = await group_factory()
    response = await admin.post(f"/api/v1/groups/{group.id}/survey")
    assert response.status_code == 409
    assert response.json()["error"]["detail"]["reason"] == "survey_disabled"


async def test_the_flag_also_stops_the_broadcast(
    admin: AsyncClient, group_factory
) -> None:
    await group_factory()
    response = await admin.post("/api/v1/groups/surveys/broadcast")
    assert response.status_code == 409


async def test_reading_collected_ratings_still_works_with_the_flag_off(
    admin: AsyncClient,
) -> None:
    """The flag stops surveys being SENT. Rows already written stay readable —
    the same line ``analysis.enabled`` draws."""
    assert (await admin.get("/api/v1/surveys")).status_code == 200


# ── Nothing is delivered ───────────────────────────────────────────────────


async def test_a_queued_survey_is_not_marked_sent(
    admin: AsyncClient, group_factory, surveys_on, db
) -> None:
    """⚠️ The load-bearing assertion of this whole port.

    The shipped transport delivers nothing, so the row stays ``pending`` with
    ``sent_at`` NULL. Marking it ``sent`` would show a customer group as
    surveyed on the panel when nothing had been posted, and an admin would have
    no way to tell that from a group that really was.
    """
    await surveys_on()
    group = await group_factory()
    body = (await admin.post(f"/api/v1/groups/{group.id}/survey")).json()

    assert body["delivered"] is False
    assert body["status"] == "pending"
    survey = await db.get(SurveyModel, uuid.UUID(body["survey_id"]))
    assert survey is not None
    assert survey.status == "pending"
    assert survey.sent_at is None
    assert survey.chat_message_id is None


async def test_the_logging_transport_reports_failure_rather_than_success() -> None:
    """``PushSender``'s reasoning, applied here: a transport claiming delivery
    it did not perform turns 'nothing was sent' into 'the customer ignored us',
    and those are different faults."""
    sender = transport.LoggingSurveyTransport()
    result = await sender.post(
        transport.Dispatch(
            survey_id=uuid.uuid4(), token="t", chat_id=-100, agent_name="A"
        )
    )
    assert result.delivered is False
    assert result.chat_message_id is None
    assert result.reason == "no_telegram_bot"
    assert (
        await sender.refresh(
            transport.CounterUpdate(
                survey_id=uuid.uuid4(), chat_id=-100, chat_message_id=1, response_count=2
            )
        )
        is False
    )


async def test_the_shipped_transport_is_the_logging_one() -> None:
    assert isinstance(transport.get_transport(), transport.LoggingSurveyTransport)


async def test_nothing_is_refreshed_or_removed_while_nothing_was_posted(
    db, survey_factory
) -> None:
    from src.modules.surveys.service import SurveyService

    await survey_factory()
    service = SurveyService(db)
    assert await service.refresh_counters() == 0
    assert await service.remove_expired_messages() == 0


# ── Eligibility ────────────────────────────────────────────────────────────


async def test_an_unbound_group_is_refused_even_with_force(
    admin: AsyncClient, group_factory, surveys_on
) -> None:
    """Structural, never bypassable: there would be nobody to attribute the
    rating to. "Send to everyone now" means ignore the calendar, not invent an
    employee."""
    await surveys_on()
    group = await group_factory(agent=None)
    response = await admin.post(
        f"/api/v1/groups/{group.id}/survey", json={"force": True}
    )
    assert response.status_code == 409
    assert response.json()["error"]["detail"]["reason"] == "group_not_bound"


async def test_a_group_asked_too_recently_is_refused_and_force_clears_it(
    admin: AsyncClient, group_factory, surveys_on, days_ago
) -> None:
    await surveys_on()
    group = await group_factory(last_survey_at=days_ago(2))

    refused = await admin.post(f"/api/v1/groups/{group.id}/survey")
    assert refused.status_code == 409
    detail = refused.json()["error"]["detail"]
    assert detail["reason"] == "survey_suppressed"
    assert detail["days_since"] == 2
    assert detail["days_remaining"] == 8

    forced = await admin.post(
        f"/api/v1/groups/{group.id}/survey", json={"force": True}
    )
    assert forced.status_code == 201


async def test_a_second_request_returns_the_survey_already_queued(
    admin: AsyncClient, group_factory, surveys_on
) -> None:
    """Not an error: it is what stops one chat receiving two identical messages."""
    await surveys_on()
    group = await group_factory()
    first = (await admin.post(f"/api/v1/groups/{group.id}/survey")).json()
    second = (
        await admin.post(f"/api/v1/groups/{group.id}/survey", json={"force": True})
    ).json()
    assert second["reused"] is True
    assert second["survey_id"] == first["survey_id"]


async def test_an_expired_pending_survey_does_not_block_the_group_for_ever(
    admin: AsyncClient, group_factory, survey_factory, surveys_on, db
) -> None:
    """⚠️ A FIX, and the silent one.

    Nothing in the source ever moves a row out of ``pending``, and its reuse
    check looks only at the status. A survey queued while the transport was
    down therefore stays ``pending`` past its seven-day expiry, is counted as
    ``reused`` by every later broadcast, and **that group is never surveyed
    again** — permanently, with no error anywhere.
    """
    await surveys_on()
    group = await group_factory()
    await survey_factory(
        group=group,
        status="pending",
        expires_at=clock.now() - timedelta(days=1),
    )

    body = (
        await admin.post(f"/api/v1/groups/{group.id}/survey", json={"force": True})
    ).json()
    assert body["reused"] is False


# ── Broadcast ──────────────────────────────────────────────────────────────


async def test_the_broadcast_accounts_for_every_group(
    admin: AsyncClient, group_factory, surveys_on
) -> None:
    """⚠️ ``created + reused + len(skipped) == total_groups``, always.

    "8 sent" on its own sent an admin to the groups page to count rows and work
    out what happened to the other 992.
    """
    await surveys_on()
    await group_factory()
    await group_factory()
    await group_factory(agent=None)
    await group_factory(is_active=False)

    body = (await admin.post("/api/v1/groups/surveys/broadcast")).json()
    assert body["total_groups"] == 4
    assert body["created"] + body["reused"] + len(body["skipped"]) == 4
    assert body["created"] == 2
    reasons = sorted(item["reason"] for item in body["skipped"])
    assert reasons == ["group_inactive", "group_not_bound"]


async def test_the_broadcast_delivers_nothing(
    admin: AsyncClient, group_factory, surveys_on
) -> None:
    await surveys_on()
    await group_factory()
    body = (await admin.post("/api/v1/groups/surveys/broadcast")).json()
    assert body["created"] == 1
    assert body["delivered"] == 0


async def test_the_broadcast_ignores_the_window_by_default(
    admin: AsyncClient, group_factory, surveys_on, days_ago
) -> None:
    """The whole point of the button: when an admin says "send to everyone
    now", silently sending nothing because of a ten-day window is broken."""
    await surveys_on()
    await group_factory(last_survey_at=days_ago(1))
    body = (await admin.post("/api/v1/groups/surveys/broadcast")).json()
    assert body["created"] == 1


async def test_the_broadcast_honours_the_window_when_told_to(
    admin: AsyncClient, group_factory, surveys_on, days_ago
) -> None:
    await surveys_on()
    await group_factory(last_survey_at=days_ago(1))
    body = (
        await admin.post("/api/v1/groups/surveys/broadcast", json={"force": False})
    ).json()
    assert body["created"] == 0
    assert body["skipped"][0]["reason"] == "survey_suppressed"


async def test_broadcast_is_routed_before_the_uuid_segment(
    admin: AsyncClient, surveys_on
) -> None:
    """⚠️ ``/surveys/broadcast`` must be declared before ``/{group_id}/survey``
    or ``surveys`` is parsed as a UUID and answers 422."""
    await surveys_on()
    response = await admin.post("/api/v1/groups/surveys/broadcast")
    assert response.status_code != 422


async def test_only_an_admin_may_broadcast(manager: AsyncClient) -> None:
    assert (
        await manager.post("/api/v1/groups/surveys/broadcast")
    ).status_code == 403


# ── The cadence job ────────────────────────────────────────────────────────


async def test_the_cadence_job_does_nothing_while_either_switch_is_off(
    db, group_factory, set_setting
) -> None:
    """Two switches, both off by default. ``survey.enabled`` asks "may surveys
    exist"; ``survey.auto_send`` asks "may they go out unattended". Turning the
    first on must not start the second."""
    from src.modules.surveys.groups import GroupService

    await group_factory()
    service = GroupService(db)
    assert await service.run_cadence() == 0

    await set_setting(SettingKey.SURVEY_ENABLED, True)
    assert await GroupService(db).run_cadence() == 0

    await set_setting(SettingKey.SURVEY_AUTO_SEND, True)
    assert await GroupService(db).run_cadence() == 1


async def test_the_cadence_job_is_safe_to_run_twice(
    db, group_factory, set_setting
) -> None:
    """It stores "when did I last run" nowhere; the decision is recomputed from
    the data every time. A server that reboots twice a day, a lost schedule and
    an operator triggering it by hand all produce the same outcome."""
    from src.modules.surveys.groups import GroupService

    await set_setting(SettingKey.SURVEY_ENABLED, True)
    await set_setting(SettingKey.SURVEY_AUTO_SEND, True)
    await group_factory()

    assert await GroupService(db).run_cadence() == 1
    assert await GroupService(db).run_cadence() == 0


# ── The ratings page ───────────────────────────────────────────────────────


async def test_no_token_is_401(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/surveys")).status_code == 401
    assert (await client.get("/api/v1/surveys/red-flags")).status_code == 401


async def test_the_red_flag_registry_is_served_from_the_server(
    admin: AsyncClient,
) -> None:
    body = (await admin.get("/api/v1/surveys/red-flags")).json()
    assert len(body) == len(RED_FLAGS)
    assert body[0] == {"key": "rude", "label": "Qo'pol muomala qildi"}


async def test_the_average_is_withheld_below_the_threshold(
    admin: AsyncClient, response_factory, survey_factory
) -> None:
    """Null, never 0.0. One customer's bad morning must not become a score."""
    survey = await survey_factory()
    for _ in range(3):
        await response_factory(survey=survey, csat=2)

    body = (await admin.get("/api/v1/surveys")).json()
    assert body["count"] == 3
    assert body["ready"] is False
    assert body["average"] is None
    assert body["min_responses"] == 5


async def test_the_average_opens_on_the_threshold(
    admin: AsyncClient, response_factory, survey_factory
) -> None:
    survey = await survey_factory()
    for csat in (5, 5, 5, 4, 4):
        await response_factory(survey=survey, csat=csat)

    body = (await admin.get("/api/v1/surveys")).json()
    assert body["ready"] is True
    assert body["average"] == 4.6
    assert body["distribution"] == {"1": 0, "2": 0, "3": 0, "4": 2, "5": 3}


async def test_the_threshold_comes_from_settings_and_not_from_a_constant(
    admin: AsyncClient, response_factory, survey_factory, set_setting
) -> None:
    """⚠️ The defect the source's own comment records: an admin sets 8, the
    code keeps comparing against a hard-coded 5, and the setting "looks like it
    works" while affecting nothing."""
    await set_setting(SettingKey.SURVEY_MIN_RESPONSES, 8)
    survey = await survey_factory()
    for _ in range(5):
        await response_factory(survey=survey, csat=5)

    body = (await admin.get("/api/v1/surveys")).json()
    assert body["min_responses"] == 8
    assert body["ready"] is False


async def test_a_salesperson_gets_their_summary_and_never_the_rows(
    sales: AsyncClient, admin: AsyncClient, survey_factory, group_factory, response_factory
) -> None:
    """⚠️ The privacy rule, and it outranks the access setting.

    One Telegram group is one customer, so one visible rating row tells the
    salesperson exactly which customer wrote it — and the anonymity was
    promised to that customer in their own chat.
    """
    agent_id = sales.principal.agent_id  # type: ignore[attr-defined]
    group = await group_factory(agent=None)
    group.agent_id = agent_id
    group.bound_at = clock.now()
    survey = await survey_factory(group=group, agent_id=agent_id)
    for _ in range(5):
        await response_factory(survey=survey, csat=4, comment="Yaxshi")

    body = (await sales.get("/api/v1/surveys")).json()
    assert body["count"] == 5
    assert body["ready"] is True
    assert body["items"] == []
    assert body["items_withheld"] is True

    # The manager's view of the same data DOES carry the rows.
    seen = (await admin.get("/api/v1/surveys")).json()
    assert len(seen["items"]) == 5
    assert seen["items_withheld"] is False


async def test_hidden_closes_the_section_to_a_salesperson(
    sales: AsyncClient, set_setting
) -> None:
    await set_setting(SettingKey.ACCESS_SALES_CLIENT_RATING, "hidden")
    assert (await sales.get("/api/v1/surveys")).status_code == 403


async def test_a_salesperson_cannot_read_another_agents_ratings(
    sales: AsyncClient, agent_factory, survey_factory, group_factory, response_factory
) -> None:
    """The ``agent_id`` in the URL is ignored rather than merged: the permission
    admits and the SERVICE narrows (§11)."""
    other = await agent_factory()
    group = await group_factory(agent=other)
    survey = await survey_factory(group=group, agent_id=other.id)
    for _ in range(5):
        await response_factory(survey=survey, csat=5)

    body = (
        await sales.get("/api/v1/surveys", params={"agent_id": str(other.id)})
    ).json()
    assert body["count"] == 0


async def test_the_window_is_asia_tashkent_calendar_days(
    admin: AsyncClient, survey_factory, response_factory
) -> None:
    survey = await survey_factory()
    await response_factory(survey=survey, responded_at=clock.now())

    today = clock.today_tashkent().isoformat()
    body = (
        await admin.get(
            "/api/v1/surveys", params={"date_from": today, "date_to": today}
        )
    ).json()
    assert body["count"] == 1


async def test_a_backwards_range_names_the_offending_field(admin: AsyncClient) -> None:
    response = await admin.get(
        "/api/v1/surveys",
        params={"date_from": "2026-09-17", "date_to": "2026-09-01"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["detail"]["field"] == "date_from"


async def test_the_response_rate_is_null_when_nothing_was_sent(
    admin: AsyncClient, survey_factory
) -> None:
    """Null, not 0 %: there is no basis to compute, and 0 reads as "nobody
    answered". With the logging transport nothing is ever sent, so this is the
    permanent state of this figure in this deployment."""
    await survey_factory()
    body = (await admin.get("/api/v1/surveys")).json()
    assert body["response_rate"] is None


async def test_the_search_filters_the_headline_too(
    admin: AsyncClient, agent_factory, group_factory, survey_factory, response_factory
) -> None:
    """The server filters, because the average and the distribution have to
    describe what was found — filtering the rendered list would leave a
    headline about a different set of answers."""
    wanted = await agent_factory(full_name="Dilshod Akramov")
    other = await agent_factory(full_name="Zafar Tursunov")
    for agent, csat in ((wanted, 5), (other, 1)):
        group = await group_factory(agent=agent)
        await response_factory(
            survey=await survey_factory(group=group, agent_id=agent.id), csat=csat
        )

    body = (await admin.get("/api/v1/surveys", params={"search": "Dilshod"})).json()
    assert body["count"] == 1
    assert body["distribution"]["5"] == 1
    assert body["distribution"]["1"] == 0
