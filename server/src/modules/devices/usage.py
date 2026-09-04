"""Per-device data accounting (T56, N14, N15).

**Server-side counting is authoritative** (SPEC §3.7). The device reports its
own figure in the heartbeat and that is kept for comparison, but the cap is
enforced on this: the number that costs an employee money is not a number the
app gets to report.

**The honest approximation, stated rather than hidden.** What is counted here
is the *request* body, measured when the request arrives. Response bodies are
not, and for this product that is close to exact: N14's 1 GB monthly cellular
cap is essentially all audio upload, and an audio chunk is ~512 KB against a
~1 KB response. The error is on the order of a tenth of a percent, and it errs
by *under*-counting responses the employee did not pay much for. If that ever
stops being true — a large download to the phone, say — this is the place that
has to change, and the docstring is here so nobody has to work that out.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.clock import TASHKENT
from src.core.enums import NetworkType
from src.modules.devices.models import DataUsageDailyModel


class DataUsageService:
    """Accumulates per-installation, per-day byte counts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        installation_id: uuid.UUID,
        network_type: NetworkType | None,
        request_bytes: int,
        period: date | None = None,
    ) -> None:
        """Add one request's bytes to today's row.

        An ``INSERT … ON CONFLICT DO UPDATE``, so two concurrent uploads from
        one phone both count. A read-then-write would lose one of them, which
        is the same class of bug as a ``SELECT``-then-``INSERT`` idempotency
        check and is wrong for the same reason.

        A device that has not told us which network it is on is counted as
        cellular: the cap exists to protect the employee's bill, and guessing
        in their favour is the wrong direction to guess.
        """
        day = period or clock.now().astimezone(TASHKENT).date()
        cellular = request_bytes if network_type is not NetworkType.WIFI else 0
        wifi = request_bytes if network_type is NetworkType.WIFI else 0
        statement = (
            insert(DataUsageDailyModel.__table__)
            .values(
                id=uuid.uuid4(),
                installation_id=installation_id,
                period_date=day,
                cellular_bytes=cellular,
                wifi_bytes=wifi,
                requests=1,
            )
            .on_conflict_do_update(
                index_elements=["installation_id", "period_date"],
                set_={
                    "cellular_bytes": DataUsageDailyModel.cellular_bytes + cellular,
                    "wifi_bytes": DataUsageDailyModel.wifi_bytes + wifi,
                    "requests": DataUsageDailyModel.requests + 1,
                },
            )
        )
        await self.session.execute(statement)

    async def month_to_date(self) -> list[dict]:
        """Per-installation totals for the current Tashkent month (N14).

        A month, not a rolling window, because that is how the employee's own
        operator bills them and the cap has to mean the same thing to both.
        """
        today = clock.now().astimezone(TASHKENT).date()
        first = today.replace(day=1)
        rows = (
            await self.session.execute(
                select(
                    DataUsageDailyModel.installation_id,
                    func.coalesce(func.sum(DataUsageDailyModel.cellular_bytes), 0).label(
                        "cellular"
                    ),
                    func.coalesce(func.sum(DataUsageDailyModel.wifi_bytes), 0).label("wifi"),
                    func.coalesce(func.sum(DataUsageDailyModel.requests), 0).label(
                        "requests"
                    ),
                )
                .where(DataUsageDailyModel.period_date >= first)
                .group_by(DataUsageDailyModel.installation_id)
                .order_by(func.sum(DataUsageDailyModel.cellular_bytes).desc())
            )
        ).all()
        # The agent's name comes from the module that has the foreign key into
        # agents. Imported here rather than at module level because
        # ``installations`` imports this one for the queue snapshot (§2).
        from src.modules.installations.service import InstallationService

        names = await InstallationService(self.session).agent_names_for(
            [row.installation_id for row in rows]
        )
        return [
            {
                "installation_id": row.installation_id,
                "agent_name": names.get(row.installation_id, ""),
                "cellular_bytes_month": row.cellular,
                "wifi_bytes_month": row.wifi,
                "requests_month": row.requests,
            }
            for row in rows
        ]
