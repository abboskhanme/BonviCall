"""``LocalFsAudioStorage`` and the seam it implements (T42, SPEC §6, D-01)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from src.core.errors import ErrorCode, NotFoundError
from src.core.storage import (
    AudioStorage,
    LocalFsAudioStorage,
    build_audio_key,
    sha256_of,
)


@pytest.fixture
def storage(tmp_path: Path) -> LocalFsAudioStorage:
    store = LocalFsAudioStorage(tmp_path / "audio")
    store.ensure_ready()
    return store


def test_local_storage_satisfies_the_protocol(storage: LocalFsAudioStorage) -> None:
    """The seam is a Protocol so an S3 implementation is a config change, not a refactor."""
    assert isinstance(storage, AudioStorage)


def test_key_layout_is_dated(tmp_path: Path) -> None:
    """180,000 files a year in one directory is how an ``ls`` becomes an incident."""
    call_id = uuid4()
    key = build_audio_key(call_id, datetime(2026, 9, 4, tzinfo=UTC), "ogg")
    assert key == f"calls/2026/09/04/{call_id}.ogg"


def test_put_moves_the_file_and_reports_its_checksum(
    storage: LocalFsAudioStorage, tmp_path: Path
) -> None:
    source = tmp_path / "incoming.part"
    payload = b"OggS" + bytes(range(256)) * 4
    source.write_bytes(payload)

    stored = storage.put("calls/2026/09/04/x.ogg", source)

    assert stored.bytes == len(payload)
    assert stored.sha256 == hashlib.sha256(payload).hexdigest()
    assert not source.exists(), "the partial must be moved, not copied"
    assert (storage.root / stored.key).read_bytes() == payload


def test_open_range_returns_exactly_the_inclusive_slice(
    storage: LocalFsAudioStorage, tmp_path: Path
) -> None:
    """HTTP ``Range`` is inclusive; converting conventions in three call sites
    is how a player ends up one byte short of the last frame (N43)."""
    payload = bytes(range(256))
    source = tmp_path / "a.part"
    source.write_bytes(payload)
    key = storage.put("calls/2026/09/04/a.ogg", source).key

    with storage.open_range(key, 10, 19) as handle:
        assert handle.read() == payload[10:20]
    with storage.open_range(key, 250, None) as handle:
        assert handle.read() == payload[250:]
    with storage.open_range(key, 0, 10_000) as handle:
        assert handle.read() == payload


def test_open_range_past_the_end_is_refused(
    storage: LocalFsAudioStorage, tmp_path: Path
) -> None:
    source = tmp_path / "b.part"
    source.write_bytes(b"12345")
    key = storage.put("calls/2026/09/04/b.ogg", source).key
    with pytest.raises(NotFoundError) as caught:
        storage.open_range(key, 99, None)
    assert caught.value.code == ErrorCode.RANGE_NOT_SATISFIABLE


def test_missing_object_is_a_not_found_not_an_oserror(
    storage: LocalFsAudioStorage,
) -> None:
    """A retention-deleted recording must reach the client as 410/404, never a 500."""
    with pytest.raises(NotFoundError):
        storage.open_range("calls/2026/09/04/nope.ogg", 0, None)
    with pytest.raises(NotFoundError):
        storage.stat("calls/2026/09/04/nope.ogg")


def test_delete_is_idempotent(storage: LocalFsAudioStorage, tmp_path: Path) -> None:
    """The retention job may retry; a second delete must not raise (UC-26)."""
    source = tmp_path / "c.part"
    source.write_bytes(b"x")
    key = storage.put("calls/2026/09/04/c.ogg", source).key
    storage.delete(key)
    storage.delete(key)


def test_a_key_cannot_escape_the_storage_root(storage: LocalFsAudioStorage) -> None:
    """``storage_key`` is a column, and columns get edited."""
    for evil in ("../../etc/passwd", "calls/../../../etc/passwd"):
        with pytest.raises(ValueError, match="escapes the storage root"):
            storage.stat(evil)


def test_incoming_path_is_inside_the_root(storage: LocalFsAudioStorage) -> None:
    upload_id = uuid4()
    path = storage.incoming_path(upload_id)
    assert path == storage.root / "incoming" / f"{upload_id}.part"
    assert path.parent.is_dir()


def test_ensure_ready_proves_the_volume_is_writable(tmp_path: Path) -> None:
    """``/readyz`` uses this: accepting uploads we cannot store is worse than 503."""
    store = LocalFsAudioStorage(tmp_path / "fresh")
    store.ensure_ready()
    assert (store.root / "calls").is_dir()
    assert (store.root / "incoming").is_dir()
    assert not (store.root / ".write-probe").exists()


def test_sha256_of_matches_hashlib(tmp_path: Path) -> None:
    """The device deletes its local copy on this value (N11)."""
    payload = b"y" * (1024 * 1024 + 7)
    path = tmp_path / "big.bin"
    path.write_bytes(payload)
    assert sha256_of(path) == hashlib.sha256(payload).hexdigest()
