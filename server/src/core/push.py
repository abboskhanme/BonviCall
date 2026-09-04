"""The wake-up seam (SPEC §4.6 step 2, D-03).

When a phone's socket is down the server sends an FCM **high-priority data
message** so the app wakes and polls. That is the only thing FCM does here.

**There is deliberately no payload argument on this interface.** SPEC §4.6:
the message is ``{"cmd":"poll"}`` and *never* the command payload, because FCM
is a transport we do not control and the dial target is a customer's phone
number. A method that cannot be handed a payload cannot leak one — the same
reasoning as §8's privacy boundary, applied to a signature instead of a DTO.
If a future caller needs to say more to the phone, it opens a socket.

Release 1 ships :class:`LoggingPushSender`, which reports honestly that it
cannot wake anything, because two pieces are missing and neither is invented
here: an FCM project, and somewhere to keep the per-installation registration
token (``docs/PENDING_WIRING.md``). A phone with a dead socket is therefore
genuinely unreachable today, and the command lifecycle already has the right
word for that — ``failed`` / ``device_offline`` — so nothing pretends.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from src.core.logging import get_logger

log = get_logger(__name__)


@runtime_checkable
class PushSender(Protocol):
    """One operation, because that is all §4.6 asks of push."""

    async def wake(self, installation_id: uuid.UUID, push_token: str | None) -> bool:
        """Ask a phone to come and poll. ``True`` if a wake-up was dispatched.

        ``push_token`` is ``None`` when we hold no registration token for the
        installation, which is the normal case until the app sends one. That is
        a "no address for this phone" answer, not an error.
        """
        ...


class LoggingPushSender:
    """Records the intent and returns ``False``. The release-1 implementation.

    It does **not** return ``True``: a sender that claims delivery it did not
    perform would let a command sit in ``sent`` until the ack timeout and be
    reported as a phone that ignored us, when in fact nothing was ever sent.
    Those are different faults and the panel has to tell them apart.
    """

    async def wake(self, installation_id: uuid.UUID, push_token: str | None) -> bool:
        # N26: the registration token is a credential and is never logged, not
        # even truncated — only whether we had one.
        log.info(
            "push_wake_unavailable",
            installation_id=str(installation_id),
            has_token=push_token is not None,
            reason="no_fcm_project",
        )
        return False


_sender: PushSender = LoggingPushSender()


def get_sender() -> PushSender:
    """The process-wide sender. Call it as ``push.get_sender()`` (§ layering)."""
    return _sender


def set_sender(sender: PushSender) -> None:
    """Swap the implementation. ``main.py`` wires the real one when it exists."""
    global _sender
    _sender = sender
