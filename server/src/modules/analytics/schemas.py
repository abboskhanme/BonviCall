"""Analytics wire schemas — the six aggregates the TAHLIL dashboard draws.

Defined here and not imported from ``calls`` or ``analysis``: §2.1 rule 3 says
what crosses back out of a module that owns no table is that module's **own**
type, never a foreign entity. Nothing below is an ORM object and nothing below
is persisted.

**Every rate and average is ``Decimal``, never ``float``.** The same call
``gaps/schemas.py`` makes for the capture rate, for the same reason: these
numbers are rendered next to one another on a single screen and read as exact,
and a float average of integer scores serialises as ``78.30000000000001``
often enough to be noticed. PostgreSQL's ``avg()`` already returns NUMERIC, so
keeping it is also *less* work than casting it away. On the wire a Decimal is a
string; the panel converts once, where it builds the chart rows.

Ported from ``../BonviZvonki/.../analytics/presentation/router.py`` and the
hand-written response interfaces in ``web/src/modules/analytics/api.ts``.
**Three families of field are dropped rather than invented:** ``client_rating``
and ``divergence`` (their CSAT survey tables are phase 3 and BonviCall has
none), ``color``/``avatar_url`` on an agent row (this panel has no avatar
component, and the stored colour is a hex literal a page here may not render),
and the Uzbek ``label`` each breakdown row carried — labels live in the panel's
``uz.json`` (CONVENTIONS.md §14), so the server sends the key and nothing else.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from src.core import clock
from src.core.enums import CallType
from src.modules.analytics import rules

#: The bucket a timeseries is grouped into. Typed as the three names
#: ``rules.BUCKETS`` allows, so an unknown bucket is a 422 from FastAPI rather
#: than a ``date_trunc`` the database refuses at query time.
Bucket = Literal["day", "week", "month"]

#: "Last N days" when the caller names no window. Thirty, as BonviZvonki's
#: dashboard opened on; a month is the shortest period in which a fifteen-person
#: team produces a readable score distribution.
DEFAULT_DAYS = 30

#: The widest window a caller may ask for in one request.
MAX_DAYS = 365


class AnalyticsFilters(BaseModel):
    """The filter set every one of the six reports is computed under.

    **The window is always closed.** BonviZvonki carried ``date_from: None``
    into six methods and ``_previous_period`` then had to give up, so the
    delta silently disappeared on exactly the default view most people open.
    Here :meth:`resolve` turns "last N days" into two dates once, in the
    router's dependency, and everything below works with a real window.
    """

    date_from: date = Field(
        description="Asia/Tashkent calendar date, inclusive (D-08)."
    )
    date_to: date = Field(description="Asia/Tashkent calendar date, inclusive.")
    agent_id: list[uuid.UUID] | None = Field(
        default=None, description="One or more agents; absent means every agent."
    )
    call_type: CallType | None = Field(
        default=None,
        description=(
            "internal | external | unknown. BonviCall classifies this at ingest "
            "(calls/rules.py::classify_call_type); the analytics module never "
            "re-derives it."
        ),
    )

    @classmethod
    def resolve(
        cls,
        *,
        days: int = DEFAULT_DAYS,
        date_from: date | None = None,
        date_to: date | None = None,
        agent_id: list[uuid.UUID] | None = None,
        call_type: CallType | None = None,
    ) -> AnalyticsFilters:
        """Query parameters to a closed window.

        An explicit bound always wins. A missing one is filled from the other
        end of "the last ``days`` days" rather than from "now", so a caller who
        sends only ``date_from`` gets a window that ends today instead of a
        ``TypeError`` — which is what BonviZvonki answered with a 500 on
        ``?date_from=2026-08-10`` alone, on three of its endpoints.
        """
        today = clock.today_tashkent()
        upper = date_to or today
        lower = date_from or rules.window_start(days, upper)
        if lower > upper:
            # Reversed silently returns another period's numbers, which is the
            # one answer worse than an error.
            lower = upper
        return cls(
            date_from=lower,
            date_to=upper,
            agent_id=agent_id or None,
            call_type=call_type,
        )


class AnalyticsWindow(BaseModel):
    """The window a report was computed over, echoed back.

    On every response, because five of the six are opened without naming a
    window at all — the caller asked for "the last 30 days" and the page has to
    be able to say which days those were.
    """

    date_from: date
    date_to: date


class CountMetricOut(BaseModel):
    """A count, with its change against the previous period of equal length."""

    value: int
    delta_percent: Decimal | None = Field(
        description=(
            "Percent change. Null when the previous period was zero or has no "
            "value — 'up from nothing' is not a percentage."
        )
    )


class ScoreMetricOut(BaseModel):
    """An average score out of 100, to one decimal place."""

    value: Decimal | None = Field(description="Null when nothing was scored.")
    delta_percent: Decimal | None


class CallTypeCountsOut(BaseModel):
    """Calls by type, over the window. **Every key is always present.**

    A fixed object rather than a map, so a type with nothing in it is a visible
    zero instead of an absent key the panel defaults for itself — which is how
    the two lists drift apart. The fields are pinned against ``CallType`` by a
    test.

    **Deliberately not narrowed to scored calls.** This is the breakdown that
    explains the headline: the ``calls`` metric counts *scored* conversations,
    and without this row a manager who sees "6" in a month of 22,000 calls
    concludes the system lost the rest. Measured in BonviZvonki: 72 against
    22,026 for the same period.
    """

    internal: int = 0
    external: int = 0
    unknown: int = 0


class AnalyticsOverviewResponse(AnalyticsWindow):
    """The KPI cards (BonviZvonki ``GET /analytics/overview``)."""

    calls: CountMetricOut = Field(
        description=(
            "**Scored** calls — the join to call_scores is an inner one. A call "
            "the pipeline skipped or has not reached is not in it; call_types "
            "below is what accounts for the difference."
        )
    )
    calls_total: int = Field(description="Every call in the window, scored or not.")
    call_types: CallTypeCountsOut
    ai_score: ScoreMetricOut
    red_flags: CountMetricOut = Field(
        description="Scored calls carrying at least one red flag, not flags found."
    )
    avg_duration_sec: int = Field(
        description="Mean call length over the scored calls, rounded half up."
    )
    compared_with: AnalyticsWindow = Field(
        description="The window every delta_percent above is measured against."
    )


class TimeseriesPointOut(BaseModel):
    """One period of the trend line.

    ``period_start`` and not BonviZvonki's ``date``: in the weekly bucket the
    value is the Monday and in the monthly one the first of the month, so
    "date" invites a reader to plot it as the day something happened.
    """

    period_start: date = Field(
        description="The period's first day, in Asia/Tashkent (Monday for a week)."
    )
    calls: int
    ai_score: Decimal | None = Field(
        description="Null where nothing was scored in the period — a gap, not a zero."
    )


class AnalyticsTimeseriesResponse(AnalyticsWindow):
    """The trend (BonviZvonki ``GET /analytics/timeseries``)."""

    bucket: Bucket
    filled: bool = Field(
        description=(
            "True when every period in the window is present, empty ones "
            "included. False past the 550-period ceiling, where only periods "
            "with data are returned — the panel then draws what it was given "
            "rather than pretending the axis is complete."
        )
    )
    points: list[TimeseriesPointOut]


class AgentRankRowOut(BaseModel):
    """One agent's standing over the window."""

    agent_id: uuid.UUID
    agent_name: str
    rank: int = Field(description="1 is the highest average score.")
    rank_delta: int | None = Field(
        description=(
            "Places gained against the previous period; positive means moved up. "
            "Null for an agent who scored nothing in that period."
        )
    )
    calls: int
    ai_score: Decimal | None
    red_flags: int
    avg_duration_sec: int


class AgentRankingResponse(AnalyticsWindow):
    """The leaderboard (BonviZvonki ``GET /analytics/agents``)."""

    items: list[AgentRankRowOut]
    total: int = Field(description="Agents with at least one scored call.")


class BlockScoreOut(BaseModel):
    """One rubric block, averaged over the window."""

    block: str = Field(
        description=(
            "The rubric's own key. An open vocabulary on purpose: scores are "
            "written under a pinned rubric_version, so a block a later rubric "
            "adds must still be readable. The panel renders an unknown key as "
            "the key."
        )
    )
    score: Decimal
    max: int = Field(
        description=(
            "From the rubric, never a second constant. The two were once typed "
            "separately, diverged 25 against 15, and the radar chart drew 106 % "
            "in front of a manager."
        )
    )
    percent: Decimal = Field(
        description="score/max. The radar chart's axis, which is why it is bounded."
    )
    scored_calls: int = Field(description="Calls this block's average is taken over.")


class BlockBreakdownResponse(AnalyticsWindow):
    """The radar chart (BonviZvonki ``GET /analytics/blocks``).

    A block the rubric does not name is **left out** rather than sent with a
    null percentage: we do not know what to divide it by, and a bar with no
    scale is worse than a missing one.
    """

    items: list[BlockScoreOut]


class RedFlagCountOut(BaseModel):
    """One kind of breach, and how often it was found."""

    type: str = Field(description="The rubric's key; open, like the block keys.")
    count: int = Field(
        description="Occurrences, not calls — one call can carry the same type twice."
    )


class RedFlagBreakdownResponse(AnalyticsWindow):
    """The breach breakdown (BonviZvonki ``GET /analytics/red-flags``)."""

    items: list[RedFlagCountOut]
    total: int = Field(description="Every occurrence counted, across all types.")


class ScoreBucketOut(BaseModel):
    """One ten-point band of the histogram."""

    floor: int
    ceiling: int = Field(
        description=(
            "Inclusive. The top band is 90-100 rather than 90-99: a perfect "
            "score belongs in the highest bar, not in an eleventh one of its own."
        )
    )
    calls: int


class ScoreDistributionResponse(AnalyticsWindow):
    """The histogram (BonviZvonki ``GET /analytics/distribution``).

    Always ten bands, empty ones included — the same decision
    :class:`CallTypeCountsOut` makes, and for the same reason: a histogram with
    holes in it reads as a filter that ate rows.
    """

    items: list[ScoreBucketOut]
    scored_calls: int


__all__ = [
    "DEFAULT_DAYS",
    "MAX_DAYS",
    "AgentRankRowOut",
    "AgentRankingResponse",
    "AnalyticsFilters",
    "AnalyticsOverviewResponse",
    "AnalyticsTimeseriesResponse",
    "AnalyticsWindow",
    "BlockBreakdownResponse",
    "BlockScoreOut",
    "Bucket",
    "CallTypeCountsOut",
    "CountMetricOut",
    "RedFlagBreakdownResponse",
    "RedFlagCountOut",
    "ScoreBucketOut",
    "ScoreDistributionResponse",
    "ScoreMetricOut",
    "TimeseriesPointOut",
]
