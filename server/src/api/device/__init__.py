"""Device API routers (the Android app). Prefix: ``/api/device/v1``.

Every route here is part of a contract with a client on phones we cannot
force-update, so the rules of CONVENTIONS.md §4 apply to all of them: path
versioning, additive-only changes inside v1, the version gate with its
drain-route allow-list, and ``X-App-Version`` / ``X-Installation-Id`` required
on every request.

Module routers are included here rather than in ``main.py``: the composition
root mounts three surface routers and nothing else, so adding a module never
touches a file another unit is editing.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.api import DEVICE_API_PREFIX
from src.api.device import audio, auth, calls, commands, enrolment, telemetry

router = APIRouter(prefix=DEVICE_API_PREFIX)
router.include_router(enrolment.router)
router.include_router(auth.router)
router.include_router(calls.router)
router.include_router(telemetry.router)
router.include_router(audio.router)
router.include_router(commands.router)
