"""Device token refresh (SPEC §4.2, §4.3).

This is the **only** device route that may ever refuse an old client on version
(N34), and only once its queue has drained. Ingest never refuses: refusing an
old version must never destroy data.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.core import clock
from src.core.deps import SessionDep
from src.modules.enrolment.schemas import DeviceRefreshIn, DeviceTokenPairOut
from src.modules.installations.service import InstallationService

router = APIRouter(prefix="/auth", tags=["Device auth"])


@router.post("/refresh", response_model=DeviceTokenPairOut)
async def refresh(payload: DeviceRefreshIn, session: SessionDep) -> DeviceTokenPairOut:
    """Rotate the installation's token pair.

    Guarded by the refresh token itself: there is no access token to check,
    because the whole reason to call this is that the access token expired.
    Reuse of a spent token increments ``token_version``, which kills every
    token already issued to that installation.
    """
    installation, pair = await InstallationService(session).refresh_device(payload.refresh_token)
    return DeviceTokenPairOut(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
        installation_id=installation.id,
        status=installation.status,
        verification_method=installation.verification_method,
        server_time=clock.now(),
    )
