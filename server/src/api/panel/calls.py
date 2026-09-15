"""Panel call list and detail (T25's other half, T45, T46, T47).

``sales`` reaches these routes through ``calls:read:own`` and the **service
query** narrows the rows. A second permission check would put a business rule in
a router, and a wrong owner returns **404, not 403** — 403 confirms the row
exists, which tells a salesperson that a colleague spoke to a given number.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from src.core import clock
from src.core.clock import TASHKENT
from src.core.deps import PrincipalDep, SessionDep
from src.core.enums import (
    AppVariant,
    AudioMissingReason,
    CallDirection,
    CallDisposition,
    CallType,
    CaptureRoute,
)
from src.core.errors import ErrorCode, MethodNotAllowedError
from src.core.pagination import MAX_LIMIT_CALLS, Cursor, clamp_limit
from src.core.permissions import Perm, require_any_permission, require_permission
from src.modules.audio.archive import stream_archive
from src.modules.audio.service import MANIFEST_NAME, AudioService
from src.modules.calls.schemas import (
    CallFilters,
    CallListResponse,
    CallResponse,
    CallStatsPeriod,
    CallStatsResponse,
    UpdateCallNoteRequest,
)
from src.modules.calls.service import CallService

router = APIRouter(prefix="/calls", tags=["Calls"])

#: The export's columns, in order. No audio, and no column a role may not see —
#: the scoped query already removed the rows, and there is no agent *name* here
#: because a sales export must not carry a colleague's identity.
EXPORT_COLUMNS = (
    "id",
    "seq",
    "started_at",
    "answered_at",
    "ended_at",
    "direction",
    "disposition",
    "call_type",
    "remote_number",
    "contact_name",
    "duration_sec",
    "has_audio",
    "audio_missing_reason",
    "app_version",
    "app_variant",
    "received_at",
)


def _csv_cell(call, column: str) -> str:
    """One field, escaped for a semicolon-delimited file."""
    value = getattr(call, column, None)
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(getattr(value, "value", value))
    if any(character in text for character in ';"\r\n'):
        return '"' + text.replace('"', '""') + '"'
    return text

_read_any = require_any_permission(Perm.CALLS_READ, Perm.CALLS_READ_OWN)


def call_filters(
    agent_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    number_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    installation_id: uuid.UUID | None = None,
    direction: CallDirection | None = None,
    disposition: CallDisposition | None = None,
    call_type: CallType | None = None,
    has_audio: bool | None = None,
    audio_missing_reason: Annotated[list[AudioMissingReason] | None, Query()] = None,
    capture_route: Annotated[list[CaptureRoute] | None, Query()] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    remote_number: str | None = None,
    q: str | None = None,
    min_duration_sec: int | None = None,
    max_duration_sec: int | None = None,
    device_model: str | None = None,
    app_variant: AppVariant | None = None,
) -> CallFilters:
    """SPEC §4.7's filter set, as one dependency.

    One object, so the list and the export cannot drift: UC-22 requires the
    export's row count to equal the count on screen for the same filter, and
    the only way to be sure is for both to build the query the same way.
    """
    return CallFilters(
        agent_id=agent_id,
        number_id=number_id,
        installation_id=installation_id,
        direction=direction,
        disposition=disposition,
        call_type=call_type,
        has_audio=has_audio,
        audio_missing_reason=audio_missing_reason,
        capture_route=capture_route,
        date_from=date_from,
        date_to=date_to,
        remote_number=remote_number,
        q=q,
        min_duration_sec=min_duration_sec,
        max_duration_sec=max_duration_sec,
        device_model=device_model,
        app_variant=app_variant,
    )


FiltersDep = Annotated[CallFilters, Depends(call_filters)]


@router.get("", response_model=CallListResponse, dependencies=[Depends(_read_any)])
async def list_calls(
    principal: PrincipalDep,
    session: SessionDep,
    filters: FiltersDep,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT_CALLS),
    cursor: str | None = None,
    with_total: bool = False,
    sort: Literal["received_at", "started_at", "duration_sec"] = "received_at",
    order: Literal["asc", "desc"] = "desc",
) -> CallListResponse:
    """A cursor page. Default and guaranteed-stable sort is ``received_at DESC``.

    Keyset, not offset: no row that existed when paging started is skipped or
    returned twice, which is what UC-19 asks for and what an OFFSET cannot give
    while calls keep arriving. **Every sort pairs with ``id``**, or paging
    duplicates the rows whose sort values tie — and duration ties constantly.
    """
    page = await CallService(session).list(
        principal=principal,
        limit=clamp_limit(limit, MAX_LIMIT_CALLS),
        cursor=Cursor.decode(cursor) if cursor else None,
        with_total=with_total,
        filters=filters,
        sort=sort,
        order=order,
    )
    return CallListResponse(
        items=page.items,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        total=page.total,
    )


@router.get("/export", dependencies=[Depends(require_permission(Perm.REPORTS_EXPORT))])
async def export_calls(
    principal: PrincipalDep, session: SessionDep, filters: FiltersDep
) -> StreamingResponse:
    """Streaming CSV for the same filter as the list (T48, UC-22).

    UTF-8 **with a BOM** and a ``;`` delimiter: Excel in a ru/uz locale renders
    a comma-separated UTF-8 file as one column, and the person who opens it has
    no way to know that is what happened.

    A ``sales`` export is own-rows-only and carries no other agent's name,
    because the same scoped query builds it.
    """
    service = CallService(session)

    async def rows():
        yield "\ufeff" + ";".join(EXPORT_COLUMNS) + "\r\n"
        async for call in service.stream_export(principal, filters):
            yield ";".join(_csv_cell(call, column) for column in EXPORT_COLUMNS) + "\r\n"

    return StreamingResponse(
        rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="calls.csv"'},
    )


@router.get(
    "/audio-archive",
    dependencies=[Depends(require_permission(Perm.AUDIO_DOWNLOAD))],
)
async def download_audio_archive(
    principal: PrincipalDep,
    session: SessionDep,
    filters: FiltersDep,
    request: Request,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT_CALLS),
    cursor: str | None = None,
    sort: Literal["received_at", "started_at", "duration_sec"] = "received_at",
    order: Literal["asc", "desc"] = "desc",
) -> StreamingResponse:
    """The recordings of **the page the reader is looking at**, as one ZIP.

    Deliberately a page and not a filter. The button sits under fifty rows and
    hands over those fifty rows; "everything since January" is a different
    product decision, and one whose size nobody can see before pressing it.
    It therefore takes the same ``cursor``, ``limit`` and sort as the list, so
    the archive and the screen cannot disagree about which calls they mean.

    ``limit`` is clamped exactly as the list clamps it, so hand-editing the URL
    widens nothing.

    Every recording it contains is one this principal may already download one
    at a time: the page comes from the same scoped query, so own-scope means
    own recordings. **One audit row per archive**, not one per file — the
    question this action answers is "who took a copy, and of what", and seven
    hundred rows would bury the log the way open alerts once buried the alerts
    page.
    """
    page = await CallService(session).list(
        principal=principal,
        limit=clamp_limit(limit, MAX_LIMIT_CALLS),
        cursor=Cursor.decode(cursor) if cursor else None,
        filters=filters,
        sort=sort,
        order=order,
    )
    audio = AudioService(session)
    plan = await audio.archive_for(page.items)
    await audio.record_archive_download(
        principal,
        calls=len(page.items),
        files=len(plan.entries),
        ip=request.client.host if request.client else None,
    )

    stamp = clock.now().astimezone(TASHKENT).strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        stream_archive(plan, MANIFEST_NAME),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="bonvicall-{stamp}.zip"'
        },
    )


@router.get("/stats", response_model=CallStatsResponse, dependencies=[Depends(_read_any)])
async def call_stats(
    principal: PrincipalDep,
    session: SessionDep,
    period: CallStatsPeriod = "week",
    date_from: date | None = None,
    date_to: date | None = None,
) -> CallStatsResponse:
    """Calls per day (or per month) per class, for the dashboard's chart.

    Declared **above** ``/{call_id}``: that route takes a UUID, so a request
    for ``/calls/stats`` matched against it answers 422 rather than reaching
    this one.

    A preset window is the server's arithmetic and not the caller's — the
    browser asking for "a year" in its own timezone would draw a chart whose
    edges disagree with every other date in the product (D-10) — so
    ``date_from``/``date_to`` are read only for ``period=custom``, and both are
    required there. The granularity of a custom range is derived from its span,
    not chosen: two dates are the question, and a second control before an
    answer is one decision too many.

    Own-scope applies exactly as it does to the list, because it is the same
    query.
    """
    return await CallService(session).stats(
        principal, period, date_from=date_from, date_to=date_to
    )


@router.get("/{call_id}", response_model=CallResponse, dependencies=[Depends(_read_any)])
async def get_call(
    call_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> CallResponse:
    """404 for a call that belongs to another agent."""
    service = CallService(session)
    return await service.view(await service.get(principal, call_id))


@router.patch(
    "/{call_id}",
    response_model=CallResponse,
    dependencies=[Depends(require_permission(Perm.CALLS_NOTE))],
)
async def update_call_note(
    call_id: uuid.UUID,
    payload: UpdateCallNoteRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> CallResponse:
    """The note and nothing else — every other field is the device's."""
    service = CallService(session)
    return await service.view(
        await service.set_note(principal, call_id, payload.note)
    )


@router.delete("/{call_id}")
async def delete_call(call_id: uuid.UUID, principal: PrincipalDep) -> None:
    """**405 for every role, including admin** (UC-26, T45).

    The route exists precisely so that the refusal is explicit and testable.
    Without it a DELETE would 405 from the router with FastAPI's own body, and
    "nobody can delete a call" would be an absence rather than a decision.
    Only the retention job removes audio, and it never removes a call.

    **No permission dependency on purpose.** T45 asserts 405 for all five
    roles, so the refusal has to outrank authorisation: a role that cannot read
    calls getting 403 here would mean the answer depends on who is asking, and
    it does not.
    A caller with no token still gets 401 — that is the principal dependency.
    """
    raise MethodNotAllowedError(ErrorCode.DELETE_NOT_ALLOWED)


@router.delete("/{call_id}/audio")
async def delete_call_audio(call_id: uuid.UUID, principal: PrincipalDep) -> None:
    """405 for every role, for the same reason (UC-26)."""
    raise MethodNotAllowedError(ErrorCode.DELETE_NOT_ALLOWED)
