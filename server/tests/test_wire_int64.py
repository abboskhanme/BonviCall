"""Integer fields declare the width their range actually needs.

The bug this exists for: Pydantic's ``int`` is unbounded, so a 64-bit value
serialises perfectly and stores in a ``BIGINT``, but it reaches OpenAPI as a
formatless ``integer`` and openapi-generator maps that to a 32-bit
``kotlin.Int``. ``System.currentTimeMillis()`` is ~1.77e12 against an
``Int.MAX_VALUE`` of 2.1e9. Every timestamp on the wire, on every device.

It was found by the Android side generating a client, because neither half is
wrong on its own — and once found, the same mistake turned out to be on the
service surface too (``CallbackEventIn.receiver_epoch_ms``), which nobody
generating an *Android* client could have seen.

So this checks the contract, not the schemas: it is the generated artefact that
a client is built from. It fails in **both** directions on purpose. A field that
needs 64 bits and does not say so is the original bug; a field that claims 64
bits it cannot use makes the list unauditable, and an unauditable list is how
the original bug survives a review.
"""

from __future__ import annotations

import json
import re

import pytest

from src.contract_export import CONTRACT_DIR, build_documents

#: Names whose real range exceeds 32 bits. Wall-clock milliseconds (1.77e12 and
#: growing), and byte counts of things measured in gigabytes — free storage on a
#: 128 GB handset is 1.28e11, and the audio volume is provisioned at 250 GB.
NEEDS_64_BITS = re.compile(r"(_epoch_ms$|bytes)")

#: Byte-named fields that genuinely fit in 32 bits, with the reason. Each one is
#: a *single audio file*: a 90-minute call at 24 kbps is about 16 MB, and the
#: chunk ceiling is 8 MB. A field that cannot overflow should not claim it can.
FITS_IN_32_BITS: dict[str, str] = {
    "OpenUploadIn.bytes_total": "one recording, ~16 MB at 90 minutes",
    "UploadStatusOut.bytes_total": "same file",
    "UploadStatusOut.received_bytes": "progress through the same file",
    "OpenUploadOut.received_bytes": "progress through the same file",
    "ChunkAcceptedOut.received_bytes": "progress through the same file",
    "CommitOut.bytes": "the stored recording",
}

#: Fields declared 64-bit for a reason the name does not show. Kept explicit so
#: the annotation cannot spread by imitation.
WIDENED_BY_EXCEPTION: dict[str, str] = {
    "CallResponse.seq": "BIGINT sequence; it is also the export cursor",
    "ExportCallOut.seq": "the cursor BonviZvonki pages on",
    "ExportCallsResponse.next_since": "the cursor, round-tripped by an adapter",
}


def _integer_properties() -> list[tuple[str, str, dict]]:
    """``(document, "Schema.property", spec)`` for every integer on the wire."""
    found = []
    for stem, document in build_documents().items():
        if not stem.startswith("openapi-"):
            continue
        schemas = document.get("components", {}).get("schemas", {})
        for name, schema in schemas.items():
            for prop, spec in (schema.get("properties") or {}).items():
                # ``int | None`` becomes an anyOf; the integer branch is the one
                # a generator turns into a field type.
                for variant in spec.get("anyOf", [spec]):
                    if variant.get("type") == "integer":
                        found.append((stem, f"{name}.{prop}", variant))
                        break
    return found


def test_every_field_that_needs_64_bits_says_so() -> None:
    """The original bug, on every surface at once."""
    narrow = [
        f"{stem}: {key}"
        for stem, key, spec in _integer_properties()
        if NEEDS_64_BITS.search(key.split(".", 1)[1])
        and key not in FITS_IN_32_BITS
        and spec.get("format") != "int64"
    ]
    assert narrow == [], (
        "these reach a generated client as a 32-bit integer and cannot hold "
        f"their range: {narrow}. Annotate them `Int64` (src/core/wire.py), or "
        "add them to FITS_IN_32_BITS with the reason they cannot overflow."
    )


def test_nothing_claims_64_bits_it_cannot_use() -> None:
    """The other direction, so the list stays worth reading."""
    unjustified = [
        f"{stem}: {key}"
        for stem, key, spec in _integer_properties()
        if spec.get("format") == "int64"
        and not NEEDS_64_BITS.search(key.split(".", 1)[1])
        and key not in WIDENED_BY_EXCEPTION
    ]
    assert unjustified == [], (
        f"declared int64 with nothing in the name to justify it: {unjustified}. "
        "Either it is a byte count or an epoch and should be named like one, or "
        "it belongs in WIDENED_BY_EXCEPTION with its reason."
    )


def test_the_32_bit_exceptions_all_still_exist() -> None:
    """A stale exception is a hole that looks like a decision."""
    live = {key for _, key, _ in _integer_properties()}
    stale = sorted(
        key for key in FITS_IN_32_BITS | WIDENED_BY_EXCEPTION if key not in live
    )
    assert stale == [], f"listed but no longer on the wire: {stale}"


@pytest.mark.parametrize(
    "field",
    [
        "DeviceRedeemIn.device_epoch_ms",
        "DeviceCallIn.device_epoch_ms",
        "DeviceHeartbeatIn.device_epoch_ms",
        "DeviceHeartbeatIn.free_storage_bytes",
        "DeviceHeartbeatIn.queue_bytes",
        "DeviceHeartbeatIn.cellular_bytes_month",
        "DeviceEventDetailIn.free_storage_bytes",
        "DeviceEventDetailIn.queue_bytes",
        "DeviceEventDetailIn.deleted_bytes",
    ],
)
def test_the_nine_android_reported_are_int64_in_the_committed_contract(field: str) -> None:
    """Named one by one, against the file on disk.

    ``android/scripts/widen_int64.py`` patched exactly these, and their
    ``Int64WireContractTest`` fails once they carry the format — which is the
    signal to delete the stopgap. Listing them individually means this suite
    says which one regressed, not merely that something did.
    """
    document = json.loads(
        (CONTRACT_DIR / "openapi-device-v1.json").read_text(encoding="utf-8")
    )
    schema_name, prop = field.split(".")
    spec = document["components"]["schemas"][schema_name]["properties"][prop]
    variant = next(
        (v for v in spec.get("anyOf", [spec]) if v.get("type") == "integer"), None
    )
    assert variant is not None, f"{field} is no longer an integer"
    assert variant.get("format") == "int64", f"{field} would generate as kotlin.Int"
