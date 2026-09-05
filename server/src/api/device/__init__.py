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
from src.api.device import audio, auth, calls, commands, enrolment, telemetry, ws

router = APIRouter(prefix=DEVICE_API_PREFIX)
router.include_router(enrolment.router)
router.include_router(auth.router)
router.include_router(calls.router)
router.include_router(telemetry.router)
router.include_router(audio.router)
router.include_router(commands.router)
# The realtime socket (SPEC §4.6). No prefix of its own: it is one path,
# and ``/ws`` under a ``/commands`` prefix would say it carries only
# commands, which is already untrue — it carries presence and the ping
# clock too.
router.include_router(ws.router)
