"""Auth wire schemas (SPEC §4.2, §4.7)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.core.enums import UserRole
from src.core.security import MIN_PASSWORD_LENGTH


class LoginRequest(BaseModel):
    """``POST /api/v1/auth/login`` — public, rate-limited."""

    email: EmailStr = Field(description="Case-insensitive; the column is CITEXT.")
    password: str = Field(min_length=1, description="Never logged, never echoed.")


class TokenResponse(BaseModel):
    """An access token and the refresh token that renews it."""

    access_token: str = Field(description="JWT bearer token.")
    refresh_token: str = Field(
        description="Opaque, rotated on every use; reuse revokes the whole chain."
    )
    token_type: str = Field(default="bearer", description="Always 'bearer'.")
    expires_in: int = Field(description="Access-token lifetime in seconds.")


class RefreshRequest(BaseModel):
    """``POST /api/v1/auth/refresh``."""

    refresh_token: str = Field(description="The token issued by the previous call.")


class ChangePasswordRequest(BaseModel):
    """``POST /api/v1/auth/password`` — the user's own password."""

    current_password: str = Field(min_length=1, description="Wrong value gives 401.")
    new_password: str = Field(
        min_length=MIN_PASSWORD_LENGTH,
        description=(
            "Minimum 10 characters and no other composition rule (SPEC §4.7): "
            "a rule people cannot follow is a rule they write on a sticky note."
        ),
    )


class CurrentUserResponse(BaseModel):
    """``GET /api/v1/auth/me`` — what the panel's ``can()`` reads.

    The permission list is resolved server-side and sent whole. The panel never
    holds a role-to-permission map: a second copy of the matrix is a second
    thing to forget to update.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    agent_id: uuid.UUID | None = Field(
        default=None, description="Set for a 'sales' account; what own-scope filters on."
    )
    must_change_password: bool = Field(
        description="The panel forces the change before anything else loads."
    )
    permissions: list[str] = Field(description="Resolved from the role, sorted.")
