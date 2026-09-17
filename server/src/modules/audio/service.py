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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import IO

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.clock import TASHKENT
from src.core.config import get_settings
from src.core.deps import Principal
from src.core.enums import (
    ActorType,
    AnalysisFailure,
    AudioContainer,
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
from src.modules.audio.archive import ArchiveEntry, ArchivePlan
from src.modules.audio.models import (
    AudioUploadSessionModel,
    CallAudioModel,
    StorageUsageDailyModel,
)
from src.modules.audio.rules import (
    archive_entry_filename,
    duration_mismatch,
    is_attributable,
    recording_filename,
    unique_filename,
)
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


#: The manifest's own columns, and the same `﻿` + `;` shape the CSV export
#: uses — for the same reason it does: Excel in a ru/uz locale renders a
#: comma-separated UTF-8 file as one column, and the person who opens it has no
#: way to know that is what happened.
MANIFEST_NAME = "manifest.csv"
MANIFEST_COLUMNS = ("vaqti", "xodim", "raqam", "fayl", "sabab")

#: Written when a call has no recording and the product recorded no reason —
#: rare, because ``audio_missing_reason`` is NOT NULL whenever ``has_audio`` is
#: false, but a blank cell would read as "we did not check".
MANIFEST_NO_AUDIO = "no_audio"


def _manifest_csv(rows: list[tuple[str, ...]]) -> bytes:
    lines = [";".join(MANIFEST_COLUMNS)]
    lines.extend(";".join(_manifest_cell(cell) for cell in row) for row in rows)
    return ("﻿" + "\r\n".join(lines) + "\r\n").encode("utf-8")


def _manifest_cell(value: str) -> str:
    """A separator inside a cell would silently shift every later column."""
    return value.replace(";", ",").replace("\r", " ").replace("\n", " ")




@dataclass(frozen=True)
class PlaybackSource:
    """Everything the Range handler needs, with the file already located."""

    audio: CallAudioModel
    stat: ObjectStat
    content_type: str
    filename: str


#: ``call_audio.container`` → the media type and the file extension the
#: analysis pipeline hands a provider. Declared as a pair because the vendor
#: SDKs infer the type from the **filename**: an ``audio/mp4`` body called
#: ``.ogg`` comes back as a complaint about the codec, which is the least
#: useful place for this to surface. The container is an enum, so nothing here
#: has to guess from an HTTP header — the map BonviZvonki needed for that is
#: one of the pieces this port deletes (SPEC-ANALYTICS §3.2).
ANALYSIS_MEDIA_TYPES: dict[AudioContainer, tuple[str, str]] = {
    AudioContainer.OGG: ("audio/ogg", "ogg"),
    AudioContainer.MP4: ("audio/mp4", "m4a"),
}


@dataclass(frozen=True)
class AnalysisSource:
    """One recording, ready for an ASR provider — and no storage key in it.

    ``open`` is bound by :class:`AudioService` over the storage seam, so the
    caller reads the bytes while holding neither a key nor a path: **no module
    outside this one opens an audio file** (SPEC §6, CONVENTIONS.md §2). It is
    the same idiom as :meth:`AudioService.archive_for`, which binds
    ``open_bytes`` per entry.

    Call ``open()`` once per attempt rather than once per call: a retry after a
    provider timeout wants a fresh handle, not a stream somebody already read
    to the end. Opening a local file again costs nothing, which is the whole
    difference between this and a source that had to be downloaded.

    ``bytes`` and ``duration_ms`` are also the two facts the pipeline records
    on the transcript row — ASR is billed per second of audio, and a cost
    nobody measured is a cost nobody can cap (SPEC-ANALYTICS §11.1).
    """

    call_id: uuid.UUID
    bytes: int
    duration_ms: int | None
    content_type: str
    filename: str
    open: Callable[[], IO[bytes]]


class AudioNotAnalysable(Exception):
    """The file is there and readable, but sending it would be waste.

    Carries a :class:`~src.core.enums.AnalysisFailure` and not an
    ``ErrorCode``: these answers never leave through an HTTP status. They are
    written to ``call_analysis_state.failure_code`` and read back through the
    panel (SPEC-ANALYTICS §6.3), so the caller stores ``.failure`` verbatim and
    there is no second translation table to keep in step with this one.
    """

    def __init__(self, failure: AnalysisFailure, detail: str) -> None:
        super().__init__(f"{failure.value}: {detail}")
        self.failure = failure
        self.detail = detail


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
        return await self._source_for(call)

    async def playback_source_for_device(
        self, installation, call_id: uuid.UUID
    ) -> PlaybackSource:
        """The same recording, located for the employee's own phone (T59).

        Scoped by the installation's binding rather than by a principal's
        permissions — see ``DeviceCallReadService``. A call belonging to another
        agent is 404 from that lookup, so this method never has to decide it.
        """
        from src.modules.calls.service import DeviceCallReadService

        call = await DeviceCallReadService(self.session).get(installation, call_id)
        return await self._source_for(call)

    async def _source_for(self, call) -> PlaybackSource:
        """Shared by both playback paths, so the 404/410 rules cannot diverge."""
        audio = await self.session.scalar(
            select(CallAudioModel).where(CallAudioModel.call_id == call.id)
        )
        if audio is None:
            raise NotFoundError(ErrorCode.AUDIO_NOT_FOUND)
        if audio.deleted_at is not None:
            raise GoneError(ErrorCode.AUDIO_EXPIRED)

        stat = self.storage.stat(audio.storage_key)
        content_type = "audio/ogg" if audio.container.value == "ogg" else "audio/mp4"
        extension = Path(audio.storage_key).suffix.lstrip(".")
        # ⚠️ **The agent's name belongs in this filename** and was missing for
        # the whole life of the product: SPEC §4.8 states
        # ``<agent>_<yyyymmdd-hhmm>.<ext>`` and the code built
        # ``<yyyymmdd-hhmm>.<ext>``, so a recording saved to somebody's desktop
        # said nothing about whose call it was. The rule now lives in
        # ``audio/rules.py`` and the archive uses the same function, because
        # the two names disagreeing is exactly what happened here.
        from src.modules.calls.service import CallService

        agent_name = await CallService(self.session).agent_display_name(call.agent_id)
        return PlaybackSource(
            audio=audio,
            stat=stat,
            content_type=content_type,
            # Tashkent, not UTC. Timestamps are stored in UTC and rendered in
            # Tashkent everywhere a person reads one (D-10), and a filename is
            # read by a person: a call the panel lists at 13:55 must not arrive
            # on their desktop called ``…_0855``.
            filename=recording_filename(
                agent_name, call.started_at.astimezone(TASHKENT), extension
            ),
        )

    async def record_device_playback(
        self, installation, call_id: uuid.UUID, range_start: int | None, ip: str | None
    ) -> bool:
        """UC-24 applies to the employee's own listening too.

        An employee playing their own recording is not a privacy event, but the
        audit log's value is that it is complete: "who listened to this call"
        has to include the person who made it, or the answer is a half-truth.
        Actor is the **device**, so the two are told apart at a glance.
        """
        if (range_start or 0) > 0:
            return False  # a seek, not a play — same rule as the panel
        if await self.audit.recorded_recently(
            AuditAction.AUDIO_PLAY,
            actor_user_id=None,
            object_id=call_id,
            within_seconds=PLAYBACK_AUDIT_DEDUPE_SECONDS,
            actor_type=ActorType.DEVICE,
        ):
            return False
        await self.audit.record(
            action=AuditAction.AUDIO_PLAY,
            object_type="calls",
            object_id=call_id,
            actor_type=ActorType.DEVICE,
            ip=ip,
            # ``audit_log`` has no installation actor column and this does not
            # warrant one: the object is the call, and which phone played it is
            # context. It is the same place the rebind audit puts its context.
            detail={"installation_id": str(installation.id)},
        )
        await self.session.commit()
        return True

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

    # --- The analysis seam (SPEC-ANALYTICS §3) -----------------------------

    async def analysis_source(
        self,
        call_id: uuid.UUID,
        *,
        min_duration_ms: int | None = None,
        max_bytes: int | None = None,
    ) -> AnalysisSource:
        """Locate one recording for the analysis pipeline, or refuse it.

        **BonviCall owns this file**, so this is a local read. The apparatus
        BonviZvonki needed because it never owned the bytes — an HTTP stream
        opened per attempt, a counting passthrough so nothing was ever
        buffered, a re-download on every retry — has no counterpart here and is
        not ported (SPEC-ANALYTICS §3.2).

        **No ``Principal``.** The caller is a worker job, not a request, and
        inventing a principal for it would be a lie. Row-level scope is decided
        where a person asks (:meth:`playback_source`); nothing here is answered
        to a browser.

        Four refusals, in the order in which they save money:

        * no ``call_audio`` row at all → ``404 audio_not_found``
        * ``deleted_at`` set, i.e. retention took it → ``410 audio_expired``
        * the row is there and the bytes are not → ``404 audio_not_found``
        * over ``max_bytes``, or under ``min_duration_ms`` →
          :class:`AudioNotAnalysable`, before a byte is read

        The first two are the same two answers :meth:`_source_for` already
        gives the panel, so the two readers of ``call_audio`` cannot drift
        apart. The third is why this stats the file rather than trusting the
        row: a blob that is gone without ``deleted_at`` — a database restored
        in front of an unrestored disk, or a hand-deleted file — would
        otherwise be discovered halfway through a provider call, as a paid-for
        failure wearing a confusing message.

        ``min_duration_ms`` is measured against the **file**, not the call log.
        The two disagree exactly when the recorder truncated the call
        (``calls.audio_duration_mismatch``, UC-14), and that is the case where
        paying to transcribe is most obviously wasted. An unknown duration is
        never short: a null is an absent measurement, not a small one.

        Both limits belong to the caller. This module holds no analysis policy
        and reads no ``analysis.*`` setting; ``None`` means "do not judge".
        """
        audio = await self.session.scalar(
            select(CallAudioModel).where(CallAudioModel.call_id == call_id)
        )
        if audio is None:
            raise NotFoundError(ErrorCode.AUDIO_NOT_FOUND)
        if audio.deleted_at is not None:
            raise GoneError(ErrorCode.AUDIO_EXPIRED)

        # Raises 404 ``audio_not_found`` when the key resolves to nothing —
        # the same answer playback gives, reached the same way.
        stat = self.storage.stat(audio.storage_key)
        if max_bytes is not None and stat.bytes > max_bytes:
            raise AudioNotAnalysable(
                AnalysisFailure.AUDIO_TOO_LARGE,
                f"{stat.bytes} bytes exceeds the {max_bytes}-byte ceiling",
            )
        if (
            min_duration_ms is not None
            and audio.duration_ms is not None
            and audio.duration_ms < min_duration_ms
        ):
            raise AudioNotAnalysable(
                AnalysisFailure.CALL_TOO_SHORT,
                f"{audio.duration_ms} ms of audio, floor is {min_duration_ms} ms",
            )

        content_type, extension = ANALYSIS_MEDIA_TYPES[audio.container]
        key = audio.storage_key
        return AnalysisSource(
            call_id=call_id,
            # The size on disk, not ``call_audio.bytes``: this is the number
            # ``open()`` will actually yield, and therefore the number the
            # vendor bills and the transcript row should record.
            bytes=stat.bytes,
            duration_ms=audio.duration_ms,
            content_type=content_type,
            # Deliberately not ``recording_filename()``, which names the agent
            # for the person saving it to a desktop. This name is read by a
            # third party in another country, and the call id is all it needs
            # (SPEC-ANALYTICS §11.5).
            filename=f"call-{call_id}.{extension}",
            # ``key=key`` keeps the storage key inside this closure and inside
            # this module: what crosses the boundary is a callable, never a
            # path. Same binding trick, and same reason, as ``archive_for``.
            open=lambda key=key: self.storage.open_range(key, 0, None),
        )

    # --- The archive of one page (UC-22's sibling) -------------------------

    async def record_archive_download(
        self, principal: Principal, calls: int, files: int, ip: str | None
    ) -> None:
        """One audit row for the whole archive (UC-24).

        Not one per recording. The question this log answers is "who took a
        copy, and of how much" — a hundred rows saying the same thing at the
        same second answers it worse, and buries everything around it. The
        counts are in the detail so "they downloaded a page and got four files"
        is still readable a month later.
        """
        await self.audit.record(
            action=AuditAction.AUDIO_DOWNLOAD,
            object_type="calls",
            actor_type=ActorType.SERVICE if principal.kind == "service" else ActorType.USER,
            actor_user_id=principal.id if principal.kind == "user" else None,
            actor_service_token_id=principal.id if principal.kind == "service" else None,
            ip=ip,
            detail={"archive": True, "calls": calls, "files": files},
        )
        await self.session.commit()

    async def archive_for(self, calls: list) -> ArchivePlan:
        """What to put in the ZIP for the calls the reader is looking at.

        Takes the page the list endpoint already produced rather than a filter,
        for the reason the client gave: the button sits under fifty rows and
        must hand over those fifty rows. It also means the agent names are
        already resolved — the page carries them — so this adds one query, for
        the storage keys, and not one per file.

        ⚠️ **The manifest is not decoration.** A page of fifty calls of which
        four have audio produces four files, and a download that silently drops
        forty-six rows is indistinguishable from a broken one. The manifest
        names every call on the page and, for each one without a recording,
        the reason the product already recorded.
        """
        by_call = {
            row.call_id: row
            for row in (
                await self.session.scalars(
                    select(CallAudioModel).where(
                        CallAudioModel.call_id.in_([call.id for call in calls]),
                        CallAudioModel.deleted_at.is_(None),
                    )
                )
            ).all()
        }

        entries: list[ArchiveEntry] = []
        rows: list[tuple[str, ...]] = []
        taken: list[str] = []
        for call in calls:
            local_start = call.started_at.astimezone(TASHKENT)
            audio = by_call.get(call.id)
            if audio is None:
                reason = (
                    call.audio_missing_reason.value
                    if call.audio_missing_reason
                    else MANIFEST_NO_AUDIO
                )
                rows.append(
                    (
                        local_start.strftime("%Y-%m-%d %H:%M"),
                        call.agent_name,
                        call.remote_number or "",
                        "",
                        reason,
                    )
                )
                continue

            name = unique_filename(
                archive_entry_filename(
                    call.agent_name,
                    local_start,
                    Path(audio.storage_key).suffix.lstrip("."),
                    call.remote_number,
                ),
                taken,
            )
            taken.append(name)
            key = audio.storage_key
            entries.append(
                ArchiveEntry(
                    name=name,
                    modified_at=local_start,
                    # Bound now, opened later: fifty entries must not mean
                    # fifty open descriptors from the moment the response
                    # starts. `key=key` binds this row's key rather than the
                    # loop variable, which every later iteration would rebind.
                    open_bytes=lambda key=key: self.storage.open_range(key, 0, None),
                )
            )
            rows.append(
                (
                    local_start.strftime("%Y-%m-%d %H:%M"),
                    call.agent_name,
                    call.remote_number or "",
                    name,
                    "",
                )
            )

        return ArchivePlan(entries=entries, manifest=_manifest_csv(rows))

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

    async def current_storage(self) -> tuple[int, int]:
        """``(bytes, files)`` held **right now**, from the rows not the rollup.

        The nightly snapshot gives the growth *curve*; it cannot give today's
        total, because on a server whose job has not run yet there is no row —
        and the report then answered "0 bytes of audio" while the recordings
        were sitting on disk. "No history yet" is a true statement; "you are
        using no storage" is a false one, and it is false in the direction that
        says the volume is fine.

        The concern behind reading the rollup was never the aggregate — it was
        not running a ``du`` over 200 GB per page view. This is a ``SUM`` over a
        small indexed table, which is what the job itself runs.
        """
        totals = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(CallAudioModel.bytes), 0),
                    func.count(),
                ).where(CallAudioModel.deleted_at.is_(None))
            )
        ).one()
        return int(totals[0]), int(totals[1])

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
