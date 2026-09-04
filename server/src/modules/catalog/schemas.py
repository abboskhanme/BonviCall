"""Reference-data wire schemas (SPEC §3.8, §4.7)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.core.enums import DirectoryRuleKind


class CreateDirectoryEntryRequest(BaseModel):
    """``POST /api/v1/line-directory`` — an admin extra for UC-25."""

    pattern: str = Field(
        min_length=2,
        max_length=32,
        description="Digits to match. UC-25's '*700' is the suffix rule '700'.",
    )
    kind: DirectoryRuleKind
    label: str | None = Field(default=None, max_length=64)


class DirectoryEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pattern: str
    kind: DirectoryRuleKind
    label: str | None
    is_active: bool
    created_at: datetime


class DirectoryEntryListResponse(BaseModel):
    items: list[DirectoryEntryResponse]
    total: int


class ReclassifyResponse(BaseModel):
    """A directory change is only half done until the calls agree with it."""

    entry: DirectoryEntryResponse
    calls_reclassified: int = Field(
        description="Calls whose call_type changed as a result of this edit."
    )
