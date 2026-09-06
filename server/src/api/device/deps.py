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
from starlette.requests import HTTPConnection

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


def require_device_headers(connection: HTTPConnection) -> None:
    """400 ``header_missing`` when the app forgot one, naming which.

    ``HTTPConnection`` rather than ``Request`` so the realtime socket's
    handshake is held to the same rule as every REST call — an app that opens a
    socket without ``X-Installation-Id`` is refused there too, and there is one
    implementation of that rule rather than two (SPEC §4.6).
    """
    missing = [
        name for name in REQUIRED_DEVICE_HEADERS if not connection.headers.get(name)
    ]
    if missing:
        raise BadRequestError(ErrorCode.HEADER_MISSING, detail={"headers": missing})


async def require_device(
    connection: HTTPConnection, principal: PrincipalDep
) -> Principal:
    """The caller is an installation, and it sent the headers it must send.

    Order matters and is the reason the header check lives here rather than as
    a route-level dependency: a request with no token at all must answer 401,
    not "you forgot X-App-Version". Telling an unauthenticated caller which
    headers we expect is both a leak and confusing.
    """
    if principal.kind != "device":
        raise UnauthorizedError()
    require_device_headers(connection)
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


def _assert_verified(installation: InstallationModel) -> None:
    """The privacy boundary's server-side gate, in one place.

    ``replaced`` is deliberately allowed through — a superseded installation
    keeps draining its queue, and only its *refresh* is refused (SPEC §9.3).
    Refusing an old binding must never destroy data.

    It lives in its own function because both the REST gate and the socket gate
    ask it, and a rule about who may send us recordings that exists twice is a
    rule that will one day only be fixed once.
    """
    if installation.status not in (
        InstallationStatus.ACTIVE,
        InstallationStatus.REPLACED,
    ):
        raise ForbiddenError(ErrorCode.VERIFICATION_REQUIRED)


async def require_active_installation(
    request: Request,
    session: SessionDep,
    installation: Annotated[InstallationModel, Depends(require_installation)],
) -> InstallationModel:
    """The installation must be verified, and the request must be counted.

    This is where the privacy boundary starts on the server: an unverified
    phone cannot upload a single call, because it cannot get past this
    dependency (SPEC §4.2). The verification rule itself is
    :func:`_assert_verified`, shared with the socket gate.
    """
    _assert_verified(installation)
    await _count_request(request, session, installation)
    return installation


async def _count_request(
    request: Request, session: SessionDep, installation: InstallationModel
) -> None:
    """N14/N15's accounting, on every device write.

    Kept out of the verification gate so that the routes which do **not**
    require verification are still counted: the employee pays for this data,
    and a request we chose not to gate is not a request we chose not to meter.
    The approximation is documented in modules/devices/usage.py.
    """
    health = await session.get(DeviceHealthModel, installation.id)
    await DataUsageService(session).record(
        installation.id,
        health.network_type if health else None,
        int(request.headers.get("Content-Length") or 0),
    )


async def require_self_reporting_installation(
    request: Request,
    session: SessionDep,
    installation: Annotated[InstallationModel, Depends(require_installation)],
) -> InstallationModel:
    """A phone reporting facts **about itself**, verified or not (R17, UC-06).

    Capability states and enrolment events are posted during E2 — one per
    permission, as each check completes — which is *before* E4/E5 where the
    number is verified. Gating them on verification threw away every one of
    them, and threw away most reliably for the phone that never finishes
    verifying, which is the phone an admin most needs to see.

    That is exactly R17's purpose: knowing **which permission** a stuck
    salesperson is stuck on, within two minutes, without telephoning them.

    Safe because of what these routes are, not because of who is asking:
    a device writes facts about the installation its own token is bound to. It
    reads nothing, returns nothing about anybody else, and cannot reach another
    agent's data. Verification protects the *number binding* — "is this handset
    really on this line" — and a permission state is not a claim about a line.

    Everything about a specific agent's data stays behind
    :func:`require_active_installation`: ``/calls`` in both directions, the
    audio routes, and the heartbeat.
    """
    await _count_request(request, session, installation)
    return installation


async def require_ws_installation(
    installation: Annotated[InstallationModel, Depends(require_installation)],
) -> InstallationModel:
    """The realtime socket's gate (SPEC §4.6).

    Same verification rule as :func:`require_active_installation` and
    deliberately **not** its data accounting: that is per-request and reads
    ``Content-Length``, and a socket has neither. N15's cellular budget is about
    metadata and audio uploads, which do not travel on this channel.
    """
    _assert_verified(installation)
    return installation


DeviceHeadersDep = Depends(require_device_headers)
DevicePrincipalDep = Annotated[Principal, Depends(require_device)]
InstallationDep = Annotated[InstallationModel, Depends(require_installation)]
ActiveInstallationDep = Annotated[
    InstallationModel, Depends(require_active_installation)
]
WsInstallationDep = Annotated[InstallationModel, Depends(require_ws_installation)]
SelfReportingInstallationDep = Annotated[
    InstallationModel, Depends(require_self_reporting_installation)
]

__all__ = [
    "REQUIRED_DEVICE_HEADERS",
    "ActiveInstallationDep",
    "DeviceHeadersDep",
    "DevicePrincipalDep",
    "InstallationDep",
    "SelfReportingInstallationDep",
    "WsInstallationDep",
    "require_active_installation",
    "require_device",
    "require_device_headers",
    "require_installation",
    "require_self_reporting_installation",
    "require_ws_installation",
]
