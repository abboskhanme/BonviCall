"""The audio pipeline: upload, the attribution gate, playback (T41–T44).

Two of these are load-bearing and may not be weakened:
``test_audio_unmatched_rejected`` (CONVENTIONS.md §8 names it) and the
interrupted-resume test that proves an identical SHA-256 with no bytes re-sent.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from src.core.enums import AuditAction, CallDisposition, UploadStatus
from src.modules.audio.models import AudioUploadSessionModel, CallAudioModel
from src.modules.audit.models import AuditLogModel

pytestmark = pytest.mark.asyncio

#: ~4 KB of pretend Opus. Enough to split into chunks, small enough to hash.
PAYLOAD = b"OggS" + bytes(range(256)) * 16
SHA = hashlib.sha256(PAYLOAD).hexdigest()


def session_body(recorded_at: datetime, **overrides) -> dict:
    body = {
        "bytes_total": len(PAYLOAD),
        "sha256": SHA,
        "codec": "opus",
        "container": "ogg",
        "sample_rate_hz": 16000,
        "channels": 1,
        "bitrate_bps": 24000,
        "duration_ms": 120_000,
        "capture_route": "oem_file_harvest",
        "capture_route_detail": "Recordings/Call",
        "recorded_at": recorded_at.isoformat(),
    }
    body.update(overrides)
    return body


async def _call_and_device(call_factory, installation_factory, device_client_factory, **kw):
    installation = await installation_factory()
    started = datetime.now(UTC) - timedelta(minutes=5)
    # An unanswered call must carry duration 0 — the CHECK constraint says so,
    # so the helper must not force one in.
    answered = kw.get("disposition", CallDisposition.ANSWERED) is CallDisposition.ANSWERED
    call = await call_factory(
        installation=installation,
        started_at=started,
        ended_at=started + timedelta(seconds=120),
        duration_sec=120 if answered else 0,
        **kw,
    )
    client = await device_client_factory(installation)
    return call, client


async def _upload(client, call, payload: bytes = PAYLOAD, chunks: int = 2) -> dict:
    opened = await client.post(
        f"/api/device/v1/calls/{call.client_call_id}/audio/session",
        json=session_body(call.started_at + timedelta(seconds=125)),
    )
    assert opened.status_code == 201, opened.text
    upload_id = opened.json()["upload_id"]
    size = len(payload) // chunks + 1
    offset = 0
    while offset < len(payload):
        block = payload[offset : offset + size]
        response = await client.put(
            f"/api/device/v1/audio/{upload_id}/chunk?offset={offset}",
            content=block,
            headers={"X-Chunk-SHA256": hashlib.sha256(block).hexdigest()},
        )
        assert response.status_code == 200, response.text
        offset += len(block)
    return {"upload_id": upload_id}


# --- The attribution gate (T44, N28) ---------------------------------------


async def test_audio_unmatched_rejected(
    db, call_factory, installation_factory, device_client_factory
) -> None:
    """**Load-bearing (CONVENTIONS.md §8).** Do not delete, skip or weaken.

    The OEM recordings folder on the employee's own phone holds their private
    calls. A file whose window does not overlap a registered-number call is
    refused and **the bytes are never written**.
    """
    call, client = await _call_and_device(
        call_factory, installation_factory, device_client_factory
    )
    response = await client.post(
        f"/api/device/v1/calls/{call.client_call_id}/audio/session",
        json=session_body(call.started_at - timedelta(hours=3)),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "audio_not_attributable"
    assert await db.scalar(sa.select(sa.func.count()).select_from(AudioUploadSessionModel)) == 0
    await db.refresh(call)
    assert call.audio_missing_reason.value == "attribution_failed", (
        "a rising count here means the harvest window is mistuned, which is "
        "the difference between a bug and a privacy incident"
    )


async def test_audio_for_an_unanswered_call_is_rejected(
    db, call_factory, installation_factory, device_client_factory
) -> None:
    """An unanswered call had no conversation, so a file claiming to be one
    did not come from it."""
    call, client = await _call_and_device(
        call_factory,
        installation_factory,
        device_client_factory,
        disposition=CallDisposition.NO_ANSWER,
    )
    response = await client.post(
        f"/api/device/v1/calls/{call.client_call_id}/audio/session",
        json=session_body(call.started_at + timedelta(seconds=10)),
    )
    assert response.status_code == 409


async def test_audio_for_another_installations_call_is_404(
    call_factory, installation_factory, device_client_factory
) -> None:
    call, _ = await _call_and_device(
        call_factory, installation_factory, device_client_factory
    )
    other = await installation_factory()
    stranger = await device_client_factory(other)
    response = await stranger.post(
        f"/api/device/v1/calls/{call.client_call_id}/audio/session",
        json=session_body(call.started_at + timedelta(seconds=10)),
    )
    assert response.status_code == 404


async def test_audio_before_its_call_arrives_asks_the_app_to_retry(
    installation_factory, device_client_factory
) -> None:
    """Metadata before audio, always: the cheap and important half lands first."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    response = await client.post(
        f"/api/device/v1/calls/{uuid.uuid4()}/audio/session",
        json=session_body(datetime.now(UTC)),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "call_not_found"
    assert response.json()["error"]["detail"]["retry_after_ms"] > 0


# --- The resumable protocol (T41) ------------------------------------------


async def test_a_chunked_upload_commits_with_the_declared_checksum(
    db, call_factory, installation_factory, device_client_factory
) -> None:
    call, client = await _call_and_device(
        call_factory, installation_factory, device_client_factory
    )
    opened = await _upload(client, call, chunks=4)
    committed = await client.post(
        f"/api/device/v1/audio/{opened['upload_id']}/commit"
    )
    assert committed.status_code == 200
    assert committed.json()["sha256"] == SHA
    assert committed.json()["bytes"] == len(PAYLOAD)

    await db.refresh(call)
    assert call.has_audio is True
    assert call.audio_missing_reason is None, "the CHECK constraint depends on this"


async def test_an_interrupted_upload_resumes_without_resending_bytes(
    db, call_factory, installation_factory, device_client_factory
) -> None:
    """UC-14/N11. The case is a 90-minute call on a bad edge connection: a
    ``multipart/form-data`` re-POST never completes it."""
    call, client = await _call_and_device(
        call_factory, installation_factory, device_client_factory
    )
    half = len(PAYLOAD) // 2
    opened = await client.post(
        f"/api/device/v1/calls/{call.client_call_id}/audio/session",
        json=session_body(call.started_at + timedelta(seconds=125)),
    )
    upload_id = opened.json()["upload_id"]
    await client.put(
        f"/api/device/v1/audio/{upload_id}/chunk?offset=0", content=PAYLOAD[:half]
    )

    # The app restarts and re-opens: it gets the same session and the true
    # offset, not a new session starting from zero.
    resumed = await client.post(
        f"/api/device/v1/calls/{call.client_call_id}/audio/session",
        json=session_body(call.started_at + timedelta(seconds=125)),
    )
    assert resumed.json()["upload_id"] == upload_id
    assert resumed.json()["received_bytes"] == half

    await client.put(
        f"/api/device/v1/audio/{upload_id}/chunk?offset={half}", content=PAYLOAD[half:]
    )
    committed = await client.post(f"/api/device/v1/audio/{upload_id}/commit")
    assert committed.json()["sha256"] == SHA, "identical SHA-256 after a resume"


async def test_a_wrong_offset_is_409_carrying_the_expected_one(
    call_factory, installation_factory, device_client_factory
) -> None:
    """The client seeks and retries; it never restarts."""
    call, client = await _call_and_device(
        call_factory, installation_factory, device_client_factory
    )
    opened = await client.post(
        f"/api/device/v1/calls/{call.client_call_id}/audio/session",
        json=session_body(call.started_at + timedelta(seconds=125)),
    )
    upload_id = opened.json()["upload_id"]
    await client.put(
        f"/api/device/v1/audio/{upload_id}/chunk?offset=0", content=PAYLOAD[:100]
    )
    response = await client.put(
        f"/api/device/v1/audio/{upload_id}/chunk?offset=9999", content=b"xxx"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "chunk_offset_mismatch"
    assert response.json()["error"]["detail"]["expected_offset"] == 100


async def test_a_bad_chunk_checksum_leaves_the_offset_alone(
    call_factory, installation_factory, device_client_factory
) -> None:
    """Writing a corrupt chunk would poison the whole file."""
    call, client = await _call_and_device(
        call_factory, installation_factory, device_client_factory
    )
    opened = await client.post(
        f"/api/device/v1/calls/{call.client_call_id}/audio/session",
        json=session_body(call.started_at + timedelta(seconds=125)),
    )
    upload_id = opened.json()["upload_id"]
    bad = await client.put(
        f"/api/device/v1/audio/{upload_id}/chunk?offset=0",
        content=PAYLOAD[:100],
        headers={"X-Chunk-SHA256": "0" * 64},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "chunk_checksum_mismatch"
    probe = await client.get(f"/api/device/v1/audio/{upload_id}")
    assert probe.json()["received_bytes"] == 0


async def test_a_whole_file_checksum_mismatch_aborts_the_session(
    db, call_factory, installation_factory, device_client_factory
) -> None:
    """The reassembled file is not the file the device hashed."""
    call, client = await _call_and_device(
        call_factory, installation_factory, device_client_factory
    )
    opened = await client.post(
        f"/api/device/v1/calls/{call.client_call_id}/audio/session",
        json=session_body(call.started_at + timedelta(seconds=125)),
    )
    upload_id = opened.json()["upload_id"]
    corrupt = b"\x00" * len(PAYLOAD)
    await client.put(
        f"/api/device/v1/audio/{upload_id}/chunk?offset=0", content=corrupt
    )
    response = await client.post(f"/api/device/v1/audio/{upload_id}/commit")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "checksum_mismatch"
    upload = await db.get(AudioUploadSessionModel, uuid.UUID(upload_id))
    assert upload.status is UploadStatus.ABORTED


async def test_committing_twice_returns_the_same_answer(
    db, call_factory, installation_factory, device_client_factory
) -> None:
    """The device may not have seen the first response, and must not be made
    to re-upload 3 MB to find out (N11)."""
    call, client = await _call_and_device(
        call_factory, installation_factory, device_client_factory
    )
    opened = await _upload(client, call)
    first = await client.post(f"/api/device/v1/audio/{opened['upload_id']}/commit")
    second = await client.post(f"/api/device/v1/audio/{opened['upload_id']}/commit")
    assert first.json() == second.json()
    assert await db.scalar(sa.select(sa.func.count()).select_from(CallAudioModel)) == 1


async def test_a_duration_that_disagrees_with_the_call_log_is_flagged(
    db, call_factory, installation_factory, device_client_factory
) -> None:
    """UC-14. Not an error — a two-minute gap means a different call."""
    call, client = await _call_and_device(
        call_factory, installation_factory, device_client_factory
    )
    opened = await client.post(
        f"/api/device/v1/calls/{call.client_call_id}/audio/session",
        json=session_body(
            call.started_at + timedelta(seconds=125), duration_ms=10_000
        ),
    )
    upload_id = opened.json()["upload_id"]
    await client.put(
        f"/api/device/v1/audio/{upload_id}/chunk?offset=0", content=PAYLOAD
    )
    committed = await client.post(f"/api/device/v1/audio/{upload_id}/commit")
    await db.refresh(call)
    assert call.audio_duration_mismatch is True
    # And the handset is told. A device whose recorder truncates every call
    # learns it here or not at all — the flag was once hardcoded to false,
    # which made the whole field decorative.
    assert committed.json()["duration_mismatch"] is True
    # Idempotent in the flag too, not just the id: the device may only ever
    # see the second response.
    replay = await client.post(f"/api/device/v1/audio/{upload_id}/commit")
    assert replay.json()["duration_mismatch"] is True


async def test_upload_needs_a_verified_installation(
    installation_factory, device_client_factory
) -> None:
    from src.core.enums import InstallationStatus

    installation = await installation_factory(status=InstallationStatus.PENDING)
    client = await device_client_factory(installation)
    response = await client.post(
        f"/api/device/v1/calls/{uuid.uuid4()}/audio/session",
        json=session_body(datetime.now(UTC)),
    )
    assert response.status_code == 403


# --- Playback with Range (T43, UC-20, N43) ---------------------------------


async def test_playback_without_a_token_returns_401_and_no_audio(
    client, audio_factory
) -> None:
    """UC-20 says "401 and zero bytes"; N35 says every non-2xx carries the
    envelope. Both cannot be literally true, and the envelope wins.

    The criterion is about **audio** bytes, and none leave: the response is the
    JSON error body and nothing else. A literally empty 401 would also break
    the Android client, which parses one envelope shape and cannot tell an
    empty body from a truncated one.
    """
    audio = await audio_factory(payload=PAYLOAD)
    response = await client.get(f"/api/v1/calls/{audio.call_id}/audio")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "unauthorized"
    assert PAYLOAD not in response.content
    assert b"OggS" not in response.content


async def test_playback_without_a_range_returns_the_whole_body(
    manager, audio_factory
) -> None:
    audio = await audio_factory(payload=PAYLOAD)
    response = await manager.get(f"/api/v1/calls/{audio.call_id}/audio")
    assert response.status_code == 200
    assert response.content == PAYLOAD
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"].startswith("audio/ogg")
    assert response.headers["content-disposition"].startswith("inline")


async def test_a_range_request_returns_206_with_content_range(
    manager, audio_factory
) -> None:
    """N43. Without this the panel can download a recording but not seek it."""
    audio = await audio_factory(payload=PAYLOAD)
    response = await manager.get(
        f"/api/v1/calls/{audio.call_id}/audio", headers={"Range": "bytes=100-199"}
    )
    assert response.status_code == 206
    assert response.content == PAYLOAD[100:200]
    assert response.headers["content-range"] == f"bytes 100-199/{len(PAYLOAD)}"
    assert response.headers["content-length"] == "100"


async def test_an_open_ended_range_runs_to_the_end(manager, audio_factory) -> None:
    audio = await audio_factory(payload=PAYLOAD)
    response = await manager.get(
        f"/api/v1/calls/{audio.call_id}/audio", headers={"Range": "bytes=4000-"}
    )
    assert response.status_code == 206
    assert response.content == PAYLOAD[4000:]


async def test_an_unsatisfiable_range_is_416(manager, audio_factory) -> None:
    audio = await audio_factory(payload=PAYLOAD)
    response = await manager.get(
        f"/api/v1/calls/{audio.call_id}/audio", headers={"Range": "bytes=99999-"}
    )
    assert response.status_code == 416


async def test_download_sets_an_attachment_disposition(manager, audio_factory) -> None:
    audio = await audio_factory(payload=PAYLOAD)
    response = await manager.get(f"/api/v1/calls/{audio.call_id}/audio?download=true")
    assert response.headers["content-disposition"].startswith("attachment")


async def test_retention_deleted_audio_is_410_not_404_or_500(
    db, manager, audio_factory
) -> None:
    """UC-26: never a 500, never an empty 200."""
    from src.modules.audio.service import AudioService

    audio = await audio_factory(payload=PAYLOAD)
    call = audio.call_id
    await db.refresh(audio)
    audio.recorded_at = datetime.now(UTC) - timedelta(days=800)
    await db.flush()

    deleted = await AudioService(db).apply_retention()
    assert deleted == 1

    response = await manager.get(f"/api/v1/calls/{call}/audio")
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "audio_expired"


async def test_retention_keeps_the_row_and_the_call(db, audio_factory) -> None:
    """"There was a recording and it expired" must stay answerable (UC-26)."""
    from src.modules.audio.service import AudioService

    audio = await audio_factory(payload=PAYLOAD)
    audio.recorded_at = datetime.now(UTC) - timedelta(days=800)
    await db.flush()

    await AudioService(db).apply_retention()
    await db.refresh(audio)
    assert audio.deleted_at is not None
    assert audio.deleted_reason == "retention"
    assert await db.scalar(sa.select(sa.func.count()).select_from(CallAudioModel)) == 1


async def test_recent_audio_survives_retention(db, audio_factory) -> None:
    from src.modules.audio.service import AudioService

    audio = await audio_factory(payload=PAYLOAD)
    assert await AudioService(db).apply_retention() == 0
    await db.refresh(audio)
    assert audio.deleted_at is None


async def test_another_agents_audio_is_404_not_403(sales, audio_factory) -> None:
    """UC-21: 403 would confirm the recording exists."""
    audio = await audio_factory(payload=PAYLOAD)
    response = await sales.get(f"/api/v1/calls/{audio.call_id}/audio")
    assert response.status_code == 404


async def test_a_salesperson_can_play_their_own_audio(
    db, sales, audio_factory, call_factory, installation_factory
) -> None:
    from src.modules.agents.models import AgentModel

    own_agent = await db.get(AgentModel, sales.principal.agent_id)
    installation = await installation_factory(agent=own_agent)
    call = await call_factory(
        installation=installation, has_audio=True, audio_missing_reason=None
    )
    await audio_factory(call=call, payload=PAYLOAD)
    response = await sales.get(f"/api/v1/calls/{call.id}/audio")
    assert response.status_code == 200


async def test_a_role_without_audio_play_never_reaches_a_recording(
    service_token, audio_factory
) -> None:
    """The machine token reads audio through the export route, not this one."""
    audio = await audio_factory(payload=PAYLOAD)
    response = await service_token.get(f"/api/v1/calls/{audio.call_id}/audio")
    assert response.status_code == 403


# --- Playback auditing (UC-24) ---------------------------------------------


async def _audio_play_rows(db) -> int:
    return await db.scalar(
        sa.select(sa.func.count())
        .select_from(AuditLogModel)
        .where(AuditLogModel.action == AuditAction.AUDIO_PLAY)
    )


async def test_one_audit_row_per_playback_start(db, manager, audio_factory) -> None:
    audio = await audio_factory(payload=PAYLOAD)
    await manager.get(f"/api/v1/calls/{audio.call_id}/audio")
    assert await _audio_play_rows(db) == 1


async def test_seeking_a_long_file_adds_no_audit_rows(
    db, manager, audio_factory
) -> None:
    """UC-24's acceptance criterion: scrubbing must not make forty rows."""
    audio = await audio_factory(payload=PAYLOAD)
    await manager.get(f"/api/v1/calls/{audio.call_id}/audio")
    for start in (100, 900, 2000, 3500):
        await manager.get(
            f"/api/v1/calls/{audio.call_id}/audio",
            headers={"Range": f"bytes={start}-{start + 99}"},
        )
    assert await _audio_play_rows(db) == 1


async def test_a_range_starting_at_zero_still_counts_as_a_start(
    db, manager, audio_factory
) -> None:
    """That is what a player's first request looks like."""
    audio = await audio_factory(payload=PAYLOAD)
    await manager.get(
        f"/api/v1/calls/{audio.call_id}/audio", headers={"Range": "bytes=0-99"}
    )
    assert await _audio_play_rows(db) == 1


async def test_a_download_always_writes_its_own_row(db, manager, audio_factory) -> None:
    audio = await audio_factory(payload=PAYLOAD)
    await manager.get(f"/api/v1/calls/{audio.call_id}/audio?download=true")
    rows = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AuditLogModel)
        .where(AuditLogModel.action == AuditAction.AUDIO_DOWNLOAD)
    )
    assert rows == 1


async def test_the_storage_report_is_true_before_the_nightly_job_has_run(
    db, admin, call_factory, installation_factory, device_client_factory
) -> None:
    """It answered "0 bytes" on a server holding recordings, which is worse
    than empty: it is false in the direction that says the volume is fine.

    The daily snapshots are the growth curve and only they can give it. Today's
    total is a ``SUM`` over the rows, which is what the nightly job runs anyway.
    """
    call, client = await _call_and_device(
        call_factory, installation_factory, device_client_factory
    )
    opened = await _upload(client, call)
    await client.post(f"/api/device/v1/audio/{opened['upload_id']}/commit")

    body = (await admin.get("/api/v1/reports/storage")).json()
    assert body["audio_files"] == 1
    assert body["audio_bytes_total"] == len(PAYLOAD)
    # No snapshot has been written, so there is no growth rate to project from.
    assert body["history"] == []
    assert body["projected_bytes_12m"] == len(PAYLOAD)


async def test_retention_deleted_audio_stops_counting_against_the_volume(
    db, admin, call_factory, installation_factory, device_client_factory
) -> None:
    """Those bytes are off the disk; counting them would overstate usage and
    make the 250 GB provision look tighter than it is."""
    call, client = await _call_and_device(
        call_factory, installation_factory, device_client_factory
    )
    opened = await _upload(client, call)
    await client.post(f"/api/device/v1/audio/{opened['upload_id']}/commit")

    audio = await db.scalar(sa.select(CallAudioModel))
    audio.recorded_at = datetime.now(UTC) - timedelta(days=800)
    await db.flush()
    from src.modules.audio.service import AudioService

    await AudioService(db).apply_retention()

    body = (await admin.get("/api/v1/reports/storage")).json()
    assert body["audio_files"] == 0
    assert body["audio_bytes_total"] == 0
