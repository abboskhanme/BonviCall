"""Liveness and readiness — the only two routes with no audience (SPEC §4.7).

They are not on any of the three surfaces because they belong to none of them:
Docker, Caddy and the person on call read them. Both are public, and both are
listed in ``core.permissions.PUBLIC_ROUTES``.

``/healthz`` answers "is this process alive". ``/readyz`` answers "can it do
its job": a server that accepts uploads it cannot store, or writes it cannot
commit, must report itself unready rather than accept traffic.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from src.core.config import get_settings
from src.core.database import ping
from src.core.deps import SessionDep
from src.core.logging import get_logger
from src.core.storage import LocalFsAudioStorage

router = APIRouter(tags=["Health"])
log = get_logger(__name__)


class HealthResponse(BaseModel):
    """Process liveness."""

    status: str = Field(description="Always 'ok' when the process is serving.")


class ReadyResponse(BaseModel):
    """Dependency readiness, one flag per dependency."""

    status: str = Field(description="'ok' when every dependency is usable.")
    database: bool = Field(description="A trivial query succeeded.")
    storage: bool = Field(description="The audio root exists and is writable.")


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Liveness. Touches nothing, so a slow database cannot restart the app."""
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=ReadyResponse)
async def readyz(session: SessionDep, response: Response) -> ReadyResponse:
    """Readiness: the database answers and the audio root is writable."""
    database_ok = await ping(session)
    storage_ok = False
    if not database_ok:
        log.warning("readyz_database_unreachable")
    try:
        LocalFsAudioStorage(get_settings().audio_storage_path).ensure_ready()
        storage_ok = True
    except OSError as exc:  # the audio volume is missing, full or read-only
        log.warning("readyz_storage_failed", error=str(exc))

    ready = database_ok and storage_ok
    if not ready:
        response.status_code = 503
    return ReadyResponse(
        status="ok" if ready else "degraded", database=database_ok, storage=storage_ok
    )
