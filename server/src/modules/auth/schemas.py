"""Auth wire schemas (SPEC §4.2, §4.7)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from src.core.enums import UserRole
from src.core.security import MIN_PASSWORD_LENGTH


class LoginRequest(BaseModel):
    """``POST /api/v1/auth/login`` — public, rate-limited."""

    email: str = Field(
        min_length=1,
        max_length=255,
        description=(
            "The login identifier, matched verbatim against ``users.email``. "
            "Case-insensitive; the column is CITEXT."
        ),
    )
    password: str = Field(min_length=1, description="Never logged, never echoed.")

    # ⚠️ **Not ``EmailStr``, and that is deliberate.** This field identifies an
    # account; it does not deliver mail. Validating its format here refuses
    # ``admin`` before any lookup happens, which makes a short operator login
    # impossible — while adding nothing: an address that passes ``EmailStr``
    # and belongs to nobody fails at exactly the same place, with exactly the
    # same 401. ``UserCreateRequest`` still requires a real address, because a
    # panel account is invited by e-mail and one that cannot be written to is
    # an account nobody can recover.


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
