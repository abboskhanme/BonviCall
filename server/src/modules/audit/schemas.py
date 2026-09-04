"""Audit log wire schemas (UC-24)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.enums import ActorType, AuditAction


class AuditResponse(BaseModel):
    """One thing that happened. Immutable, by database trigger."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    at: datetime
    actor_type: ActorType
    actor_user_id: uuid.UUID | None
    actor_service_token_id: uuid.UUID | None
    action: AuditAction
    object_type: str
    object_id: uuid.UUID | None
    ip: str | None
    user_agent: str | None

    @field_validator("ip", mode="before")
    @classmethod
    def _stringify_inet(cls, value: object) -> str | None:
        """asyncpg returns INET as an ``ipaddress`` object, not a string.

        The wire carries a string, so it is coerced here rather than in every
        caller — and it is a validator rather than a type change because the
        column really is an address and comparing it as one is useful in SQL.
        """
        return None if value is None else str(value)
    detail: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Before/after values and counts. Never a password, a token or an "
            "enrolment code (N26). Open by nature — this is a server-side "
            "record, not a device payload, so §8's allow-list does not apply."
        ),
    )


class AuditListResponse(BaseModel):
    items: list[AuditResponse]
    total: int
