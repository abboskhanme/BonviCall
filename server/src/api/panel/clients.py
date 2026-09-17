"""The customer directory for the panel — who we talk to, and how much.

Ported from BonviZvonki ``modules/clients/presentation/router.py``.

═══ WHAT A CUSTOMER IS ═════════════════════════════════════════════════════
One phone NUMBER and every conversation held with it. Not a catalogue row —
there is no customer catalogue here, and theirs is empty. The reasoning is in
``modules/clients/rules.py``.

═══ ACCESS ═════════════════════════════════════════════════════════════════
``calls:read`` or ``calls:read:own``, because this is the calls table asked a
different question: whoever may read a call may read the customer it was with.
A ``sales`` principal holds the second, passes the gate, and
``ClientDirectory`` narrows the query to their own agent — the house rule
(CONVENTIONS.md §11): the permission admits, the QUERY narrows, and there is
never a second check in a router.

A number this caller has never spoken to is a **404**, and so is a number that
does not exist: the two answers are identical on purpose (SPEC §4.1 rule 2) —
a 403 would confirm that a colleague spoke to it.

═══ NOT HERE: ``GET /clients/{key}/sales`` ═════════════════════════════════
The source's card carries a sales tab, gated **separately** on ``sales:read``
and explicitly NOT inherited from the right to open the card, because that list
is a check carried out ON a salesperson. The ``sales`` module is being ported
separately; nothing in this file creates, reads or references a ``sales*``
table.
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.core.clock import TASHKENT
from src.core.deps import PrincipalDep, SessionDep
from src.core.errors import BadRequestError, ErrorCode, NotFoundError
from src.core.pagination import Cursor
from src.core.permissions import Perm, require_any_permission
from src.modules.clients.rules import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ClientFilter,
    ClientScope,
    ClientSort,
    CursorInvalid,
    DirectoryCursor,
    SortOrder,
    WindowInvalid,
    client_window,
    is_client_key,
)
from src.modules.clients.schemas import (
    ClientAgentRow,
    ClientCallRow,
    ClientCallsResponse,
    ClientDetailResponse,
    ClientPageResponse,
    ClientRowOut,
)
from src.modules.clients.service import ClientDirectory

router = APIRouter(prefix="/clients", tags=["Clients"])

_read = require_any_permission(Perm.CALLS_READ, Perm.CALLS_READ_OWN)


def directory_filter(
    date_from: Annotated[
        date | None, Query(description="Asia/Tashkent calendar date.")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Asia/Tashkent calendar date, INCLUSIVE.")
    ] = None,
    scope: Annotated[
        ClientScope,
        Query(description="`clients` — everything except internal lines (default)."),
    ] = ClientScope.CLIENTS,
    search: Annotated[
        str | None, Query(max_length=100, description="Name, code or number.")
    ] = None,
) -> ClientFilter:
    """The filter, resolved once for ALL THREE endpoints.

    ⚠️ It must not be built twice. If the list and the card resolve different
    windows, the card contradicts the list and the reader has no way to know
    which to believe.

    ⚠️ BOTH DATE BOUNDS MAY BE ABSENT and the default is "everything". The
    directory's first question is *who are our customers*, and a window that
    silently defaulted to the last seven days would answer a different one.
    """
    try:
        window = client_window(date_from=date_from, date_to=date_to, zone=TASHKENT)
    except WindowInvalid as invalid:
        raise BadRequestError(
            ErrorCode.BAD_REQUEST, detail={"field": invalid.field_name}
        ) from invalid
    # ``agent_ids`` is deliberately left unset here and decided by ``_scoped``
    # below, which asks the SERVICE. A dependency that narrowed it itself would
    # be a second copy of the own-scope rule living in a router (§2, §11).
    return ClientFilter(window=window, agent_ids=None, scope=scope, search=search)


FilterDep = Annotated[ClientFilter, Depends(directory_filter)]


def _key(raw: str) -> str:
    """The path segment as a directory key.

    The key never reaches SQL as text — it is a bound parameter — but an exact
    shape shows the mistake early: ``/clients/undefined`` should get a
    comprehensible answer and not an empty page.
    """
    if not is_client_key(raw):
        raise BadRequestError(ErrorCode.BAD_REQUEST, detail={"field": "key"})
    return raw.strip()


def _directory_cursor(raw: str | None) -> DirectoryCursor | None:
    if raw is None:
        return None
    try:
        return DirectoryCursor.decode(raw)
    except CursorInvalid as invalid:
        raise BadRequestError(
            ErrorCode.BAD_REQUEST, detail={"field": "cursor"}
        ) from invalid


def _row(row) -> ClientRowOut:
    """One aggregate as its wire row. ``missed_rate`` is the dataclass's own
    property, so the list and the card cannot compute it differently."""
    return ClientRowOut(
        phone_key=row.phone_key,
        name=row.name,
        phone=row.phone,
        code=row.code,
        calls_total=row.calls_total,
        inbound=row.inbound,
        outbound=row.outbound,
        missed=row.missed,
        missed_rate=row.missed_rate,
        talk_seconds=row.talk_seconds,
        first_call_at=row.first_call_at,
        last_call_at=row.last_call_at,
        agent_count=row.agent_count,
        main_agent_id=row.main_agent_id,
        main_agent_name=row.main_agent_name,
        avg_score=row.avg_score,
        scored=row.scored,
    )


@router.get("", response_model=ClientPageResponse, dependencies=[Depends(_read)])
async def list_clients(
    principal: PrincipalDep,
    session: SessionDep,
    filters: FilterDep,
    agent_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    sort: Annotated[ClientSort, Query()] = ClientSort.LAST_CALL,
    order: Annotated[SortOrder, Query()] = SortOrder.DESC,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(description="From the previous page.")] = None,
    with_total: Annotated[
        bool, Query(description="Ask for the count. First page only.")
    ] = False,
) -> ClientPageResponse:
    """Who has been spoken to, how often, and when last.

    The search matches a name, a customer code or a number in any format
    ("90 123", "+998901112233") — comparison is on digits alone.

    A ``sales`` caller sees only the customers they have spoken to, and the
    ``agent_id`` filter is ignored for them rather than merged.
    """
    directory = ClientDirectory(session)
    scoped = _scoped(directory, principal, filters, agent_id)
    page = await directory.page(
        scoped,
        limit=limit,
        sort=sort,
        order=order,
        cursor=_directory_cursor(cursor),
        with_total=with_total,
    )
    return ClientPageResponse(
        items=[_row(row) for row in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        total=page.total,
        date_from=filters.window.date_from,
        date_to=filters.window.date_to,
    )


@router.get("/{key}", response_model=ClientDetailResponse, dependencies=[Depends(_read)])
async def get_client(
    key: str,
    principal: PrincipalDep,
    session: SessionDep,
    filters: FilterDep,
    agent_id: Annotated[list[uuid.UUID] | None, Query()] = None,
) -> ClientDetailResponse:
    """One customer: the same aggregate the list showed, plus who spoke to them.

    ⚠️ The card takes the SAME filter the list took. Otherwise a customer
    listed with "12 calls" opens onto a different number and the reader cannot
    tell which to believe.

    An empty period is not an unknown customer: the card opens and shows zeros
    (``ClientDirectory.summary``). A cut that hides the number is not one
    either: the cut is widened and the answer says which one found them.
    """
    directory = ClientDirectory(session)
    scoped = _scoped(directory, principal, filters, agent_id)
    found = await directory.locate(_key(key), scoped)
    if found is None:
        raise NotFoundError()

    # ⚠️ `resolved` is the filter the customer was ACTUALLY found under. The
    # "who spoke to them" list is built from that same one — otherwise the card
    # would show a full aggregate above an empty employee list.
    summary, resolved = found
    agents = await directory.agents_of(_key(key), resolved)
    return ClientDetailResponse(
        client=_row(summary),
        agents=[
            ClientAgentRow(
                agent_id=agent.agent_id,
                full_name=agent.full_name,
                calls=agent.calls,
                last_call_at=agent.last_call_at,
            )
            for agent in agents
        ],
        scope=resolved.scope.value,
    )


@router.get(
    "/{key}/calls", response_model=ClientCallsResponse, dependencies=[Depends(_read)]
)
async def client_calls(
    key: str,
    principal: PrincipalDep,
    session: SessionDep,
    filters: FilterDep,
    agent_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
    with_total: Annotated[bool, Query()] = False,
) -> ClientCallsResponse:
    """Every conversation with this customer, newest first.

    ⚠️ Same widening rule as the card, and for the same reason: an internal
    number's card would otherwise open with an empty table under it. The second
    lookup only happens when the first page came back EMPTY — while there are
    rows the cut is right and nothing extra is asked.
    """
    directory = ClientDirectory(session)
    cleaned = _key(key)
    scoped = _scoped(directory, principal, filters, agent_id)
    page = await directory.calls(
        cleaned,
        scoped,
        limit=limit,
        cursor=Cursor.decode(cursor) if cursor else None,
        with_total=with_total,
    )
    if not page.items and cursor is None:
        found = await directory.locate(cleaned, scoped)
        if found is not None and found[1].scope is not scoped.scope:
            page = await directory.calls(
                cleaned, found[1], limit=limit, with_total=with_total
            )

    return ClientCallsResponse(
        items=[
            ClientCallRow(
                id=row.call_id,
                started_at=row.started_at,
                received_at=row.received_at,
                duration_sec=row.duration_sec,
                direction=row.direction,
                disposition=row.disposition,
                call_type=row.call_type,
                has_audio=row.has_audio,
                agent_id=row.agent_id,
                agent_name=row.agent_name,
                score=row.score,
                red_flag_count=row.red_flag_count,
                needs_review=row.needs_review,
            )
            for row in page.items
        ],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        total=page.total,
    )


def _scoped(
    directory: ClientDirectory,
    principal: PrincipalDep,
    filters: ClientFilter,
    agent_id: list[uuid.UUID] | None,
) -> ClientFilter:
    """The filter with its agent list decided by the SERVICE, not by this file.

    The rule ("a salesperson sees their own and the URL's `agent_id` is
    ignored") lives in ``ClientDirectory.scope``; the router only hands it the
    request's own value. Re-deriving it here would put a second copy of the
    own-scope rule in a router, which CONVENTIONS.md §2 forbids and §11 gives
    the reason for.
    """
    return ClientFilter(
        window=filters.window,
        agent_ids=directory.scope(principal, agent_id),
        scope=filters.scope,
        search=filters.search,
    )
