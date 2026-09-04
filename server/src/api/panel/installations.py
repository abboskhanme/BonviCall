"""Installation lifecycle from the panel (T35, T142; UC-07, UC-08)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request

from src.core.deps import PrincipalDep, SessionDep
from src.core.enums import InstallationStatus
from src.core.permissions import Perm, require_permission
from src.modules.installations.schemas import (
    AttestRequest,
    InstallationListResponse,
    InstallationResponse,
    RevokeRequest,
    RevokeResponse,
)
from src.modules.installations.service import InstallationService

router = APIRouter(prefix="/installations", tags=["Installations"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get(
    "",
    response_model=InstallationListResponse,
    dependencies=[Depends(require_permission(Perm.INSTALLATIONS_READ))],
)
async def list_installations(
    session: SessionDep,
    status: InstallationStatus | None = None,
    agent_id: uuid.UUID | None = None,
) -> InstallationListResponse:
    items, total = await InstallationService(session).list(status, agent_id)
    return InstallationListResponse(
        items=[InstallationResponse.model_validate(row) for row in items], total=total
    )


@router.get(
    "/{installation_id}",
    response_model=InstallationResponse,
    dependencies=[Depends(require_permission(Perm.INSTALLATIONS_READ))],
)
async def get_installation(
    installation_id: uuid.UUID, session: SessionDep
) -> InstallationResponse:
    return InstallationResponse.model_validate(
        await InstallationService(session).get(installation_id)
    )


@router.post(
    "/{installation_id}/attest",
    response_model=InstallationResponse,
    dependencies=[Depends(require_permission(Perm.ENROLMENT_ATTEST))],
)
async def attest_installation(
    installation_id: uuid.UUID,
    payload: AttestRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> InstallationResponse:
    """Admin attestation (T142) — weaker than proven, and shown as such.

    The reason is mandatory and lands in the audit log. The funnel stage
    becomes ``verified_by_admin``, which the panel renders differently from
    ``number_verified`` everywhere it appears.
    """
    installation = await InstallationService(session).attest(
        installation_id, payload.reason, principal.id, _client_ip(request)
    )
    return InstallationResponse.model_validate(installation)


@router.post(
    "/{installation_id}/revoke",
    response_model=RevokeResponse,
    dependencies=[Depends(require_permission(Perm.INSTALLATIONS_REVOKE))],
)
async def revoke_installation(
    installation_id: uuid.UUID,
    payload: RevokeRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> RevokeResponse:
    """Stop capture and kill every issued token (UC-08).

    The response carries what was still queued at last contact, because the
    admin's next question is always "did we lose anything".
    """
    installation = await InstallationService(session).revoke(
        installation_id, principal.id, _client_ip(request), payload.reason
    )
    return RevokeResponse(
        installation_id=installation.id,
        status=installation.status,
        revoked_at=installation.revoked_at,
        pending_records=installation.revoke_pending_records,
        pending_bytes=installation.revoke_pending_bytes,
        confirmed=installation.revoke_confirmed_at is not None,
    )
