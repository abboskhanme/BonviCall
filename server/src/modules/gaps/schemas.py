"""The gap report's own types (UC-23, N3, N4).

Defined here, not imported from ``calls``: §2.1 rule 3 says what crosses back
out of a read-only module is that module's own schema, never a foreign entity.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from src.core.enums import AudioMissingReason


class GapByReasonOut(BaseModel):
    """Why audio is missing, and how often. The closed enum, never free text."""

    reason: AudioMissingReason
    calls: int
    counts_against_capture_rate: bool = Field(
        description=(
            "``pending_upload`` and ``not_expected`` are excluded from the "
            "denominator: an unanswered call in it makes '% of answered calls "
            "with audio' meaningless (SPEC §3.9)."
        )
    )


class GapByAgentOut(BaseModel):
    agent_id: uuid.UUID
    agent_name: str
    answered_calls: int
    calls_with_audio: int
    capture_rate: Decimal | None = Field(description="Percent. NUMERIC, never float.")


class GapByModelOut(BaseModel):
    manufacturer: str
    model: str
    answered_calls: int
    calls_with_audio: int
    capture_rate: Decimal | None
    baseline_rate: Decimal | None = Field(description="From the M0 baseline (T14).")
    delta_pp: Decimal | None = Field(description="Below the threshold raises N4's alert.")
    regression: bool


class OpenDeltaOut(BaseModel):
    """A device whose own call-log count never reconciled (N3, §4.1 B)."""

    installation_id: uuid.UUID
    agent_name: str
    period_date: date
    device_counted: int
    uploaded_count: int
    delta: int
    subscription_unknown_count: int = Field(
        description="Never folded into either side of the rate — the fail-closed "
        "rule made visible."
    )


class GapReportResponse(BaseModel):
    """UC-23. Totals reconcile exactly with ``/calls?has_audio=false``."""

    answered_calls: int
    calls_with_audio: int
    capture_rate: Decimal | None
    missing_total: int = Field(
        description="Matches the filtered call list, because the same rows are counted."
    )
    by_reason: list[GapByReasonOut]
    by_agent: list[GapByAgentOut]
    by_model: list[GapByModelOut]
    open_deltas: list[OpenDeltaOut]
