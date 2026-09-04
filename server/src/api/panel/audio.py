"""Audio playback with Range support (T43, UC-20, UC-24, N43).

**Range is mandatory.** ``Accept-Ranges: bytes`` on every response; a Range
request answers 206 with ``Content-Range``, an unsatisfiable one answers 416
with ``Content-Range: bytes */total``. Without it a twenty-minute recording
cannot be seeked, only downloaded.

**The panel cannot put an ``Authorization`` header on ``<audio src>``.** A plain
``<audio>`` element pointed at this route appears to work and then fails to
seek, because the browser issues its Range requests without the header. The
Service Worker bridge (T153) is what makes it work; the ``blob:`` fallback is
required too, and is what keeps a LAN ``http://`` demo working.

**Audit (UC-24):** one row per playback *start*. A seek is a Range above byte
zero and writes nothing, so scrubbing does not produce forty rows.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import StreamingResponse

from src.core.deps import PrincipalDep, SessionDep
from src.core.errors import ErrorCode, RangeNotSatisfiableError
from src.core.permissions import Perm, require_any_permission
from src.modules.audio.rules import parse_range_header
from src.modules.audio.service import AudioService

router = APIRouter(prefix="/calls", tags=["Audio"])

_play_any = require_any_permission(Perm.AUDIO_PLAY, Perm.AUDIO_PLAY_OWN)

#: 64 KiB. Large enough that a 3 MB file is fifty writes, small enough that a
#: cancelled seek does not push megabytes into a socket nobody is reading.
STREAM_CHUNK = 64 * 1024


def _stream(handle, remaining: int):
    """Yield the slice, then close. A generator so nothing is buffered whole."""

    def generate():
        try:
            left = remaining
            while left > 0:
                block = handle.read(min(STREAM_CHUNK, left))
                if not block:
                    break
                left -= len(block)
                yield block
        finally:
            handle.close()

    return generate()


@router.get("/{call_id}/audio", dependencies=[Depends(_play_any)])
async def stream_audio(
    call_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
    download: bool = False,
    range_header: str | None = Header(default=None, alias="Range"),
) -> Response:
    """Stream a recording. 200 whole, 206 partial, 410 once retention took it."""
    service = AudioService(session)
    source = await service.playback_source(principal, call_id)
    size = source.stat.bytes

    try:
        window = parse_range_header(range_header, size)
    except ValueError as exc:
        # 416 must carry the total, or the player cannot recover by asking for
        # a range it can satisfy.
        raise RangeNotSatisfiableError(
            ErrorCode.RANGE_NOT_SATISFIABLE, detail={"size": size}
        ) from exc

    disposition = (
        f'attachment; filename="{source.filename}"'
        if download
        else f'inline; filename="{source.filename}"'
    )
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": disposition,
        "Cache-Control": "private, no-store",
    }

    await service.record_playback(
        principal,
        call_id,
        download=download,
        range_start=window[0] if window else None,
        ip=request.client.host if request.client else None,
    )

    if window is None:
        handle = service.open_range(source.audio, 0, None)
        headers["Content-Length"] = str(size)
        return StreamingResponse(
            _stream(handle, size), media_type=source.content_type, headers=headers
        )

    start, end = window
    length = end - start + 1
    handle = service.open_range(source.audio, start, end)
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(length)
    return StreamingResponse(
        _stream(handle, length),
        status_code=206,
        media_type=source.content_type,
        headers=headers,
    )
