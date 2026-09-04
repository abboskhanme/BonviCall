"""The device realtime hub (SPEC §4.6, D-03).

Who is holding a socket right now, so a command can be pushed instead of
waited for. UC-16 wants a dial ringing within five seconds; a phone that polls
every 120 s cannot do that, and a phone holding an open socket can.

**Process-local, and that is a stated limit — not an oversight.** Release 1 is
one uvicorn process on one host (``STACK.md``), so a dict is the whole design.
Behind two workers a command would reach the phone only when it happened to be
handled by the worker holding that phone's socket, and the other worker would
report it undeliverable. When the server grows a second process this becomes a
Redis pub/sub fan-out and the call sites do not change — the same trade, stated
the same way, as ``core/ratelimit.py``.

**One socket per installation.** An installation is one app on one phone. A
second connection for the same installation is the app having reconnected
before the old socket's close was noticed, so the newcomer wins and the old one
is told ``logout: replaced``. Keeping both would mean a dial rings once and is
acknowledged twice.

``core`` owns this because it is a connection registry, not a business rule:
nothing here knows what a command is. It is the same shape as
``core/storage.py`` — an interface plus the one implementation release 1 needs.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol, runtime_checkable

from src.core.logging import get_logger

log = get_logger(__name__)


@runtime_checkable
class FrameSink(Protocol):
    """Anything that can be sent a JSON frame — in practice a ``WebSocket``.

    Narrow on purpose: the hub must be testable without a network, and a
    protocol this small makes a fake three lines long.
    """

    async def send_json(self, frame: dict[str, Any]) -> None: ...


class ConnectionHub:
    """Live device sockets, by installation.

    Not a singleton by construction — :func:`get_hub` provides the process-wide
    one, and a test builds its own rather than reaching into global state.
    """

    def __init__(self) -> None:
        self._sinks: dict[uuid.UUID, FrameSink] = {}

    def register(self, installation_id: uuid.UUID, sink: FrameSink) -> FrameSink | None:
        """Attach ``sink``. Returns the socket it displaced, if any.

        The caller is responsible for saying goodbye to the displaced socket —
        the hub does not send frames it was not asked to send, and the goodbye
        (``logout: replaced``) is a protocol decision, not a registry one.
        """
        previous = self._sinks.get(installation_id)
        self._sinks[installation_id] = sink
        return previous if previous is not sink else None

    def unregister(self, installation_id: uuid.UUID, sink: FrameSink) -> bool:
        """Detach ``sink``, and **only** if it is still the current one.

        The identity check is the whole point. When socket B displaces socket A,
        A's cleanup runs afterwards; an unguarded ``del`` there would evict B
        and leave a connected phone that the hub believes is offline — every
        command to it failing with ``device_offline`` while its socket is open.
        """
        if self._sinks.get(installation_id) is sink:
            del self._sinks[installation_id]
            return True
        return False

    def is_connected(self, installation_id: uuid.UUID) -> bool:
        return installation_id in self._sinks

    def connected(self) -> frozenset[uuid.UUID]:
        """Every installation with a live socket. Used by health and by tests."""
        return frozenset(self._sinks)

    async def send(self, installation_id: uuid.UUID, frame: dict[str, Any]) -> bool:
        """Push one frame. ``False`` means "no live socket", not "error".

        A phone whose socket died mid-send is offline, which is an ordinary
        state in this product and must not become a 500 on the panel request
        that issued the command. The exception is swallowed *and logged*, and
        the socket is dropped so the next attempt goes to FCM instead of
        writing into a closed transport forever.
        """
        sink = self._sinks.get(installation_id)
        if sink is None:
            return False
        try:
            await sink.send_json(frame)
        except Exception:  # noqa: BLE001 — a closed socket raises many types
            log.info("ws_send_failed", installation_id=str(installation_id))
            self.unregister(installation_id, sink)
            return False
        return True


_hub = ConnectionHub()


def get_hub() -> ConnectionHub:
    """The process-wide hub.

    Call it as ``realtime.get_hub()``; binding the name at import time makes it
    unpatchable, which ``tests/test_layering.py`` enforces for exactly the
    reason it already caught twice in this project.
    """
    return _hub
