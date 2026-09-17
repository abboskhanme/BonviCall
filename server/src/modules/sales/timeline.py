"""Conversation <-> sale sequence, per customer.

Ported from BonviZvonki ``modules/sales/application/timeline.py``.

The manager's question here is DIFFERENT from the queue's. The queue answers
"which sale is suspicious"; this answers "which customers has this employee
worked with, and how did the conversation go". The unit is the CUSTOMER, not
the sale, and beside each one stands the chain of everything that happened.

⚠️ THE RULES ARE NOT REWRITTEN HERE. ``verdict`` and ``broken_rules`` come from
``ComplianceService.verdict_rows()`` — the same computation as the queue. A
second copy would give one sale two different verdicts on two screens, and the
manager would not know which to believe.

⚠️ A CUSTOMER IS A CODE, NOT A NUMBER. Calls reach a customer through their
CODE: code -> every number known for that code (``service.partner_phones``).
Matched on the SAP card's number alone, a conversation from the customer's
SECOND number would drop out of the chain.

⚠️ ON ONE DAY, THE CONVERSATION COMES BEFORE THE SALE. A sale has no time (SAP
gives only a date), and the rules read it the same way: a conversation on the
sale's own day JUSTIFIES R1, i.e. it is taken to have happened first. The chain
has to show that reading, or the screen would print the lie "sold first, then
talked".

PERFORMANCE. No query per customer — TWO queries in total: the sales (with
their verdicts) in one, the calls in one, and the grouping happens in Python.
Measured (3 weeks, 467 customers, 1,696 sales, 5,150 calls): ~0.6 s for both.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.core.clock import TASHKENT
from src.core.enums import CallDisposition
from src.modules.agents.models import AgentModel
from src.modules.calls.models import CallModel
from src.modules.sales.rules import Verdict
from src.modules.sales.service import (
    CUSTOMER_CALL,
    ComplianceFilter,
    ComplianceService,
    broken_rules,
    day_start,
    partner_phones,
)

#: How many customers come back by default.
#
# ⚠️ THERE MUST BE A CEILING. Over a month the customer count runs past a
# thousand and each brings dozens of events — the answer would reach tens of
# megabytes and the browser would not draw the screen at all.
DEFAULT_MAX_CLIENTS = 300

#: Event kinds.
KIND_CALL = "call"
KIND_SALE = "sale"

#: Order inside one day: the conversation, then the sale.
#
# See the module note — this is the rules' own reading, not decoration.
_RANK_CALL = 0
_RANK_SALE = 1


@dataclass(slots=True)
class TimelineEvent:
    """One event in the chain — either a conversation or a sale.

    ⚠️ BOTH COME BACK AS ONE TYPE, told apart by ``kind``. As two separate
    lists, the work of interleaving them would fall to the panel, and the
    ordering rule (a conversation precedes a sale on the same day) would have
    to be written a second time there — which is how two sides come to disagree.
    """

    kind: str
    at: datetime
    """A call: the real instant. A sale: 00:00 of that local day."""
    agent_name: str | None = None

    # ── calls only ────────────────────────────────────────────
    call_id: uuid.UUID | None = None
    direction: str | None = None
    answered: bool | None = None
    duration_sec: int | None = None
    has_audio: bool | None = None
    """Whether the conversation can be listened to — the evidence BonviZvonki
    cannot offer, because it stores no recordings."""

    # ── sales only ────────────────────────────────────────────
    sale_id: uuid.UUID | None = None
    external_id: str | None = None
    doc_number: str | None = None
    amount: float | None = None
    currency: str | None = None
    amount_usd: float | None = None
    verdict: str | None = None
    broken_rules: list[str] = field(default_factory=list)
    days_before: int | None = None
    """Days from the nearest earlier conversation to the sale. ``0`` — the same
    day; ``None`` — never spoken to before it."""


@dataclass(slots=True)
class TimelineClient:
    """One customer: the period's totals and the whole chain."""

    partner_code: str
    partner_name: str | None
    phone: str | None
    """The number on the SAP card — FOR DISPLAY.

    ⚠️ Not the matching key: a customer may hold other numbers and the chain
    covers those as well (``service.partner_phones``)."""

    agents: list[str]
    """Who sold in this period, without repeats."""
    sales_count: int
    suspicious_count: int
    amount_usd: float
    calls_count: int
    events: list[TimelineEvent]
    """In ASCENDING date order."""


@dataclass(slots=True)
class ComplianceTimeline:
    window_days: int
    truncated: bool
    """Whether ``max_clients`` cut the list — written out on the screen, or the
    list would silently be incomplete."""
    clients: list[TimelineClient]


@dataclass(slots=True)
class _Bucket:
    """A customer while it is being assembled, with unordered events."""

    partner_code: str
    partner_name: str | None = None
    phone: str | None = None
    agents: list[str] = field(default_factory=list)
    sales_count: int = 0
    suspicious_count: int = 0
    amount_usd: float = 0.0
    calls_count: int = 0
    events: list[tuple[Any, TimelineEvent]] = field(default_factory=list)
    """``(sort key, event)`` — sorted by the key at the end."""


def _sale_at(day: date) -> datetime:
    """A sale's date as an instant — LOCAL midnight.

    ⚠️ A sale has no time, so it is placed at 00:00 — but WITH ITS ZONE. Call
    instants carry a UTC offset, and an unzoned sale on the same axis would
    shift the day boundary by five hours.
    """
    return datetime.combine(day, time.min, tzinfo=TASHKENT)


class SalesTimelineService:
    """Builds the customer <-> conversation chain. Read-only."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build(
        self,
        f: ComplianceFilter,
        *,
        only_suspicious: bool = True,
        max_clients: int = DEFAULT_MAX_CLIENTS,
    ) -> ComplianceTimeline:
        """The customers in scope and their conversation <-> sale chain.

        Stages:

          1. **the sales** — from the SAME expression as the queue
             (``verdict_rows``), so the verdict arrives already computed;
          2. **choose the customers** — ``only_suspicious`` and ``max_clients``
             are applied in Python, because the criterion ("the customer with
             the most suspicious sales first") depends on the TOTALS and those
             are only known once the grouping is done;
          3. **the calls** — for the CHOSEN codes only, in one query.

        ⚠️ Stage 3 comes after stage 2 deliberately: asked before the cut, the
        calls of 400 customers nobody will see would be dragged in for nothing.
        """
        service = ComplianceService(self.session)

        # ── 1. Sales, with their verdicts ─────────────────────
        #
        # ⚠️ The ORDER is in the query: the customer's name is taken from the
        # NEWEST sale (the catalogue name may have changed since), which falls
        # out by itself when rows arrive in date order.
        rows = service.verdict_rows(f).subquery("timeline")
        result = (
            await self.session.execute(
                select(rows).order_by(rows.c.occurred_on, rows.c.external_id)
            )
        ).all()

        buckets: dict[str, _Bucket] = {}
        for row in result:
            bucket = buckets.get(row.partner_code)
            if bucket is None:
                bucket = _Bucket(partner_code=row.partner_code)
                buckets[row.partner_code] = bucket

            if row.partner_name:
                bucket.partner_name = row.partner_name
            if row.phone and bucket.phone is None:
                bucket.phone = row.phone
            if row.agent_name and row.agent_name not in bucket.agents:
                bucket.agents.append(row.agent_name)

            bucket.sales_count += 1
            if row.verdict == Verdict.SUSPICIOUS.value:
                bucket.suspicious_count += 1
            if row.amount_usd is not None:
                bucket.amount_usd += float(row.amount_usd)

            at = _sale_at(row.occurred_on)
            bucket.events.append(
                (
                    # ``external_id`` is the stable tiebreak: two sales to one
                    # customer on one day is normal and they must not swap
                    # places between one request and the next.
                    (row.occurred_on, _RANK_SALE, at, row.external_id),
                    TimelineEvent(
                        kind=KIND_SALE,
                        at=at,
                        agent_name=row.agent_name,
                        sale_id=row.id,
                        external_id=row.external_id,
                        doc_number=row.doc_number,
                        amount=None if row.amount is None else float(row.amount),
                        currency=row.currency,
                        amount_usd=(
                            None if row.amount_usd is None else float(row.amount_usd)
                        ),
                        verdict=row.verdict,
                        broken_rules=broken_rules(row),
                        days_before=row.days_before,
                    ),
                )
            )

        # ── 2. Which customers reach the screen ───────────────
        #
        # ⚠️ ``only_suspicious`` works at CUSTOMER level, not sale level: a
        # suspicious customer's CLEAN sales stay in the chain. Without that the
        # sequence would lie — it would read as "every sale to this customer
        # was suspicious".
        chosen = [
            bucket
            for bucket in buckets.values()
            if not only_suspicious or bucket.suspicious_count > 0
        ]
        chosen.sort(key=lambda b: (-b.suspicious_count, -b.amount_usd, b.partner_code))
        truncated = len(chosen) > max_clients
        chosen = chosen[:max_clients]

        # ── 3. The calls — one query ──────────────────────────
        if chosen:
            for code, event in await self._calls(
                f, codes=[b.partner_code for b in chosen]
            ):
                bucket = buckets[code]
                bucket.calls_count += 1
                bucket.events.append(event)

        return ComplianceTimeline(
            window_days=int(f.window_days),
            truncated=truncated,
            clients=[
                TimelineClient(
                    partner_code=b.partner_code,
                    partner_name=b.partner_name,
                    phone=b.phone,
                    agents=b.agents,
                    sales_count=b.sales_count,
                    suspicious_count=b.suspicious_count,
                    # Three decimals — the same precision as the
                    # ``sales.amount_usd`` column itself.
                    amount_usd=round(b.amount_usd, 3),
                    calls_count=b.calls_count,
                    events=[event for _, event in sorted(b.events, key=lambda p: p[0])],
                )
                for b in chosen
            ],
        )

    async def _calls(
        self, f: ComplianceFilter, *, codes: list[str]
    ) -> list[tuple[str, tuple[Any, TimelineEvent]]]:
        """The chosen customers' conversations inside the period.

        ⚠️ MATCHED BY CODE (``service.partner_phones``), not by number — the
        SAME route ``_evidence`` takes. Matched differently, the conversation
        that justified a verdict could be missing from the chain and the
        manager would not find the evidence for the "clean" badge.

        ⚠️ INTERNAL CALLS ARE EXCLUDED, exactly as the rules exclude them: a
        colleague-to-colleague call is not an agreement with a customer, and in
        the chain it would look like justifying evidence.

        ⚠️ The period is cut with HALF-OPEN INSTANTS around Asia/Tashkent
        midnights (``service.day_start``). Cut in UTC, conversations after
        19:00 fall onto the next day and vanish at the edge of the period.
        """
        phones = partner_phones("timeline_phones")
        talker = aliased(AgentModel)

        statement = (
            select(
                phones.c.code.label("code"),
                CallModel.id.label("call_id"),
                CallModel.started_at.label("at"),
                CallModel.direction.label("direction"),
                CallModel.disposition.label("disposition"),
                CallModel.duration_sec.label("duration_sec"),
                CallModel.has_audio.label("has_audio"),
                talker.full_name.label("agent_name"),
            )
            .select_from(CallModel)
            .join(phones, phones.c.phone_key == CallModel.remote_number_key)
            # The employee is OPTIONAL: a call whose agent row is gone must not
            # fall out of the chain.
            .outerjoin(talker, talker.id == CallModel.agent_id)
            .where(CUSTOMER_CALL)
            .where(phones.c.code.in_(codes))
        )
        if f.since is not None:
            statement = statement.where(CallModel.started_at >= day_start(f.since))
        if f.until is not None:
            # Half-open: ``until`` is an inclusive calendar date, so the bound
            # is the midnight that OPENS the following day. Written as
            # ``<= until`` the whole of the last day would be lost.
            statement = statement.where(
                CallModel.started_at < day_start(f.until + timedelta(days=1))
            )

        return [
            (
                row.code,
                (
                    # ``call_id`` is the stable tiebreak (as ``external_id`` is
                    # for sales): two calls in one second keep their order.
                    (
                        row.at.astimezone(TASHKENT).date(),
                        _RANK_CALL,
                        row.at,
                        str(row.call_id),
                    ),
                    TimelineEvent(
                        kind=KIND_CALL,
                        at=row.at,
                        agent_name=row.agent_name,
                        call_id=row.call_id,
                        direction=row.direction.value,
                        answered=row.disposition == CallDisposition.ANSWERED,
                        duration_sec=row.duration_sec,
                        has_audio=row.has_audio,
                    ),
                ),
            )
            for row in (await self.session.execute(statement)).all()
        ]


__all__ = [
    "DEFAULT_MAX_CLIENTS",
    "KIND_CALL",
    "KIND_SALE",
    "ComplianceTimeline",
    "SalesTimelineService",
    "TimelineClient",
    "TimelineEvent",
]
