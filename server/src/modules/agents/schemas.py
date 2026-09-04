"""Agent wire schemas (SPEC §3.3, §4.7)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class CreateAgentRequest(BaseModel):
    """``POST /api/v1/agents``. Creating an agent never creates a login."""

    full_name: str = Field(min_length=1, max_length=255)
    employee_code: str | None = Field(
        default=None, max_length=32, description="The roster import key; unique where set."
    )
    hired_at: date | None = None
    color: str | None = Field(default=None, max_length=16)
    note: str | None = None


class UpdateAgentRequest(BaseModel):
    """``PATCH /api/v1/agents/{id}``. Absent fields are unchanged."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    employee_code: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None
    hired_at: date | None = None
    color: str | None = Field(default=None, max_length=16)
    note: str | None = None


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    employee_code: str | None
    is_active: bool
    archived_at: datetime | None
    hired_at: date | None
    color: str
    note: str | None
    created_at: datetime


class AgentListResponse(BaseModel):
    items: list[AgentResponse]
    total: int


class ImportRowResult(BaseModel):
    """What would happen, or did happen, to one roster line."""

    line: int
    full_name: str
    employee_code: str | None
    action: str = Field(description="create | update | skip | error")
    reason: str | None = Field(
        default=None, description="Why it was skipped or refused."
    )


class ImportAgentsRequest(BaseModel):
    """``POST /api/v1/agents/import`` — CSV text, not a file upload.

    A one-off for ~33 people (T59), not a live integration. Text rather than a
    multipart file because the realistic input is a paste out of a spreadsheet,
    and asking somebody to save a file first is a step that fails.
    """

    csv: str = Field(
        min_length=1,
        max_length=200_000,
        description="Header row plus data: full_name[,employee_code[,hired_at]].",
    )
    dry_run: bool = Field(
        default=True,
        description=(
            "Default true, deliberately: the diff is shown before anything is "
            "written, because a roster import that half-succeeded is worse "
            "than one that did not run."
        ),
    )


class ImportAgentsResponse(BaseModel):
    dry_run: bool
    created: int
    updated: int
    skipped: int
    errors: int
    rows: list[ImportRowResult]
