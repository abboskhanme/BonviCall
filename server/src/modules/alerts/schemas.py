"""Alert wire schemas (SPEC §3.8, §4.7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.enums import AlertKind, AlertSeverity
from src.core.messages_uz import alert_text


class AlertResponse(BaseModel):
    """One open or acknowledged alert, as the inbox renders it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: AlertKind
    severity: AlertSeverity
    title_uz: str = Field(
        description="What happened, in Uzbek. Derived from `kind`, not stored."
    )
    body_uz: str | None = Field(
        description="What to do about it. Derived from `kind`, not stored."
    )
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

    @model_validator(mode="after")
    def _text_from_kind(self) -> AlertResponse:
        """Render the wording now, rather than serve the copy stored at raise.

        ``alerts.title_uz`` / ``body_uz`` are written when the alert is raised
        and are the record of what it said then. They are deliberately **not**
        what the API returns: an alert that has been open for a week would
        otherwise keep whatever wording shipped a week ago, so improving the
        text would reach only alerts raised after the deploy — which is how
        every stored row still said the English "Device offline" long after
        that was recognised as a bug.

        ``kind`` is a closed enum and part of the machine contract; the
        sentence is presentation, and presentation belongs to whatever is
        rendering it now. ``core/messages_uz.py`` is the one place it lives.
        """
        self.title_uz, self.body_uz = alert_text(self.kind.value)
        return self


class AlertListResponse(BaseModel):
    items: list[AlertResponse]
    total: int
    open_count: int = Field(description="Neither acknowledged nor resolved.")
