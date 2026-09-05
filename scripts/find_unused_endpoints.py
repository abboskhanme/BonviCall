#!/usr/bin/env python3
"""Endpoints the contract declares and no client calls.

WHY THIS EXISTS
---------------
Six times in this project something was built, tested, lint-clean and
**unreachable**, and every suite stayed green because the tests exercised the
thing directly:

* ``POST /api/v1/auth/password`` — no caller
* the WebSocket router — finished, unregistered, its own tests mounted it
* ``DeviceCallsApi.heartbeat`` — generated, never called
* the attest endpoint — no caller
* ``SessionStore.saveBaseUrl`` — no caller
* a base URL pointing at a domain that does not exist

None of these is a bug a unit test can see, because the gap is *between* the
units. The contract is the one place that knows the whole surface, and the repo
root is the one place that can see both clients — which is why this is a script
run from there rather than a test inside a container that mounts one directory.

WHAT IT DOES
------------
Reads every path out of ``contract/openapi-*.json``, then looks for that path in
the panel's and the app's sources. A path nobody mentions is reported.

Deliberately a **text search**, not a call graph: the panel builds URLs from
generated types and the app from Retrofit annotations, and an analyser clever
enough to follow both would be wrong in a new way every month. A grep that
occasionally reports a false positive, and says so, is the honest tool.

    make check-endpoints
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contract"

CLIENT_SOURCES = (ROOT / "panel/src", ROOT / "android/app/src/main/kotlin")
SOURCE_SUFFIXES = {".ts", ".tsx", ".kt", ".java"}

#: **Generated** sources are excluded, and this is the whole trick.
#: ``types.gen.ts`` is generated *from* the contract, so it contains every path
#: by construction and searching it would report that everything has a caller —
#: which is the answer that makes the check useless. What we are looking for is
#: hand-written code that *uses* the generated types.
GENERATED = ("types.gen.ts", "/data/remote/dto/")


def is_generated(path: pathlib.Path) -> bool:
    text = path.as_posix()
    return any(marker in text for marker in GENERATED)

#: Paths with no client caller **on purpose**, each with the reason. An entry
#: here claims something other than a client uses it; a claim that stops being
#: true shows up as a stale entry.
ALLOWED: dict[str, str] = {
    "/readyz": "Docker and Caddy, not a client",
    "/api/service/v1/export/calls": "BonviZvonki's adapter, a different repository",
    "/api/service/v1/export/agents": "BonviZvonki's adapter",
    "/api/service/v1/export/calls/{call_id}/audio": "BonviZvonki's adapter",
    "/api/service/v1/callback-events": "BonviZvonki posts these to us",
}
# ``/healthz`` was in this list with the reason "Docker and Caddy, not a
# client". The reverse check removed it within minutes of the list being
# written: the app probes it to find its server before enrolment
# (``ServerAddressRepository``). The audio upload routes were listed as "client
# in flight" and were called by the time the list was read. Both are why the
# reverse check exists — an allow-list is a set of claims, and claims rot.


def contract_paths() -> dict[str, set[str]]:
    paths: dict[str, set[str]] = {}
    for document in sorted(CONTRACT.glob("openapi-*.json")):
        data = json.loads(document.read_text(encoding="utf-8"))
        for path, operations in data.get("paths", {}).items():
            paths.setdefault(path, set()).update(
                method.upper() for method in operations if method != "parameters"
            )
    return paths


def client_text() -> str:
    chunks = []
    for root in CLIENT_SOURCES:
        if not root.is_dir():
            print(f"note: {root} not present, skipping", file=sys.stderr)
            continue
        for path in root.rglob("*"):
            if path.suffix in SOURCE_SUFFIXES and path.is_file() and not is_generated(path):
                chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


#: Clients write paths **relative to their base URL**: Retrofit annotations say
#: ``@POST("heartbeat")`` and the panel's client is constructed with the ``/api/v1``
#: prefix already applied. Matching the full path finds nothing.
API_PREFIXES = ("/api/device/v1/", "/api/service/v1/", "/api/v1/")


def searchable(path: str) -> str:
    """The part of a path a hand-written client source actually contains.

    The surface prefix is stripped, then the longest literal run of what
    remains: ``/api/v1/devices/{installation_id}/commands`` is a template in the
    panel and a Retrofit annotation with its own placeholder names in the app,
    so the parameter names cannot be matched and the literal runs can.
    """
    tail = path
    for prefix in API_PREFIXES:
        if path.startswith(prefix):
            tail = path[len(prefix) :]
            break
    runs = [run.strip("/") for run in re.split(r"\{[^}]+\}", tail)]
    # Longest wins, and a tie goes to the **last** run: for
    # "audio/{upload_id}/chunk" both "audio" and "chunk" are five characters,
    # and "audio" appears in half the client tree while "chunk" is the endpoint.
    return max(enumerate(runs), key=lambda pair: (len(pair[1]), pair[0]))[1]


def mentioned(needle: str, text: str) -> bool:
    """Whether a client source uses ``needle`` **as a path segment**.

    Bare substring matching found "chunk" in a transcoder loop and "commit" in
    the word "committing". A path is written after a quote or a slash —
    ``@PUT("audio/{uploadId}/chunk")``, ``'/line-directory'`` — so that is what
    is required. Still a grep, still occasionally wrong, but wrong far less
    often than the version that reads prose.
    """
    return re.search(rf"""[/"'`]{re.escape(needle)}\b""", text) is not None


def main() -> int:
    text = client_text()
    if not text:
        print("no client sources found — nothing to check", file=sys.stderr)
        return 0

    paths = contract_paths()
    unused = [
        f"{'/'.join(sorted(methods)):18} {path}"
        for path, methods in sorted(paths.items())
        if path not in ALLOWED
        and len(searchable(path)) >= 4
        and not mentioned(searchable(path), text)
    ]
    stale = [
        f"{entry}: no such path in the contract"
        for entry in sorted(ALLOWED)
        if entry not in paths
    ]
    # The other direction, and the one that matters: an entry that says "no
    # client calls this" while a client now does. Without it an allow-list
    # entry outlives its reason and quietly re-hides the next dead endpoint.
    stale += [
        f"{entry}: a client calls it now — remove the entry ({reason})"
        for entry, reason in sorted(ALLOWED.items())
        if entry in paths
        and len(searchable(entry)) >= 4
        and mentioned(searchable(entry), text)
    ]

    for entry in stale:
        print(f"stale allow-list entry — {entry}")
    if unused:
        print(f"\n{len(unused)} endpoint(s) no client mentions:\n")
        for line in unused:
            print(f"  {line}")
        print(
            "\nEach is either dead weight, or something a client was meant to "
            "call and does not.\nIf it is deliberate, add it to ALLOWED in this "
            "file with the reason."
        )
    else:
        print("every endpoint has a caller")
    return 1 if (unused or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
