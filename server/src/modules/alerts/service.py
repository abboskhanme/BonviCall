"""Raising alerts (T39, SPEC §3.8, §10.3).

Two properties the panel depends on, both enforced here rather than hoped for:

* **One open alert per cause.** A phone reporting a revoked permission every two
  minutes must not produce 720 rows a day, so a repeat bumps
  ``occurrence_count`` and ``last_seen_at`` on the open row. The uniqueness is a
  partial index, so two concurrent ingests cannot both insert.
* **Nothing in the device API can touch this table.** UC-06 and UC-18 are
  explicit that an agent cannot dismiss or suppress an alert about their own
  phone; there is no method here that acknowledges, and the one that does lives
  behind ``alerts:ack``, which only ``admin`` holds.

Email delivery (T39's other half) is not here yet — it belongs with the
scheduler (T150), and an alert that is visible in the panel is already the
durable half.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.enums import ActorType, AlertKind, AlertSeverity, AuditAction, InstallationStatus
from src.core.errors import NotFoundError
from src.core.logging import get_logger
from src.core.messages_uz import alert_text
from src.modules.alerts.models import AlertModel
from src.modules.alerts.schemas import AlertResponse
from src.modules.audit.service import AuditService
from src.modules.installations.models import InstallationModel

log = get_logger(__name__)


def dedupe_key(kind: AlertKind, scope: str | uuid.UUID | None) -> str:
    """``<kind>:<installation_id|agent_id|model|fleet>`` (SPEC §3.8)."""
    return f"{kind.value}:{scope or 'fleet'}"


class AlertService:
    """Raises and acknowledges alerts. Never commits — the caller owns that.

    Deliberate, as with the audit log: the alert and the thing that caused it
    must land in the same transaction, or the panel shows an alert about an
    event that was rolled back.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def _is_live(self, installation_id: uuid.UUID) -> bool:
        """Whether this installation is the one the agent is actually using."""
        status = await self.session.scalar(
            select(InstallationModel.status).where(
                InstallationModel.id == installation_id
            )
        )
        return status in (None, InstallationStatus.ACTIVE, InstallationStatus.PENDING)

    async def open_for(self, kind: AlertKind, installation_ids) -> set[uuid.UUID]:
        """Which of these installations currently have an open alert of ``kind``.

        Exists so another module can ask without holding an ``AlertModel``:
        what crosses a module boundary is a value, not an entity the other side
        could then write to (§2). ``installations`` needs this to know whether
        an agent is waiting for help.
        """
        wanted = {value for value in installation_ids if value is not None}
        if not wanted:
            return set()
        rows = await self.session.scalars(
            select(AlertModel.installation_id).where(
                AlertModel.kind == kind,
                AlertModel.installation_id.in_(wanted),
                AlertModel.resolved_at.is_(None),
            )
        )
        return set(rows.all())

    async def resolve_all_for(self, installation_id: uuid.UUID) -> int:
        """Close every open alert for an installation that has been superseded.

        Called when a phone is replaced or revoked. Without it the alerts
        raised while it *was* live stay open for ever — nobody will fix a
        handset the agent no longer holds, so nobody will acknowledge them, and
        they sit at the top of a page sorted worst-first.
        """
        rows = list(
            (
                await self.session.scalars(
                    select(AlertModel).where(
                        AlertModel.installation_id == installation_id,
                        AlertModel.resolved_at.is_(None),
                    )
                )
            ).all()
        )
        for alert in rows:
            alert.resolved_at = clock.now()
        await self.session.flush()
        return len(rows)

    async def raise_alert(
        self,
        kind: AlertKind,
        severity: AlertSeverity,
        scope: str | uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
        installation_id: uuid.UUID | None = None,
        number_id: uuid.UUID | None = None,
        device_model: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AlertModel | None:
        """Raise ``kind`` for ``scope``, or bump the open one if it exists.

        The Uzbek wording comes from ``core/messages_uz.py``: a caller names the
        cause, it never writes the sentence (§14).
        """
        if installation_id is not None and not await self._is_live(installation_id):
            # A superseded or revoked phone cannot be fixed: the agent is
            # holding a different handset. Alerts about it are work an admin
            # cannot do, and forty-seven of them buried the six that mattered.
            # The queue of a ``replaced`` installation is still accepted
            # (SPEC §9.3) — this suppresses the *alerting*, not the ingest.
            log.debug("alert_suppressed_for_superseded_installation", kind=kind.value)
            return None

        title_uz, body_uz = alert_text(
            kind.value, first_report=bool(detail and detail.get("first_report"))
        )
        key = dedupe_key(kind, scope)
        existing = await self.session.scalar(
            select(AlertModel).where(
                AlertModel.dedupe_key == key,
                AlertModel.acknowledged_at.is_(None),
                AlertModel.resolved_at.is_(None),
            )
        )
        if existing is not None:
            existing.last_seen_at = clock.now()
            existing.occurrence_count += 1
            if detail is not None:
                existing.detail = detail
            await self.session.flush()
            return existing

        alert = AlertModel(
            kind=kind,
            severity=severity,
            title_uz=title_uz,
            body_uz=body_uz,
            dedupe_key=key,
            agent_id=agent_id,
            installation_id=installation_id,
            number_id=number_id,
            device_model=device_model,
            detail=detail,
        )
        self.session.add(alert)
        await self.session.flush()
        log.info("alert_raised", alert_kind=kind.value, severity=severity.value, scope=str(scope))
        return alert

    async def list(
        self,
        severity: AlertSeverity | None = None,
        open_only: bool = True,
        limit: int = 200,
    ) -> tuple[list[AlertResponse], int, int]:
        """The inbox feed, newest activity first."""
        statement = select(AlertModel).order_by(AlertModel.last_seen_at.desc())
        if severity is not None:
            statement = statement.where(AlertModel.severity == severity)
        if open_only:
            statement = statement.where(
                AlertModel.acknowledged_at.is_(None), AlertModel.resolved_at.is_(None)
            )
        rows = list((await self.session.scalars(statement.limit(limit))).all())
        open_count = await self.session.scalar(
            select(func.count())
            .select_from(AlertModel)
            .where(
                AlertModel.acknowledged_at.is_(None), AlertModel.resolved_at.is_(None)
            )
        )
        # The installation's status, for the whole page in one query. Without
        # it a panel filtering out superseded phones needs a second request per
        # alert, which is why it was inferring instead.
        statuses = await self._statuses_for(
            [row.installation_id for row in rows if row.installation_id]
        )
        items = [
            AlertResponse.model_validate(row).model_copy(
                update={"installation_status": statuses.get(row.installation_id)}
            )
            for row in rows
        ]
        return items, len(items), open_count

    async def _statuses_for(self, installation_ids) -> dict:
        wanted = {value for value in installation_ids if value is not None}
        if not wanted:
            return {}
        rows = await self.session.execute(
            select(InstallationModel.id, InstallationModel.status).where(
                InstallationModel.id.in_(wanted)
            )
        )
        return dict(rows.all())

    async def acknowledge(self, alert_id: uuid.UUID, actor_id: uuid.UUID) -> AlertModel:
        """Mark it seen. Idempotent, and it never removes the row.

        The audit trail of who silenced what is the point: an alert that can be
        deleted is an alert that can be hidden.
        """
        alert = await self.session.get(AlertModel, alert_id)
        if alert is None:
            raise NotFoundError()
        if alert.acknowledged_at is None:
            alert.acknowledged_at = clock.now()
            alert.acknowledged_by = actor_id
            await self.audit.record(
                action=AuditAction.ALERT_ACKNOWLEDGED,
                object_type="alerts",
                object_id=alert.id,
                actor_type=ActorType.USER,
                actor_user_id=actor_id,
                detail={"kind": alert.kind.value},
            )
        await self.session.commit()
        return alert

    async def resolve(self, kind: AlertKind, scope: str | uuid.UUID | None) -> None:
        """Mark the open alert for this cause resolved, if there is one.

        Used when the condition goes away by itself — a phone that comes back
        online should not leave an alert an admin has to click.
        """
        alert = await self.session.scalar(
            select(AlertModel).where(
                AlertModel.dedupe_key == dedupe_key(kind, scope),
                AlertModel.acknowledged_at.is_(None),
                AlertModel.resolved_at.is_(None),
            )
        )
        if alert is not None:
            alert.resolved_at = clock.now()
            await self.session.flush()
