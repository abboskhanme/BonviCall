"""Dependencies every device route uses (SPEC §4.2, CONVENTIONS.md §4).

A device principal holds no permissions — there is no role matrix on the phone
side. What protects these routes is the installation-bound token plus the two
gates below, and every device route carries at least
:data:`ActiveInstallationDep` or :data:`DeviceInstallationDep`.

The required headers are checked here rather than per route, so a missing one is
a 400 ``header_missing`` and never a 500 (§4 rule 5).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from src.core.deps import Principal, PrincipalDep, SessionDep
from src.core.enums import InstallationStatus
from src.core.errors import BadRequestError, ErrorCode, ForbiddenError, UnauthorizedError
from src.modules.devices.models import DeviceHealthModel
from src.modules.devices.usage import DataUsageService
from src.modules.installations.models import InstallationModel

#: Sent by the app on every request (SPEC §4.2). ``X-Installation-Id`` and
#: ``X-Device-Fingerprint`` are additionally matched against the token's claims
#: by the principal resolver — that is the N24 binding.
REQUIRED_DEVICE_HEADERS = ("X-App-Version", "X-Installation-Id")


def require_device_headers(request: Request) -> None:
    """400 ``header_missing`` when the app forgot one, naming which."""
    missing = [name for name in REQUIRED_DEVICE_HEADERS if not request.headers.get(name)]
    if missing:
        raise BadRequestError(ErrorCode.HEADER_MISSING, detail={"headers": missing})


async def require_device(request: Request, principal: PrincipalDep) -> Principal:
    """The caller is an installation, and it sent the headers it must send.

    Order matters and is the reason the header check lives here rather than as
    a route-level dependency: a request with no token at all must answer 401,
    not "you forgot X-App-Version". Telling an unauthenticated caller which
    headers we expect is both a leak and confusing.
    """
    if principal.kind != "device":
        raise UnauthorizedError()
    require_device_headers(request)
    return principal


async def require_installation(
    session: SessionDep, principal: Annotated[Principal, Depends(require_device)]
) -> InstallationModel:
    """The installation row behind the token, in whatever state it is in.

    Used by the routes an unverified phone is still allowed to call.
    """
    installation = await session.get(InstallationModel, principal.installation_id)
    if installation is None:
        raise UnauthorizedError()
    return installation


async def require_active_installation(
    request: Request,
    session: SessionDep,
    installation: Annotated[InstallationModel, Depends(require_installation)],
) -> InstallationModel:
    """The installation must be verified.

    This is where the privacy boundary starts on the server: an unverified
    phone cannot upload a single call, because it cannot get past this
    dependency (SPEC §4.2). ``replaced`` is deliberately allowed through —
    a superseded installation keeps draining its queue, and only its *refresh*
    is refused (SPEC §9.3). Refusing an old binding must never destroy data.
    """
    if installation.status not in (
        InstallationStatus.ACTIVE,
        InstallationStatus.REPLACED,
    ):
        raise ForbiddenError(ErrorCode.VERIFICATION_REQUIRED)

    # N14/N15's accounting happens here because this is the one place every
    # ingest request passes through and the request size is already known.
    # The approximation is documented in modules/devices/usage.py.
    health = await session.get(DeviceHealthModel, installation.id)
    await DataUsageService(session).record(
        installation.id,
        health.network_type if health else None,
        int(request.headers.get("Content-Length") or 0),
    )
    return installation


DeviceHeadersDep = Depends(require_device_headers)
DevicePrincipalDep = Annotated[Principal, Depends(require_device)]
InstallationDep = Annotated[InstallationModel, Depends(require_installation)]
ActiveInstallationDep = Annotated[
    InstallationModel, Depends(require_active_installation)
]

__all__ = [
    "REQUIRED_DEVICE_HEADERS",
    "ActiveInstallationDep",
    "DeviceHeadersDep",
    "DevicePrincipalDep",
    "InstallationDep",
    "require_active_installation",
    "require_device",
    "require_device_headers",
    "require_installation",
]
