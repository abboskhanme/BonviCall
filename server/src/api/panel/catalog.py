"""The line directory: the admin's half of internal/external (T49, UC-25).

The **derived** half — every registered number — is computed at classification
time and never copied into this table. Copying it is exactly how BonviZvonki's
directory starved: somebody had to maintain it, and 10 of 33 employees had an
entry, after which a content classifier had to guess and mislabelled 82 of 98
calls.

Changing a rule re-runs the classification, because a number that is internal
today was internal yesterday too and a report that says otherwise is wrong.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status

from src.core.deps import PrincipalDep, SessionDep
from src.core.permissions import Perm, require_permission
from src.modules.catalog.schemas import (
    CreateDirectoryEntryRequest,
    DirectoryEntryListResponse,
    DirectoryEntryResponse,
    ReclassifyResponse,
)
from src.modules.catalog.service import CatalogService

router = APIRouter(prefix="/line-directory", tags=["Line directory"])


@router.get(
    "",
    response_model=DirectoryEntryListResponse,
    dependencies=[Depends(require_permission(Perm.SETTINGS_READ))],
)
async def list_entries(session: SessionDep) -> DirectoryEntryListResponse:
    items, total = await CatalogService(session).list_directory_entries()
    return DirectoryEntryListResponse(
        items=[DirectoryEntryResponse.model_validate(row) for row in items], total=total
    )


@router.post(
    "",
    response_model=ReclassifyResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(Perm.SETTINGS_WRITE))],
)
async def create_entry(
    payload: CreateDirectoryEntryRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> ReclassifyResponse:
    """Add a rule and re-run the classification in the same transaction."""
    entry, reclassified = await CatalogService(session).add_directory_entry(
        payload, principal.id, request.client.host if request.client else None
    )
    return ReclassifyResponse(
        entry=DirectoryEntryResponse.model_validate(entry), calls_reclassified=reclassified
    )


@router.delete(
    "/{entry_id}",
    response_model=ReclassifyResponse,
    dependencies=[Depends(require_permission(Perm.SETTINGS_WRITE))],
)
async def delete_entry(
    entry_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> ReclassifyResponse:
    """Deactivate a rule and re-run the classification."""
    entry, reclassified = await CatalogService(session).remove_directory_entry(
        entry_id, principal.id, request.client.host if request.client else None
    )
    return ReclassifyResponse(
        entry=DirectoryEntryResponse.model_validate(entry), calls_reclassified=reclassified
    )
