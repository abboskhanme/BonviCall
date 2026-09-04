"""The settings screen (T58, SPEC §3.8, §3.11).

Reading is ``settings:read`` (admin and manager); writing is
``settings:write`` (admin). Every threshold in the product is here, so nothing
is out of reach without a deploy.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from src.core.deps import PrincipalDep, SessionDep
from src.core.permissions import Perm, require_permission
from src.modules.settings.schemas import (
    SettingListResponse,
    SettingResponse,
    UpdateSettingRequest,
)
from src.modules.settings.service import SettingsService

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get(
    "",
    response_model=SettingListResponse,
    dependencies=[Depends(require_permission(Perm.SETTINGS_READ))],
)
async def list_settings(session: SessionDep) -> SettingListResponse:
    items, total = await SettingsService(session).list()
    return SettingListResponse(
        items=[SettingResponse.model_validate(row) for row in items], total=total
    )


@router.put(
    "",
    response_model=SettingResponse,
    dependencies=[Depends(require_permission(Perm.SETTINGS_WRITE))],
)
async def update_setting(
    payload: UpdateSettingRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> SettingResponse:
    """409 ``retention_confirmation_required`` when the change deletes data.

    Shortening retention removes recordings that still exist. Refusing without
    an explicit confirmation is the difference between a policy change and an
    accident nobody can undo.
    """
    row = await SettingsService(session).update(
        payload.key,
        payload.value,
        payload.confirm,
        principal.id,
        request.client.host if request.client else None,
    )
    return SettingResponse.model_validate(row)
