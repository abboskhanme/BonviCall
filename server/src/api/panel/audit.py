"""The audit log viewer (T54, UC-24, N27).

**Read-only, and admin-only.** There is no route that updates or deletes an
audit row, and the table carries a trigger that raises if anything tries — so
append-only is a property of the database, not of this file.

``audit:read`` is granted to ``admin`` alone. A manager is one of the people
this log records, which is the reason.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from src.core.deps import SessionDep
from src.core.enums import AuditAction
from src.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, clamp_limit
from src.core.permissions import Perm, require_permission
from src.modules.audit.schemas import AuditListResponse, AuditResponse
from src.modules.audit.service import AuditService

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get(
    "",
    response_model=AuditListResponse,
    dependencies=[Depends(require_permission(Perm.AUDIT_READ))],
)
async def list_audit(
    session: SessionDep,
    action: AuditAction | None = None,
    object_type: str | None = None,
    object_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    limit: int = DEFAULT_LIMIT,
) -> AuditListResponse:
    """Who, what, which object, when, from which IP."""
    items, total = await AuditService(session).list(
        action=action,
        object_type=object_type,
        object_id=object_id,
        actor_user_id=actor_user_id,
        limit=clamp_limit(limit, MAX_LIMIT),
    )
    return AuditListResponse(
        items=[AuditResponse.model_validate(row) for row in items], total=total
    )
