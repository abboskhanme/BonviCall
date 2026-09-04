"""Storage and data-usage reporting types (T56, T57; N14, N18)."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field


class StoragePointOut(BaseModel):
    """One day of the growth curve."""

    period_date: date
    audio_bytes_total: int
    audio_files: int
    bytes_added: int
    bytes_deleted: int


class StorageReportResponse(BaseModel):
    """N18: current usage, 30-day growth, and the projection it implies."""

    audio_bytes_total: int
    audio_files: int
    bytes_added_30d: int
    projected_bytes_12m: int = Field(
        description=(
            "Today's total plus a year at the last 30 days' rate. The provision "
            "is 250 GB, and this is what says whether that is enough."
        )
    )
    history: list[StoragePointOut]


class DataUsageRowOut(BaseModel):
    """One installation's traffic against the cap the employee pays for."""

    installation_id: uuid.UUID
    agent_name: str
    cellular_bytes_month: int
    wifi_bytes_month: int
    requests_month: int
    cap_bytes_month: int
    over_cap: bool = Field(
        description="Past N14's cap: the app stops uploading audio over cellular."
    )


class DataUsageResponse(BaseModel):
    items: list[DataUsageRowOut]
    total: int
    cap_bytes_month: int
