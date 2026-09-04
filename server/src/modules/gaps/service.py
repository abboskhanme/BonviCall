"""The gap report (T53, UC-23, N3, N4).

**The product's own smoke alarm.** A phone whose OEM battery manager killed the
capture service still uploads call metadata; what stops is the *audio*. This
report is where that becomes visible, and it is why it must stay fast enough
that nobody replaces it with a raw query later — hence the §2.1 exception, and
hence aggregates rather than loops.

Every query below is a projection or an aggregate. No ORM entity is loaded, so
nothing foreign can leak out of this module, and the report is a handful of
grouped counts rather than 500,000 objects.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.clock import TASHKENT
from src.core.enums import AudioMissingReason, CallDisposition
from src.modules.agents.models import AgentModel
from src.modules.calls.models import CallModel
from src.modules.catalog.models import SupportedModelModel
from src.modules.devices.models import CallLogDeltaModel, DeviceModel
from src.modules.gaps.schemas import (
    GapByAgentOut,
    GapByModelOut,
    GapByReasonOut,
    GapReportResponse,
    OpenDeltaOut,
)
from src.modules.installations.models import InstallationModel
from src.modules.settings.models import AppSettingModel

#: Reasons that are **not** capture failures (SPEC §3.9). ``pending_upload`` is
#: audio that has not arrived yet; ``not_expected`` is a call nobody answered.
#: Counting either against the capture rate makes the number meaningless.
EXCLUDED_REASONS = (
    AudioMissingReason.PENDING_UPLOAD,
    AudioMissingReason.NOT_EXPECTED,
)

SETTING_REGRESSION_PP = "alerts.capture_regression_pp"

#: N3: a delta still open after this long is a real gap, not a slow upload.
OPEN_DELTA_HOURS = 24


def _rate(with_audio: int, answered: int) -> Decimal | None:
    """Percent, to two places. NUMERIC and never float: this value is compared
    against a threshold on three platforms and float rounds differently on
    each (§10)."""
    if not answered:
        return None
    return (Decimal(with_audio) * 100 / Decimal(answered)).quantize(Decimal("0.01"))


class GapService:
    """Read-only aggregates across four modules' tables (§2.1)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _conditions(self, date_from: date | None, date_to: date | None) -> list:
        """Answered calls in the window — the denominator UC-23 names.

        A list of conditions rather than a bare ``select(<Model>)``: §2.1
        rule 3 forbids that here, because loading an ORM entity is
        what would let a foreign object escape this module. Every query below
        projects columns.
        """
        conditions = [CallModel.disposition == CallDisposition.ANSWERED]
        if date_from is not None:
            conditions.append(CallModel.started_at >= _tashkent_midnight(date_from))
        if date_to is not None:
            conditions.append(
                CallModel.started_at < _tashkent_midnight(date_to) + timedelta(days=1)
            )
        return conditions

    async def report(
        self, date_from: date | None = None, date_to: date | None = None
    ) -> GapReportResponse:
        where = and_(*self._conditions(date_from, date_to))
        answered_expr = func.count()
        with_audio_expr = func.count(case((CallModel.has_audio.is_(True), 1)))

        totals = (
            await self.session.execute(
                select(answered_expr, with_audio_expr).select_from(CallModel).where(where)
            )
        ).one()
        answered, with_audio = totals

        by_reason = [
            GapByReasonOut(
                reason=reason,
                calls=count,
                counts_against_capture_rate=reason not in EXCLUDED_REASONS,
            )
            for reason, count in (
                await self.session.execute(
                    select(CallModel.audio_missing_reason, func.count())
                    .where(where, CallModel.has_audio.is_(False))
                    .group_by(CallModel.audio_missing_reason)
                    .order_by(func.count().desc())
                )
            ).all()
            if reason is not None
        ]

        by_agent = [
            GapByAgentOut(
                agent_id=row.agent_id,
                agent_name=row.full_name,
                answered_calls=row.answered,
                calls_with_audio=row.with_audio,
                capture_rate=_rate(row.with_audio, row.answered),
            )
            for row in (
                await self.session.execute(
                    select(
                        CallModel.agent_id,
                        AgentModel.full_name,
                        answered_expr.label("answered"),
                        with_audio_expr.label("with_audio"),
                    )
                    .join(AgentModel, AgentModel.id == CallModel.agent_id)
                    .where(where)
                    .group_by(CallModel.agent_id, AgentModel.full_name)
                    .order_by(AgentModel.full_name)
                )
            ).all()
        ]

        by_model = await self._by_model(where)
        deltas = await self._open_deltas()

        return GapReportResponse(
            answered_calls=answered,
            calls_with_audio=with_audio,
            capture_rate=_rate(with_audio, answered),
            missing_total=answered - with_audio,
            by_reason=by_reason,
            by_agent=by_agent,
            by_model=by_model,
            open_deltas=deltas,
        )

    async def _by_model(self, where) -> list[GapByModelOut]:
        """Per handset model, against the M0 baseline (N4).

        "Capture is worse than it was" is an opinion without a stored baseline,
        which is why ``supported_models`` exists as data rather than prose.
        """
        threshold = await self.session.scalar(
            select(AppSettingModel.value).where(
                AppSettingModel.key == SETTING_REGRESSION_PP
            )
        )
        limit = Decimal(str(threshold if threshold is not None else 10))

        rows = (
            await self.session.execute(
                select(
                    DeviceModel.manufacturer,
                    DeviceModel.model,
                    func.count().label("answered"),
                    func.count(case((CallModel.has_audio.is_(True), 1))).label(
                        "with_audio"
                    ),
                )
                .join(
                    InstallationModel,
                    InstallationModel.id == CallModel.installation_id,
                )
                .join(DeviceModel, DeviceModel.id == InstallationModel.device_id)
                .where(where)
                .group_by(DeviceModel.manufacturer, DeviceModel.model)
                .order_by(DeviceModel.manufacturer, DeviceModel.model)
            )
        ).all()

        baselines = {
            (row.manufacturer, row.model): row.baseline_audio_capture_rate
            for row in (
                await self.session.execute(
                    select(
                        SupportedModelModel.manufacturer,
                        SupportedModelModel.model,
                        SupportedModelModel.baseline_audio_capture_rate,
                    )
                )
            ).all()
        }

        results: list[GapByModelOut] = []
        for row in rows:
            rate = _rate(row.with_audio, row.answered)
            baseline = baselines.get((row.manufacturer, row.model))
            delta = (
                (rate - baseline).quantize(Decimal("0.01"))
                if rate is not None and baseline is not None
                else None
            )
            results.append(
                GapByModelOut(
                    manufacturer=row.manufacturer,
                    model=row.model,
                    answered_calls=row.answered,
                    calls_with_audio=row.with_audio,
                    capture_rate=rate,
                    baseline_rate=baseline,
                    delta_pp=delta,
                    regression=delta is not None and delta < -limit,
                )
            )
        return results

    async def _open_deltas(self) -> list[OpenDeltaOut]:
        """Devices whose own call-log count never reconciled (N3)."""
        cutoff = clock.now() - timedelta(hours=OPEN_DELTA_HOURS)
        rows = (
            await self.session.execute(
                select(
                    CallLogDeltaModel.installation_id,
                    AgentModel.full_name,
                    CallLogDeltaModel.period_date,
                    CallLogDeltaModel.device_counted,
                    CallLogDeltaModel.uploaded_count,
                    CallLogDeltaModel.delta,
                    CallLogDeltaModel.subscription_unknown_count,
                )
                .join(
                    InstallationModel,
                    InstallationModel.id == CallLogDeltaModel.installation_id,
                )
                .join(AgentModel, AgentModel.id == InstallationModel.agent_id)
                .where(
                    CallLogDeltaModel.closed_at.is_(None),
                    CallLogDeltaModel.delta != 0,
                    CallLogDeltaModel.first_reported_at < cutoff,
                )
                .order_by(CallLogDeltaModel.period_date.desc())
            )
        ).all()
        return [
            OpenDeltaOut(
                installation_id=row.installation_id,
                agent_name=row.full_name,
                period_date=row.period_date,
                device_counted=row.device_counted,
                uploaded_count=row.uploaded_count,
                delta=row.delta,
                subscription_unknown_count=row.subscription_unknown_count,
            )
            for row in rows
        ]


def _tashkent_midnight(day: date):
    from datetime import datetime, time

    return datetime.combine(day, time.min, tzinfo=TASHKENT)
