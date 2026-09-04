"""The nightly capture-rate window (T151, N4).

``gaps`` computes the aggregate — it holds the §2.1 read exception and never
writes — and this module persists it, because it owns ``model_capture_stats``
and ``supported_models``.

**Materialised on purpose.** Recomputing the window per request would be cheap
at this volume; it is written down anyway so that "what did the system see on
the day it alerted" is still answerable six months later. An alert whose
evidence has been recomputed away cannot be argued with in either direction.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.clock import TASHKENT
from src.core.enums import AlertKind, AlertSeverity
from src.core.logging import get_logger
from src.core.settings_keys import SettingKey
from src.modules.alerts.service import AlertService
from src.modules.catalog.models import ModelCaptureStatModel
from src.modules.gaps.service import GapService
from src.modules.settings.service import SettingsService

log = get_logger(__name__)

#: N4's window. Seven days, so one bad afternoon does not raise an alert and a
#: model that has genuinely stopped recording cannot hide for a week either.
WINDOW_DAYS = 7

#: Below this many answered calls a rate is noise. A model with four calls at
#: 50 % has told us nothing, and alerting on it trains people to ignore the
#: alert that matters.
MIN_SAMPLE_CALLS = 10


async def model_capture_stats(session: AsyncSession) -> int:
    """Write the 7-day window per model and raise N4's regression alert.

    Idempotent twice over: the row is unique on
    ``(manufacturer, model, api_level, app_variant, window_end)`` and upserted,
    and the alert dedupes on its own key. Running it twice on the same night
    recomputes the same numbers and raises nothing new.
    """
    today = clock.now().astimezone(TASHKENT).date()
    window_start = today - timedelta(days=WINDOW_DAYS)
    limit = Decimal(
        str(await SettingsService(session).get_int(SettingKey.ALERTS_CAPTURE_REGRESSION_PP))
    )

    rows = await GapService(session).capture_rates_by_model(window_start, today)
    alerts = AlertService(session)
    written = 0

    for row in rows:
        regressed = (
            row.delta_pp is not None
            and row.delta_pp < -limit
            and row.answered_calls >= MIN_SAMPLE_CALLS
        )
        await session.execute(
            insert(ModelCaptureStatModel.__table__)
            .values(
                id=uuid.uuid4(),
                manufacturer=row.manufacturer,
                model=row.model,
                api_level=row.api_level,
                app_variant=row.app_variant,
                window_start=window_start,
                window_end=today,
                answered_calls=row.answered_calls,
                calls_with_audio=row.calls_with_audio,
                rate=row.capture_rate,
                baseline_rate=row.baseline_rate,
                delta_pp=row.delta_pp,
                alert_raised=regressed,
            )
            .on_conflict_do_update(
                index_elements=[
                    "manufacturer",
                    "model",
                    "api_level",
                    "app_variant",
                    "window_end",
                ],
                set_={
                    "answered_calls": row.answered_calls,
                    "calls_with_audio": row.calls_with_audio,
                    "rate": row.capture_rate,
                    "baseline_rate": row.baseline_rate,
                    "delta_pp": row.delta_pp,
                    "alert_raised": regressed,
                },
            )
        )
        written += 1

        if regressed:
            await alerts.raise_alert(
                kind=AlertKind.CAPTURE_RATE_REGRESSION,
                severity=AlertSeverity.CRITICAL,
                scope=f"{row.manufacturer} {row.model}",
                device_model=f"{row.manufacturer} {row.model}",
                detail={
                    "rate": str(row.capture_rate),
                    "baseline_rate": str(row.baseline_rate),
                    "delta_pp": str(row.delta_pp),
                    "answered_calls": row.answered_calls,
                },
            )
            log.warning(
                "capture_rate_regression",
                model=f"{row.manufacturer} {row.model}",
                delta_pp=str(row.delta_pp),
            )

    await session.commit()
    return written
