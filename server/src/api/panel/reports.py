"""The gap report (T53, UC-23).

Totals reconcile exactly with ``/calls?has_audio=false`` because both count the
same rows; a report that disagrees with the list it links to is worse than no
report.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends

from src.core.deps import SessionDep
from src.core.permissions import Perm, require_permission
from src.core.settings_keys import SettingKey
from src.modules.audio.reports import (
    DataUsageResponse,
    DataUsageRowOut,
    StoragePointOut,
    StorageReportResponse,
)
from src.modules.audio.service import AudioService
from src.modules.devices.usage import DataUsageService
from src.modules.gaps.schemas import GapReportResponse
from src.modules.gaps.service import GapService
from src.modules.settings.service import SettingsService

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get(
    "/gap",
    response_model=GapReportResponse,
    dependencies=[Depends(require_permission(Perm.REPORTS_READ))],
)
async def gap_report(
    session: SessionDep, date_from: date | None = None, date_to: date | None = None
) -> GapReportResponse:
    """Calls without audio by reason, agent and handset model, plus the deltas.

    The denominator is **answered** calls: an unanswered call in it makes the
    percentage meaningless, which is why ``not_expected`` is a reason rather
    than a gap.
    """
    return await GapService(session).report(date_from=date_from, date_to=date_to)


@router.get(
    "/storage",
    response_model=StorageReportResponse,
    dependencies=[Depends(require_permission(Perm.REPORTS_READ))],
)
async def storage_report(session: SessionDep) -> StorageReportResponse:
    """Current GB and 30-day growth, without a ``du`` over 200 GB (N18)."""
    service = AudioService(session)
    history = await service.storage_history()
    # Today's figures come from the rows, not from the last snapshot: the job
    # runs nightly and the answer must be true on a server where it has not run
    # yet. The snapshots are the growth curve, which only they can give.
    total, files = await service.current_storage()
    added = sum(point.bytes_added for point in history)
    return StorageReportResponse(
        audio_bytes_total=total,
        audio_files=files,
        bytes_added_30d=added,
        # A year at the last 30 days' rate. Deliberately linear: a smarter
        # model would imply a confidence the data does not support. With no
        # history there is no rate, so the projection is today's total — an
        # honest "we cannot say yet" rather than a flat line drawn from one point.
        projected_bytes_12m=total + added * 12,
        history=[StoragePointOut.model_validate(point, from_attributes=True) for point in history],
    )


@router.get(
    "/data-usage",
    response_model=DataUsageResponse,
    dependencies=[Depends(require_permission(Perm.REPORTS_READ))],
)
async def data_usage_report(session: SessionDep) -> DataUsageResponse:
    """Per-device cellular traffic against the cap (N14, R14).

    The employee pays for this, so it is a first-class report rather than a
    debug counter — an unexplained data charge on a personal phone is exactly
    what gets an app uninstalled.
    """
    cap = await SettingsService(session).get_int(
        SettingKey.DATA_CELLULAR_CAP_BYTES_MONTH
    )
    rows = await DataUsageService(session).month_to_date()
    return DataUsageResponse(
        items=[
            DataUsageRowOut(
                **row, cap_bytes_month=cap, over_cap=row["cellular_bytes_month"] >= cap
            )
            for row in rows
        ],
        total=len(rows),
        cap_bytes_month=cap,
    )
