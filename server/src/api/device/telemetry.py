"""Device telemetry: heartbeat, capabilities, call-log delta, events (T36–T40).

**None of these routes may ever refuse on version** (N34, SPEC §4.3). They are
ingest, and refusing an old client here would lose the very data the version
gate exists to protect. The refusal lives on ``POST /auth/refresh`` and fires
only once the phone's queue is empty.

``replaced`` installations are accepted here too, for the same reason: a
superseded phone keeps draining (SPEC §9.3).
"""

from __future__ import annotations

from fastapi import APIRouter

from src.api.device.deps import ActiveInstallationDep
from src.core import clock
from src.core.deps import SessionDep
from src.modules.devices.schemas import (
    DeviceCallLogDeltaIn,
    DeviceCallLogDeltaOut,
    DeviceCapabilityBatchIn,
    DeviceCapabilityBatchOut,
    DeviceEventBatchIn,
    DeviceEventBatchOut,
    DeviceHeartbeatIn,
    DeviceHeartbeatOut,
)
from src.modules.devices.service import DeviceService

router = APIRouter(tags=["Device telemetry"])


@router.post("/heartbeat", response_model=DeviceHeartbeatOut)
async def heartbeat(
    payload: DeviceHeartbeatIn,
    installation: ActiveInstallationDep,
    session: SessionDep,
) -> DeviceHeartbeatOut:
    """Every 120 seconds while the foreground service is alive (UC-17).

    Five missed beats is OFFLINE within ten minutes. The 120-second timer is a
    coroutine inside the service, not a WorkManager job — WorkManager's floor
    is fifteen minutes, and that distinction is the difference between UC-17's
    detection window working and not.
    """
    skew, update = await DeviceService(session).ingest_heartbeat(installation, payload)
    return DeviceHeartbeatOut(
        server_time=clock.now(),
        clock_skew_sec=skew,
        pending_command_count=0,
        update=update,
    )


@router.post("/capabilities", response_model=DeviceCapabilityBatchOut)
async def report_capabilities(
    payload: DeviceCapabilityBatchIn,
    installation: ActiveInstallationDep,
    session: SessionDep,
) -> DeviceCapabilityBatchOut:
    """Capability drift (UC-06, UC-18, R3).

    The alert is raised inside this request, so the ten-minute bound is a
    reporting-interval question. An OEM battery manager killing the capture
    service is invisible unless the server notices the absence — this is where
    it notices.
    """
    transitions, alerts = await DeviceService(session).record_capabilities(
        installation, payload.capabilities
    )
    return DeviceCapabilityBatchOut(
        accepted=len(payload.capabilities),
        transitions=transitions,
        alerts_raised=alerts,
        server_time=clock.now(),
    )


@router.post("/call-log-delta", response_model=DeviceCallLogDeltaOut)
async def report_call_log_delta(
    payload: DeviceCallLogDeltaIn,
    installation: ActiveInstallationDep,
    session: SessionDep,
) -> DeviceCallLogDeltaOut:
    """The production measurement rig (N1, N3, §4.1 B).

    The device sweeps its own call log and reports what it counted next to what
    it uploaded. Without this, capture rate is unverifiable the day the
    acceptance window ends.
    """
    row = await DeviceService(session).record_call_log_delta(installation, payload)
    return DeviceCallLogDeltaOut(
        period_date=row.period_date,
        device_counted=row.device_counted,
        uploaded_count=row.uploaded_count,
        delta=row.delta,
        server_time=clock.now(),
    )


@router.post("/events", response_model=DeviceEventBatchOut)
async def report_events(
    payload: DeviceEventBatchIn,
    installation: ActiveInstallationDep,
    session: SessionDep,
) -> DeviceEventBatchOut:
    """Device events that are not calls (SPEC §4.4).

    An unknown event name still raises, at ``info``: a phone telling us
    something we do not understand is itself news, and dropping it is the
    silence this subsystem exists to prevent.
    """
    raised = await DeviceService(session).record_events(installation, payload.events)
    return DeviceEventBatchOut(
        accepted=len(payload.events), alerts_raised=raised, server_time=clock.now()
    )
