"""The client directory — customers assembled from calls. **Read only.**

Ported from BonviZvonki ``modules/clients/application/directory.py``
(``ClientDirectory``). Every query, every join and every reason for them is
theirs; what changed is named at each seam below. What a "client" is, and why
the key is the last nine digits, is in ``rules.py``.

This module owns no table and is declared in ``core/reads.py``
(CONVENTIONS.md §2.1), so three rules bind it and ``tests/test_layering.py``
checks all three: it reads only the models in its entry, it never writes, and
it never selects a bare ORM entity — only projections and aggregates, so
nothing foreign can escape past this boundary.

════════════════════════════════════════════════════════════════
 THE SEAMS THAT CHANGED, AND WHY
════════════════════════════════════════════════════════════════

**The phone key is a column, not an expression.** BonviZvonki groups on
``right(regexp_replace(coalesce(calls.client_phone,''),'\\D','','g'), 9)``,
written out in three different places under three different names
(``PHONE_TAIL`` here, ``PHONE_KEY_DIGITS`` in ``calls/domain/routing.py``, an
inline ``right(..., 9)`` in ``bootstrap.py``) — which CONVENTIONS.md §7 names
as the defect it is. BonviCall has ``calls.remote_number_key``, a STORED
generated column produced by ``core.phone.phone_key_sql`` and indexed by
``ix_calls_remote``, so the expression, its three copies and the
``literal_column`` workaround around them all disappear. ``client_phone IS NOT
NULL AND digits <> ''`` becomes ``remote_number_key IS NOT NULL``, which is the
same test done by the database.

**The name is resolved INSIDE the aggregate, not in a second query.** Theirs
runs the grouping, then asks a separate ``_identities()`` query for the page's
keys, because its identity chain is a full outer join over two tables and
cannot be joined in. Ours is one table with a unique ``phone_key``, so it is a
plain 1:1 LEFT JOIN that cannot multiply a row — and that fixes a real defect:
**their list is SORTED by a column it does not SHOW.** ``ClientSort.NAME``
orders by ``mode(calls.client_name)`` — the provider's frozen name — while the
cell renders the resolved contact name, so "sort by name" produces an order the
reader cannot account for. Here both are the same expression.

**Pagination is keyset, not ``OFFSET``.** See ``rules.DirectoryCursor``.

**Own-scope narrowing is this module's job**, exactly as
``ActivityService._scope`` does it: the permission admits, the query narrows,
and a row belonging to another agent is a 404 and never a 403
(CONVENTIONS.md §11, SPEC §4.1 rule 2).

**Nothing here reads a ``sales`` table.** BonviZvonki's directory and card pull
the SAP partner catalogue into the identity chain (``application/identity.py``)
and hang a sales tab off the card. That module is being ported separately;
every place it would attach is marked ``SALES SEAM``.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, and_, case, distinct, func, nullslast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import Principal
from src.core.enums import CallDirection, CallDisposition, CallType
from src.core.pagination import Cursor, Page, apply_keyset, coerce_sort_value
from src.core.permissions import Perm
from src.modules.agents.models import AgentModel
from src.modules.analysis.models import CallScoreModel
from src.modules.calls.models import CallModel
from src.modules.clients.rules import (
    ClientAgent,
    ClientCall,
    ClientFilter,
    ClientRow,
    ClientScope,
    ClientSort,
    ClientWindow,
    DirectoryCursor,
    SortOrder,
    escape_like,
    search_digits,
)
from src.modules.contacts.models import ClientContactModel
from src.modules.contacts.rules import NAMING_KINDS

#: Permissions that see the whole fleet. Anything else is narrowed to the
#: principal's own agent. Exactly the fleet-wide half of the router's gate, for
#: the reason ``ActivityService.FLEET_WIDE`` states: listing more would be a
#: second, drifting definition of "may see everybody".
FLEET_WIDE: tuple[str, ...] = (Perm.CALLS_READ,)

_INCOMING = CallModel.direction == CallDirection.INCOMING
_OUTGOING = CallModel.direction == CallDirection.OUTGOING

#: INCOMING and no conversation: ``missed`` or ``rejected``. The SAME
#: definition ``activity`` uses — two sections must not disagree about what a
#: missed call is.
_MISSED = and_(_INCOMING, CallModel.disposition != CallDisposition.ANSWERED)

#: The matching key, generated and indexed by the database (N37).
_KEY = CallModel.remote_number_key

#: The kinds of contact allowed to name a customer, as stored values.
#: ``personal`` and ``internal`` are excluded — see ``contacts.rules``.
_NAMING_KINDS: tuple[str, ...] = tuple(kind.value for kind in NAMING_KINDS)

#: "Every call we have ever seen." One object rather than a literal per call
#: site, so that "no window" has one meaning.
_UNBOUNDED = ClientWindow(since=None, until=None, date_from=None, date_to=None)


def _count(*conditions: Any) -> Any:
    """``COUNT`` of the rows matching every condition. NULL rows count zero."""
    return func.count(case((and_(*conditions), 1)))


class ClientDirectory:
    """Customers assembled from calls. Reads only (CONVENTIONS.md §2.1)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Scope ─────────────────────────────────────────────────

    def scope(
        self, principal: Principal, agent_id: list[uuid.UUID] | None
    ) -> list[uuid.UUID] | None:
        """The agents this caller may see, narrowed by permission.

        ⚠️ A ``sales`` principal's ``agent_id`` filter from the URL is IGNORED,
        not merged: a salesperson must not be able to name a colleague and read
        that colleague's customers. They see exactly one agent — their own —
        and a ``sales`` account with no linked agent sees nothing rather than
        everything (the database CHECK makes that state unreachable; this is
        the belt to its braces).

        ``None`` means "every agent", and is only ever returned for a
        fleet-wide principal.
        """
        if not principal.has_any(*FLEET_WIDE):
            return [principal.agent_id] if principal.agent_id else []
        return list(agent_id) if agent_id else None

    # ── Shared conditions ─────────────────────────────────────

    def _scoped(self, statement: Select, filters: ClientFilter) -> Select:
        """Apply the filter to the CALL rows.

        ⚠️ The search is deliberately NOT here: it selects CUSTOMERS, not rows.
        A row-level search for "Ali" would count only the calls that happen to
        carry the name and the customer's totals would silently shrink — a
        search must never change a number it is only supposed to find.
        """
        statement = statement.where(_KEY.is_not(None))
        if filters.window.since is not None:
            statement = statement.where(CallModel.started_at >= filters.window.since)
        if filters.window.until is not None:
            statement = statement.where(CallModel.started_at < filters.window.until)
        if filters.agent_ids is not None:
            statement = statement.where(CallModel.agent_id.in_(filters.agent_ids))

        if filters.scope is ClientScope.INTERNAL:
            statement = statement.where(CallModel.call_type == CallType.INTERNAL)
        elif filters.scope is ClientScope.CLIENTS:
            statement = statement.where(CallModel.call_type != CallType.INTERNAL)
        return statement

    def _searched(self, statement: Select, filters: ClientFilter) -> Select:
        """Narrow to the customers a search matches — never to their calls.

        Three ways to match, and every one of them is either key-level or comes
        off the 1:1 contact row, so none of them can drop part of a customer's
        history and change their totals:

          · the digits typed, against the key itself;
          · the uploaded contact's name, cleaned name or code;
          · the handset-resolved name on ANY ONE of that customer's calls —
            which has to be a subquery over keys, because it is the one
            per-row condition of the three. One call carrying the name is
            enough: the customer is found, and then their WHOLE history shows.
        """
        text = (filters.search or "").strip()
        if not text:
            return statement

        pattern = f"%{escape_like(text)}%"
        conditions = [
            ClientContactModel.raw_name.ilike(pattern, escape="\\"),
            ClientContactModel.name.ilike(pattern, escape="\\"),
            ClientContactModel.code.ilike(pattern, escape="\\"),
        ]
        digits = search_digits(text)
        if digits:
            conditions.append(_KEY.like(f"%{digits}%"))

        by_call_name = self._scoped(
            select(_KEY)
            .select_from(CallModel)
            .join(AgentModel, AgentModel.id == CallModel.agent_id)
            .where(CallModel.contact_name.ilike(pattern, escape="\\")),
            filters,
        ).distinct()
        conditions.append(_KEY.in_(by_call_name))

        return statement.where(or_(*conditions))

    def _aggregate(self, filters: ClientFilter) -> Select:
        """One row per customer — the core of the directory.

        ⚠️ ARCHIVED EMPLOYEES ARE NOT EXCLUDED, and that is the opposite of
        what the activity report does. The report is about employees, so
        somebody who has left has no row in it. The directory is about
        CUSTOMERS, and a customer who was only ever served by somebody who has
        since left is still a customer — dropping them would delete real people
        from the list the day an account is archived. The join to ``agents``
        stays because the attribution has to resolve to a real employee.
        """
        # ⚠️ Only a contact kind that may NAME a customer contributes a name or
        # a code. A private acquaintance's name must not surface in a company
        # report, and a colleague is not a customer (``contacts.rules``). The
        # row still exists — only its name is withheld.
        may_name = ClientContactModel.kind.in_(_NAMING_KINDS)
        contact_name = case(
            (
                may_name,
                func.coalesce(ClientContactModel.name, ClientContactModel.raw_name),
            ),
            else_=None,
        )
        contact_code = case((may_name, ClientContactModel.code), else_=None)

        statement = (
            select(
                _KEY.label("phone_key"),
                # The uploaded dictionary first, the handset's own resolution
                # as the fallback. ``mode()`` — the most frequent value — and
                # not "the latest": the handset does not always resolve a name,
                # and taking the last call's value would leave a customer
                # nameless at random.
                func.coalesce(
                    contact_name,
                    func.mode().within_group(CallModel.contact_name),
                ).label("name"),
                contact_code.label("code"),
                func.coalesce(
                    ClientContactModel.phone,
                    func.mode().within_group(CallModel.remote_number),
                ).label("phone"),
                # The main employee — whoever spoke to them most. The list
                # shows one name and "+N" for the rest.
                func.mode().within_group(CallModel.agent_id).label("main_agent_id"),
                func.count().label("calls_total"),
                _count(_INCOMING).label("inbound"),
                _count(_OUTGOING).label("outbound"),
                _count(_MISSED).label("missed"),
                func.coalesce(func.sum(CallModel.duration_sec), 0).label("talk_seconds"),
                func.min(CallModel.started_at).label("first_call_at"),
                func.max(CallModel.started_at).label("last_call_at"),
                func.count(distinct(CallModel.agent_id)).label("agent_count"),
                func.avg(CallScoreModel.overall_score).label("avg_score"),
                func.count(CallScoreModel.overall_score).label("scored"),
            )
            .select_from(CallModel)
            .join(AgentModel, AgentModel.id == CallModel.agent_id)
            # 1:1 — ``client_contacts.phone_key`` is unique, so this cannot
            # multiply a call row. That is what makes resolving the name inside
            # the aggregate safe, and it is why sorting by name is honest here.
            .outerjoin(
                ClientContactModel, ClientContactModel.phone_key == _KEY
            )
            # The score is OPTIONAL: an INNER JOIN would drop every unscored
            # conversation out of the counts. ``call_scores.call_id`` is
            # UNIQUE, so this join does not multiply rows either.
            .outerjoin(CallScoreModel, CallScoreModel.call_id == CallModel.id)
            # ⚠️ The raw contact columns are grouped, and the CASE expressions
            # above are only in the SELECT. Grouping by the CASE itself is what
            # produced BonviZvonki's "column must appear in the GROUP BY
            # clause" error: an expression carrying bind parameters gets
            # different parameter numbers in SELECT and in GROUP BY, and
            # PostgreSQL then calls them two different expressions. Grouping by
            # the columns cannot split a group, because the join is 1:1.
            .group_by(
                _KEY,
                ClientContactModel.kind,
                ClientContactModel.name,
                ClientContactModel.raw_name,
                ClientContactModel.code,
                ClientContactModel.phone,
            )
        )
        return self._searched(self._scoped(statement, filters), filters)

    # ── The list ──────────────────────────────────────────────

    async def page(
        self,
        filters: ClientFilter,
        *,
        limit: int,
        sort: ClientSort = ClientSort.LAST_CALL,
        order: SortOrder = SortOrder.DESC,
        cursor: DirectoryCursor | None = None,
        with_total: bool = False,
    ) -> Page[ClientRow]:
        """One keyset page of the directory."""
        aggregate = self._aggregate(filters).subquery("d")
        column = {
            ClientSort.LAST_CALL: aggregate.c.last_call_at,
            ClientSort.CALLS: aggregate.c.calls_total,
            ClientSort.MISSED: aggregate.c.missed,
            ClientSort.TALK: aggregate.c.talk_seconds,
            ClientSort.SCORE: aggregate.c.avg_score,
            ClientSort.NAME: aggregate.c.name,
        }[sort]
        descending = order is SortOrder.DESC

        total: int | None = None
        if with_total:
            # ⚠️ Counted once per FILTER, never once per page — the same rule
            # ``/calls`` follows (SPEC §4.0). The count is over the grouped
            # rows, so it is "how many customers", which is the number the
            # header shows.
            total = int(
                (
                    await self.session.execute(
                        select(func.count()).select_from(aggregate)
                    )
                ).scalar_one()
            )

        statement = select(aggregate).order_by(
            # ⚠️ NULLS LAST in BOTH directions, and the seek predicate below
            # matches it. A customer with no score sorts after every scored one
            # whichever way the arrow points, which is what a reader expects
            # from "best first" and from "worst first" alike. PostgreSQL's
            # default is NULLS FIRST for ASC, so leaving this off would put the
            # unscored ones at the top of "worst first" and make the column
            # look empty.
            nullslast(column.desc() if descending else column.asc()),
            # The tiebreak. It is the group key, so it is unique by
            # construction and always ascending — a stable order under a column
            # full of ties is the whole reason a keyset page never repeats a
            # row.
            aggregate.c.phone_key.asc(),
        )
        if cursor is not None:
            statement = statement.where(
                _seek(column, aggregate.c.phone_key, cursor, descending=descending)
            )

        rows = (await self.session.execute(statement.limit(limit + 1))).all()
        has_more = len(rows) > limit
        rows = rows[:limit]

        agents = await self._agent_names({row.main_agent_id for row in rows})
        items = [_row(row, agents) for row in rows]
        next_cursor = (
            DirectoryCursor(
                sort_value=getattr(rows[-1], column.name), key=rows[-1].phone_key
            ).encode()
            if has_more and rows
            else None
        )
        return Page(
            items=items, next_cursor=next_cursor, has_more=has_more, total=total
        )

    async def _agent_names(
        self, ids: set[uuid.UUID | None]
    ) -> dict[uuid.UUID, str]:
        """Names for the employees on THIS page only.

        Not folded into the aggregate: ``mode()`` only tells you which employee
        won after the grouping has happened, so there is nothing to join to
        beforehand. One extra query for at most a page's worth of ids.
        """
        real = [value for value in ids if value is not None]
        if not real:
            return {}
        rows = await self.session.execute(
            select(AgentModel.id, AgentModel.full_name).where(AgentModel.id.in_(real))
        )
        return {row.id: row.full_name for row in rows}

    # ── One customer ──────────────────────────────────────────

    async def summary(self, key: str, filters: ClientFilter) -> ClientRow | None:
        """One customer's aggregate, or None when the number is unknown.

        The search text is dropped: once the card is open the box is irrelevant
        and the customer is already chosen.

        ⚠️ AN EMPTY PERIOD IS NOT "NO SUCH CUSTOMER". If nothing matches inside
        the chosen dates, the dates are removed and the question asked again:
        if the number exists at all, the card opens and shows zeros. Otherwise
        somebody who narrowed the period would be told the customer does not
        exist.

        ⚠️ The EMPLOYEE and SCOPE conditions are kept while doing that — a
        salesperson must not be able to open the card of a customer they have
        never spoken to.
        """
        unsearched = ClientFilter(
            window=filters.window, agent_ids=filters.agent_ids, scope=filters.scope
        )
        row = await self._one(key, unsearched)
        if row is not None:
            return row
        if not unsearched.window.bounded:
            return None
        all_time = ClientFilter(
            window=_UNBOUNDED,
            agent_ids=unsearched.agent_ids,
            scope=unsearched.scope,
        )
        row = await self._one(key, all_time)
        if row is None:
            return None
        return ClientRow(
            phone_key=row.phone_key,
            name=row.name,
            phone=row.phone,
            code=row.code,
            calls_total=0,
            inbound=0,
            outbound=0,
            missed=0,
            talk_seconds=0,
            first_call_at=None,
            last_call_at=None,
            agent_count=0,
            main_agent_id=None,
            main_agent_name=None,
            avg_score=None,
            scored=0,
        )

    async def _one(self, key: str, filters: ClientFilter) -> ClientRow | None:
        aggregate = self._aggregate(filters).where(_KEY == key).subquery("d")
        row = (await self.session.execute(select(aggregate))).first()
        if row is None:
            return None
        agents = await self._agent_names({row.main_agent_id})
        return _row(row, agents)

    async def locate(
        self, key: str, filters: ClientFilter
    ) -> tuple[ClientRow, ClientFilter] | None:
        """Find the customer, widening the CUT if the chosen one hides them.

        ⚠️ WHY THE CUT IS WIDENED. ``scope`` is a view of the list, not a truth
        about the customer: by default ``clients`` leaves internal numbers out.
        A card URL with no ``scope`` on it — which is what somebody who saved
        the link or typed it has — would never open an internal number and
        would answer 404. The number is in the database and the reader is
        allowed to see it; only the SELECTION in the request does not match,
        and answering with an error in that case teaches people the system is
        broken.

        ⚠️ The employee and date conditions are NOT widened
        (``ClientFilter.widened`` changes ``scope`` and nothing else).
        """
        found = await self.summary(key, filters)
        if found is not None:
            return found, filters
        if filters.scope is ClientScope.ALL:
            return None
        wide = filters.widened()
        found = await self.summary(key, wide)
        return (found, wide) if found is not None else None

    async def agents_of(self, key: str, filters: ClientFilter) -> list[ClientAgent]:
        """WHO spoke to this customer — most first.

        One customer may have been served by several employees (a handover, a
        holiday, a change of job) and that is a manager's first question.
        """
        statement = (
            select(
                CallModel.agent_id,
                AgentModel.full_name,
                func.count().label("calls"),
                func.max(CallModel.started_at).label("last_call_at"),
            )
            .select_from(CallModel)
            .join(AgentModel, AgentModel.id == CallModel.agent_id)
            .where(_KEY == key)
            .group_by(CallModel.agent_id, AgentModel.full_name)
            .order_by(func.count().desc(), func.max(CallModel.started_at).desc())
        )
        rows = await self.session.execute(self._scoped(statement, filters))
        return [
            ClientAgent(
                agent_id=row.agent_id,
                full_name=row.full_name,
                calls=int(row.calls or 0),
                last_call_at=row.last_call_at,
            )
            for row in rows
        ]

    async def calls(
        self,
        key: str,
        filters: ClientFilter,
        *,
        limit: int,
        cursor: Cursor | None = None,
        with_total: bool = False,
    ) -> Page[ClientCall]:
        """Every conversation with this customer — newest first.

        Keyset on ``started_at`` with ``id`` as the tiebreak, which is the
        product's own rule (CONVENTIONS.md, ``core/pagination.py``) and is
        reused here rather than re-implemented: unlike the directory, this list
        is over ``calls`` ROWS and every row has an id.

        Ordered by ``started_at`` and not by ``received_at``, for the reason
        ``CallsPage`` states: a recovery sweep uploads yesterday's calls after
        today's, and a customer's history read in receipt order is not a
        history.
        """
        base = (
            select(
                CallModel.id,
                CallModel.started_at,
                CallModel.received_at,
                CallModel.duration_sec,
                CallModel.direction,
                CallModel.disposition,
                CallModel.call_type,
                CallModel.has_audio,
                CallModel.agent_id,
                AgentModel.full_name.label("agent_name"),
                CallScoreModel.overall_score,
                CallScoreModel.red_flags,
                CallScoreModel.needs_review,
            )
            .select_from(CallModel)
            .join(AgentModel, AgentModel.id == CallModel.agent_id)
            .outerjoin(CallScoreModel, CallScoreModel.call_id == CallModel.id)
            .where(_KEY == key)
        )
        base = self._scoped(base, filters)

        total: int | None = None
        if with_total:
            total = int(
                (
                    await self.session.execute(
                        select(func.count()).select_from(base.subquery())
                    )
                ).scalar_one()
            )

        statement = apply_keyset(
            base, CallModel.started_at, CallModel.id, cursor, descending=True
        ).limit(limit + 1)
        rows = (await self.session.execute(statement)).all()
        has_more = len(rows) > limit
        rows = rows[:limit]

        items = [
            ClientCall(
                call_id=row.id,
                started_at=row.started_at,
                received_at=row.received_at,
                duration_sec=int(row.duration_sec or 0),
                direction=str(row.direction),
                disposition=str(row.disposition),
                call_type=str(row.call_type),
                has_audio=bool(row.has_audio),
                agent_id=row.agent_id,
                agent_name=row.agent_name,
                score=row.overall_score,
                red_flag_count=len(row.red_flags or []),
                needs_review=bool(row.needs_review),
            )
            for row in rows
        ]
        next_cursor = (
            Cursor(sort_value=rows[-1].started_at, row_id=rows[-1].id).encode()
            if has_more and rows
            else None
        )
        return Page(
            items=items, next_cursor=next_cursor, has_more=has_more, total=total
        )

    # ── What the contacts page asks this module ───────────────

    async def call_counts(self, keys: set[str]) -> dict[str, int]:
        """Number -> how many calls it has, fleet-wide.

        The ``contacts`` module owns a dictionary, not traffic, so it asks this
        module rather than reading ``calls`` itself (CONVENTIONS.md §2). Used
        by the upload preview, where the answer decides which contacts are
        worth importing at all — "611 contacts" sounds smaller than "1,517"
        until you see that the 611 cover far more conversations.

        Unscoped on purpose: the contacts page is fleet reference data behind
        ``settings:read``, and a per-agent count would answer a question nobody
        on that page is asking.
        """
        if not keys:
            return {}
        rows = await self.session.execute(
            select(_KEY.label("phone_key"), func.count().label("calls"))
            .where(_KEY.in_(keys))
            .group_by(_KEY)
        )
        return {row.phone_key: int(row.calls) for row in rows}

    async def brief(self, key: str) -> ClientRow | None:
        """The whole-history aggregate for one number, ignoring every filter.

        What the contact card shows beside the dictionary row. Deliberately
        unfiltered: the card is about the NUMBER, and narrowing it by scope or
        by employee would answer a question the contacts page does not ask.
        """
        return await self._one(
            key, ClientFilter(window=_UNBOUNDED, scope=ClientScope.ALL)
        )


def _seek(column: Any, key_column: Any, cursor: DirectoryCursor, *, descending: bool):
    """The keyset predicate for ``ORDER BY <column> NULLS LAST, key ASC``.

    ⚠️ The cursor value is put back into the COLUMN's own Python type first,
    through ``core.pagination.coerce_sort_value`` — the same function
    ``apply_keyset`` uses, not a second copy of the rule. A cursor travels as
    JSON, so a ``timestamptz`` comes back as an ISO string and PostgreSQL
    refuses to compare the two: "operator does not exist: timestamp with time
    zone < character varying", which is a 500 on a request the client did
    nothing wrong in. It is the first thing that breaks on page two, and only
    on page two.

    Written out rather than expressed as a row-value comparison, because
    ``(a, b) < (c, d)`` has no way to say NULLS LAST and the sort column here
    is nullable — ``avg_score`` is NULL for every customer nobody has scored,
    and ``last_call_at`` can be NULL on an empty period. A row-value seek would
    put those rows on the wrong side of the cursor and the page would either
    repeat them forever or skip them entirely.

    Three cases, and the middle one is the one that is easy to forget: once the
    cursor is past the non-NULL rows, everything still to come is a NULL row.
    """
    if cursor.sort_value is None:
        # Already inside the NULL tail: only the tiebreak advances.
        return and_(column.is_(None), key_column > cursor.key)
    value = coerce_sort_value(column, cursor.sort_value)
    beyond = column < value if descending else column > value
    return or_(
        beyond,
        column.is_(None),
        and_(column == value, key_column > cursor.key),
    )


def _row(row: Any, agents: dict[uuid.UUID, str]) -> ClientRow:
    """One aggregate row as the module's own type. Never an ORM entity (§2.1)."""
    return ClientRow(
        phone_key=row.phone_key,
        name=row.name,
        phone=row.phone,
        code=row.code,
        calls_total=int(row.calls_total or 0),
        inbound=int(row.inbound or 0),
        outbound=int(row.outbound or 0),
        missed=int(row.missed or 0),
        talk_seconds=int(row.talk_seconds or 0),
        first_call_at=row.first_call_at,
        last_call_at=row.last_call_at,
        agent_count=int(row.agent_count or 0),
        main_agent_id=row.main_agent_id,
        main_agent_name=agents.get(row.main_agent_id) if row.main_agent_id else None,
        avg_score=round(float(row.avg_score), 1) if row.avg_score is not None else None,
        scored=int(row.scored or 0),
    )


__all__ = ["FLEET_WIDE", "ClientDirectory"]
