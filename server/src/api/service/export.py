"""The machine export (T51, T52; UC-29, SPEC §4.9, §5.4).

**A committed contract, not a convenience.** BonviZvonki's ingest adapter is
wired to these two routes in release 2, so a change here is a breaking change
for another product. Additive-only inside v1.

A ``service`` token cannot write anything, cannot read ``/users`` and cannot
read ``/audit`` — its scopes are checked in addition to the permission, so a
token issued for callbacks cannot read the export even though the role could.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from src.core.deps import PrincipalDep, SessionDep
from src.core.errors import ErrorCode, RangeNotSatisfiableError
from src.core.permissions import Perm, require_permission
from src.modules.audio.rules import parse_range_header
from src.modules.audio.service import AudioService
from src.modules.exports.schemas import ExportAgentsResponse, ExportCallsResponse
from src.modules.exports.service import MAX_EXPORT_LIMIT, ExportService

router = APIRouter(prefix="/export", tags=["Service export"])

STREAM_CHUNK = 64 * 1024


@router.get(
    "/calls",
    response_model=ExportCallsResponse,
    dependencies=[Depends(require_permission(Perm.EXPORT_READ))],
)
async def export_calls(
    session: SessionDep, since: int = 0, limit: int = MAX_EXPORT_LIMIT
) -> ExportCallsResponse:
    """``seq ASC`` with a ten-second settling window.

    The window is what makes "two consecutive full passes over an unchanging
    dataset return identical row sets" true rather than nearly true: ``seq``
    comes from a sequence, and a lower one can commit after a higher one.
    """
    items, next_since = await ExportService(session).calls(since=since, limit=limit)
    return ExportCallsResponse(items=items, next_since=next_since, count=len(items))


@router.get(
    "/agents",
    response_model=ExportAgentsResponse,
    dependencies=[Depends(require_permission(Perm.EXPORT_READ))],
)
async def export_agents(session: SessionDep) -> ExportAgentsResponse:
    """Agents with their number history — the mapping L3 got wrong."""
    items = await ExportService(session).agents()
    return ExportAgentsResponse(items=items, count=len(items))


@router.get(
    "/calls/{call_id}/audio",
    dependencies=[Depends(require_permission(Perm.EXPORT_AUDIO))],
)
async def export_audio(
    call_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
    range_header: str | None = Header(default=None, alias="Range"),
) -> StreamingResponse:
    """**Range is mandatory here too** (N43, §5.4 consequence 2).

    BonviZvonki streams audio rather than copying it, so 206 with
    ``Content-Range`` is the whole point. Every access writes an audit row with
    ``actor_type='service'``.
    """
    service = AudioService(session)
    source = await service.playback_source(principal, call_id)
    size = source.stat.bytes

    try:
        window = parse_range_header(range_header, size)
    except ValueError as exc:
        raise RangeNotSatisfiableError(
            ErrorCode.RANGE_NOT_SATISFIABLE, detail={"size": size}
        ) from exc

    await service.record_playback(
        principal,
        call_id,
        download=True,
        range_start=window[0] if window else None,
        ip=request.client.host if request.client else None,
    )

    start, end = window if window else (0, size - 1)
    length = end - start + 1
    handle = service.open_range(source.audio, start, end)

    def stream():
        try:
            left = length
            while left > 0:
                block = handle.read(min(STREAM_CHUNK, left))
                if not block:
                    break
                left -= len(block)
                yield block
        finally:
            handle.close()

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(length)}
    if window is not None:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        stream(),
        status_code=206 if window else 200,
        media_type=source.content_type,
        headers=headers,
    )
