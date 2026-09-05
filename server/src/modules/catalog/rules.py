"""Reading an APK well enough to refuse the wrong one (N33).

The server is the update channel, so it hands salespeople the bytes their
phones install. Two things about those bytes have to be checked before they are
published, and neither is a matter of trusting the uploader:

1. **Is it an APK at all?** A zip with an ``AndroidManifest.xml`` entry. Cheap,
   and it catches the wrong file in the file picker.
2. **Which key signed it?** Android will not install a differently-signed build
   as an update — only as an uninstall-and-reinstall, which destroys the
   phone's unsent queue. On a fleet of personal handsets that is not a
   re-install, it is a data loss event and a second visit to fifteen people.

Only the **v2/v3 signing block** is read, not the legacy ``META-INF/*.RSA``.
A build whose only signature is v1 will not install on a modern target at all,
so "no v2/v3 block" is itself a finding worth refusing on rather than a case to
fall back for.

Pure: no framework, no ORM, no project imports. It parses bytes and returns
what it found (CONVENTIONS.md §2).
"""

from __future__ import annotations

import hashlib
import struct
import zipfile
from dataclasses import dataclass
from io import BytesIO

#: Section 4.3.16 of the zip spec. Located by scanning backwards; the comment
#: field means it is not at a fixed offset.
EOCD_MAGIC = b"PK\x05\x06"
EOCD_MIN_SIZE = 22
MAX_ZIP_COMMENT = 0xFFFF

#: The 16 bytes that end an APK Signing Block.
APK_SIG_BLOCK_MAGIC = b"APK Sig Block 42"

#: Scheme ids inside the block. v3 supersedes v2 and carries the same
#: certificate, so whichever is present answers the question.
SCHEME_V2_ID = 0x7109_871A
SCHEME_V3_ID = 0xF053_68C0


@dataclass(frozen=True)
class ApkInspection:
    """What the bytes turned out to be. Never raises — a bad file is an answer."""

    is_apk: bool
    signer_sha256: str | None
    reason: str | None
    sha256: str
    size_bytes: int

    @property
    def is_signed(self) -> bool:
        return self.signer_sha256 is not None


def normalise_fingerprint(value: str | None) -> str | None:
    """``AA:BB:…`` and ``aabb…`` are the same fingerprint.

    ``keytool`` prints colons and ``apksigner`` does not, and the configured
    value is typed by a person from whichever tool they happened to run.
    """
    if not value:
        return None
    return value.replace(":", "").replace(" ", "").strip().lower()


def inspect_apk(payload: bytes) -> ApkInspection:
    """Everything the publish path needs to know about an uploaded file."""
    digest = hashlib.sha256(payload).hexdigest()
    base = {"sha256": digest, "size_bytes": len(payload)}

    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError):
        return ApkInspection(False, None, "not_a_zip", **base)

    if "AndroidManifest.xml" not in names:
        return ApkInspection(False, None, "no_android_manifest", **base)

    try:
        fingerprint = _v2_signer_fingerprint(payload)
    except (struct.error, ValueError, IndexError):
        # A malformed signing block is not a crash, it is a refusal — and the
        # reason has to be specific enough for an admin to act on.
        return ApkInspection(True, None, "signing_block_unreadable", **base)

    if fingerprint is None:
        return ApkInspection(True, None, "no_v2_signature", **base)
    return ApkInspection(True, fingerprint, None, **base)


def _v2_signer_fingerprint(payload: bytes) -> str | None:
    """SHA-256 of the first signer's certificate, as ``apksigner`` prints it."""
    block = _signing_block(payload)
    if block is None:
        return None
    for scheme_id in (SCHEME_V3_ID, SCHEME_V2_ID):
        value = block.get(scheme_id)
        if value is not None:
            certificate = _first_certificate(value)
            if certificate is not None:
                return hashlib.sha256(certificate).hexdigest()
    return None


def _signing_block(payload: bytes) -> dict[int, bytes] | None:
    """The id-value pairs of the APK Signing Block, or ``None`` if absent."""
    central_directory = _central_directory_offset(payload)
    if central_directory is None or central_directory < 32:
        return None
    if payload[central_directory - 16 : central_directory] != APK_SIG_BLOCK_MAGIC:
        return None

    (size_at_end,) = struct.unpack_from("<Q", payload, central_directory - 24)
    start = central_directory - 8 - size_at_end
    if start < 0:
        return None
    (size_at_start,) = struct.unpack_from("<Q", payload, start)
    if size_at_start != size_at_end:
        return None

    pairs: dict[int, bytes] = {}
    cursor = start + 8
    limit = central_directory - 24
    while cursor < limit:
        (length,) = struct.unpack_from("<Q", payload, cursor)
        cursor += 8
        if length < 4 or cursor + length > central_directory:
            break
        (pair_id,) = struct.unpack_from("<I", payload, cursor)
        pairs[pair_id] = payload[cursor + 4 : cursor + length]
        cursor += length
    return pairs


def _first_certificate(value: bytes) -> bytes | None:
    """Walk the nested length-prefixed structure down to the first DER cert.

    ``signers -> signer -> signed_data -> digests, certificates -> cert``,
    every level a little-endian ``uint32`` length followed by that many bytes.
    Only the first signer is read: a build signed by several keys still has to
    match on the one Android compares, which is the first.
    """
    signers = _sized(value, 0)
    if signers is None:
        return None
    signer = _sized(signers, 0)
    if signer is None:
        return None
    signed_data = _sized(signer, 0)
    if signed_data is None:
        return None

    digests = _sized(signed_data, 0)
    if digests is None:
        return None
    certificates = _sized(signed_data, 4 + len(digests))
    if certificates is None:
        return None
    return _sized(certificates, 0)


def _sized(buffer: bytes, offset: int) -> bytes | None:
    """The length-prefixed chunk at ``offset``, or ``None`` if it does not fit."""
    if offset + 4 > len(buffer):
        return None
    (length,) = struct.unpack_from("<I", buffer, offset)
    end = offset + 4 + length
    if end > len(buffer):
        return None
    return buffer[offset + 4 : end]


def _central_directory_offset(payload: bytes) -> int | None:
    """Read it from the End of Central Directory record."""
    scan_from = max(0, len(payload) - EOCD_MIN_SIZE - MAX_ZIP_COMMENT)
    index = payload.rfind(EOCD_MAGIC, scan_from)
    if index < 0 or index + EOCD_MIN_SIZE > len(payload):
        return None
    (offset,) = struct.unpack_from("<I", payload, index + 16)
    return offset if offset < len(payload) else None
