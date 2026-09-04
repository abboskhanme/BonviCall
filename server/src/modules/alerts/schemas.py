"""Alert wire schemas (SPEC §3.8, §4.7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.core.enums import AlertKind, AlertSeverity


class AlertResponse(BaseModel):
    """One open or acknowledged alert, as the inbox renders it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: AlertKind
    severity: AlertSeverity
    title_uz: str
    body_uz: str | None
    agent_id: uuid.UUID | None
    installation_id: uuid.UUID | None
    number_id: uuid.UUID | None
    device_model: str | None
    detail: dict[str, Any] | None
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_count: int = Field(
        description="Repeats bump this rather than inserting a row: a phone "
        "reporting every two minutes must not produce 720 rows a day."
    )
    acknowledged_at: datetime | None
    acknowledged_by: uuid.UUID | None
    resolved_at: datetime | None


class AlertListResponse(BaseModel):
    items: list[AlertResponse]
    total: int
    open_count: int = Field(description="Neither acknowledged nor resolved.")
