"""Generate the committed wire contract (T23, CONVENTIONS.md §1).

**Code-first.** The Pydantic schemas are the source of truth; the JSON under
``contract/`` is a build artefact that is committed, and CI runs::

    make contract && git diff --exit-code contract/

so a wire-format change that is not visible in the pull request diff is
impossible. Kotlin DTOs and panel types are generated from these files and are
never hand-written — a renamed field must be a compile error on a fleet of 15
phones we cannot force-update, not a runtime ``undefined``.

Four artefacts:

===========================================  ==================================
``contract/openapi-device-v1.json``          Android DTOs
``contract/openapi-panel-v1.json``           panel TypeScript types
``contract/openapi-service-v1.json``         BonviZvonki's ingest adapter
``contract/error-codes.json``                the ``code`` catalogue of §9
===========================================  ==================================

The error-code file carries codes and statuses only, never messages: clients
branch on ``code`` and never on ``message`` (SPEC §4.0), and the Uzbek text
lives in ``core/messages_uz.py``, which is one of the three files allowed to
contain Uzbek (§14).

``/healthz`` and ``/readyz`` are exported in the panel document. They belong to
no surface — Docker and Caddy read them — and inventing a fourth document for
two routes would be worse than saying so here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from src.api import DEVICE_API_PREFIX, PANEL_API_PREFIX, SERVICE_API_PREFIX
from src.core.errors import ErrorCode
from src.main import API_VERSION, create_app

#: ``server/../contract``. The Makefile mounts the repository, so this resolves
#: to the same directory inside the container and on a developer machine.
CONTRACT_DIR = Path(__file__).resolve().parents[2] / "contract"

#: (file stem, title, prefix). Order is the order the files are written in.
SURFACES: tuple[tuple[str, str, str], ...] = (
    ("openapi-device-v1", "BonviCall device API", DEVICE_API_PREFIX),
    ("openapi-panel-v1", "BonviCall panel API", PANEL_API_PREFIX),
    ("openapi-service-v1", "BonviCall service API", SERVICE_API_PREFIX),
)

#: Routes with no surface of their own, exported with the panel document.
UNPREFIXED_PATHS: frozenset[str] = frozenset({"/healthz", "/readyz"})


def _routes_for(app: FastAPI, prefix: str) -> list[APIRoute]:
    routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(prefix)
    ]
    if prefix == PANEL_API_PREFIX:
        routes += [
            route
            for route in app.routes
            if isinstance(route, APIRoute) and route.path in UNPREFIXED_PATHS
        ]
    return sorted(routes, key=lambda route: (route.path, sorted(route.methods)))


def _dump(path: Path, document: dict[str, Any]) -> bool:
    """Write ``document`` deterministically. True when the bytes changed."""
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    previous = path.read_text(encoding="utf-8") if path.exists() else None
    path.write_text(text, encoding="utf-8")
    return previous != text


def build_documents(app: FastAPI | None = None) -> dict[str, dict[str, Any]]:
    """Every contract document, keyed by file stem. Pure — writes nothing."""
    app = app or create_app()
    documents = {
        stem: get_openapi(
            title=title,
            version=API_VERSION,
            description=f"Generated from the Pydantic schemas. Prefix: {prefix}",
            routes=_routes_for(app, prefix),
        )
        for stem, title, prefix in SURFACES
    }
    documents["error-codes"] = {
        "description": (
            "Stable machine contract. Clients branch on 'code', never on the "
            "message; the Uzbek text lives in server/src/core/messages_uz.py."
        ),
        "codes": sorted(ErrorCode.all_codes()),
    }
    return documents


def export(directory: Path = CONTRACT_DIR) -> list[str]:
    """Write every document. Returns the stems whose bytes changed."""
    directory.mkdir(parents=True, exist_ok=True)
    return [
        stem
        for stem, document in build_documents().items()
        if _dump(directory / f"{stem}.json", document)
    ]


if __name__ == "__main__":
    changed = export()
    if changed:
        print("contract updated:", ", ".join(sorted(changed)))
    else:
        print("contract unchanged")
