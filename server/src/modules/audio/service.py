"""Audio: resumable upload, the attribution gate, playback, retention.

**The attribution gate is the server's half of the privacy boundary** (N28,
T44). The OEM recordings folder on the employee's own phone holds their private
calls; the device-side guard is the primary defence, and this is the backstop
for an app that has been tampered with. A recording whose window does not
overlap a registered-number call is refused with 409 ``audio_not_attributable``
and **the bytes are never written to storage**.

The upload protocol is three steps (SPEC §4.5, D-04): open a session, PUT
chunks at a byte offset, commit. Resumable by offset, no third-party dependency
on either side, and reassembled by appending to one ``.part`` file. The device
deletes its local copy only after the commit confirms the SHA-256 (N11).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.clock import TASHKENT
from src.core.config import get_settings
from src.core.deps import Principal
from src.core.enums import (
    ActorType,
    AudioMissingReason,
    AuditAction,
    CallDisposition,
    UploadStatus,
)
from src.core.errors import (
    ConflictError,
    ErrorCode,
    GoneError,
    NotFoundError,
    PayloadTooLargeError,
    ValidationError,
)
from src.core.logging import get_logger
from src.core.storage import LocalFsAudioStorage, ObjectStat, build_audio_key
from src.modules.audio.models import (
    AudioUploadSessionModel,
    CallAudioModel,
    StorageUsageDailyModel,
)
from src.modules.audio.rules import duration_mismatch, is_attributable
from src.modules.audio.schemas import OpenUploadIn
from src.modules.audit.service import AuditService
from src.modules.calls.models import CallModel
from src.modules.installations.models import InstallationModel
from src.modules.settings.service import SettingsService

log = get_logger(__name__)

SETTING_CHUNK_SIZE = "upload.chunk_size_bytes"
SETTING_MAX_CHUNK = "upload.max_chunk_bytes"
SETTING_SESSION_TTL_DAYS = "upload.session_ttl_days"
SETTING_RETENTION_MONTHS = "retention.audio_months"

#: UC-24: one audit row per playback *start*, deduped inside this window.
#: Seeking a twenty-minute file must not produce forty rows.
PLAYBACK_AUDIT_DEDUPE_SECONDS = 60

DELETED_REASON_RETENTION = "retention"

#: Where the panel fetches a recording. A path, never a signed or public URL
#: (N20): the route is token-protected and the browser reaches it through the
#: Service Worker bridge, which is the only way an <audio> element can carry an
#: Authorization header and still issue real Range requests (T153, N43).
PLAYBACK_PATH = "/api/v1/calls/{call_id}/audio"


@dataclass(frozen=True)
class PlaybackSource:
    """Everything the Range handler needs, with the file already located."""

    audio: CallAudioModel
    stat: ObjectStat
    content_type: str
    filename: str


class AudioService:
    """The upload protocol, playback and retention. Owns its transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = SettingsService(session)
        self.audit = AuditService(session)
        self.storage = LocalFsAudioStorage(get_settings().audio_storage_path)

    # --- Step 1: open ------------------------------------------------------

    async def open_session(
        self, installation: InstallationModel, client_call_id: uuid.UUID, payload: OpenUploadIn
    ) -> AudioUploadSessionModel:
        """Open, or hand back the existing open session (the resume path).

        Re-opening returns the true ``received_bytes`` rather than zero, which
        is what lets an app that restarted mid-upload continue instead of
        starting again on a 3G connection.
        """
        call = await self.session.scalar(
            select(CallModel).where(CallModel.client_call_id == client_call_id)
        )
        if call is None:
            # Metadata before audio, always: the cheap and important half lands
            # first (R7). The app posts the call row and retries.
            raise ConflictError(
                ErrorCode.CALL_NOT_FOUND, detail={"retry_after_ms": 5000}
            )
        if call.installation_id != installation.id:
            raise NotFoundError(ErrorCode.CALL_NOT_FOUND)
        if call.disposition is not CallDisposition.ANSWERED:
            # An unanswered call had no conversation to record, so a file
            # claiming to be one did not come from it.
            await self._mark_unattributable(call)
            raise ConflictError(ErrorCode.AUDIO_NOT_ATTRIBUTABLE)
        if not is_attributable(
            payload.recorded_at, call.started_at, call.ended_at, call.duration_sec
        ):
            await self._mark_unattributable(call)
            log.warning(
                "audio_not_attributable",
                call_id=str(call.id),
                installation_id=str(installation.id),
            )
            raise ConflictError(ErrorCode.AUDIO_NOT_ATTRIBUTABLE)

        existing = await self.session.scalar(
            select(AudioUploadSessionModel).where(
                AudioUploadSessionModel.installation_id == installation.id,
                AudioUploadSessionModel.client_call_id == client_call_id,
                AudioUploadSessionModel.status == UploadStatus.OPEN,
            )
        )
        if existing is not None:
            return existing

        chunk_size = await self.settings.get_int(SETTING_CHUNK_SIZE)
        ttl_days = await self.settings.get_int(SETTING_SESSION_TTL_DAYS)
        upload = AudioUploadSessionModel(
            installation_id=installation.id,
            client_call_id=client_call_id,
            call_id=call.id,
            bytes_total=payload.bytes_total,
            chunk_size=chunk_size,
            sha256_expected=payload.sha256,
            codec=payload.codec,
            container=payload.container,
            duration_ms=payload.duration_ms,
            capture_route=payload.capture_route,
            recorded_at=payload.recorded_at,
            status=UploadStatus.OPEN,
            expires_at=clock.now() + timedelta(days=ttl_days),
        )
        self.session.add(upload)
        await self.session.flush()
        upload.part_path = str(self.storage.incoming_path(upload.id).name)
        await self.session.commit()
        return upload

    async def _mark_unattributable(self, call: CallModel) -> None:
        """A rising count here means the harvest window is mistuned — which is
        the difference between a bug and a privacy incident (SPEC §3.9)."""
        if not call.has_audio:
            call.audio_missing_reason = AudioMissingReason.ATTRIBUTION_FAILED
        await self.session.commit()

    # --- Step 2: chunks ----------------------------------------------------

    async def append_chunk(
        self,
        installation: InstallationModel,
        upload_id: uuid.UUID,
        offset: int,
        payload: bytes,
        chunk_sha256: str | None,
    ) -> int:
        """Append at ``offset``. Returns the new ``received_bytes``.

        A mismatched offset is a 409 carrying the expected one, so the client
        **seeks and retries** rather than restarting a 3 MB upload — which is
        the entire reason this protocol exists rather than a re-POST.
        """
        upload = await self._open_upload(installation, upload_id)
        max_chunk = await self.settings.get_int(SETTING_MAX_CHUNK)
        if len(payload) > max_chunk:
            raise PayloadTooLargeError(detail={"max_chunk_bytes": max_chunk})
        if offset != upload.received_bytes:
            raise ConflictError(
                ErrorCode.CHUNK_OFFSET_MISMATCH,
                detail={"expected_offset": upload.received_bytes},
            )
        if chunk_sha256 and hashlib.sha256(payload).hexdigest() != chunk_sha256:
            # Discard, leave received_bytes alone, let the client resend this
            # chunk. Writing a corrupt chunk would poison the whole file.
            raise ValidationError(ErrorCode.CHUNK_CHECKSUM_MISMATCH)
        if upload.received_bytes + len(payload) > upload.bytes_total:
            raise ValidationError(
                ErrorCode.CHUNK_CHECKSUM_MISMATCH,
                detail={"reason": "more bytes than declared"},
            )

        part = self.storage.incoming_path(upload.id)
        with part.open("ab") as handle:
            handle.write(payload)
        upload.received_bytes += len(payload)
        upload.last_chunk_at = clock.now()
        await self.session.commit()
        return upload.received_bytes

    # --- Step 3: commit ----------------------------------------------------

    async def commit(
        self, installation: InstallationModel, upload_id: uuid.UUID
    ) -> tuple[CallAudioModel, bool]:
        """Verify, store, and flip the call to ``has_audio``.

        Returns the audio row and whether the file's length disagrees with the
        call log by more than two seconds (UC-14). That second value goes back
        to the handset: a device whose recorder truncates every call needs to
        hear so, and it is the only signal that says so.

        Idempotent: committing twice returns the same row *and the same flag*,
        because the device may not have seen the first response and must not be
        made to re-upload 3 MB to find out.
        """
        upload = await self.session.get(AudioUploadSessionModel, upload_id)
        if upload is None or upload.installation_id != installation.id:
            raise NotFoundError()
        if upload.status is UploadStatus.COMMITTED:
            audio = await self.session.scalar(
                select(CallAudioModel).where(CallAudioModel.call_id == upload.call_id)
            )
            committed_call = await self.session.get(CallModel, upload.call_id)
            return audio, committed_call.audio_duration_mismatch
        if upload.status is not UploadStatus.OPEN:
            raise GoneError(ErrorCode.UPLOAD_EXPIRED)

        part = self.storage.incoming_path(upload.id)
        if upload.received_bytes != upload.bytes_total or not part.is_file():
            raise ValidationError(
                ErrorCode.CHECKSUM_MISMATCH,
                detail={
                    "received_bytes": upload.received_bytes,
                    "bytes_total": upload.bytes_total,
                },
            )
        digest = hashlib.sha256(part.read_bytes()).hexdigest()
        if digest != upload.sha256_expected:
            # The reassembled file is not the file the device hashed. Abort the
            # session and delete the partial; the client restarts once, and a
            # second failure parks the record (N9).
            upload.status = UploadStatus.ABORTED
            part.unlink(missing_ok=True)
            await self.session.commit()
            raise ValidationError(ErrorCode.CHECKSUM_MISMATCH)

        call = await self.session.get(CallModel, upload.call_id)
        extension = "ogg" if upload.container.value == "ogg" else "mp4"
        key = build_audio_key(call.id, upload.recorded_at or call.started_at, extension)
        stored = self.storage.put(key, part)

        audio = CallAudioModel(
            call_id=call.id,
            storage_key=stored.key,
            bytes=stored.bytes,
            sha256=stored.sha256,
            codec=upload.codec,
            container=upload.container,
            duration_ms=upload.duration_ms,
            capture_route=upload.capture_route,
            recorded_at=upload.recorded_at,
            uploaded_at=clock.now(),
            upload_id=upload.id,
        )
        self.session.add(audio)
        call.has_audio = True
        call.audio_missing_reason = None
        call.audio_duration_mismatch = duration_mismatch(
            upload.duration_ms, call.duration_sec
        )
        upload.status = UploadStatus.COMMITTED
        await self.session.commit()
        await self.session.refresh(audio)
        log.info("audio_committed", call_id=str(call.id), bytes=stored.bytes)
        return audio, call.audio_duration_mismatch

    async def probe(
        self, installation: InstallationModel, upload_id: uuid.UUID
    ) -> AudioUploadSessionModel:
        """Step 4: how far did we get? Used after a crash, before resuming."""
        upload = await self.session.get(AudioUploadSessionModel, upload_id)
        if upload is None or upload.installation_id != installation.id:
            raise NotFoundError()
        return upload

    async def _open_upload(
        self, installation: InstallationModel, upload_id: uuid.UUID
    ) -> AudioUploadSessionModel:
        upload = await self.session.get(AudioUploadSessionModel, upload_id)
        if upload is None or upload.installation_id != installation.id:
            raise NotFoundError()
        if upload.status is not UploadStatus.OPEN:
            raise GoneError(ErrorCode.UPLOAD_EXPIRED)
        if upload.expires_at <= clock.now():
            upload.status = UploadStatus.EXPIRED
            await self.session.commit()
            raise GoneError(ErrorCode.UPLOAD_EXPIRED)
        return upload

    async def summaries_for(self, call_ids) -> dict:
        """Audio summaries for a page of calls, in one query.

        Returns this module's own schema type, so ``calls`` never holds a
        ``CallAudioModel``: what crosses a module boundary is a value, not an
        entity another module could then write to.
        """
        from src.modules.calls.schemas import CallAudioSummary

        if not call_ids:
            return {}
        rows = (
            await self.session.execute(
                select(
                    CallAudioModel.call_id,
                    CallAudioModel.capture_route,
                    CallAudioModel.capture_route_detail,
                    CallAudioModel.duration_ms,
                    CallAudioModel.deleted_at,
                ).where(CallAudioModel.call_id.in_(set(call_ids)))
            )
        ).all()
        return {
            row.call_id: CallAudioSummary(
                available=row.deleted_at is None,
                url=(
                    PLAYBACK_PATH.format(call_id=row.call_id)
                    if row.deleted_at is None
                    else None
                ),
                capture_route=row.capture_route,
                capture_route_detail=row.capture_route_detail,
                duration_ms=row.duration_ms,
                expired_at=row.deleted_at,
            )
            for row in rows
        }

    # --- Playback (UC-20, N43) --------------------------------------------

    async def playback_source(
        self, principal: Principal, call_id: uuid.UUID
    ) -> PlaybackSource:
        """Locate a recording for streaming, or say why not.

        A recording removed by retention is **410 ``audio_expired``**, never a
        500 and never an empty 200 (UC-26). A call belonging to another agent is
        404, like every other scoped read.
        """
        from src.modules.calls.service import CallService

        call = await CallService(self.session).get(principal, call_id)
        audio = await self.session.scalar(
            select(CallAudioModel).where(CallAudioModel.call_id == call.id)
        )
        if audio is None:
            raise NotFoundError(ErrorCode.AUDIO_NOT_FOUND)
        if audio.deleted_at is not None:
            raise GoneError(ErrorCode.AUDIO_EXPIRED)

        stat = self.storage.stat(audio.storage_key)
        content_type = "audio/ogg" if audio.container.value == "ogg" else "audio/mp4"
        stamp = call.started_at.strftime("%Y%m%d-%H%M")
        extension = Path(audio.storage_key).suffix.lstrip(".")
        return PlaybackSource(
            audio=audio,
            stat=stat,
            content_type=content_type,
            filename=f"{stamp}.{extension}",
        )

    def open_range(self, audio: CallAudioModel, start: int, end: int | None):
        """The byte stream itself. Only this module opens an audio file."""
        return self.storage.open_range(audio.storage_key, start, end)

    async def record_playback(
        self,
        principal: Principal,
        call_id: uuid.UUID,
        download: bool,
        range_start: int | None,
        ip: str | None,
    ) -> bool:
        """One audit row per playback start (UC-24). True when one was written.

        A seek is a Range starting above zero, and it writes nothing: otherwise
        scrubbing through a twenty-minute recording produces forty rows and the
        audit log stops being readable. A download always writes.
        """
        if not download and (range_start or 0) > 0:
            return False
        if not download:
            if await self.audit.recorded_recently(
                AuditAction.AUDIO_PLAY,
                actor_user_id=principal.id,
                object_id=call_id,
                within_seconds=PLAYBACK_AUDIT_DEDUPE_SECONDS,
            ):
                return False
        await self.audit.record(
            action=AuditAction.AUDIO_DOWNLOAD if download else AuditAction.AUDIO_PLAY,
            object_type="calls",
            object_id=call_id,
            actor_type=ActorType.SERVICE if principal.kind == "service" else ActorType.USER,
            actor_user_id=principal.id if principal.kind == "user" else None,
            actor_service_token_id=principal.id if principal.kind == "service" else None,
            ip=ip,
        )
        await self.session.commit()
        return True

    # --- Storage accounting (T57, N18) ------------------------------------

    async def record_storage_usage(self) -> StorageUsageDailyModel:
        """Write today's storage totals (N18).

        Written nightly and read from the table rather than measured on demand:
        the panel's "GB now and 30-day growth" must not run a ``du`` over 200 GB
        every time somebody opens a page, and the growth figure needs yesterday
        to exist anyway.
        """
        day = clock.now().astimezone(TASHKENT).date()
        totals = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(CallAudioModel.bytes), 0),
                    func.count(),
                ).where(CallAudioModel.deleted_at.is_(None))
            )
        ).one()
        deleted = await self.session.scalar(
            select(func.coalesce(func.sum(CallAudioModel.bytes), 0)).where(
                CallAudioModel.deleted_at.is_not(None)
            )
        )
        previous = await self.session.scalar(
            select(StorageUsageDailyModel.audio_bytes_total)
            .where(StorageUsageDailyModel.period_date < day)
            .order_by(StorageUsageDailyModel.period_date.desc())
            .limit(1)
        )
        row = await self.session.get(StorageUsageDailyModel, day)
        if row is None:
            row = StorageUsageDailyModel(period_date=day)
            self.session.add(row)
        row.audio_bytes_total = totals[0]
        row.audio_files = totals[1]
        row.bytes_added = max(totals[0] - (previous or 0), 0)
        row.bytes_deleted = deleted or 0
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def storage_history(self, days: int = 30) -> list[StorageUsageDailyModel]:
        """The last ``days`` rows, oldest first — the growth curve N18 wants."""
        cutoff = clock.now().astimezone(TASHKENT).date() - timedelta(days=days)
        return list(
            (
                await self.session.scalars(
                    select(StorageUsageDailyModel)
                    .where(StorageUsageDailyModel.period_date >= cutoff)
                    .order_by(StorageUsageDailyModel.period_date.asc())
                )
            ).all()
        )

    # --- Retention (T42, UC-26, N19) --------------------------------------

    async def apply_retention(self) -> int:
        """Delete audio past ``retention.audio_months``. Returns the count.

        The **row stays**: ``deleted_at`` and ``deleted_reason`` are set, so
        "there was a recording and it expired" is still answerable and playback
        can return 410 instead of 404. Calls are never deleted (UC-26).
        """
        months = await self.settings.get_int(SETTING_RETENTION_MONTHS)
        cutoff = clock.now() - timedelta(days=months * 30)
        rows = list(
            (
                await self.session.scalars(
                    select(CallAudioModel).where(
                        CallAudioModel.deleted_at.is_(None),
                        CallAudioModel.recorded_at < cutoff,
                    )
                )
            ).all()
        )
        for audio in rows:
            self.storage.delete(audio.storage_key)
            audio.deleted_at = clock.now()
            audio.deleted_reason = DELETED_REASON_RETENTION
            await self.audit.record(
                action=AuditAction.AUDIO_DELETED,
                object_type="call_audio",
                object_id=audio.id,
                actor_type=ActorType.SYSTEM,
                detail={"reason": DELETED_REASON_RETENTION},
            )
        await self.session.commit()
        if rows:
            log.info("audio_retention_applied", deleted=len(rows), months=months)
        return len(rows)
