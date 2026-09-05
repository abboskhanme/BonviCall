"""The device realtime socket and the FCM seam (T55, SPEC §4.6).

Driven against the **registered** route through the ASGI interface directly,
rather than through ``TestClient.websocket_connect``. ``TestClient`` runs the app in its own thread
and event loop, and the ``db`` fixture is an asyncpg connection bound to *this*
loop inside an open savepoint — the two cannot see each other, and a test that
appears to pass across that boundary is testing a different database than the
one it set up. Sixty lines of harness is the cheaper half of that trade.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from fastapi import FastAPI

from src.api import DEVICE_API_PREFIX
from src.api.device import ws as ws_module
from src.core import realtime
from src.core.enums import CommandKind, CommandStatus
from src.core.push import LoggingPushSender
from src.modules.commands.schemas import CreateCommandRequest
from src.modules.commands.service import CommandService
from src.modules.devices.models import DeviceHealthModel

pytestmark = pytest.mark.asyncio


class Socket:
    """One client end of an ASGI WebSocket, driven from the test's own loop."""

    def __init__(self) -> None:
        self.to_server: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.from_server: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.closed: dict[str, Any] | None = None
        self.denied: int | None = None

    async def receive(self) -> dict[str, Any]:
        return await self.to_server.get()

    async def send(self, message: dict[str, Any]) -> None:
        if message["type"] == "websocket.close":
            self.closed = message
        if message["type"] == "websocket.http.response.start":
            self.denied = message["status"]
        await self.from_server.put(message)

    async def send_frame(self, frame: dict[str, Any]) -> None:
        await self.to_server.put({"type": "websocket.receive", "text": json.dumps(frame)})

    async def next_frame(self, timeout: float = 1.0) -> dict[str, Any]:
        """The next application frame, skipping the accept handshake.

        A timeout is reported as "no frame arrived" rather than left to surface
        as a ``CancelledError`` and then as the hub-leak fixture complaining
        about the socket this test never got to close. The first message a
        failing test prints should be the thing that actually went wrong.
        """
        while True:
            try:
                message = await asyncio.wait_for(self.from_server.get(), timeout)
            except TimeoutError:
                raise AssertionError(
                    f"no frame arrived within {timeout}s"
                ) from None
            if message["type"] == "websocket.send":
                return json.loads(message["text"])
            if message["type"] in ("websocket.close", "websocket.http.response.start"):
                raise AssertionError(f"socket ended: {message}")


async def _open(app: FastAPI, headers: dict[str, str], socket: Socket) -> asyncio.Task:
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "path": f"{DEVICE_API_PREFIX}/ws",
        "raw_path": f"{DEVICE_API_PREFIX}/ws".encode(),
        "query_string": b"",
        "root_path": "",
        "scheme": "ws",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("10.0.0.1", 51234),
        "server": ("testserver", 80),
        "subprotocols": [],
        "state": {},
    }
    task = asyncio.create_task(app(scope, socket.receive, socket.send))
    await socket.to_server.put({"type": "websocket.connect"})
    return task


async def _settle(predicate, timeout: float = 2.0) -> None:
    """Yield until ``predicate`` holds. A real condition, never a fixed sleep.

    The handshake, the hub registration and a database write all happen before
    the endpoint is ready; sleeping a guessed number of milliseconds for that is
    how a suite acquires tests that pass on a fast machine and fail in CI.

    The predicate must not touch the database. The endpoint under test shares
    this test's ``AsyncSession``, so polling a row from here would be two
    coroutines using one session — see :func:`_drain` for how a row is waited
    for instead.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(0.005)


async def _connected(
    db, installation_factory, device_client_factory
) -> tuple[Any, Socket, asyncio.Task, FastAPI]:
    """A verified installation with a live socket, ready to be talked to."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    app = client._transport.app  # noqa: SLF001 — the test's own app
    socket = Socket()
    task = await _open(app, dict(client.headers), socket)
    await _settle(lambda: realtime.get_hub().is_connected(installation.id))
    return installation, socket, task, app


async def _drain(socket: Socket, task: asyncio.Task) -> None:
    """Disconnect, and wait for the endpoint to finish.

    Also the way this file waits for a frame's *effects*. Frames are handled in
    order on one task, so when the task has ended every frame sent before the
    disconnect has been fully processed — and, more importantly, the endpoint
    has stopped using the session this test is about to read from. Sleeping a
    guessed interval instead would be racing the endpoint on one
    ``AsyncSession``, which is a hang rather than a flake.
    """
    await socket.to_server.put({"type": "websocket.disconnect", "code": 1000})
    await asyncio.wait_for(task, timeout=2)


# --- the hub itself --------------------------------------------------------


class Recorder:
    """A frame sink that keeps what it was sent."""

    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send_json(self, frame: dict) -> None:
        self.frames.append(frame)


class Broken:
    async def send_json(self, frame: dict) -> None:
        raise ConnectionResetError("socket went away")


async def test_hub_sends_to_the_registered_socket_and_nowhere_else() -> None:
    hub = realtime.ConnectionHub()
    one, two = uuid.uuid4(), uuid.uuid4()
    sink = Recorder()
    hub.register(one, sink)

    assert await hub.send(one, {"type": "ping"}) is True
    assert await hub.send(two, {"type": "ping"}) is False
    assert sink.frames == [{"type": "ping"}]


async def test_a_dead_socket_is_a_false_not_an_exception() -> None:
    """A phone that vanished mid-send must not 500 the panel request."""
    hub = realtime.ConnectionHub()
    installation_id = uuid.uuid4()
    hub.register(installation_id, Broken())

    assert await hub.send(installation_id, {"type": "ping"}) is False
    # And it is dropped, so the next command goes to FCM instead of writing
    # into a closed transport for ever.
    assert not hub.is_connected(installation_id)


async def test_a_displaced_socket_cannot_evict_its_replacement() -> None:
    """The bug this guard exists for: A reconnects as B, then A's cleanup runs.

    An unguarded ``del`` there leaves a phone whose socket is open but which the
    hub believes is offline — every command to it failing ``device_offline``.
    """
    hub = realtime.ConnectionHub()
    installation_id = uuid.uuid4()
    first, second = Recorder(), Recorder()

    hub.register(installation_id, first)
    displaced = hub.register(installation_id, second)
    assert displaced is first

    assert hub.unregister(installation_id, first) is False
    assert hub.is_connected(installation_id)
    assert await hub.send(installation_id, {"type": "ping"}) is True
    assert second.frames and not first.frames


# --- the handshake ---------------------------------------------------------


async def test_the_socket_refuses_an_unauthenticated_handshake(app) -> None:
    """No token, no socket — and the ordinary error envelope, not a bare close."""
    socket = Socket()
    task = await _open(app, {"x-app-version": "1.0.0"}, socket)
    await asyncio.wait_for(task, timeout=2)
    assert socket.denied == 401


async def test_the_socket_needs_the_same_headers_as_every_other_device_call(
    installation_factory, device_client_factory
) -> None:
    """A socket is not a second, weaker way in (SPEC §4.2)."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    headers = {
        key: value
        for key, value in client.headers.items()
        if key.lower() != "x-installation-id"
    }
    socket = Socket()
    task = await _open(client._transport.app, headers, socket)  # noqa: SLF001
    await asyncio.wait_for(task, timeout=2)
    assert socket.denied == 400


async def test_an_unverified_installation_gets_no_socket(
    installation_factory, device_client_factory
) -> None:
    """The privacy boundary starts before the socket opens (SPEC §4.2)."""
    from src.core.enums import InstallationStatus

    installation = await installation_factory()
    client = await device_client_factory(installation)
    installation.status = InstallationStatus.PENDING
    socket = Socket()
    task = await _open(client._transport.app, dict(client.headers), socket)  # noqa: SLF001
    await asyncio.wait_for(task, timeout=2)
    assert socket.denied == 403


# --- delivery --------------------------------------------------------------


async def test_a_dial_reaches_a_connected_phone_on_the_socket(
    db, installation_factory, device_client_factory, user_factory
) -> None:
    """UC-16's fast path, which is the only one with a chance at five seconds."""
    from src.core.enums import UserRole

    installation, socket, task, _ = await _connected(
        db, installation_factory, device_client_factory
    )
    user = await user_factory(UserRole.ADMIN)
    service = CommandService(db)
    command = await service.issue(
        installation.id,
        CreateCommandRequest(kind=CommandKind.DIAL, number="+998935554433"),
        user.id,
        ip=None,
    )

    assert await service.deliver(command) is True
    frame = await socket.next_frame()
    assert frame["type"] == "command"
    assert frame["command_id"] == str(command.id)
    assert frame["number"] == "+998935554433"
    # The dial target is a named field, not a payload map (§8 rule 5).
    assert "payload" not in frame
    await _drain(socket, task)


async def test_a_dial_to_a_phone_with_no_socket_is_not_reported_as_delivered(
    db, installation_factory, user_factory, monkeypatch
) -> None:
    """No socket means a wake-up and a wait, and ``deliver`` says so.

    The FCM sender honestly cannot wake anything yet, so this is also the test
    that the command does not sit in a state implying it was delivered.
    """
    from src.core.enums import UserRole

    installation = await installation_factory()
    user = await user_factory(UserRole.ADMIN)
    woken: list[uuid.UUID] = []

    class Recording(LoggingPushSender):
        async def wake(self, installation_id, push_token):
            woken.append(installation_id)
            return await super().wake(installation_id, push_token)

    # The sender behind ``push.get_sender()``, not the getter: swapping the
    # getter as well would leave two objects and hide which one was called.
    monkeypatch.setattr("src.core.push._sender", Recording())

    service = CommandService(db)
    command = await service.issue(
        installation.id,
        CreateCommandRequest(kind=CommandKind.DIAL, number="+998935554433"),
        user.id,
        ip=None,
    )
    assert await service.deliver(command) is False
    assert woken == [installation.id]
    assert command.status is CommandStatus.SENT
    assert command.sent_at is not None


# --- frames ----------------------------------------------------------------


async def test_an_ack_on_the_socket_completes_the_command(
    db, installation_factory, device_client_factory, user_factory
) -> None:
    """Same lifecycle as the REST ack — one command concept, two transports."""
    from src.core.enums import UserRole

    installation, socket, task, _ = await _connected(
        db, installation_factory, device_client_factory
    )
    user = await user_factory(UserRole.ADMIN)
    service = CommandService(db)
    command = await service.issue(
        installation.id,
        CreateCommandRequest(kind=CommandKind.DIAL, number="+998935554433"),
        user.id,
        ip=None,
    )
    await service.deliver(command)
    await socket.next_frame()

    await socket.send_frame(
        {"type": "ack", "command_id": str(command.id), "status": "acknowledged"}
    )
    await _drain(socket, task)

    await db.refresh(command)
    assert command.status is CommandStatus.ACKNOWLEDGED
    assert command.latency_ms is not None


async def test_an_ack_for_somebody_elses_command_does_not_drop_the_socket(
    db, installation_factory, device_client_factory, user_factory
) -> None:
    """A confused app is not a reason to make the next dial go the slow way."""
    from src.core.enums import UserRole

    other = await installation_factory()
    installation, socket, task, _ = await _connected(
        db, installation_factory, device_client_factory
    )
    user = await user_factory(UserRole.ADMIN)
    service = CommandService(db)
    theirs = await service.issue(
        other.id,
        CreateCommandRequest(kind=CommandKind.DIAL, number="+998935554433"),
        user.id,
        ip=None,
    )

    await socket.send_frame(
        {"type": "ack", "command_id": str(theirs.id), "status": "acknowledged"}
    )
    # Still connected *after* the frame was handled, which is the claim.
    await _settle(lambda: socket.to_server.empty())
    assert realtime.get_hub().is_connected(installation.id)
    await _drain(socket, task)

    await db.refresh(theirs)
    assert theirs.status is CommandStatus.PENDING


async def test_a_frame_outside_the_allow_list_closes_the_socket(
    db, installation_factory, device_client_factory
) -> None:
    """§8 rule 5 applies on this channel too: the schema is the allow-list."""
    _, socket, task, _ = await _connected(
        db, installation_factory, device_client_factory
    )
    await socket.send_frame({"type": "exfiltrate", "path": "/sdcard/Recordings"})
    await asyncio.wait_for(task, timeout=2)
    assert socket.closed is not None
    assert socket.closed["code"] == ws_module.CLOSE_UNSUPPORTED_DATA


async def test_presence_records_the_queue_without_claiming_health(
    db, installation_factory, device_client_factory
) -> None:
    """A socket says "reachable". ``last_heartbeat_at`` says "healthy"."""
    installation, socket, task, _ = await _connected(
        db, installation_factory, device_client_factory
    )
    db.add(DeviceHealthModel(installation_id=installation.id))
    await db.flush()

    await socket.send_frame({"type": "presence", "state": "online", "queue_records": 7})
    await _drain(socket, task)

    health = await db.get(DeviceHealthModel, installation.id)
    assert health.queue_records == 7
    # Presence never touches the heartbeat clock — that is the whole point of
    # keeping the two fields apart.
    assert health.last_heartbeat_at is None


async def test_the_device_page_learns_the_socket_is_up_and_then_down(
    db, installation_factory, device_client_factory, monkeypatch
) -> None:
    """``ws_connected`` is the panel's copy of the hub, and both edges matter.

    A phone stuck showing "connected" after its socket died is worse than one
    showing nothing: it is the field an admin uses to decide the handset is fine.
    """
    monkeypatch.setattr(ws_module, "PING_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(ws_module, "PONG_TIMEOUT_SECONDS", 5)

    installation = await installation_factory()
    db.add(DeviceHealthModel(installation_id=installation.id))
    await db.flush()
    client = await device_client_factory(installation)
    socket = Socket()
    task = await _open(
        client._transport.app,  # noqa: SLF001
        dict(client.headers),
        socket,
    )

    # The first ping proves the endpoint finished connecting and is now idle in
    # receive — which is also the moment the shared session is free to read.
    assert (await socket.next_frame(timeout=2))["type"] == "ping"
    health = await db.get(DeviceHealthModel, installation.id)
    await db.refresh(health)
    assert health.ws_connected is True

    await _drain(socket, task)
    await db.refresh(health)
    assert health.ws_connected is False


async def test_the_hub_forgets_a_socket_that_disconnects(
    db, installation_factory, device_client_factory
) -> None:
    """Otherwise every later command would be pushed into a closed transport."""
    installation, socket, task, _ = await _connected(
        db, installation_factory, device_client_factory
    )
    assert realtime.get_hub().is_connected(installation.id)
    await _drain(socket, task)
    assert not realtime.get_hub().is_connected(installation.id)


async def test_a_silent_socket_is_pinged_and_then_closed(
    db, installation_factory, device_client_factory, monkeypatch
) -> None:
    """SPEC §4.6: ping every 30 s, no pong within 15 s and the socket goes.

    The intervals are shortened rather than the clock frozen: this loop waits on
    ``asyncio``, not on ``clock.now()``, so a frozen clock would prove nothing.
    """
    monkeypatch.setattr(ws_module, "PING_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(ws_module, "PONG_TIMEOUT_SECONDS", 0.05)
    _, socket, task, _ = await _connected(
        db, installation_factory, device_client_factory
    )

    ping = await socket.next_frame(timeout=2)
    assert ping["type"] == "ping"
    await asyncio.wait_for(task, timeout=2)
    assert socket.closed["code"] == ws_module.CLOSE_GOING_AWAY


async def test_a_pong_keeps_the_socket_open(
    db, installation_factory, device_client_factory, monkeypatch
) -> None:
    """The other half — a ping test that never passes is worth nothing."""
    monkeypatch.setattr(ws_module, "PING_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(ws_module, "PONG_TIMEOUT_SECONDS", 0.5)
    installation, socket, task, _ = await _connected(
        db, installation_factory, device_client_factory
    )

    assert (await socket.next_frame(timeout=2))["type"] == "ping"
    await socket.send_frame({"type": "pong"})
    assert (await socket.next_frame(timeout=2))["type"] == "ping"
    assert realtime.get_hub().is_connected(installation.id)
    await _drain(socket, task)


async def test_a_second_socket_replaces_the_first_and_says_why(
    db, installation_factory, device_client_factory
) -> None:
    """One installation is one phone. Two live sockets would ack a dial twice."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    app = client._transport.app  # noqa: SLF001
    headers = dict(client.headers)

    first, second = Socket(), Socket()
    first_task = await _open(app, headers, first)
    await _settle(lambda: realtime.get_hub().is_connected(installation.id))
    second_task = await _open(app, headers, second)

    goodbye = await first.next_frame()
    assert goodbye == {"type": "logout", "reason": "replaced"}
    assert realtime.get_hub().is_connected(installation.id)

    await _drain(first, first_task)
    # The loser's cleanup must not have evicted the winner.
    assert realtime.get_hub().is_connected(installation.id)
    await _drain(second, second_task)
    assert not realtime.get_hub().is_connected(installation.id)


async def test_a_command_never_travels_through_the_push_transport() -> None:
    """SPEC §4.6: FCM carries ``{"cmd":"poll"}`` and never the dial target.

    Enforced by the signature — the seam has no payload argument — so this
    guards the interface rather than an implementation, and a future
    ``FcmPushSender`` cannot quietly grow one.
    """
    import inspect

    from src.core.push import PushSender

    signature = inspect.signature(PushSender.wake)
    assert list(signature.parameters) == ["self", "installation_id", "push_token"]


async def test_click_to_call_from_the_panel_reaches_a_connected_phone(
    db, admin, installation_factory, device_client_factory
) -> None:
    """The whole of UC-16's fast path, through the real endpoints.

    Everything above tests a piece. This is the one that would have caught the
    panel issuing commands and never delivering them, which is exactly what it
    did until the socket existed: ``issue`` was called, ``deliver`` was not, and
    every dial waited for the phone to poll.
    """
    installation, socket, task, _ = await _connected(
        db, installation_factory, device_client_factory
    )

    response = await admin.post(
        f"/api/v1/devices/{installation.id}/commands",
        json={"kind": "dial", "number": "+998935554433", "reason": "callback"},
    )
    assert response.status_code == 202

    frame = await socket.next_frame()
    assert frame["type"] == "command"
    assert frame["kind"] == "dial"
    assert frame["number"] == "+998935554433"
    assert frame["command_id"] == response.json()["id"]

    # And the phone answers on the same socket, closing the loop the panel
    # renders: sent → acknowledged, with the latency UC-16 is measured on.
    await socket.send_frame(
        {"type": "ack", "command_id": frame["command_id"], "status": "acknowledged"}
    )
    await _drain(socket, task)

    detail = await admin.get(f"/api/v1/commands/{frame['command_id']}")
    assert detail.json()["status"] == "acknowledged"
    assert detail.json()["latency_ms"] is not None


async def test_a_push_outage_does_not_break_click_to_call(
    db, admin, installation_factory, monkeypatch
) -> None:
    """FCM is somebody else's service, and it will be down one day.

    The command is already recorded by then, and a phone we failed to wake is a
    phone that does not answer — which ``expire_stale`` already calls
    ``device_offline``. An outage at Google must not turn a panel click into a
    500 that tells an admin nothing.
    """

    class Exploding(LoggingPushSender):
        async def wake(self, installation_id, push_token):
            raise RuntimeError("fcm is unreachable")

    monkeypatch.setattr("src.core.push._sender", Exploding())

    installation = await installation_factory()
    response = await admin.post(
        f"/api/v1/devices/{installation.id}/commands",
        json={"kind": "dial", "number": "+998935554433"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "sent"
