"""Panel API routers (the web panel). Prefix: ``/api/v1``.

Module routers are included here rather than in ``main.py``, for the same
reason as on the device surface: the composition root mounts three routers and
nothing else.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.api import PANEL_API_PREFIX
from src.api.panel import (
    agents,
    alerts,
    audio,
    audit,
    auth,
    calls,
    catalog,
    commands,
    devices,
    enrolment,
    installations,
    numbers,
    reports,
    settings,
    users,
)

router = APIRouter(prefix=PANEL_API_PREFIX)
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(agents.router)
router.include_router(numbers.router)
router.include_router(numbers.assignments_router)
router.include_router(enrolment.router)
router.include_router(enrolment.codes_router)
router.include_router(installations.router)
router.include_router(devices.router)
router.include_router(commands.router)
router.include_router(alerts.router)
router.include_router(audio.router)
router.include_router(catalog.router)
router.include_router(reports.router)
router.include_router(audit.router)
router.include_router(settings.router)
router.include_router(calls.router)
