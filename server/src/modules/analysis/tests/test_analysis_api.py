"""The panel's analysis endpoints: RBAC, the four refusals, and the reads.

**No test here reaches a provider.** None of the four endpoints may contact a
vendor — the button writes a queued row and the worker does the work — so a
file that needed a stub client would be evidence that something in the request
path spends money.

The claims this file is responsible for:

* every endpoint answers 401 with no token, 403 for a role without the
  permission, and a service token is refused (CONVENTIONS.md §13, §11);
* ``analysis:run`` is refused for ``manager`` and allowed for ``admin`` — they
  both review calls, and only one of them may spend money doing it (§6.1);
* a call that is not this principal's is **404 and never 403**;
* each of §6.2's four 409s is reachable and carries its own code;
* a call the pipeline has never touched is a 200 with nulls, not a 404.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import get_args

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from src.core.config import get_settings
from src.core.deps import Principal, get_current_principal
from src.core.enums import (
    AiRole,
    AnalysisFailure,
    AnalysisStage,
    CallType,
    TranscriptQuality,
)
from src.core.permissions import Perm, Role
from src.core.settings_keys import SettingKey
from src.modules.analysis.entities import ScoreSummary
from src.modules.analysis.models import CallAnalysisStateModel
from src.modules.analysis.schemas import (
    SCORE_BAND_RANGE,
    AnalysisStageCounts,
    ScoreBand,
)
from src.modules.settings.models import AppSettingModel

pytestmark = pytest.mark.asyncio

LIST_URL = "/api/v1/analysis/calls"
STATUS_URL = "/api/v1/analysis/status"


# --- Harness ---------------------------------------------------------------


async def set_setting(db, key: str, value) -> None:
    """Change one seeded ``app_settings`` row, as the pipeline tests do it."""
    row = await db.get(AppSettingModel, key)
    row.value = value
    await db.flush()


async def enable_analysis(db) -> None:
    """``analysis.enabled`` is seeded **false**, so every run test flips it."""
    await set_setting(db, SettingKey.ANALYSIS_ENABLED, True)


def configure_ai(monkeypatch) -> None:
    """Give the ASR and LLM roles a key.

    There is no ``AI_GEMINI_API_KEY`` in the test environment — deliberately, so
    that nothing in the suite can reach a vendor — which makes
    ``ai_not_configured`` the *default* answer and this the explicit opt-out.
    """
    monkeypatch.setattr(
        get_settings(), "ai_gemini_api_key", SecretStr("test-key-not-a-real-one")
    )


async def state_of(db, call_id: uuid.UUID) -> CallAnalysisStateModel | None:
    """The pipeline's row for a call, or ``None``.

    Selected on ``call_id`` and not ``session.get``: the table carries the
    house ``UUIDMixin``, so its primary key is ``id`` and ``call_id`` is the
    unique index beside it.
    """
    return await db.scalar(
        sa.select(CallAnalysisStateModel).where(
            CallAnalysisStateModel.call_id == call_id
        )
    )


async def analysable_call(call_factory, **overrides):
    """An answered, external call with a recording — the §2.6 gate satisfied."""
    return await call_factory(
        has_audio=True,
        audio_missing_reason=None,
        call_type=overrides.pop("call_type", CallType.EXTERNAL),
        duration_sec=overrides.pop("duration_sec", 180),
        **overrides,
    )


async def own_scope_client(db, agent_id: uuid.UUID) -> AsyncClient:
    """A reviewer who holds ``analysis:read`` and **not** ``calls:read``.

    No role in the registry is shaped like this today: ``analysis:read`` goes to
    ``admin`` and ``manager``, both of whom also hold ``calls:read``, and
    ``sales`` holds neither (§6.1). The principal is built by hand — the shape
    ``test_exports_api`` already uses for a scoped token — because the scope
    narrowing in ``AnalysisService._scoped`` has to be *proved* rather than
    assumed correct on the day §12 Q1 is reversed and a grant makes it live.
    """
    from conftest import build_app

    application = build_app(db)
    principal = Principal(
        kind="user",
        id=uuid.uuid4(),
        role=str(Role.SALES),
        permissions=frozenset({Perm.ANALYSIS_READ}),
        agent_id=agent_id,
    )
    application.dependency_overrides[get_current_principal] = lambda: principal
    return AsyncClient(
        transport=ASGITransport(app=application), base_url="http://testserver"
    )


# --- RBAC: 401, 403, the service token, 404 --------------------------------


async def test_every_endpoint_is_401_without_a_token(client, call_factory) -> None:
    call = await call_factory()
    assert (await client.get(LIST_URL)).status_code == 401
    assert (await client.get(STATUS_URL)).status_code == 401
    assert (await client.get(f"{LIST_URL}/{call.id}")).status_code == 401
    assert (await client.post(f"{LIST_URL}/{call.id}", json={})).status_code == 401


async def test_sales_cannot_reach_any_analysis_endpoint(sales, call_factory) -> None:
    """§12 Q1: withheld on purpose, not by oversight.

    N41 promises an employee their own calls and their own phone's health. An
    unreviewed machine score of their own work is a different thing, and showing
    it before any human has calibrated the rubric invites a dispute the tool
    cannot win.
    """
    call = await call_factory()
    assert (await sales.get(LIST_URL)).status_code == 403
    assert (await sales.get(STATUS_URL)).status_code == 403
    assert (await sales.get(f"{LIST_URL}/{call.id}")).status_code == 403
    assert (await sales.post(f"{LIST_URL}/{call.id}", json={})).status_code == 403


async def test_a_service_token_is_refused_everywhere(
    service_token, call_factory
) -> None:
    """The export contract (SPEC §4.9) is frozen and analysis is not in it."""
    call = await call_factory()
    assert (await service_token.get(LIST_URL)).status_code == 403
    assert (await service_token.get(STATUS_URL)).status_code == 403
    assert (await service_token.get(f"{LIST_URL}/{call.id}")).status_code == 403
    assert (await service_token.post(f"{LIST_URL}/{call.id}", json={})).status_code == 403


async def test_a_call_that_does_not_exist_is_404_on_both_call_routes(admin) -> None:
    missing = uuid.uuid4()
    read = await admin.get(f"{LIST_URL}/{missing}")
    assert read.status_code == 404
    assert read.json()["error"]["code"] == "call_not_found"

    run = await admin.post(f"{LIST_URL}/{missing}", json={})
    assert run.status_code == 404
    assert run.json()["error"]["code"] == "call_not_found"


async def test_another_agents_call_is_404_not_403(
    db, call_factory, installation_factory, agent_factory
) -> None:
    """403 would confirm the row exists (§4.1 rule 2, §9).

    Driven through an own-scope reviewer because no registry role is narrowed
    here today; see :func:`own_scope_client`.
    """
    mine = await agent_factory()
    own = await call_factory(installation=await installation_factory(agent=mine))
    theirs = await call_factory()

    async with await own_scope_client(db, mine.id) as reviewer:
        assert (await reviewer.get(f"{LIST_URL}/{own.id}")).status_code == 200
        refused = await reviewer.get(f"{LIST_URL}/{theirs.id}")

    assert refused.status_code == 404
    assert refused.json()["error"]["code"] == "call_not_found"


async def test_an_own_scope_reviewers_list_holds_only_their_own_calls(
    db, call_factory, installation_factory, agent_factory, analysis_state_factory
) -> None:
    """The scope is the query's job, never a second permission check (§11)."""
    mine = await agent_factory()
    own = await call_factory(installation=await installation_factory(agent=mine))
    theirs = await call_factory()
    await analysis_state_factory(call=own)
    await analysis_state_factory(call=theirs)

    async with await own_scope_client(db, mine.id) as reviewer:
        body = (await reviewer.get(LIST_URL)).json()

    ids = {item["call"]["call_id"] for item in body["items"]}
    assert ids == {str(own.id)}


async def test_a_failure_row_of_another_agents_call_is_not_on_the_status_page(
    db, call_factory, installation_factory, agent_factory, analysis_state_factory
) -> None:
    """``recent_failures`` names a call, so it is scoped like the list."""
    mine = await agent_factory()
    own = await call_factory(installation=await installation_factory(agent=mine))
    theirs = await call_factory()
    for call in (own, theirs):
        await analysis_state_factory(
            call=call,
            stage=AnalysisStage.FAILED,
            failure_code=AnalysisFailure.PROVIDER_AUTH,
            last_run_at=datetime.now(UTC),
        )

    async with await own_scope_client(db, mine.id) as reviewer:
        body = (await reviewer.get(STATUS_URL)).json()

    assert [row["call_id"] for row in body["recent_failures"]] == [str(own.id)]


# --- analysis:run is admin only --------------------------------------------


async def test_a_manager_may_read_an_analysis_but_not_run_one(
    db, manager, call_factory, monkeypatch
) -> None:
    """A manager reviews calls; pressing the button spends money (§6.1).

    The same line the registry already draws at ``settings:write`` and
    ``installations:revoke``.
    """
    await enable_analysis(db)
    configure_ai(monkeypatch)
    call = await analysable_call(call_factory)

    assert (await manager.get(f"{LIST_URL}/{call.id}")).status_code == 200
    assert (await manager.get(LIST_URL)).status_code == 200
    assert (await manager.get(STATUS_URL)).status_code == 200

    refused = await manager.post(f"{LIST_URL}/{call.id}", json={})
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "forbidden"


async def test_an_admin_may_run_one(db, admin, call_factory, monkeypatch) -> None:
    await enable_analysis(db)
    configure_ai(monkeypatch)
    call = await analysable_call(call_factory)

    response = await admin.post(f"{LIST_URL}/{call.id}", json={})

    assert response.status_code == 200
    assert response.json()["stage"] == AnalysisStage.QUEUED.value
    # Committed, not merely answered: the worker reads this row from its own
    # session, so a state that only existed inside the request would be a
    # button that reports success and queues nothing.
    state = await state_of(db, call.id)
    assert state is not None
    assert state.stage is AnalysisStage.QUEUED


# --- The four refusals of §6.2 ---------------------------------------------


async def test_queueing_with_the_feature_off_is_analysis_disabled(
    admin, call_factory, monkeypatch
) -> None:
    """``analysis.enabled`` is seeded false, so this is the default answer."""
    configure_ai(monkeypatch)
    call = await analysable_call(call_factory)

    response = await admin.post(f"{LIST_URL}/{call.id}", json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "analysis_disabled"


async def test_a_call_with_no_audio_is_call_not_analysable(
    db, admin, call_factory, monkeypatch
) -> None:
    """§2.6's gate, with the rule that refused it named in the detail."""
    await enable_analysis(db)
    configure_ai(monkeypatch)
    call = await call_factory(has_audio=False, call_type=CallType.EXTERNAL)

    response = await admin.post(f"{LIST_URL}/{call.id}", json={})

    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "call_not_analysable"
    assert body["detail"]["rule"] == AnalysisFailure.NO_AUDIO.value


async def test_a_call_under_the_duration_floor_is_call_not_analysable(
    db, admin, call_factory, monkeypatch
) -> None:
    """The floor is one settings row, read in one place, so the button and the
    worker cannot disagree about it."""
    await enable_analysis(db)
    configure_ai(monkeypatch)
    call = await analysable_call(call_factory, duration_sec=5)

    response = await admin.post(f"{LIST_URL}/{call.id}", json={})

    assert response.status_code == 409
    assert (
        response.json()["error"]["detail"]["rule"]
        == AnalysisFailure.CALL_TOO_SHORT.value
    )


async def test_a_reached_cap_is_analysis_cost_cap_reached(
    db, admin, call_factory, monkeypatch
) -> None:
    """A cap of 0 means **stop**, not "no limit" (§4.5).

    The detail names which of the two caps tripped: raising the call cap and
    raising the money cap are different decisions taken by different people.
    """
    await enable_analysis(db)
    configure_ai(monkeypatch)
    await set_setting(db, SettingKey.ANALYSIS_MONTHLY_MAX_CALLS, 0)
    call = await analysable_call(call_factory)

    response = await admin.post(f"{LIST_URL}/{call.id}", json={})

    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "analysis_cost_cap_reached"
    assert body["detail"]["cap"] == "monthly_max_calls"


async def test_no_provider_key_is_ai_not_configured(db, admin, call_factory) -> None:
    """Refused before the row is queued, not discovered by the worker: a queue
    of calls that cannot run spends money the moment somebody fixes the key."""
    await enable_analysis(db)
    call = await analysable_call(call_factory)

    response = await admin.post(f"{LIST_URL}/{call.id}", json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ai_not_configured"
    assert await state_of(db, call.id) is None


# --- Queueing behaviour ----------------------------------------------------


async def test_pressing_the_button_twice_is_indistinguishable_from_once(
    db, admin, call_factory, monkeypatch
) -> None:
    """§5's idempotency shape, applied to a panel write."""
    await enable_analysis(db)
    configure_ai(monkeypatch)
    call = await analysable_call(call_factory)

    first = await admin.post(f"{LIST_URL}/{call.id}", json={})
    second = await admin.post(f"{LIST_URL}/{call.id}", json={})

    assert first.status_code == second.status_code == 200
    assert first.json()["queued_at"] is not None
    assert second.json()["stage"] == AnalysisStage.QUEUED.value


async def test_force_clears_the_transcript_and_the_score(
    db, admin, call_factory, transcript_factory, score_factory, monkeypatch
) -> None:
    """The only path in the product that spends money twice on one call."""
    await enable_analysis(db)
    configure_ai(monkeypatch)
    call = await analysable_call(call_factory)
    await transcript_factory(call=call)
    await score_factory(call=call)

    response = await admin.post(f"{LIST_URL}/{call.id}", json={"force": True})
    assert response.status_code == 200

    after = (await admin.get(f"{LIST_URL}/{call.id}")).json()
    assert after["transcript"] is None
    assert after["score"] is None
    assert after["state"]["stage"] == AnalysisStage.QUEUED.value


async def test_queueing_without_force_keeps_the_existing_work(
    db, admin, call_factory, transcript_factory, monkeypatch
) -> None:
    """A re-queue is not a re-spend: the transcript that exists is kept."""
    await enable_analysis(db)
    configure_ai(monkeypatch)
    call = await analysable_call(call_factory)
    await transcript_factory(call=call)

    assert (await admin.post(f"{LIST_URL}/{call.id}", json={})).status_code == 200

    after = (await admin.get(f"{LIST_URL}/{call.id}")).json()
    assert after["transcript"] is not None


# --- GET /analysis/calls/{call_id} -----------------------------------------


async def test_a_call_the_pipeline_never_touched_is_200_with_nulls(
    admin, call_factory
) -> None:
    """**Not 404.** The page has to tell "not analysed" from "no such call":
    one of them offers a button and the other does not (§7.4)."""
    call = await call_factory()

    response = await admin.get(f"{LIST_URL}/{call.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] is None
    assert body["transcript"] is None
    assert body["score"] is None
    assert body["enabled"] is False
    assert body["call"]["call_id"] == str(call.id)


async def test_the_detail_carries_the_calls_own_facts(
    admin, call_factory, installation_factory, agent_factory
) -> None:
    """§7.4: the reader is not sent to another page to learn which conversation
    they are looking at."""
    agent = await agent_factory(full_name="Dilnoza Karimova")
    call = await call_factory(
        installation=await installation_factory(agent=agent),
        remote_number="+998935554433",
        duration_sec=212,
    )

    header = (await admin.get(f"{LIST_URL}/{call.id}")).json()["call"]

    assert header["agent_name"] == "Dilnoza Karimova"
    assert header["remote_number"] == "+998935554433"
    assert header["duration_sec"] == 212
    assert header["started_at"] is not None


async def test_a_completed_call_returns_its_state_transcript_and_score(
    db, admin, call_factory, analysis_state_factory, transcript_factory, score_factory
) -> None:
    call = await analysable_call(call_factory)
    await analysis_state_factory(
        call=call,
        stage=AnalysisStage.COMPLETED,
        attempts=1,
        asr_calls=1,
        llm_calls=1,
        transcribed_at=datetime.now(UTC),
        scored_at=datetime.now(UTC),
    )
    await transcript_factory(call=call, word_count=412)
    await score_factory(
        call=call,
        overall_score=78,
        blocks={"script": 20, "communication": 18, "resolution": 22, "sales_skill": 18},
        transcript_quality=TranscriptQuality.HIGH,
        confidence_pct=84,
    )

    body = (await admin.get(f"{LIST_URL}/{call.id}")).json()

    assert body["state"]["stage"] == AnalysisStage.COMPLETED.value
    assert body["state"]["failure_code"] is None
    assert body["transcript"]["word_count"] == 412
    assert body["score"]["overall_score"] == 78
    assert body["score"]["blocks"]["script"] == 20
    assert body["score"]["rubric_version"] == "v1"


async def test_a_skipped_call_carries_the_reason_it_was_skipped(
    admin, call_factory, analysis_state_factory
) -> None:
    """``skipped`` is not a failure and the panel must not paint it as one
    (§2.4) — but it always says why."""
    call = await call_factory()
    await analysis_state_factory(
        call=call,
        stage=AnalysisStage.SKIPPED,
        failure_code=AnalysisFailure.CALL_TYPE_UNKNOWN,
    )

    state = (await admin.get(f"{LIST_URL}/{call.id}")).json()["state"]

    assert state["stage"] == AnalysisStage.SKIPPED.value
    assert state["failure_code"] == AnalysisFailure.CALL_TYPE_UNKNOWN.value


# --- GET /analysis/calls (the list, §7.3) -----------------------------------


async def test_the_list_holds_only_calls_the_pipeline_has_touched(
    admin, call_factory, analysis_state_factory
) -> None:
    touched = await call_factory()
    await call_factory()  # never queued; not a row on this page
    await analysis_state_factory(call=touched)

    body = (await admin.get(LIST_URL)).json()

    assert [item["call"]["call_id"] for item in body["items"]] == [str(touched.id)]


async def test_the_list_is_newest_conversation_first(
    admin, call_factory, analysis_state_factory
) -> None:
    """``started_at DESC`` — the order §7.3 names, which is the diary order and
    not the arrival order."""
    older = await call_factory(started_at=datetime(2026, 9, 1, 9, tzinfo=UTC))
    newer = await call_factory(started_at=datetime(2026, 9, 5, 9, tzinfo=UTC))
    for call in (older, newer):
        await analysis_state_factory(call=call)

    body = (await admin.get(LIST_URL)).json()

    assert [item["call"]["call_id"] for item in body["items"]] == [
        str(newer.id),
        str(older.id),
    ]


async def test_the_cursor_pages_without_skipping_or_repeating(
    admin, call_factory, analysis_state_factory
) -> None:
    """Keyset, not offset: the pipeline keeps finishing calls underneath."""
    for index in range(5):
        call = await call_factory(
            started_at=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(hours=index)
        )
        await analysis_state_factory(call=call)

    seen: list[str] = []
    cursor = None
    for _ in range(5):
        url = f"{LIST_URL}?limit=2" + (f"&cursor={cursor}" if cursor else "")
        body = (await admin.get(url)).json()
        seen.extend(item["call"]["call_id"] for item in body["items"])
        cursor = body["next_cursor"]
        if not body["has_more"]:
            break

    assert len(seen) == len(set(seen)) == 5


async def test_a_tampered_cursor_is_400_not_500(admin) -> None:
    assert (await admin.get(f"{LIST_URL}?cursor=not-a-cursor")).status_code == 400


async def test_with_total_counts_the_filtered_set(
    admin, call_factory, analysis_state_factory
) -> None:
    for _ in range(2):
        await analysis_state_factory(call=await call_factory())

    assert (await admin.get(f"{LIST_URL}?with_total=true")).json()["total"] == 2
    assert (await admin.get(LIST_URL)).json()["total"] is None


async def test_the_stage_filter_finds_failures(
    admin, call_factory, analysis_state_factory
) -> None:
    """A stage filter over scored rows only would answer "nothing found" on the
    one day it is asked — which is why the list is driven by the state row."""
    failed = await call_factory()
    await analysis_state_factory(
        call=failed,
        stage=AnalysisStage.FAILED,
        failure_code=AnalysisFailure.PROVIDER_RATE_LIMIT,
    )
    await analysis_state_factory(call=await call_factory())

    body = (await admin.get(f"{LIST_URL}?stage=failed")).json()

    assert [item["call"]["call_id"] for item in body["items"]] == [str(failed.id)]
    assert body["items"][0]["failure_code"] == AnalysisFailure.PROVIDER_RATE_LIMIT.value
    assert body["items"][0]["overall_score"] is None


async def test_the_score_band_filter_uses_the_bands_the_panel_colours_from(
    admin, call_factory, analysis_state_factory, score_factory
) -> None:
    excellent = await call_factory()
    poor = await call_factory()
    for call, score in ((excellent, 92), (poor, 31)):
        await analysis_state_factory(call=call, stage=AnalysisStage.COMPLETED)
        await score_factory(call=call, overall_score=score, blocks={"script": score})

    body = (await admin.get(f"{LIST_URL}?score_band=excellent")).json()

    assert [item["call"]["call_id"] for item in body["items"]] == [str(excellent.id)]
    assert body["items"][0]["overall_score"] == 92


async def test_an_unknown_score_band_is_422_not_an_empty_page(admin) -> None:
    """A silently empty page reads as "no calls scored well", which is a lie."""
    assert (await admin.get(f"{LIST_URL}?score_band=brilliant")).status_code == 422


async def test_the_needs_review_filter_is_the_review_queue(
    admin, call_factory, analysis_state_factory, score_factory
) -> None:
    flagged = await call_factory()
    clean = await call_factory()
    for call, needs_review in ((flagged, True), (clean, False)):
        await analysis_state_factory(call=call, stage=AnalysisStage.COMPLETED)
        await score_factory(call=call, needs_review=needs_review)

    body = (await admin.get(f"{LIST_URL}?needs_review=true")).json()

    assert [item["call"]["call_id"] for item in body["items"]] == [str(flagged.id)]


async def test_a_row_carries_its_red_flag_types_and_not_the_quotes(
    admin, call_factory, analysis_state_factory, score_factory
) -> None:
    """A list of fifty conversations is not a place to ship fifty customers'
    words; the chips only need to say what was flagged."""
    call = await call_factory()
    await analysis_state_factory(call=call, stage=AnalysisStage.COMPLETED)
    await score_factory(
        call=call,
        red_flags=[
            {"type": "shouting", "quote": "a customer's words", "counted": True},
            {"type": "shouting", "quote": "the second time", "counted": False},
            {"type": "badmouthing", "quote": "more words", "counted": True},
        ],
    )

    row = (await admin.get(LIST_URL)).json()["items"][0]

    assert row["red_flag_types"] == ["badmouthing", "shouting"]
    assert "quote" not in str(row)


async def test_the_agent_filter_narrows_the_list(
    admin, call_factory, installation_factory, agent_factory, analysis_state_factory
) -> None:
    wanted = await agent_factory()
    mine = await call_factory(installation=await installation_factory(agent=wanted))
    await analysis_state_factory(call=mine)
    await analysis_state_factory(call=await call_factory())

    body = (await admin.get(f"{LIST_URL}?agent_id={wanted.id}")).json()

    assert [item["call"]["call_id"] for item in body["items"]] == [str(mine.id)]


async def test_the_date_range_filters_on_the_business_day(
    admin, call_factory, analysis_state_factory
) -> None:
    """Asia/Tashkent calendar days against ``started_at``: a call made yesterday
    and uploaded today belongs to yesterday (D-08)."""
    inside = await call_factory(started_at=datetime(2026, 9, 4, 10, tzinfo=UTC))
    outside = await call_factory(started_at=datetime(2026, 8, 20, 10, tzinfo=UTC))
    for call in (inside, outside):
        await analysis_state_factory(call=call)

    body = (
        await admin.get(f"{LIST_URL}?date_from=2026-09-01&date_to=2026-09-30")
    ).json()

    assert [item["call"]["call_id"] for item in body["items"]] == [str(inside.id)]


# --- GET /analysis/status (§7.5) -------------------------------------------


async def test_the_status_counts_every_stage_including_the_empty_ones(
    admin, call_factory, analysis_state_factory
) -> None:
    """A chart that receives only the stages something is in draws a quiet day
    as a missing key the panel has to default itself."""
    await analysis_state_factory(call=await call_factory())
    await analysis_state_factory(
        call=await call_factory(), stage=AnalysisStage.COMPLETED
    )

    body = (await admin.get(STATUS_URL)).json()

    assert body["stages"] == {
        "queued": 1,
        "transcribing": 0,
        "scoring": 0,
        "completed": 1,
        "skipped": 0,
        "failed": 0,
    }
    assert body["enabled"] is False


async def test_the_status_groups_skips_by_reason(
    admin, call_factory, analysis_state_factory
) -> None:
    """"412 calls are waiting on the line directory" has to be visible rather
    than silent (§2.6)."""
    for _ in range(2):
        await analysis_state_factory(
            call=await call_factory(),
            stage=AnalysisStage.SKIPPED,
            failure_code=AnalysisFailure.CALL_TYPE_UNKNOWN,
        )
    await analysis_state_factory(
        call=await call_factory(),
        stage=AnalysisStage.SKIPPED,
        failure_code=AnalysisFailure.CALL_TOO_SHORT,
    )

    rows = (await admin.get(STATUS_URL)).json()["not_analysable"]

    assert rows[0] == {"code": AnalysisFailure.CALL_TYPE_UNKNOWN.value, "calls": 2}
    assert {row["code"] for row in rows} == {
        AnalysisFailure.CALL_TYPE_UNKNOWN.value,
        AnalysisFailure.CALL_TOO_SHORT.value,
    }


async def test_waiting_retry_is_separate_from_failed(
    db, admin, call_factory, analysis_state_factory
) -> None:
    """One of them needs a person and the other does not (§6.2).

    Getting that membership wrong is how 885 rate-limited calls stayed
    permanently failed after the quota they were waiting on had reset.
    """
    await analysis_state_factory(
        call=await call_factory(),
        stage=AnalysisStage.FAILED,
        failure_code=AnalysisFailure.PROVIDER_RATE_LIMIT,
        last_run_at=datetime.now(UTC),
    )
    await analysis_state_factory(
        call=await call_factory(),
        stage=AnalysisStage.FAILED,
        failure_code=AnalysisFailure.PROVIDER_AUTH,
        last_run_at=datetime.now(UTC),
    )

    body = (await admin.get(STATUS_URL)).json()

    assert body["stages"]["failed"] == 2
    assert body["waiting_retry"] == 1


async def test_the_status_shows_a_live_cooldown_and_hides_an_expired_one(
    admin, provider_cooldown_factory
) -> None:
    """When the queue goes quiet, "which role is sitting out and for how long"
    is the first thing an operator needs (§1.3)."""
    now = datetime.now(UTC)
    await provider_cooldown_factory(
        role=AiRole.ASR,
        started_at=now - timedelta(minutes=5),
        until_at=now + timedelta(minutes=25),
        reason_code=AnalysisFailure.PROVIDER_RATE_LIMIT,
    )
    await provider_cooldown_factory(
        role=AiRole.LLM,
        started_at=now - timedelta(hours=2),
        until_at=now - timedelta(hours=1),
    )

    cooldowns = (await admin.get(STATUS_URL)).json()["cooldowns"]

    assert [row["role"] for row in cooldowns] == [AiRole.ASR.value]
    assert 0 < cooldowns[0]["seconds_left"] <= 25 * 60
    assert cooldowns[0]["reason_code"] == AnalysisFailure.PROVIDER_RATE_LIMIT.value


async def test_the_month_reports_measured_units_and_says_it_is_not_priced(
    admin, call_factory, transcript_factory, score_factory, analysis_state_factory
) -> None:
    """§11.1: a cost of zero because nobody typed a vendor price is not a
    feature that is free, and ``priced: false`` is what stops the panel saying
    it is."""
    call = await analysable_call(call_factory)
    await analysis_state_factory(call=call, stage=AnalysisStage.COMPLETED)
    await transcript_factory(call=call, audio_duration_ms=180_000)
    await score_factory(call=call, prompt_tokens=7_200, completion_tokens=900)

    month = (await admin.get(STATUS_URL)).json()["month"]

    assert month["audio_minutes"] == 3
    assert month["prompt_tokens"] == 7_200
    assert month["completion_tokens"] == 900
    assert month["cost_micro_usd"] == 0
    assert month["priced"] is False
    assert month["cap_calls"] == 3000


async def test_the_month_reports_priced_once_a_vendor_price_is_entered(
    db, admin
) -> None:
    await set_setting(db, SettingKey.ANALYSIS_PRICE_ASR_MICRO_USD_PER_MINUTE, 6_000)

    assert (await admin.get(STATUS_URL)).json()["month"]["priced"] is True


async def test_recent_failures_are_newest_attempt_first_and_capped(
    admin, call_factory, analysis_state_factory
) -> None:
    """Capped server-side: a page that answers "what broke" needs the last few,
    not a history (§6.2)."""
    now = datetime.now(UTC)
    for index in range(22):
        await analysis_state_factory(
            call=await call_factory(),
            stage=AnalysisStage.FAILED,
            failure_code=AnalysisFailure.PROVIDER_NETWORK,
            last_run_at=now - timedelta(minutes=index),
        )

    rows = (await admin.get(STATUS_URL)).json()["recent_failures"]

    assert len(rows) == 20
    stamps = [row["last_run_at"] for row in rows]
    assert stamps == sorted(stamps, reverse=True)
    assert rows[0]["code"] == AnalysisFailure.PROVIDER_NETWORK.value
    assert rows[0]["started_at"] is not None


# --- The two derived vocabularies, pinned to their source -------------------


async def test_the_stage_counts_cover_every_analysis_stage() -> None:
    """A stage added to the enum with no field here would vanish from the queue
    page, and nothing else would notice."""
    assert set(AnalysisStageCounts.model_fields) == {
        stage.value for stage in AnalysisStage
    }


async def test_the_score_band_filter_offers_exactly_the_bands_that_exist() -> None:
    """The wire vocabulary and the derived ranges are one set.

    ``ScoreBand`` is hand-written (a Literal cannot be computed) and
    ``SCORE_BAND_RANGE`` is derived from ``ScoreSummary.grade``. A fifth grade
    added to that property would widen the ranges and leave the filter unable
    to ask for it — silently, which is the failure this pins.
    """
    assert set(get_args(ScoreBand)) == set(SCORE_BAND_RANGE)


async def test_every_score_band_range_agrees_with_the_grade_it_is_derived_from() -> None:
    """``SCORE_BAND_RANGE`` is computed from ``ScoreSummary.grade`` so the SQL
    filter and the colour the panel paints cannot say different things about
    one number. This is that claim, asserted rather than trusted — over every
    score a call can have, because the boundaries are where it would break.
    """
    for score in range(101):
        grade = ScoreSummary(
            overall=score,
            blocks={},
            red_flag_count=0,
            confidence_pct=0,
            needs_review=False,
        ).grade
        low, high = SCORE_BAND_RANGE[grade]
        assert low <= score <= high, score
        # Exactly one band claims it: overlapping ranges would make a band
        # filter return rows the panel colours as a different band.
        assert sum(lo <= score <= hi for lo, hi in SCORE_BAND_RANGE.values()) == 1, score
