"""Streaming a ZIP of recordings, without building it in memory.

``zipfile`` writes to a file-like object, so a sink that keeps what it is
handed and gives it up on demand turns it into a generator: write one entry,
hand the bytes to the response, forget them. Memory then holds one file's
worth rather than the whole archive, which is what keeps this endpoint honest
if the page size ever stops being fifty.

**Stored, never deflated.** Opus and AAC are compressed formats; running them
through deflate spends CPU to save a fraction of a percent, on a server that is
also transcoding and serving audio.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import IO

#: 64 KiB. Big enough that the loop is not the cost, small enough that a slow
#: client cannot make the server hold much on its behalf.
CHUNK_BYTES = 64 * 1024


class _StreamSink:
    """A write-only file object that hands its bytes to the caller.

    ``zipfile`` needs ``write``, ``tell`` and ``flush``; it needs ``seek`` only
    for archives it rewrites, which a streamed one never is. ``tell`` must keep
    counting across drains — the central directory it writes at the end holds
    the absolute offset of every entry, and an offset restarted at zero is an
    archive that opens and is empty.
    """

    def __init__(self) -> None:
        self._chunks: list[bytes] = []
        self._position = 0

    def write(self, data: bytes) -> int:
        self._chunks.append(bytes(data))
        self._position += len(data)
        return len(data)

    def tell(self) -> int:
        return self._position

    def flush(self) -> None:
        return None

    def drain(self) -> bytes:
        data = b"".join(self._chunks)
        self._chunks.clear()
        return data


@dataclass(frozen=True)
class ArchiveEntry:
    """One file to put in the archive.

    ``open_bytes`` is a callable rather than an open handle so fifty entries do
    not mean fifty open file descriptors from the moment the response starts.
    """

    name: str
    modified_at: datetime
    open_bytes: Callable[[], IO[bytes]]


@dataclass(frozen=True)
class ArchivePlan:
    """The entries to stream, and the manifest that explains what is missing."""

    entries: list[ArchiveEntry]
    manifest: bytes


def stream_archive(plan: ArchivePlan, manifest_name: str) -> Iterator[bytes]:
    """The manifest first, then the recordings.

    First on purpose: it is the file that explains an archive holding four
    recordings for a page of fifty calls, and an explanation nobody scrolls to
    is an explanation nobody reads.
    """
    manifest = ArchiveEntry(
        name=manifest_name,
        modified_at=datetime.now(),
        open_bytes=lambda: BytesIO(plan.manifest),
    )
    return stream_zip([manifest, *plan.entries])


def stream_zip(entries: Iterable[ArchiveEntry]) -> Iterator[bytes]:
    """Yield the archive as it is built, entry by entry."""
    sink = _StreamSink()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED) as archive:
        for entry in entries:
            info = zipfile.ZipInfo(
                entry.name, date_time=entry.modified_at.timetuple()[:6]
            )
            # Non-ASCII names are written UTF-8 with the language-encoding flag
            # set, which `zipfile` does on its own — an Uzbek name survives the
            # round trip into Explorer and Finder.
            with archive.open(info, "w") as target, entry.open_bytes() as source:
                while chunk := source.read(CHUNK_BYTES):
                    target.write(chunk)
                    if data := sink.drain():
                        yield data
            if data := sink.drain():
                yield data
    # The central directory is written by ``close()``, inside the ``with``.
    if data := sink.drain():
        yield data
