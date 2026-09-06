"""Device call ingest (T25, UC-12, SPEC §4.4).

**The whole of M1 hangs on this route.** Its contract:

* the batch is idempotent on the device's own ``client_call_id``, so a resend
  after a lost response produces no second row and the same server id;
* failure is **per item**, never per batch — a batch that fails wholesale is a
  batch the device retries forever;
* the response is always ``200``. A first write and a replay are
  indistinguishable to the client, which is exactly what UC-12 requires.

There is no version gate here on purpose (N34, SPEC §4.3): ingest accepts any
app version, forever. The refusal lives on ``POST /auth/refresh`` and fires only
once the phone's queue is empty.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import IO

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import StreamingResponse

from src.api.device.deps import ActiveInstallationDep
from src.core import clock
from src.core.deps import SessionDep
from src.core.errors import ErrorCode, RangeNotSatisfiableError
from src.core.pagination import Cursor, clamp_limit
from src.modules.audio.rules import parse_range_header
from src.modules.audio.service import AudioService
from src.modules.calls.schemas import (
    DeviceCallBatchIn,
    DeviceCallBatchOut,
    DeviceCallListOut,
)
from src.modules.calls.service import CallService, DeviceCallReadService

router = APIRouter(prefix="/calls", tags=["Device calls"])

#: A phone screen. The panel's 1 000-row pages are the panel's problem.
MAX_DEVICE_PAGE = 100

#: Read size for playback. Matches the panel's streamer.
STREAM_CHUNK_BYTES = 64 * 1024


def _stream(handle: IO[bytes], length: int) -> Iterator[bytes]:
    """Yield exactly ``length`` bytes, then close. Same as the panel's."""

    def generate() -> Iterator[bytes]:
        remaining = length
        with handle:
            while remaining > 0:
                chunk = handle.read(min(STREAM_CHUNK_BYTES, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return generate()


@router.post("", response_model=DeviceCallBatchOut)
async def ingest_calls(
    payload: DeviceCallBatchIn,
    installation: ActiveInstallationDep,
    session: SessionDep,
) -> DeviceCallBatchOut:
    """Batch upsert, at most 50 items.

    ``number_id`` and ``agent_id`` are resolved from the installation and the
    time-boxed assignment — never from the payload. The device does not get to
    say which number it is, and it does not get to move a call to another agent
    by re-sending it.
    """
    results = await CallService(session).ingest(installation, payload.calls)
    return DeviceCallBatchOut(results=results, server_time=clock.now())


@router.get("", response_model=DeviceCallListOut)
async def my_calls(
    installation: ActiveInstallationDep,
    session: SessionDep,
    limit: int = 50,
    cursor: str | None = None,
    since: datetime | None = None,
) -> DeviceCallListOut:
    """The employee's own calls, in the app, without a panel login (T59, UC-15).

    The client asked for this in one sentence: *"telefonda o'rnatiladigan appda
    ham shu xodim o'zining callarini ko'rishi va eshitishi mumkin bo'lsin —
    bizni tizimga kirib o'tirmaydi."*

    **Scoped by the installation's binding, not by a permission.** The device
    surface has been write-only until now and this is the first thing it hands
    back, so the scope is the design: a token's reach is the agent it is bound
    to, which is a property of the binding and not a grant anybody can widen.
    Narrowed in the query — never a filter the client applies to a wider
    response, because the client is the thing we cannot trust.

    No search, no filters, no notes. Every field here is also a field a lost
    handset carries.
    """
    items, next_cursor, has_more, total = await DeviceCallReadService(session).list(
        installation,
        clamp_limit(limit, maximum=MAX_DEVICE_PAGE),
        Cursor.decode(cursor) if cursor else None,
        since,
    )
    return DeviceCallListOut(
        items=items, next_cursor=next_cursor, has_more=has_more, total=total
    )


@router.get("/{call_id}/audio")
async def my_call_audio(
    call_id: uuid.UUID,
    installation: ActiveInstallationDep,
    session: SessionDep,
    request: Request,
    range_header: str | None = Header(default=None, alias="Range"),
) -> Response:
    """Play one of the employee's own recordings. Same rules as the panel.

    ``206`` with ``Content-Range`` for a ``Range`` request (N43): the player
    seeks, and seeking in a twenty-minute file must not mean downloading it over
    cellular. ``410`` once retention has taken it; ``404`` when there was never
    a recording — the list already told the app *why*, so it shows that instead
    of a dead control.

    A call belonging to another agent is **404**, from the scoped lookup. It is
    never 403: a 403 would tell whoever is holding this phone that the call
    exists and is somebody else's.
    """
    service = AudioService(session)
    source = await service.playback_source_for_device(installation, call_id)
    size = source.stat.bytes

    try:
        window = parse_range_header(range_header, size)
    except ValueError as exc:
        raise RangeNotSatisfiableError(
            ErrorCode.RANGE_NOT_SATISFIABLE, detail={"size": size}
        ) from exc

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{source.filename}"',
        # The employee's own recording is still a recording of a customer.
        "Cache-Control": "private, no-store",
    }
    await service.record_device_playback(
        installation,
        call_id,
        range_start=window[0] if window else None,
        ip=request.client.host if request.client else None,
    )

    if window is None:
        headers["Content-Length"] = str(size)
        return StreamingResponse(
            _stream(service.open_range(source.audio, 0, None), size),
            media_type=source.content_type,
            headers=headers,
        )

    start, end = window
    length = end - start + 1
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(length)
    return StreamingResponse(
        _stream(service.open_range(source.audio, start, end), length),
        status_code=206,
        media_type=source.content_type,
        headers=headers,
    )
