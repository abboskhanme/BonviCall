"""Settings wire schemas (T58, SPEC §3.8, §3.11)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SettingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: Any
    value_type: str
    description_uz: str | None
    updated_by: uuid.UUID | None
    updated_at: datetime


class SettingListResponse(BaseModel):
    items: list[SettingResponse]
    total: int


class UpdateSettingRequest(BaseModel):
    """``PUT /api/v1/settings``.

    ``confirm`` exists for one case: lowering the retention period below
    ``retention.confirm_below_months`` destroys recordings that still exist.
    Without it the server changes nothing and returns 409 (SPEC §3.11).
    """

    key: str = Field(max_length=100)
    value: Any
    confirm: bool = Field(
        default=False,
        description="Required when the change would delete data that still exists.",
    )
