"""The six analytics reports: the arithmetic, the empty case, the scope and the
Asia/Tashkent boundaries (CONVENTIONS.md §13, §2.1).

§13 requires **every aggregate in a ``core/reads.py`` module to have a test over
factory-built data**, and that rule is doing real work here: this module reads
three other modules' columns directly, so a rename in ``calls`` or
``call_scores`` has to fail in CI rather than in a dashboard nobody double-checks.

Expected values are computed in the test from the rows the test created, never
read back from the database — a test that asserts what the query returned
passes whatever the query does.

Every window below is explicit. The default is "the last 30 days ending today",
which would make these assertions depend on the day they are run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio

from src.core.clock import TASHKENT
from src.core.deps import Principal
from src.core.enums import CallType
from src.core.permissions import Perm
from src.modules.analysis.rubric_default import DEFAULT_RUBRIC
from src.modules.analysis.rubric_service import RubricService
from src.modules.analytics.schemas import AnalyticsFilters, CallTypeCountsOut
from src.modules.analytics.service import BLOCK_MAX_BY_KEY, AnalyticsService

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/analytics"

#: The six reports, as (path, the key that proves the body is the right shape).
REPORTS: tuple[tuple[str, str], ...] = (
    ("/overview", "call_types"),
    ("/timeseries", "points"),
    ("/agents", "items"),
    ("/blocks", "items"),
    ("/red-flags", "items"),
    ("/distribution", "items"),
)

#: A window in the past, so nothing a test creates can drift into or out of it
#: because of the wall clock.
WINDOW_FROM = date(2026, 6, 1)
WINDOW_TO = date(2026, 6, 30)
WINDOW = {"date_from": WINDOW_FROM.isoformat(), "date_to": WINDOW_TO.isoformat()}


def at(day: date, hour: int = 12, minute: int = 0) -> datetime:
    """An instant on a Tashkent calendar day — the zone every window is in."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TASHKENT)


@pytest.fixture
def scored_call(call_factory, score_factory):
    """One scored call, with everything the reports read under the test's control.

    ``overall_score`` and ``blocks`` are set independently on purpose: no report
    here reads both, and forcing the two to agree would mean every histogram
    test also choosing four block values it does not care about.
    """

    async def _create(
        *,
        installation,
        started_at: datetime,
        overall_score: int = 80,
        duration_sec: int = 120,
        blocks: dict | None = None,
        red_flags: list | None = None,
        call_type: CallType = CallType.EXTERNAL,
    ):
        call = await call_factory(
            installation=installation,
            started_at=started_at,
            duration_sec=duration_sec,
            call_type=call_type,
        )
        return await score_factory(
            call=call,
            overall_score=overall_score,
            blocks=blocks if blocks is not None else {"script": 20},
            red_flags=red_flags or [],
            scored_at=started_at + timedelta(minutes=5),
        )

    return _create


@pytest_asyncio.fixture
async def one_agent(installation_factory):
    """An installation, and therefore an agent, for the single-agent tests."""
    return await installation_factory()


def filters(**overrides) -> AnalyticsFilters:
    """The window every service-level test works in."""
    return AnalyticsFilters(
        date_from=overrides.pop("date_from", WINDOW_FROM),
        date_to=overrides.pop("date_to", WINDOW_TO),
        **overrides,
    )


# --- The closed enum the breakdown promises to cover --------------------------


async def test_the_call_type_breakdown_has_a_field_per_enum_value() -> None:
    """``CallTypeCountsOut`` is a fixed object, not a map, so a type with
    nothing in it is a visible zero rather than an absent key the panel
    defaults for itself. This is what keeps the two lists from drifting: a new
    ``CallType`` value fails here rather than silently disappearing from the
    row that explains the headline."""
    assert set(CallTypeCountsOut.model_fields) == {
        call_type.value for call_type in CallType
    }


# --- RBAC (T20's three cases that apply to a report) --------------------------


@pytest.mark.parametrize("path,key", REPORTS)
async def test_every_report_needs_a_token(client, path: str, key: str) -> None:
    response = await client.get(f"{BASE}{path}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("path,key", REPORTS)
async def test_a_salesperson_is_refused(sales, path: str, key: str) -> None:
    """``sales`` holds neither ``analysis:read`` nor ``analysis:run`` (§12 Q1).

    403 and not an empty report: an employee must not be able to tell from the
    response whether the feature exists and returned nothing.
    """
    response = await sales.get(f"{BASE}{path}")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize("path,key", REPORTS)
async def test_a_manager_may_read_every_report(manager, path: str, key: str) -> None:
    response = await manager.get(f"{BASE}{path}", params=WINDOW)
    assert response.status_code == 200, response.text
    assert key in response.json()


@pytest.mark.parametrize("path,key", REPORTS)
async def test_an_empty_window_is_an_empty_report_not_an_error(
    admin, path: str, key: str
) -> None:
    """The state a live BonviCall is in today: ``analysis.enabled`` is seeded
    false, so nothing has been scored and every one of these is opened against
    no rows at all. Each must answer 200 with zeros."""
    response = await admin.get(f"{BASE}{path}", params=WINDOW)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["date_from"] == WINDOW["date_from"]
    assert body["date_to"] == WINDOW["date_to"]


async def test_the_empty_overview_says_nothing_rather_than_zero_score(
    admin,
) -> None:
    """A null average and a zero average are different statements: nobody scored
    0, there was nothing to score."""
    body = (await admin.get(f"{BASE}/overview", params=WINDOW)).json()
    assert body["calls"]["value"] == 0
    assert body["ai_score"]["value"] is None
    assert body["ai_score"]["delta_percent"] is None
    assert body["avg_duration_sec"] == 0
    assert body["call_types"] == {"internal": 0, "external": 0, "unknown": 0}
    assert body["calls_total"] == 0


async def test_the_empty_histogram_still_has_ten_bands(admin) -> None:
    """A chart drawn from an empty list has no axis at all, which reads as a
    broken page rather than as a quiet month."""
    body = (await admin.get(f"{BASE}/distribution", params=WINDOW)).json()
    assert len(body["items"]) == 10
    assert body["scored_calls"] == 0
    assert [item["calls"] for item in body["items"]] == [0] * 10


# --- 1. The KPI cards ---------------------------------------------------------


async def test_overview_counts_scored_calls_and_averages_their_scores(
    admin, one_agent, scored_call
) -> None:
    for score, duration in ((60, 100), (70, 200), (81, 301)):
        await scored_call(
            installation=one_agent,
            started_at=at(date(2026, 6, 10)),
            overall_score=score,
            duration_sec=duration,
        )

    body = (await admin.get(f"{BASE}/overview", params=WINDOW)).json()

    assert body["calls"]["value"] == 3
    # (60 + 70 + 81) / 3 = 70.333…
    assert body["ai_score"]["value"] == "70.3"
    # (100 + 200 + 301) / 3 = 200.333… -> 200, and 200.5 would be 201: int()
    # truncates and biased every one of these downward.
    assert body["avg_duration_sec"] == 200


async def test_overview_counts_calls_with_a_red_flag_not_flags_found(
    admin, one_agent, scored_call
) -> None:
    """One call carrying two breaches is one flagged call."""
    await scored_call(
        installation=one_agent,
        started_at=at(date(2026, 6, 10)),
        red_flags=[
            {"type": "shouting", "severity": "high"},
            {"type": "badmouthing", "severity": "high"},
        ],
    )
    await scored_call(installation=one_agent, started_at=at(date(2026, 6, 11)))

    body = (await admin.get(f"{BASE}/overview", params=WINDOW)).json()
    assert body["red_flags"]["value"] == 1
    assert body["calls"]["value"] == 2


async def test_overview_breaks_every_call_down_by_type_scored_or_not(
    admin, one_agent, scored_call, call_factory
) -> None:
    """The row that stops "6" in a month of thousands reading as lost data.

    Measured in BonviZvonki: 72 scored against 22,026 calls for one period.
    """
    await scored_call(
        installation=one_agent,
        started_at=at(date(2026, 6, 10)),
        call_type=CallType.EXTERNAL,
    )
    # Never scored: internal conversations are not candidates (§2.6), and an
    # unclassified call is waiting on the line directory.
    for call_type in (CallType.INTERNAL, CallType.INTERNAL, CallType.UNKNOWN):
        await call_factory(
            installation=one_agent,
            started_at=at(date(2026, 6, 12)),
            call_type=call_type,
        )

    body = (await admin.get(f"{BASE}/overview", params=WINDOW)).json()
    assert body["calls"]["value"] == 1
    assert body["call_types"] == {"internal": 2, "external": 1, "unknown": 1}
    assert body["calls_total"] == 4


async def test_overview_compares_against_the_previous_window_of_equal_length(
    admin, one_agent, scored_call
) -> None:
    """Two calls this week against one last week is +100 %, and the window the
    comparison used is named in the response rather than left to be guessed."""
    # The window under test: 8-14 June. The previous one is therefore 1-7 June.
    for day in (8, 9):
        await scored_call(installation=one_agent, started_at=at(date(2026, 6, day)))
    await scored_call(installation=one_agent, started_at=at(date(2026, 6, 3)))
    # Outside both windows: it must move neither number.
    await scored_call(installation=one_agent, started_at=at(date(2026, 5, 20)))

    body = (
        await admin.get(
            f"{BASE}/overview",
            params={"date_from": "2026-06-08", "date_to": "2026-06-14"},
        )
    ).json()

    assert body["calls"]["value"] == 2
    assert body["calls"]["delta_percent"] == "100.0"
    assert body["compared_with"] == {
        "date_from": "2026-06-01",
        "date_to": "2026-06-07",
    }


async def test_a_filter_is_carried_into_the_previous_window(
    admin, installation_factory, scored_call
) -> None:
    """BonviZvonki built the previous filter by hand, dropped three fields, and
    compared a filtered period against an unfiltered one — "+25.6 %" where
    nothing had moved."""
    mine = await installation_factory()
    theirs = await installation_factory()

    await scored_call(installation=mine, started_at=at(date(2026, 6, 9)))
    await scored_call(installation=mine, started_at=at(date(2026, 6, 3)))
    # The other agent worked far harder last week. Filtered out, they must not
    # appear in the denominator of my delta.
    for day in (2, 3, 4, 5):
        await scored_call(installation=theirs, started_at=at(date(2026, 6, day)))

    body = (
        await admin.get(
            f"{BASE}/overview",
            params={
                "date_from": "2026-06-08",
                "date_to": "2026-06-14",
                "agent_id": str(mine.agent_id),
            },
        )
    ).json()

    assert body["calls"]["value"] == 1
    # 1 against 1, not 1 against 5.
    assert body["calls"]["delta_percent"] == "0.0"


async def test_the_call_type_filter_narrows_every_panel(
    admin, one_agent, scored_call
) -> None:
    await scored_call(
        installation=one_agent,
        started_at=at(date(2026, 6, 10)),
        call_type=CallType.EXTERNAL,
        overall_score=90,
    )
    await scored_call(
        installation=one_agent,
        started_at=at(date(2026, 6, 10)),
        call_type=CallType.UNKNOWN,
        overall_score=40,
    )

    body = (
        await admin.get(f"{BASE}/overview", params={**WINDOW, "call_type": "external"})
    ).json()
    assert body["calls"]["value"] == 1
    assert body["ai_score"]["value"] == "90.0"


# --- The Asia/Tashkent boundary ----------------------------------------------


async def test_the_window_is_inclusive_at_both_ends_in_tashkent(
    admin, one_agent, scored_call
) -> None:
    """A business date is an Asia/Tashkent calendar day (D-08).

    The four rows are the corners: the first and last instant that belong to the
    window, and the last and first that do not. BonviZvonki's filter was
    ``started_at <= date_to``, which dropped the whole of the final day until an
    ``_inclusive_end`` helper was added to three separate endpoints.
    """
    inside_first = at(date(2026, 6, 10), hour=0, minute=0)
    inside_last = at(date(2026, 6, 12), hour=23, minute=59)
    before = at(date(2026, 6, 9), hour=23, minute=59)
    after = at(date(2026, 6, 13), hour=0, minute=0)

    for moment in (inside_first, inside_last, before, after):
        await scored_call(installation=one_agent, started_at=moment)

    body = (
        await admin.get(
            f"{BASE}/overview",
            params={"date_from": "2026-06-10", "date_to": "2026-06-12"},
        )
    ).json()
    assert body["calls"]["value"] == 2


async def test_a_call_after_midnight_belongs_to_its_tashkent_day(
    admin, one_agent, scored_call
) -> None:
    """02:00 in Tashkent is 21:00 the previous day in UTC.

    ``date_trunc('day', started_at)`` runs in the session's zone — UTC here — so
    without ``timezone(<zone>, …)`` first, this call is drawn on the 9th and the
    day boundary of the chart disagrees with the day boundary of the filter
    above it.
    """
    await scored_call(
        installation=one_agent, started_at=at(date(2026, 6, 10), hour=2)
    )
    await scored_call(
        installation=one_agent, started_at=at(date(2026, 6, 10), hour=23)
    )

    body = (
        await admin.get(
            f"{BASE}/timeseries",
            params={"date_from": "2026-06-10", "date_to": "2026-06-10"},
        )
    ).json()

    assert body["points"] == [
        {"period_start": "2026-06-10", "calls": 2, "ai_score": "80.0"}
    ]


# --- 2. The trend -------------------------------------------------------------


async def test_the_trend_fills_every_day_in_the_window(
    admin, one_agent, scored_call
) -> None:
    """A categorical axis draws five points the same way over a week and over a
    quarter, so omitting the quiet days makes the period filter look broken."""
    await scored_call(installation=one_agent, started_at=at(date(2026, 6, 10)))

    body = (
        await admin.get(
            f"{BASE}/timeseries",
            params={"date_from": "2026-06-08", "date_to": "2026-06-14"},
        )
    ).json()

    assert body["filled"] is True
    assert [point["period_start"] for point in body["points"]] == [
        f"2026-06-{day:02d}" for day in range(8, 15)
    ]
    quiet = [point for point in body["points"] if point["period_start"] != "2026-06-10"]
    # Zero calls and NO score: a day nobody worked is a gap in the line, not a
    # zero that drags the average down.
    assert all(point["calls"] == 0 and point["ai_score"] is None for point in quiet)


async def test_weekly_buckets_start_on_monday_as_postgres_does(
    admin, one_agent, scored_call
) -> None:
    """If Python and PostgreSQL disagree about where a week begins, the filled
    key lands beside the real one and the real value disappears."""
    # Wednesday 10 June 2026 and Thursday 18 June 2026: two different weeks.
    await scored_call(installation=one_agent, started_at=at(date(2026, 6, 10)))
    await scored_call(installation=one_agent, started_at=at(date(2026, 6, 18)))

    body = (
        await admin.get(
            f"{BASE}/timeseries",
            params={
                "date_from": "2026-06-08",
                "date_to": "2026-06-21",
                "bucket": "week",
            },
        )
    ).json()

    assert [point["period_start"] for point in body["points"]] == [
        "2026-06-08",
        "2026-06-15",
    ]
    assert [point["calls"] for point in body["points"]] == [1, 1]


async def test_monthly_buckets_start_on_the_first(
    admin, one_agent, scored_call
) -> None:
    await scored_call(installation=one_agent, started_at=at(date(2026, 6, 10)))
    await scored_call(installation=one_agent, started_at=at(date(2026, 7, 2)))

    body = (
        await admin.get(
            f"{BASE}/timeseries",
            params={
                "date_from": "2026-06-05",
                "date_to": "2026-07-20",
                "bucket": "month",
            },
        )
    ).json()

    assert [point["period_start"] for point in body["points"]] == ["2026-06-01", "2026-07-01"]


async def test_an_unknown_bucket_is_refused_by_the_schema(admin) -> None:
    response = await admin.get(f"{BASE}/timeseries", params={**WINDOW, "bucket": "hour"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- 3. The leaderboard -------------------------------------------------------


async def test_agents_are_ranked_by_average_score(
    admin, installation_factory, agent_factory, scored_call
) -> None:
    best = await installation_factory(agent=await agent_factory(full_name="Best"))
    worst = await installation_factory(agent=await agent_factory(full_name="Worst"))

    await scored_call(installation=best, started_at=at(date(2026, 6, 10)), overall_score=90)
    await scored_call(installation=best, started_at=at(date(2026, 6, 11)), overall_score=80)
    await scored_call(installation=worst, started_at=at(date(2026, 6, 10)), overall_score=40)

    body = (await admin.get(f"{BASE}/agents", params=WINDOW)).json()

    assert body["total"] == 2
    first, second = body["items"]
    assert (first["agent_name"], first["rank"], first["ai_score"], first["calls"]) == (
        "Best",
        1,
        "85.0",
        2,
    )
    assert (second["agent_name"], second["rank"], second["ai_score"]) == (
        "Worst",
        2,
        "40.0",
    )


async def test_the_ranking_is_stable_when_two_agents_tie(
    admin, installation_factory, agent_factory, scored_call
) -> None:
    """Ordering on the average alone leaves a tie in whatever order the plan
    produced, so a rank flips between two reads and "places gained" invents
    movement that did not happen."""
    anvar = await installation_factory(agent=await agent_factory(full_name="Anvar"))
    zafar = await installation_factory(agent=await agent_factory(full_name="Zafar"))
    for installation in (zafar, anvar):
        await scored_call(
            installation=installation, started_at=at(date(2026, 6, 10)), overall_score=70
        )

    names = []
    for _ in range(2):
        body = (await admin.get(f"{BASE}/agents", params=WINDOW)).json()
        names.append([row["agent_name"] for row in body["items"]])
    assert names[0] == names[1] == ["Anvar", "Zafar"]


async def test_places_gained_against_the_previous_window(
    admin, installation_factory, agent_factory, scored_call
) -> None:
    climber = await installation_factory(agent=await agent_factory(full_name="Climber"))
    faller = await installation_factory(agent=await agent_factory(full_name="Faller"))

    # Last week (1-7 June): Faller first.
    await scored_call(installation=faller, started_at=at(date(2026, 6, 3)), overall_score=95)
    await scored_call(installation=climber, started_at=at(date(2026, 6, 3)), overall_score=50)
    # This week (8-14 June): the order is reversed.
    await scored_call(installation=climber, started_at=at(date(2026, 6, 9)), overall_score=92)
    await scored_call(installation=faller, started_at=at(date(2026, 6, 9)), overall_score=60)

    body = (
        await admin.get(
            f"{BASE}/agents",
            params={"date_from": "2026-06-08", "date_to": "2026-06-14"},
        )
    ).json()

    by_name = {row["agent_name"]: row for row in body["items"]}
    assert by_name["Climber"]["rank"] == 1
    # Positive means moved up: second place to first.
    assert by_name["Climber"]["rank_delta"] == 1
    assert by_name["Faller"]["rank_delta"] == -1


async def test_an_agent_new_to_the_period_has_no_place_to_have_gained(
    admin, one_agent, scored_call
) -> None:
    await scored_call(installation=one_agent, started_at=at(date(2026, 6, 9)))

    body = (
        await admin.get(
            f"{BASE}/agents",
            params={"date_from": "2026-06-08", "date_to": "2026-06-14"},
        )
    ).json()
    assert body["items"][0]["rank_delta"] is None


# --- 4. The rubric blocks -----------------------------------------------------


async def test_blocks_are_averaged_and_scaled_against_the_rubric(
    admin, one_agent, scored_call
) -> None:
    await scored_call(
        installation=one_agent,
        started_at=at(date(2026, 6, 10)),
        blocks={"script": 20, "communication": 10},
    )
    await scored_call(
        installation=one_agent,
        started_at=at(date(2026, 6, 11)),
        blocks={"script": 10, "communication": 20},
    )

    body = (await admin.get(f"{BASE}/blocks", params=WINDOW)).json()
    by_block = {row["block"]: row for row in body["items"]}

    assert by_block["script"]["score"] == "15.0"
    assert by_block["script"]["scored_calls"] == 2
    # The maximum comes from the rubric, never from a second constant: the two
    # were once typed separately, diverged 25 against 15, and the radar chart
    # drew 106 % in front of a manager.
    script_max = BLOCK_MAX_BY_KEY["script"]
    assert by_block["script"]["max"] == script_max
    assert by_block["script"]["percent"] == str(
        round(15 / script_max * 100, 1)
    )


async def test_the_block_maximum_follows_the_published_rubric(
    admin, db, one_agent, scored_call
) -> None:
    """An edited rubric moves the denominator, or the radar bar passes 100 %.

    The maxima were a constant in this module until ``rubrics`` became a table
    (migration 012). An admin who moves points between blocks would then leave
    the chart dividing by a number nobody scores against any more — which is
    the defect BonviZvonki shipped, a bar drawn at 106 %.
    """
    await scored_call(
        installation=one_agent,
        started_at=at(date(2026, 6, 10)),
        blocks={"script": 20, "communication": 10},
    )

    before = (await admin.get(f"{BASE}/blocks", params=WINDOW)).json()
    assert {row["block"]: row["max"] for row in before["items"]}[
        "script"
    ] == BLOCK_MAX_BY_KEY["script"]

    # Move five points from `script` to `communication`. The blocks still total
    # 100, so the rubric is publishable and the scores already stored are not
    # re-based — only what they are measured against changes.
    moved = []
    for block in DEFAULT_RUBRIC["blocks"]:
        edited = dict(block)
        shift = {"script": -5, "communication": +5}.get(str(edited["key"]), 0)
        if shift:
            edited["max"] = int(edited["max"]) + shift
            # A block's criteria must still add up to its maximum, so the five
            # points move on a criterion too — the widest one, which is the only
            # one guaranteed to survive losing them.
            criteria = [dict(criterion) for criterion in edited["criteria"]]
            widest = max(criteria, key=lambda criterion: int(criterion["points"]))
            widest["points"] = int(widest["points"]) + shift
            edited["criteria"] = criteria
        moved.append(edited)
    await RubricService(db).publish(
        name="Ko'chirilgan ballar",
        blocks=moved,
        red_flags=list(DEFAULT_RUBRIC["red_flags"]),
    )

    after = (await admin.get(f"{BASE}/blocks", params=WINDOW)).json()
    by_block = {row["block"]: row for row in after["items"]}
    script_max = BLOCK_MAX_BY_KEY["script"] - 5
    assert by_block["script"]["max"] == script_max
    assert by_block["script"]["percent"] == str(round(20 / script_max * 100, 1))


async def test_the_blocks_keep_the_rubric_order(
    admin, one_agent, scored_call
) -> None:
    """The radar chart's axes must not move between two reads of one page."""
    await scored_call(
        installation=one_agent,
        started_at=at(date(2026, 6, 10)),
        blocks={key: 5 for key in BLOCK_MAX_BY_KEY},
    )

    body = (await admin.get(f"{BASE}/blocks", params=WINDOW)).json()
    assert [row["block"] for row in body["items"]] == list(BLOCK_MAX_BY_KEY)


async def test_metadata_and_junk_never_become_a_fifth_block(
    admin, db, one_agent, scored_call
) -> None:
    """``_meta`` would appear as a block, and a non-numeric value used to raise
    ``TypeError`` inside the endpoint and answer 500.

    The document is replaced after the row is written because ``score_factory``
    derives ``overall_score`` from the block values and cannot express one that
    is not a number — which is the point: this shape comes from a rubric
    version nobody writes any more, not from today's writer.
    """
    score = await scored_call(
        installation=one_agent,
        started_at=at(date(2026, 6, 10)),
        blocks={"script": 20},
    )
    score.blocks = {
        "script": 20,
        "_meta": {"applicable_max": 100},
        "communication": "n/a",
        "resolution": True,
        "a_block_this_rubric_does_not_name": 7,
    }
    await db.flush()

    body = (await admin.get(f"{BASE}/blocks", params=WINDOW)).json()
    assert [row["block"] for row in body["items"]] == ["script"]


# --- 5. The breaches ----------------------------------------------------------


async def test_red_flags_are_counted_by_type_commonest_first(
    admin, one_agent, scored_call
) -> None:
    await scored_call(
        installation=one_agent,
        started_at=at(date(2026, 6, 10)),
        red_flags=[{"type": "shouting"}, {"type": "badmouthing"}],
    )
    await scored_call(
        installation=one_agent,
        started_at=at(date(2026, 6, 11)),
        red_flags=[{"type": "shouting"}],
    )
    await scored_call(installation=one_agent, started_at=at(date(2026, 6, 12)))

    body = (await admin.get(f"{BASE}/red-flags", params=WINDOW)).json()

    assert body["items"] == [
        {"type": "shouting", "count": 2},
        {"type": "badmouthing", "count": 1},
    ]
    assert body["total"] == 3


async def test_a_flag_with_no_type_is_not_counted_as_one(
    admin, one_agent, scored_call
) -> None:
    """Rather than a row keyed on null, which the panel renders as a blank chip."""
    await scored_call(
        installation=one_agent,
        started_at=at(date(2026, 6, 10)),
        red_flags=[{"severity": "high"}, {"type": "profanity"}],
    )

    body = (await admin.get(f"{BASE}/red-flags", params=WINDOW)).json()
    assert body["items"] == [{"type": "profanity", "count": 1}]


# --- 6. The histogram ---------------------------------------------------------


async def test_scores_fall_into_ten_point_bands(
    admin, one_agent, scored_call
) -> None:
    for score in (0, 9, 55, 89, 90):
        await scored_call(
            installation=one_agent,
            started_at=at(date(2026, 6, 10)),
            overall_score=score,
        )

    body = (await admin.get(f"{BASE}/distribution", params=WINDOW)).json()
    by_floor = {row["floor"]: row["calls"] for row in body["items"]}

    assert by_floor[0] == 2
    assert by_floor[50] == 1
    assert by_floor[80] == 1
    assert by_floor[90] == 1
    assert body["scored_calls"] == 5


async def test_a_perfect_score_lands_in_the_top_band(
    admin, one_agent, scored_call
) -> None:
    """``floor(100/10)*10`` is 100, which BonviZvonki reported as an eleventh
    band labelled "100-109"."""
    await scored_call(
        installation=one_agent, started_at=at(date(2026, 6, 10)), overall_score=100
    )

    body = (await admin.get(f"{BASE}/distribution", params=WINDOW)).json()
    assert len(body["items"]) == 10
    assert body["items"][-1] == {"floor": 90, "ceiling": 100, "calls": 1}


# --- Scope --------------------------------------------------------------------


def _own_scope(agent_id: uuid.UUID | None) -> Principal:
    """A principal with ``calls:read:own`` and no fleet-wide read.

    Built here rather than taken from the ``sales`` fixture's client because the
    router refuses that role with a 403 (§6.1) — the narrowing this pins lives
    in the service, and SPEC-ANALYTICS §12 Q1 records that reversing the grant
    is "this line plus a ``:own`` scope in the query".
    """
    return Principal(
        kind="user",
        id=uuid.uuid4(),
        role="sales",
        permissions=frozenset({Perm.CALLS_READ_OWN}),
        agent_id=agent_id,
    )


async def test_own_scope_sees_only_its_own_agent(
    db, installation_factory, scored_call
) -> None:
    mine = await installation_factory()
    theirs = await installation_factory()

    await scored_call(installation=mine, started_at=at(date(2026, 6, 10)), overall_score=60)
    await scored_call(installation=theirs, started_at=at(date(2026, 6, 10)), overall_score=90)
    await scored_call(installation=theirs, started_at=at(date(2026, 6, 11)), overall_score=95)

    service = AnalyticsService(db)
    principal = _own_scope(mine.agent_id)

    overview = await service.overview(principal, filters())
    assert overview.calls.value == 1
    assert str(overview.ai_score.value) == "60.0"

    ranking = await service.agent_ranking(principal, filters())
    assert [row.agent_id for row in ranking.items] == [mine.agent_id]

    distribution = await service.score_distribution(principal, filters())
    assert distribution.scored_calls == 1


async def test_own_scope_without_an_agent_sees_nothing(
    db, installation_factory, scored_call
) -> None:
    """A salesperson with no linked agent sees nothing rather than everything.

    The database CHECK makes that state unreachable; this is the belt to its
    braces, and it is the failure mode that matters — the other direction leaks
    the whole fleet's scores to one employee.
    """
    theirs = await installation_factory()
    await scored_call(installation=theirs, started_at=at(date(2026, 6, 10)))

    overview = await AnalyticsService(db).overview(_own_scope(None), filters())
    assert overview.calls.value == 0
    assert overview.calls_total == 0


async def test_a_fleet_wide_reader_sees_every_agent(
    db, installation_factory, scored_call
) -> None:
    mine = await installation_factory()
    theirs = await installation_factory()
    await scored_call(installation=mine, started_at=at(date(2026, 6, 10)))
    await scored_call(installation=theirs, started_at=at(date(2026, 6, 10)))

    principal = Principal(
        kind="user",
        id=uuid.uuid4(),
        role="manager",
        permissions=frozenset({Perm.CALLS_READ, Perm.ANALYSIS_READ}),
    )
    overview = await AnalyticsService(db).overview(principal, filters())
    assert overview.calls.value == 2


# --- The default window -------------------------------------------------------


async def test_the_default_window_is_the_last_thirty_tashkent_days(
    admin, one_agent, scored_call, frozen_clock
) -> None:
    """"Last 30 days" is thirty whole calendar days, today included.

    BonviZvonki computed it two ways — a rolling ``now - 30x24h`` here and whole
    local days on the next page — and one period showed 22,003 calls on one
    screen and 21,513 on the other.
    """
    frozen_clock(datetime(2026, 6, 30, 6, 0, tzinfo=UTC))

    await scored_call(installation=one_agent, started_at=at(date(2026, 6, 1)))
    # One day before the window opens.
    await scored_call(installation=one_agent, started_at=at(date(2026, 5, 31)))

    body = (await admin.get(f"{BASE}/overview")).json()
    assert body["date_from"] == "2026-06-01"
    assert body["date_to"] == "2026-06-30"
    assert body["calls"]["value"] == 1


async def test_a_single_bound_does_not_500(admin) -> None:
    """``?date_from=…`` alone answered 500 on three of their endpoints: the
    filter mixed a naive datetime with an aware one."""
    response = await admin.get(f"{BASE}/overview", params={"date_from": "2026-06-01"})
    assert response.status_code == 200
    assert response.json()["date_from"] == "2026-06-01"


async def test_a_backwards_range_returns_the_later_day_not_another_period(
    admin,
) -> None:
    """Reversed bounds silently returned a different period's numbers."""
    body = (
        await admin.get(
            f"{BASE}/overview",
            params={"date_from": "2026-06-30", "date_to": "2026-06-01"},
        )
    ).json()
    assert body["date_from"] == body["date_to"] == "2026-06-01"
