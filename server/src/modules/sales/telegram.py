"""The digest transport seam. **Nothing here reaches the network.**

BonviZvonki's ``modules/sales/infrastructure/telegram.py`` posts straight to
the Telegram bot API over HTTP. It is careful about it — one function, one exit
point, so that a test only has to replace one thing and "a message must never
reach a real group by accident" is concentrated in one place. That care is the
part worth keeping; the HTTP call is not.

(The vendor's host name is deliberately not written anywhere in this module:
``test_nothing_in_this_module_can_reach_the_network`` reads the source, and a
mention in prose would be indistinguishable from a call.)

⚠️ THIS PRODUCT SENDS NOTHING TO ANYBODY. The digest is ported in full — the
figures, the evidence, the shortening ladder, the replay guard — and the only
implementation of the sender below WRITES A LOG LINE saying what it WOULD have
sent. It is the same shape ``core/push.py`` already uses for FCM, and the same
honesty: :class:`LoggingDigestSender` returns ``ok=False``, because a sender
that claimed a delivery it did not perform would put ``ok = true`` in
``sale_digests`` and the audit trail would be a lie.

Turning it on is not a line of code but a deliberate piece of work: an
implementation of :class:`DigestSender` that holds a bot token (in
``core/config.py`` beside the other credentials, NEVER in ``app_settings`` —
``settings:read`` is granted to every manager), registered through
:func:`set_sender` at wiring time. Until then
``sales.digest_enabled`` is seeded **false** as well, so the scheduled path
does not even assemble the text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.core.logging import get_logger

log = get_logger(__name__)

#: Telegram's per-message ceiling, in characters.
#
# A longer message is REFUSED with ``400 Bad Request: message is too long`` —
# it does not arrive truncated, it does not arrive at all. So the text is
# shortened while it is being assembled (``digest.py``); this is only where the
# limit is declared.
DIGEST_TEXT_LIMIT = 4096


@dataclass(slots=True)
class SendResult:
    """The outcome — a value, not an exception.

    For a scheduled job a transport failure is NOT a catastrophe: there will be
    another message tomorrow. So nothing is raised; the result is returned and
    the caller writes it to the log and to ``sale_digests``.
    """

    ok: bool
    error: str | None = None


@runtime_checkable
class DigestSender(Protocol):
    """One operation, because that is all the digest asks of a transport."""

    async def send(self, *, chat_id: str, text: str) -> SendResult:
        """Deliver one assembled message. ``ok`` is whether it was accepted."""
        ...


class LoggingDigestSender:
    """Reports what it WOULD have sent and returns ``ok=False``.

    The only implementation this product ships.

    It does not return ``True``: a sender that claimed delivery would write
    ``ok = true`` into ``sale_digests``, and that table exists to answer "did
    the message go out?" — an answer that is wrong is worse than no table.

    ⚠️ The TEXT IS NOT LOGGED, only its length and where it was addressed. The
    digest names customers and employees and quotes when each was last spoken
    to; that belongs on a screen behind a permission, not in a log file that
    gets shipped somewhere for debugging (N26's reasoning, applied to a body
    rather than to a token).
    """

    async def send(self, *, chat_id: str, text: str) -> SendResult:
        log.info(
            "sales_digest_not_sent",
            chat_id=chat_id,
            chars=len(text),
            reason="no_transport_configured",
        )
        return SendResult(ok=False, error="no_transport_configured")


_sender: DigestSender = LoggingDigestSender()


def get_sender() -> DigestSender:
    """The process-wide sender. Call it as ``telegram.get_sender()``.

    Imported as the MODULE and called through it, never bound by name: a name
    bound at import time cannot be redirected, and a test that cannot redirect
    it silently exercises the real one (``tests/test_layering.py`` legislates
    the same rule for the four ``core`` singletons).
    """
    return _sender


def set_sender(sender: DigestSender) -> None:
    """Swap the implementation. Nothing in this product calls it yet."""
    global _sender
    _sender = sender


__all__ = [
    "DIGEST_TEXT_LIMIT",
    "DigestSender",
    "LoggingDigestSender",
    "SendResult",
    "get_sender",
    "set_sender",
]
