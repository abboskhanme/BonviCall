"""Scheduled work owned by ``audio`` (T151, SPEC §10.4).

**Retention deletes irreversibly**, so the order inside it is the design: the
blob is removed *first* and the row marked *second*. A crash between the two
leaves a row claiming a file that is gone, which the next run fixes because
``delete`` is idempotent. Marking first and crashing would leave a file nobody
ever deletes and nobody can find — the failure that cannot be repaired by
running the job again.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.config import get_settings
from src.core.enums import AlertKind, AlertSeverity, AudioMissingReason, UploadStatus
from src.core.logging import get_logger
from src.core.storage import LocalFsAudioStorage
from src.modules.alerts.service import AlertService
from src.modules.audio.models import AudioUploadSessionModel
from src.modules.audio.service import AudioService
from src.modules.calls.models import CallModel

log = get_logger(__name__)

#: SPEC §3.9: ``pending_upload`` older than this becomes ``upload_expired`` and
#: only then counts in the gap report. Before that it is audio in flight, not a
#: capture failure, and counting it would make the rate meaningless.
PENDING_AUDIO_HOURS = 24

#: N18: free disk below this fraction of the provisioned volume is critical.
STORAGE_CRITICAL_FRACTION = 0.20
PROVISIONED_BYTES = 250 * 1024**3


async def audio_retention(session: AsyncSession) -> int:
    """Delete audio past ``retention.audio_months`` (T42, UC-26, N19).

    Idempotent: the query only sees rows with ``deleted_at IS NULL``, so a
    second run finds nothing. The row itself is kept, so "there was a
    recording and it expired" stays answerable and playback returns 410.
    """
    return await AudioService(session).apply_retention()


async def upload_session_sweeper(session: AsyncSession) -> int:
    """Expire upload sessions past their TTL and delete the partials.

    The call's reason becomes ``upload_expired``, so a recording that never
    finished uploading shows up in the gap report as the loss it is rather
    than sitting in ``pending_upload`` forever.
    """
    storage = LocalFsAudioStorage(get_settings().audio_storage_path)
    moment = clock.now()
    stale = list(
        (
            await session.scalars(
                select(AudioUploadSessionModel).where(
                    AudioUploadSessionModel.status == UploadStatus.OPEN,
                    AudioUploadSessionModel.expires_at <= moment,
                )
            )
        ).all()
    )
    for upload in stale:
        # unlink(missing_ok=True): a partial already swept by an interrupted
        # earlier run must not stop this one.
        storage.incoming_path(upload.id).unlink(missing_ok=True)
        upload.status = UploadStatus.EXPIRED
        if upload.call_id is not None:
            call = await session.get(CallModel, upload.call_id)
            if call is not None and not call.has_audio:
                call.audio_missing_reason = AudioMissingReason.UPLOAD_EXPIRED
    await session.commit()
    if stale:
        log.info("upload_sessions_expired", count=len(stale))
    return len(stale)


async def pending_audio_sweeper(session: AsyncSession) -> int:
    """``pending_upload`` older than 24 h becomes ``upload_expired`` (§3.9).

    This is what stops the gap report flattering itself: audio that never
    arrived has to become visible eventually, and 24 hours is the line.
    """
    cutoff = clock.now() - timedelta(hours=PENDING_AUDIO_HOURS)
    rows = list(
        (
            await session.scalars(
                select(CallModel).where(
                    CallModel.has_audio.is_(False),
                    CallModel.audio_missing_reason == AudioMissingReason.PENDING_UPLOAD,
                    CallModel.received_at < cutoff,
                )
            )
        ).all()
    )
    for call in rows:
        call.audio_missing_reason = AudioMissingReason.UPLOAD_EXPIRED
    await session.commit()
    return len(rows)


async def storage_usage(session: AsyncSession) -> int:
    """Write today's storage totals and alert when the volume is filling (N18).

    Idempotent: one row per day, upserted, so a second run recomputes the same
    numbers rather than adding to them.
    """
    row = await AudioService(session).record_storage_usage()
    free_fraction = 1 - (row.audio_bytes_total / PROVISIONED_BYTES)
    if free_fraction < STORAGE_CRITICAL_FRACTION:
        await AlertService(session).raise_alert(
            kind=AlertKind.STORAGE_CAPACITY_LOW,
            severity=AlertSeverity.CRITICAL,
            scope="fleet",
            detail={
                "audio_bytes_total": row.audio_bytes_total,
                "provisioned_bytes": PROVISIONED_BYTES,
            },
        )
        await session.commit()
    return row.audio_files
