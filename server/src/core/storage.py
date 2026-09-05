"""Audio storage — one of exactly two interfaces in the product (SPEC §6, D-01).

Release 1 keeps audio on the local filesystem: ~17 GB/month for one tenant on
one host does not need object storage, and ``STACK.md`` rejected MinIO/S3 as
premature. The interface exists so that changing that decision later is a
configuration change and not a refactor — an ``S3AudioStorage`` is *not*
written now, on purpose.

The seam only holds if nothing goes around it: **no module outside
``modules/audio/`` may open an audio file by path.** ``storage_key`` is
relative to the storage root and is never a URL, so the whole tree can be moved
without touching a row.

Layout (SPEC §3.6)::

    <root>/calls/<yyyy>/<mm>/<dd>/<call_id>.<ext>   committed recordings
    <root>/incoming/<upload_id>.part                partial resumable uploads
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Protocol, runtime_checkable

from src.core.errors import ErrorCode, NotFoundError

#: Read/hash buffer. 1 MiB keeps a 90-minute recording off the heap.
CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class StoredObject:
    """What was written, as the database will record it."""

    key: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class ObjectStat:
    """Enough to answer a ``Range`` request without opening the file."""

    key: str
    bytes: int
    modified_at: datetime


@runtime_checkable
class AudioStorage(Protocol):
    """The seam. Four operations, because that is all the audio module needs."""

    def put(self, key: str, source_path: Path) -> StoredObject:
        """Move ``source_path`` into storage under ``key`` and describe it."""
        ...

    def open_range(self, key: str, start: int, end: int | None) -> IO[bytes]:
        """A byte stream for ``[start, end]`` inclusive; ``end=None`` means EOF.

        Inclusive because that is what HTTP ``Range`` means, and converting
        between the two conventions in three call sites is how a player ends up
        one byte short of the last frame (N43).
        """
        ...

    def stat(self, key: str) -> ObjectStat:
        """Size and mtime, for ``Content-Range`` and the storage report."""
        ...

    def delete(self, key: str) -> None:
        """Remove the blob. Idempotent — the retention job may retry (UC-26)."""
        ...


def build_audio_key(call_id: uuid.UUID, recorded_at: datetime, extension: str) -> str:
    """The storage key for a committed recording.

    Dated directories, not one flat folder: 15,000 recordings a month means
    180,000 files a year, and a directory listing is how an ``ls`` on the
    production host turns into an incident.
    """
    ext = extension.lstrip(".")
    return f"calls/{recorded_at:%Y/%m/%d}/{call_id}.{ext}"


class LocalFsAudioStorage:
    """The release-1 implementation: a directory tree on the app server."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def ensure_ready(self) -> None:
        """Create the tree and prove it is writable — used by ``GET /readyz``.

        A server that accepts uploads it cannot store is worse than one that
        reports itself unready.
        """
        (self.root / "calls").mkdir(parents=True, exist_ok=True)
        (self.root / "incoming").mkdir(parents=True, exist_ok=True)
        probe = self.root / ".write-probe"
        probe.write_bytes(b"")
        probe.unlink()

    def incoming_path(self, upload_id: uuid.UUID) -> Path:
        """Where a resumable upload accumulates before it is committed.

        Not part of :class:`AudioStorage`: appending at a byte offset is a
        local-filesystem capability, and an S3 implementation would resume
        differently. The audio module holds the partial through this method and
        hands the finished file to :meth:`put`.
        """
        directory = self.root / "incoming"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{upload_id}.part"

    def put(self, key: str, source_path: Path) -> StoredObject:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = sha256_of(source_path)
        size = source_path.stat().st_size
        # move, not copy: the partial and the stored object are the same bytes,
        # and copying 200 GB/year through the page cache buys nothing.
        shutil.move(os.fspath(source_path), os.fspath(target))
        return StoredObject(key=key, bytes=size, sha256=digest)

    def open_range(self, key: str, start: int, end: int | None) -> IO[bytes]:
        path = self._resolve(key)
        if not path.is_file():
            raise NotFoundError(ErrorCode.AUDIO_NOT_FOUND)
        size = path.stat().st_size
        if start < 0 or start >= max(size, 1):
            raise NotFoundError(ErrorCode.RANGE_NOT_SATISFIABLE)
        last = size - 1 if end is None else min(end, size - 1)
        handle = path.open("rb")
        handle.seek(start)
        return _LimitedReader(handle, last - start + 1)

    def stat(self, key: str) -> ObjectStat:
        path = self._resolve(key)
        if not path.is_file():
            raise NotFoundError(ErrorCode.AUDIO_NOT_FOUND)
        info = path.stat()
        return ObjectStat(
            key=key,
            bytes=info.st_size,
            modified_at=datetime.fromtimestamp(info.st_mtime).astimezone(),
        )

    def delete(self, key: str) -> None:
        self._resolve(key).unlink(missing_ok=True)

    def _resolve(self, key: str) -> Path:
        """Absolute path for ``key``, refusing anything that escapes the root.

        ``storage_key`` comes from our own code today, but it is a column and
        columns get edited; a key of ``../../etc/passwd`` must be a refusal and
        not a file read.
        """
        candidate = (self.root / key).resolve()
        root = self.root.resolve()
        if not candidate.is_relative_to(root):
            raise ValueError(f"storage key escapes the storage root: {key!r}")
        return candidate


class _LimitedReader(io.RawIOBase):
    """A read-only view of the next ``limit`` bytes of an open file."""

    def __init__(self, handle: IO[bytes], limit: int) -> None:
        self._handle = handle
        self._remaining = max(limit, 0)

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:  # type: ignore[override]
        if self._remaining <= 0:
            return 0
        wanted = min(len(buffer), self._remaining)
        chunk = self._handle.read(wanted)
        buffer[: len(chunk)] = chunk
        self._remaining -= len(chunk)
        return len(chunk)

    def close(self) -> None:
        try:
            self._handle.close()
        finally:
            super().close()


def sha256_of(path: Path) -> str:
    """Hex SHA-256 of a file, read in chunks (N11: the device deletes on this)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


__all__ = [
    "CHUNK_BYTES",
    "AudioStorage",
    "LocalFsAudioStorage",
    "ObjectStat",
    "StoredObject",
    "build_audio_key",
    "sha256_of",
]


class LocalFsReleaseStore:
    """Where published APKs live (N33).

    The app is not distributed through Google Play — Play policy prohibits
    call-recording apps — so this server *is* the update channel, and these
    bytes are what a salesperson's phone installs. Kept beside the audio store
    rather than inside it: audio is customer data under a retention policy,
    a release is an artefact that must never be deleted by one, and putting
    them in one tree is how a retention sweep eventually eats the APK.

    Deliberately a smaller interface than :class:`AudioStorage`: no ranges and
    no resumable upload, because an APK is ~30 MB over the admin's office
    Wi-Fi, not a 90-minute recording over a rural cell.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def ensure_ready(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        probe = self.root / ".write-probe"
        probe.write_bytes(b"")
        probe.unlink()

    def key_for(self, variant: str, version_code: int) -> str:
        """One key per variant and build. Overwriting one is not a scenario:
        a version code is immutable once published, which is what makes the
        stored SHA-256 mean anything."""
        return f"{variant}/{version_code}.apk"

    def put_bytes(self, key: str, payload: bytes) -> StoredObject:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return StoredObject(
            key=key, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest()
        )

    def open(self, key: str) -> IO[bytes]:
        path = self._resolve(key)
        if not path.is_file():
            raise NotFoundError(ErrorCode.NOT_FOUND)
        return path.open("rb")

    def stat(self, key: str) -> ObjectStat:
        path = self._resolve(key)
        if not path.is_file():
            raise NotFoundError(ErrorCode.NOT_FOUND)
        info = path.stat()
        return ObjectStat(
            key=key,
            bytes=info.st_size,
            modified_at=datetime.fromtimestamp(info.st_mtime, tz=UTC),
        )

    def delete(self, key: str) -> None:
        self._resolve(key).unlink(missing_ok=True)

    def _resolve(self, key: str) -> Path:
        """Same escape guard as the audio store, for the same reason."""
        candidate = (self.root / key).resolve()
        root = self.root.resolve()
        if not candidate.is_relative_to(root):
            raise ValueError(f"release key escapes the release root: {key!r}")
        return candidate
