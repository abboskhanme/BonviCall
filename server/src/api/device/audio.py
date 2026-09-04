"""The resumable audio upload protocol (T41, T44; SPEC §4.5).

Three steps and a probe. Byte-offset resumable, no third-party dependency on
either side, and reassembled by appending to one ``.part`` file — because the
case that matters is a 90-minute call on a bad edge connection, and a
``multipart/form-data`` re-POST never completes it.

Step 1 is also the **attribution gate** (N28, T44): a recording whose window
does not overlap a registered-number call on this installation is refused and
nothing is written. The employee's own phone holds their private recordings in
the same folder, so this is a privacy boundary and not a validation nicety.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Request, status

from src.api.device.deps import ActiveInstallationDep
from src.core.deps import SessionDep
from src.core.errors import ErrorCode, PayloadTooLargeError
from src.modules.audio.schemas import (
    ChunkAcceptedOut,
    CommitOut,
    OpenUploadIn,
    OpenUploadOut,
    UploadStatusOut,
)
from src.modules.audio.service import AudioService

router = APIRouter(tags=["Device audio"])

#: Hard ceiling on a single chunk body, independent of the configured size.
#: A request larger than this is refused before it is read into memory.
ABSOLUTE_MAX_CHUNK_BYTES = 8 * 1024 * 1024


@router.post(
    "/calls/{client_call_id}/audio/session",
    response_model=OpenUploadOut,
    status_code=status.HTTP_201_CREATED,
)
async def open_session(
    client_call_id: uuid.UUID,
    payload: OpenUploadIn,
    installation: ActiveInstallationDep,
    session: SessionDep,
) -> OpenUploadOut:
    """Step 1. Repeating it returns the **existing** session — the resume path.

    Keyed on ``client_call_id`` rather than the server id, so the device can
    start uploading without having seen a response first.
    """
    upload = await AudioService(session).open_session(
        installation, client_call_id, payload
    )
    return OpenUploadOut(
        upload_id=upload.id,
        chunk_size=upload.chunk_size,
        received_bytes=upload.received_bytes,
        expires_at=upload.expires_at,
    )


@router.put("/audio/{upload_id}/chunk", response_model=ChunkAcceptedOut)
async def put_chunk(
    upload_id: uuid.UUID,
    request: Request,
    installation: ActiveInstallationDep,
    session: SessionDep,
    offset: int = 0,
    x_chunk_sha256: str | None = Header(default=None),
) -> ChunkAcceptedOut:
    """Step 2. ``409`` carries the expected offset so the client seeks."""
    body = await request.body()
    if len(body) > ABSOLUTE_MAX_CHUNK_BYTES:
        raise PayloadTooLargeError(
            ErrorCode.PAYLOAD_TOO_LARGE,
            detail={"max_chunk_bytes": ABSOLUTE_MAX_CHUNK_BYTES},
        )
    received = await AudioService(session).append_chunk(
        installation, upload_id, offset, body, x_chunk_sha256
    )
    return ChunkAcceptedOut(received_bytes=received)


@router.post("/audio/{upload_id}/commit", response_model=CommitOut)
async def commit(
    upload_id: uuid.UUID, installation: ActiveInstallationDep, session: SessionDep
) -> CommitOut:
    """Step 3. Idempotent — and only after this does the device delete its copy."""
    audio, duration_mismatch = await AudioService(session).commit(
        installation, upload_id
    )
    return CommitOut(
        audio_id=audio.id,
        sha256=audio.sha256,
        bytes=audio.bytes,
        stored=True,
        duration_mismatch=duration_mismatch,
    )


@router.get("/audio/{upload_id}", response_model=UploadStatusOut)
async def probe(
    upload_id: uuid.UUID, installation: ActiveInstallationDep, session: SessionDep
) -> UploadStatusOut:
    """Step 4. How far did we get, after a crash."""
    upload = await AudioService(session).probe(installation, upload_id)
    return UploadStatusOut(
        upload_id=upload.id,
        status=upload.status,
        received_bytes=upload.received_bytes,
        bytes_total=upload.bytes_total,
        expires_at=upload.expires_at,
    )
