"""User wire schemas (SPEC §4.7).

A password never appears in a response, in a log or in an audit ``detail`` —
there is no field here that could carry one out.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.core.enums import UserRole
from src.core.security import MIN_PASSWORD_LENGTH


class CreateUserRequest(BaseModel):
    """``POST /api/v1/users`` — creates a **login**, not a salesperson."""

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    role: UserRole
    agent_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Required when role='sales' — it is what own-scope narrowing "
            "filters on, and the database has a CHECK saying so."
        ),
    )
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class UpdateUserRequest(BaseModel):
    """``PATCH /api/v1/users/{id}``. Every field optional; absent means unchanged."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: UserRole | None = None
    agent_id: uuid.UUID | None = None
    is_active: bool | None = None


class SetPasswordRequest(BaseModel):
    """``POST /api/v1/users/{id}/password`` — an admin resetting somebody else's."""

    password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class UserResponse(BaseModel):
    """A panel account. Never carries the hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    agent_id: uuid.UUID | None
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime


class UserListResponse(BaseModel):
    """A page of accounts. Small table, so no cursor: the panel shows them all."""

    items: list[UserResponse]
    total: int
