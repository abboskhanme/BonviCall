"""Service API routers (machine export, callback receiver). Prefix:
``/api/service/v1``.

This surface is a **committed contract**: BonviZvonki is wired to it in
release 2 (SPEC §4.9), so a change here is a breaking change for another
product.

"""

from __future__ import annotations

from fastapi import APIRouter

from src.api import SERVICE_API_PREFIX
from src.api.service import callback, export

router = APIRouter(prefix=SERVICE_API_PREFIX)
router.include_router(callback.router)
router.include_router(export.router)
