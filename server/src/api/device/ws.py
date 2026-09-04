"""The device realtime socket (T55, SPEC §4.6, D-03).

``wss://<host>/api/device/v1/ws``, held open by the app's foreground service.
It exists for one number: UC-16 wants a dial ringing within five seconds, and a
phone that polls every two minutes cannot do that.

**Auth is on the handshake** — ``Authorization: Bearer <access_token>`` plus the
same ``X-Installation-Id`` / ``X-App-Version`` headers as every REST call, and
through the same dependency chain, so the socket cannot drift into being a
second, weaker way in. No token in the query string: query strings land in
access logs and N26 forbids that. A rejected handshake answers with the ordinary
error envelope and never opens a socket.

**The panel does not use this channel** (D-02). A browser cannot set handshake
headers, which is one more reason it polls instead.

What this file is *not*: it holds no business rule. Frames map to service calls,
and the command lifecycle is the same one an FCM-woken phone reaches over REST.
"""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from src.api.device.deps import WsInstallationDep
from src.core import clock, realtime
from src.core.deps import SessionDep
from src.core.errors import AppError
from src.core.logging import get_logger
from src.modules.commands.schemas import (
    DEVICE_FRAME_ADAPTER,
    AckFrameIn,
    DeviceAckIn,
    LogoutFrameOut,
    PingFrameOut,
    PongFrameIn,
    PresenceFrameIn,
)
from src.modules.commands.service import CommandService
from src.modules.devices.service import DeviceService
from src.modules.installations.models import InstallationModel

log = get_logger(__name__)

router = APIRouter(tags=["Device realtime"])

#: SPEC §4.6. The server pings; a socket with no answer is not a socket.
PING_INTERVAL_SECONDS = 30
PONG_TIMEOUT_SECONDS = 15

#: RFC 6455 close codes. 1003 is "I do not understand what you sent" — the
#: honest answer to a frame outside the allow-list, and one an app can act on.
CLOSE_UNSUPPORTED_DATA = 1003
CLOSE_GOING_AWAY = 1001


@router.websocket("/ws")
async def realtime_socket(
    websocket: WebSocket, installation: WsInstallationDep, session: SessionDep
) -> None:
    """One app, one socket, until one side stops answering."""
    await websocket.accept()
    hub = realtime.get_hub()
    devices = DeviceService(session)

    displaced = hub.register(installation.id, websocket)
    if displaced is not None:
        # The app reconnected before we noticed the old socket die. Not an
        # error, but the loser is told why rather than left wondering.
        await _farewell(displaced, "replaced")

    await devices.set_ws_connected(installation.id, True)
    log.info("ws_connected", installation_id=str(installation.id))
    try:
        await _pump(websocket, installation, session)
    except WebSocketDisconnect:
        pass
    finally:
        # Guarded inside the hub: if this socket was already displaced, the
        # replacement must survive our cleanup.
        if hub.unregister(installation.id, websocket):
            await devices.set_ws_connected(installation.id, False)
        log.info("ws_disconnected", installation_id=str(installation.id))


async def _pump(
    websocket: WebSocket, installation: InstallationModel, session: SessionDep
) -> None:
    """Read frames, and keep the connection honest with a ping clock.

    One task rather than a reader plus a pinger: the deadline is either "time to
    ping" or "the pong is late", never both, so a single timeout expresses it.
    Two tasks would need to agree about who closes the socket, and that
    agreement is where this kind of loop usually goes wrong.
    """
    awaiting_pong = False
    while True:
        timeout = PONG_TIMEOUT_SECONDS if awaiting_pong else PING_INTERVAL_SECONDS
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout)
        except TimeoutError:
            if awaiting_pong:
                # It stopped answering. Closing is what makes the hub's answer
                # to "is this phone reachable" true rather than hopeful, which
                # is what commands branch on.
                log.info("ws_pong_timeout", installation_id=str(installation.id))
                await websocket.close(CLOSE_GOING_AWAY)
                return
            await websocket.send_json(PingFrameOut(at=clock.now()).model_dump(mode="json"))
            awaiting_pong = True
            continue

        frame = _parse(raw, installation)
        if frame is None:
            await websocket.close(CLOSE_UNSUPPORTED_DATA)
            return
        # Any frame proves the socket is alive — the app answering a command is
        # as good as a pong, and better, because it took work.
        awaiting_pong = False
        await _handle(frame, installation, session)


def _parse(
    raw: str, installation: InstallationModel
) -> AckFrameIn | PresenceFrameIn | PongFrameIn | None:
    """An allowed frame, or ``None`` meaning "close this socket".

    The allow-list is the schema here exactly as it is on REST (§8 rule 5).
    Silently discarding frames we do not recognise would make an app on a
    different protocol version look like a phone that ignores its commands, and
    those need different fixes.
    """
    try:
        return DEVICE_FRAME_ADAPTER.validate_python(json.loads(raw))
    except (ValidationError, json.JSONDecodeError, TypeError):
        # The frame body is not logged: an ack carries no customer data but a
        # future frame might, and N26's rule is cheaper to keep than to restore.
        log.warning("ws_frame_rejected", installation_id=str(installation.id))
        return None


async def _handle(
    frame: AckFrameIn | PresenceFrameIn | PongFrameIn,
    installation: InstallationModel,
    session: SessionDep,
) -> None:
    """Route one frame. Nothing here decides anything — services do."""
    if isinstance(frame, PongFrameIn):
        return

    if isinstance(frame, PresenceFrameIn):
        await DeviceService(session).set_ws_connected(
            installation.id, True, queue_records=frame.queue_records
        )
        return

    if isinstance(frame, AckFrameIn):
        try:
            await CommandService(session).acknowledge(
                installation,
                frame.command_id,
                DeviceAckIn(
                    status=frame.status,
                    failure_reason=frame.failure_reason,
                    at=frame.at,
                    result_client_call_id=frame.result_client_call_id,
                ),
            )
        except AppError:
            # An ack for a command that is not this installation's is a confused
            # app, not a reason to drop a socket that is otherwise working — and
            # the next dial would then have to go the slow way round.
            log.warning(
                "ws_ack_rejected",
                installation_id=str(installation.id),
                command_id=str(frame.command_id),
            )


async def _farewell(
    sink: realtime.FrameSink, reason: Literal["revoked", "replaced", "version_unsupported"]
) -> None:
    """Tell a socket why it is being let go. Never raises — it may be dead."""
    try:
        await sink.send_json(LogoutFrameOut(reason=reason).model_dump(mode="json"))
    except Exception:  # noqa: BLE001 — a closed socket raises many types
        pass
