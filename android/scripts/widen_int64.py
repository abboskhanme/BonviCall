#!/usr/bin/env python3
"""Widen the generated DTO fields whose contract type cannot hold their range.

WHY THIS EXISTS
---------------
Pydantic's ``int`` is unbounded, so a field declared ``int`` serialises fine in
Python. It reaches OpenAPI as ``{"type": "integer"}`` with **no format**, and
openapi-generator maps a formatless integer to ``kotlin.Int`` — 32 bits.

``System.currentTimeMillis()`` is about 1.77e12. ``Int.MAX_VALUE`` is 2.1e9.
Every ``device_epoch_ms`` on the wire is three orders of magnitude too big for
the type the contract asks the client to use, and the same is true of the byte
counters: free storage on a 128 GB handset is 1.28e11.

The server stores all of these as BIGINT (CONVENTIONS.md §6 and §10 both say
so), so the DATA model is right and only the wire schema is under-specified.
This script is the client-side stopgap. It is machine-applied and listed, so it
is not a hand-written DTO (CONVENTIONS.md §1) — but it IS a workaround for a
server bug and it should not outlive it.

THE FIX, AND HOW THIS FILE DIES
-------------------------------
On the server, annotate those fields so the schema carries ``format: int64``::

    Int64 = Annotated[int, Field(json_schema_extra={"format": "int64"})]
    device_epoch_ms: Int64

``make contract`` then emits ``{"type": "integer", "format": "int64"}``,
openapi-generator emits ``kotlin.Long`` unaided, and this script becomes a no-op.
``Int64WireContractTest`` fails the moment a listed field gains the format,
which is the signal to delete the entry — and the whole script once the list is
empty.

Raised for build-backend on 2026-09-05.
"""
from __future__ import annotations

import pathlib
import re
import sys

DTO_DIR = pathlib.Path(__file__).resolve().parents[1] / (
    "app/src/main/kotlin/uz/bonvi/call/data/remote/dto"
)

#: (DTO file stem, Kotlin property name). Only fields whose REAL range exceeds
#: 32 bits. A field that merely could be large one day does not belong here —
#: the list has to stay auditable.
WIDEN: tuple[tuple[str, str], ...] = (
    # Wall-clock milliseconds. ~1.77e12 today, and it only grows.
    ("DeviceRedeemIn", "deviceEpochMs"),
    ("DeviceCallIn", "deviceEpochMs"),
    ("DeviceHeartbeatIn", "deviceEpochMs"),
    # Byte counters. Free storage on a 128 GB phone is 1.28e11.
    ("DeviceHeartbeatIn", "freeStorageBytes"),
    ("DeviceHeartbeatIn", "queueBytes"),
    ("DeviceHeartbeatIn", "cellularBytesMonth"),
    ("DeviceEventDetailIn", "freeStorageBytes"),
    ("DeviceEventDetailIn", "queueBytes"),
    ("DeviceEventDetailIn", "deletedBytes"),
)

BANNER = (
    "// PATCHED by android/scripts/widen_int64.py: the contract declares this\n"
    "// field as a formatless integer, which generates as a 32-bit kotlin.Int\n"
    "// and cannot hold its real range. Delete the patch once the server emits\n"
    "// format: int64 — Int64WireContractTest says when.\n"
)


def widen(text: str, prop: str) -> tuple[str, bool]:
    pattern = re.compile(
        rf"(val\s+{re.escape(prop)}\s*:\s*)kotlin\.Int(\??)(\s*=\s*null)?",
    )
    if not pattern.search(text):
        return text, False
    return pattern.sub(r"\1kotlin.Long\2\3", text, count=1), True


def main() -> int:
    if not DTO_DIR.is_dir():
        print(f"no generated DTOs at {DTO_DIR}", file=sys.stderr)
        return 1

    missing: list[str] = []
    patched = 0
    for stem, prop in WIDEN:
        path = DTO_DIR / f"{stem}.kt"
        if not path.is_file():
            missing.append(f"{stem}.kt")
            continue
        text = path.read_text(encoding="utf-8")
        new_text, changed = widen(text, prop)
        if not changed:
            # Already Long: the server fixed it. Not an error — the entry is
            # now stale and Int64WireContractTest will say so.
            continue
        if BANNER not in new_text:
            new_text = new_text.replace("package ", BANNER + "\npackage ", 1)
        path.write_text(new_text, encoding="utf-8")
        patched += 1

    if missing:
        print("missing generated files: " + ", ".join(sorted(set(missing))), file=sys.stderr)
        return 1

    print(f"widened {patched} field(s) to kotlin.Long")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
