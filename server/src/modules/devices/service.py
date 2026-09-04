"""Handsets and their health (T36's read half, UC-17).

The list narrows by scope exactly as ``CallService.list`` does: a ``sales``
principal holding only ``devices:read:own`` gets their own phone and nothing
else. SPEC §5.2 gated the list on ``devices:read`` and the detail on
``devices:read | devices:read:own``, which left a salesperson with a page they
could open and no list that led to it — the project's own rule (scope is
narrowed by the query, not by the permission) resolves it.

``is_online`` is computed here rather than stored, from
``alerts.device_offline_minutes``: five missed two-minute heartbeats is OFFLINE
within ten minutes (UC-17).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.clock import TASHKENT
from src.core.deps import Principal
from src.core.enums import (
    AlertKind,
    AlertSeverity,
    CapabilityState,
    InstallationStatus,
)
from src.core.errors import NotFoundError
from src.core.logging import get_logger
from src.core.permissions import Perm
from src.modules.alerts.service import AlertService
from src.modules.devices.models import (
    CallLogDeltaModel,
    CapabilityStateModel,
    CapabilityTransitionModel,
    DeviceHealthModel,
    DeviceModel,
)
from src.modules.devices.rules import (
    CAPABILITY_ALERTS,
    WorkingCalendar,
    alert_for_transition,
    is_capturing,
    is_online,
    parse_hour,
    working_seconds_between,
)
from src.modules.devices.schemas import (
    DeviceCallLogDeltaIn,
    DeviceCapabilityIn,
    DeviceEventIn,
    DeviceHeartbeatIn,
)
from src.modules.installations.models import InstallationModel
from src.modules.settings.service import SettingsService

log = get_logger(__name__)

SETTING_OFFLINE_MINUTES = "alerts.device_offline_minutes"
SETTING_SILENCE_HOURS = "alerts.silence_hours"
SETTING_FLEET_SILENCE_HOURS = "alerts.fleet_silence_hours"
SETTING_WORK_START = "working_hours.start"
SETTING_WORK_END = "working_hours.end"
SETTING_WORKDAYS = "working_hours.workdays"
SETTING_HOLIDAYS = "working_hours.holidays"

#: Device event names SPEC §4.4 lists, mapped onto the alert they raise.
#: Exhaustive for the names we know; an unknown name still raises, at ``info``,
#: because a device reporting something we do not understand is itself news.
EVENT_ALERTS: dict[str, tuple[AlertKind, AlertSeverity]] = {
    "service_not_running": (AlertKind.SERVICE_NOT_RUNNING, AlertSeverity.WARNING),
    "capture_toggled_off": (AlertKind.CAPTURE_DISABLED, AlertSeverity.WARNING),
    "queue_full": (AlertKind.QUEUE_FULL, AlertSeverity.WARNING),
    "storage_low": (AlertKind.STORAGE_LOW, AlertSeverity.WARNING),
    "poisoned_record": (AlertKind.POISONED_RECORD, AlertSeverity.WARNING),
    "auth_expired": (AlertKind.AUTH_EXPIRED, AlertSeverity.WARNING),
    "recording_route_lost": (AlertKind.RECORDING_ROUTE_LOST, AlertSeverity.WARNING),
    "oem_recorder_missing": (AlertKind.RECORDING_ROUTE_LOST, AlertSeverity.WARNING),
    "attribution_discarded": (
        AlertKind.ATTRIBUTION_DISCARDED_SPIKE,
        AlertSeverity.WARNING,
    ),
}

#: Events that are facts, not problems. Recorded in the log, no alert.
QUIET_EVENTS = frozenset({"boot_completed", "app_updated", "revocation_completed"})


@dataclass(frozen=True)
class DeviceReport:
    """What a handset says about itself at enrolment (SPEC §4.2)."""

    manufacturer: str
    model: str
    android_release: str
    api_level: int
    build_fingerprint_hash: str
    marketing_name: str | None = None


class DeviceService:
    """Handset rows and device health. Owns its transaction where it writes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.alerts = AlertService(session)
        self.settings = SettingsService(session)

    async def upsert_from_report(self, report: DeviceReport) -> uuid.UUID:
        """One row per build fingerprint; a re-enrolled phone is the same row.

        Returns the id rather than the model: the caller is another module, and
        handing it an ORM entity would let it write to this module's table.
        """
        device = await self.session.scalar(
            select(DeviceModel).where(
                DeviceModel.build_fingerprint_hash == report.build_fingerprint_hash
            )
        )
        if device is None:
            device = DeviceModel(
                manufacturer=report.manufacturer,
                model=report.model,
                marketing_name=report.marketing_name,
                android_release=report.android_release,
                api_level=report.api_level,
                build_fingerprint_hash=report.build_fingerprint_hash,
            )
            self.session.add(device)
        else:
            device.last_seen_at = clock.now()
        await self.session.flush()
        return device.id

    async def describe(self, device_id: uuid.UUID | None) -> str | None:
        """``"Xiaomi Redmi Note 12"``, for a message a human reads."""
        if device_id is None:
            return None
        row = await self.session.get(DeviceModel, device_id)
        return f"{row.manufacturer} {row.model}" if row else None

    async def models_for_installations(self, installation_ids) -> dict:
        """``{installation_id: "Xiaomi Redmi Note 12"}`` in one query.

        ``calls`` has no foreign key into ``devices`` — it reaches them through
        ``installations`` — so it asks this module rather than joining across a
        boundary the keys do not describe (§2).
        """
        if not installation_ids:
            return {}
        rows = (
            await self.session.execute(
                select(
                    InstallationModel.id,
                    DeviceModel.manufacturer,
                    DeviceModel.model,
                )
                .join(DeviceModel, DeviceModel.id == InstallationModel.device_id)
                .where(InstallationModel.id.in_(set(installation_ids)))
            )
        ).all()
        return {row.id: f"{row.manufacturer} {row.model}" for row in rows}

    async def queue_snapshot(
        self, installation_id: uuid.UUID
    ) -> tuple[int | None, int | None]:
        """Records and bytes still queued at last contact (UC-08)."""
        health = await self.session.get(DeviceHealthModel, installation_id)
        if health is None:
            return None, None
        return health.queue_records, health.queue_bytes

    async def queue_is_empty(self, installation_id: uuid.UUID) -> bool:
        """Whether the phone has reported an empty queue (N34, SPEC §4.3).

        A device that has never reported is **not** empty: refusing an old
        client whose backlog we have not seen would be exactly the data loss
        the version gate exists to avoid.
        """
        records, byte_count = await self.queue_snapshot(installation_id)
        return records == 0 and byte_count == 0

    # --- Device ingest ----------------------------------------------------

    async def record_heartbeat(
        self, installation: InstallationModel, payload: DeviceHeartbeatIn
    ) -> tuple[DeviceHealthModel, int]:
        """Write the current state (T36). One row per installation, overwritten.

        Returns the row and the computed clock skew. Skew is **evidence**: it
        is shown on the device page and never used to rewrite a device
        timestamp, because a corrected timestamp would disagree with the
        handset's own call log (SPEC §3.12).
        """
        received_at = clock.now()
        transit_ms = (payload.device_rtt_ms or 0) // 2
        skew = int(
            (received_at.timestamp() * 1000 - payload.device_epoch_ms - transit_ms) / 1000
        )

        health = await self.session.get(DeviceHealthModel, installation.id)
        if health is None:
            health = DeviceHealthModel(installation_id=installation.id)
            self.session.add(health)

        was_offline = not is_online(
            health.last_heartbeat_at,
            received_at,
            await self.settings.get_int(SETTING_OFFLINE_MINUTES),
        )
        health.last_heartbeat_at = received_at
        health.clock_skew_sec = skew
        health.device_timezone = payload.device_timezone
        for field_name in (
            "app_version", "app_variant", "api_level", "battery_level",
            "battery_charging", "battery_optimisation_exempt", "power_save_mode",
            "free_storage_bytes", "queue_records", "queue_bytes", "queue_oldest_at",
            "parked_records", "network_type", "cellular_bytes_month",
            "service_running", "capture_enabled", "recording_route",
            "recording_route_ok", "ws_connected",
        ):
            value = getattr(payload, field_name)
            if value is not None:
                setattr(health, field_name, value)

        if was_offline:
            # It is back. Clear the alert rather than leaving an admin to tick
            # off a phone that fixed itself.
            await self.alerts.resolve(AlertKind.DEVICE_OFFLINE, installation.id)
        if payload.service_running is False:
            await self.alerts.raise_alert(
                kind=AlertKind.SERVICE_NOT_RUNNING,
                severity=AlertSeverity.WARNING,
                scope=installation.id,
                installation_id=installation.id,
                agent_id=installation.agent_id,
            )
        await self.session.flush()
        return health, skew

    async def ingest_heartbeat(self, installation, payload):
        """One heartbeat request, end to end: state, alerts, update block.

        The router calls this and nothing else — orchestration and the commit
        live here, so the handler stays a handler (§2). The circular import
        with ``installations`` is avoided by importing at call time: that
        module already imports this one for the queue snapshot.
        """
        from src.modules.installations.service import InstallationService

        _, skew = await self.record_heartbeat(installation, payload)
        update = await InstallationService(self.session).update_block(installation)
        await self.session.commit()
        return skew, update

    async def record_capabilities(
        self, installation: InstallationModel, reports: list[DeviceCapabilityIn]
    ) -> tuple[int, int]:
        """Upsert states, append transitions, raise alerts (T37, UC-06, UC-18).

        The alerts are raised **inside this request**, so UC-06's ten-minute
        bound is a device-reporting-interval question rather than a
        server-latency one. The only unbounded link in the chain is a device
        that is offline, which is itself an alert.
        """
        transitions = 0
        alerts = 0
        for report in reports:
            current = await self.session.scalar(
                select(CapabilityStateModel).where(
                    CapabilityStateModel.installation_id == installation.id,
                    CapabilityStateModel.capability == report.capability,
                )
            )
            previous: CapabilityState | None = current.state if current else None
            changed = previous != report.state

            if current is None:
                current = CapabilityStateModel(
                    installation_id=installation.id,
                    capability=report.capability,
                    state=report.state,
                    checked_at=report.checked_at,
                    changed_at=report.checked_at,
                    detail=report.detail,
                )
                self.session.add(current)
            else:
                current.state = report.state
                current.checked_at = report.checked_at
                current.detail = report.detail
                if changed:
                    current.changed_at = report.checked_at

            if not changed:
                continue

            transitions += 1
            self.session.add(
                CapabilityTransitionModel(
                    installation_id=installation.id,
                    capability=report.capability,
                    from_state=previous,
                    to_state=report.state,
                    at=report.checked_at,
                    source="device_report",
                    detail=report.detail,
                )
            )
            broken_kind = AlertKind(
                CAPABILITY_ALERTS.get(report.capability.value, "capture_disabled")
            )
            kind = alert_for_transition(report.capability.value, report.state.value)
            if kind is not None:
                await self.alerts.raise_alert(
                    kind=AlertKind(kind),
                    severity=AlertSeverity.WARNING,
                    scope=f"{installation.id}:{report.capability.value}",
                    installation_id=installation.id,
                    agent_id=installation.agent_id,
                    detail={
                        "capability": report.capability.value,
                        "from": previous.value if previous else None,
                        "to": report.state.value,
                    },
                )
                alerts += 1
            else:
                # Recovered. Resolve rather than raise a second alert: an agent
                # fixing a permission would otherwise generate the alert they
                # have just cleared.
                await self.alerts.resolve(
                    broken_kind, f"{installation.id}:{report.capability.value}"
                )
        await self.session.commit()
        return transitions, alerts

    async def record_call_log_delta(
        self, installation: InstallationModel, payload: DeviceCallLogDeltaIn
    ) -> CallLogDeltaModel:
        """The production rig (T40, §4.1 B).

        ``device_counted`` is monotonic within a day: a partial sweep reporting
        a lower number must not erase a full one, so a decrease is ignored and
        logged rather than written.
        """
        row = await self.session.scalar(
            select(CallLogDeltaModel).where(
                CallLogDeltaModel.installation_id == installation.id,
                CallLogDeltaModel.period_date == payload.period_date,
            )
        )
        if row is None:
            row = CallLogDeltaModel(
                installation_id=installation.id,
                number_id=installation.number_id,
                period_date=payload.period_date,
                device_counted=payload.device_counted,
                uploaded_count=payload.uploaded_count,
                subscription_unknown_count=payload.subscription_unknown_count,
            )
            self.session.add(row)
        else:
            if payload.device_counted < row.device_counted:
                log.info(
                    "call_log_delta_ignored_regression",
                    installation_id=str(installation.id),
                    stored=row.device_counted,
                    reported=payload.device_counted,
                )
            else:
                row.device_counted = payload.device_counted
            row.uploaded_count = max(row.uploaded_count, payload.uploaded_count)
            row.subscription_unknown_count = max(
                row.subscription_unknown_count, payload.subscription_unknown_count
            )
            row.last_reported_at = clock.now()
            if row.device_counted == row.uploaded_count:
                row.closed_at = clock.now()
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def record_events(
        self, installation: InstallationModel, events: list[DeviceEventIn]
    ) -> int:
        """Map device events onto alerts (SPEC §4.4).

        An unknown event name raises ``info`` rather than being dropped: a
        device telling us something we do not understand is itself news, and
        silence is the failure mode this whole subsystem exists to avoid.
        """
        raised = 0
        for event in events:
            if event.kind in QUIET_EVENTS:
                log.info(
                    "device_event", kind=event.kind, installation_id=str(installation.id)
                )
                continue
            kind, severity = EVENT_ALERTS.get(
                event.kind, (AlertKind.SERVICE_NOT_RUNNING, AlertSeverity.INFO)
            )
            await self.alerts.raise_alert(
                kind=kind,
                severity=severity,
                scope=f"{installation.id}:{event.kind}",
                installation_id=installation.id,
                agent_id=installation.agent_id,
                detail={
                    "event": event.kind,
                    **(
                        event.detail.model_dump(exclude_none=True, mode="json")
                        if event.detail
                        else {}
                    ),
                },
            )
            raised += 1
        await self.session.commit()
        return raised

    # --- Silence detection (T38, UC-27) -----------------------------------

    async def working_calendar(self) -> WorkingCalendar:
        """The business week, from the settings the migration seeded."""
        holidays = await self.settings.get_list(SETTING_HOLIDAYS)
        return WorkingCalendar(
            start_hour=parse_hour(await self.settings.get_str(SETTING_WORK_START)),
            end_hour=parse_hour(await self.settings.get_str(SETTING_WORK_END)),
            workdays=tuple(await self.settings.get_list(SETTING_WORKDAYS)),
            holidays=frozenset(date.fromisoformat(str(day)) for day in holidays),
        )

    async def detect_silence(self) -> list[uuid.UUID]:
        """Raise ``device_silent`` / ``fleet_silent`` (UC-27, T38).

        The comparison is in **working hours**, not wall-clock hours: a phone
        that stops reporting at 02:00 is asleep, and an alert for that is how
        alerts get muted. A device only counts as silent while at least one
        other device is reporting — otherwise the whole fleet is the story, and
        that is a separate, critical alert.
        """
        calendar = await self.working_calendar()
        silence_hours = await self.settings.get_int(SETTING_SILENCE_HOURS)
        fleet_hours = await self.settings.get_int(SETTING_FLEET_SILENCE_HOURS)
        moment = clock.now().astimezone(TASHKENT)

        rows = (
            await self.session.execute(
                select(DeviceHealthModel, InstallationModel)
                .join(
                    InstallationModel,
                    InstallationModel.id == DeviceHealthModel.installation_id,
                )
                .where(InstallationModel.status == InstallationStatus.ACTIVE)
            )
        ).all()
        if not rows:
            return []

        silent: list[tuple[uuid.UUID, uuid.UUID]] = []
        quiet_seconds: list[int] = []
        for health, installation in rows:
            last = health.last_call_at or health.last_heartbeat_at
            elapsed = (
                working_seconds_between(last.astimezone(TASHKENT), moment, calendar)
                if last is not None
                else silence_hours * 3600
            )
            quiet_seconds.append(elapsed)
            if elapsed >= silence_hours * 3600:
                silent.append((installation.id, installation.agent_id))

        fleet_is_silent = all(
            elapsed >= fleet_hours * 3600 for elapsed in quiet_seconds
        )
        if fleet_is_silent:
            # Every phone at once is not fifteen device problems; it is one
            # server, network or release problem, and it wakes somebody.
            await self.alerts.raise_alert(
                kind=AlertKind.FLEET_SILENT,
                severity=AlertSeverity.CRITICAL,
                scope="fleet",
                detail={"devices": len(quiet_seconds), "hours": fleet_hours},
            )
        else:
            await self.alerts.resolve(AlertKind.FLEET_SILENT, "fleet")
            for installation_id, agent_id in silent:
                await self.alerts.raise_alert(
                    kind=AlertKind.DEVICE_SILENT,
                    severity=AlertSeverity.WARNING,
                    scope=installation_id,
                    installation_id=installation_id,
                    agent_id=agent_id,
                    detail={"working_hours": silence_hours},
                )
        await self.session.commit()
        return [installation_id for installation_id, _ in silent]

    async def sweep_offline(self) -> list[uuid.UUID]:
        """Raise ``device_offline`` for phones past the heartbeat window (UC-17)."""
        minutes = await self.settings.get_int(SETTING_OFFLINE_MINUTES)
        moment = clock.now()
        rows = (
            await self.session.execute(
                select(DeviceHealthModel, InstallationModel)
                .join(
                    InstallationModel,
                    InstallationModel.id == DeviceHealthModel.installation_id,
                )
                .where(InstallationModel.status == InstallationStatus.ACTIVE)
            )
        ).all()
        offline: list[uuid.UUID] = []
        for health, installation in rows:
            if is_online(health.last_heartbeat_at, moment, minutes):
                continue
            offline.append(installation.id)
            await self.alerts.raise_alert(
                kind=AlertKind.DEVICE_OFFLINE,
                severity=AlertSeverity.WARNING,
                scope=installation.id,
                installation_id=installation.id,
                agent_id=installation.agent_id,
                detail={"offline_minutes": minutes},
            )
        await self.session.commit()
        return offline

    # --- Panel reads ------------------------------------------------------

    async def list(self, principal: Principal) -> list[dict]:
        """Device health for every installation the principal may see."""
        statement = self._scoped(
            select(DeviceHealthModel, InstallationModel, DeviceModel)
            .join(
                InstallationModel,
                InstallationModel.id == DeviceHealthModel.installation_id,
            )
            .join(DeviceModel, DeviceModel.id == InstallationModel.device_id),
            principal,
        ).order_by(DeviceHealthModel.last_heartbeat_at.desc().nullslast())
        rows = (await self.session.execute(statement)).all()
        cutoff = await self._offline_cutoff()
        return [
            self._row(health, installation, device, cutoff)
            for health, installation, device in rows
        ]

    async def capability_matrix(
        self, installation_id: uuid.UUID
    ) -> list[CapabilityStateModel]:
        """Current state of every reported capability, for the device page."""
        return list(
            (
                await self.session.scalars(
                    select(CapabilityStateModel)
                    .where(CapabilityStateModel.installation_id == installation_id)
                    .order_by(CapabilityStateModel.capability)
                )
            ).all()
        )

    async def get(self, principal: Principal, installation_id: uuid.UUID) -> dict:
        """One device. Wrong owner is 404, like every other scoped read."""
        statement = self._scoped(
            select(DeviceHealthModel, InstallationModel, DeviceModel)
            .join(
                InstallationModel,
                InstallationModel.id == DeviceHealthModel.installation_id,
            )
            .join(DeviceModel, DeviceModel.id == InstallationModel.device_id)
            .where(DeviceHealthModel.installation_id == installation_id),
            principal,
        )
        row = (await self.session.execute(statement)).first()
        if row is None:
            raise NotFoundError()
        cutoff = await self._offline_cutoff()
        health, installation, device = row
        detail = self._row(health, installation, device, cutoff)
        capabilities = await self.capability_matrix(installation_id)
        detail["capabilities"] = capabilities
        detail["capturing"] = is_capturing(
            {row.capability.value: row.state.value for row in capabilities},
            verified=installation.verified_at is not None,
            service_running=bool(health.service_running),
        )
        return detail

    def _scoped(self, statement: Select, principal: Principal) -> Select:
        if principal.has(Perm.DEVICES_READ):
            return statement
        return statement.where(InstallationModel.agent_id == principal.agent_id)

    async def _offline_cutoff(self):
        minutes = await SettingsService(self.session).get_int(SETTING_OFFLINE_MINUTES)
        return clock.now() - timedelta(minutes=minutes)

    @staticmethod
    def _row(health: DeviceHealthModel, installation: InstallationModel,
             device: DeviceModel, cutoff) -> dict:
        return {
            "installation_id": health.installation_id,
            "agent_id": installation.agent_id,
            "number_id": installation.number_id,
            "installation_status": installation.status,
            "manufacturer": device.manufacturer,
            "model": device.model,
            "android_release": device.android_release,
            "api_level": health.api_level or device.api_level,
            "app_version": health.app_version or installation.app_version,
            "app_variant": health.app_variant or installation.app_variant,
            "last_heartbeat_at": health.last_heartbeat_at,
            "last_call_at": health.last_call_at,
            "is_online": bool(
                health.last_heartbeat_at is not None and health.last_heartbeat_at > cutoff
            ),
            "ws_connected": health.ws_connected,
            "battery_level": health.battery_level,
            "battery_charging": health.battery_charging,
            "battery_optimisation_exempt": health.battery_optimisation_exempt,
            "power_save_mode": health.power_save_mode,
            "free_storage_bytes": health.free_storage_bytes,
            "queue_records": health.queue_records,
            "queue_bytes": health.queue_bytes,
            "queue_oldest_at": health.queue_oldest_at,
            "parked_records": health.parked_records,
            "clock_skew_sec": health.clock_skew_sec,
            "device_timezone": health.device_timezone,
            "network_type": health.network_type,
            "cellular_bytes_month": health.cellular_bytes_month,
            "service_running": health.service_running,
            "capture_enabled": health.capture_enabled,
            "recording_route": health.recording_route,
            "recording_route_ok": health.recording_route_ok,
            "updated_at": health.updated_at,
        }
