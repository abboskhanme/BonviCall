"""The survey transport seam — modelled on ``core/push.py::PushSender``.

═══ NOTHING HERE SENDS A MESSAGE ═══════════════════════════════════════════
Release 1 ships :class:`LoggingSurveyTransport`, which records what it *would*
have posted and reports that it delivered nothing. There is no Telegram bot
token in this deployment, none is being asked for, and **no code in this module
opens a network connection** — to Telegram or to anywhere else.

That is not a stub standing in for a missing piece; it is the honest answer for
a server that has no bot. A transport that returned "delivered" would leave
survey rows sitting at ``sent`` while nothing had been posted, and the panel
would then report a customer group as surveyed when it had not been. Those are
different faults and an admin has to be able to tell them apart — the same
reasoning ``core/push.py`` states for returning ``False`` rather than ``True``.

═══ Why an interface at all ════════════════════════════════════════════════
BonviZvonki's backend already never calls Telegram: the bot polls three
worklists and reports back, and that boundary is stated in its own source
("the Telegram-handling logic stays in the bot — the backend does not call the
Telegram API"). The interface below is that boundary given a name, so that
whoever wires a bot later has exactly one place to implement and exactly one
place a reviewer has to read to see what leaves this process.

The three operations are the three worklists, and nothing more:

* :meth:`SurveyTransport.post` — put a survey into a chat.
* :meth:`SurveyTransport.refresh` — update the "N people answered" counter on
  a message already posted.
* :meth:`SurveyTransport.remove` — delete a message this product posted.

**There is deliberately no free-form message argument.** Like ``PushSender``,
the signature carries identifiers and a token and nothing else: a method that
cannot be handed arbitrary text cannot leak any, and the wording a customer
reads is the bot's own. ``remove`` takes a ``chat_message_id`` this product
recorded when it posted — it can therefore only ever delete a message it sent
itself, which is what stops a bot shared between two applications from being
told to delete the other application's messages.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.core.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Dispatch:
    """One survey waiting to be posted into a chat."""

    survey_id: uuid.UUID
    token: str
    chat_id: int
    agent_name: str


@dataclass(frozen=True)
class CounterUpdate:
    """A posted message whose answer count has moved on."""

    survey_id: uuid.UUID
    chat_id: int
    chat_message_id: int
    response_count: int


@dataclass(frozen=True)
class MessageRemoval:
    """A posted message that has outlived ``survey.message_ttl_hours``."""

    survey_id: uuid.UUID
    chat_id: int
    chat_message_id: int


@dataclass(frozen=True)
class PostResult:
    """What a :meth:`SurveyTransport.post` attempt achieved.

    ``delivered`` False with ``chat_message_id`` None is the normal, truthful
    answer in this deployment. ``permanent`` distinguishes "try again later"
    from "this can never work" — the cleanup queue needs the difference, or a
    message past Telegram's 48-hour own-delete limit is retried for ever.
    """

    delivered: bool
    chat_message_id: int | None = None
    permanent_failure: bool = False
    reason: str = ""


@runtime_checkable
class SurveyTransport(Protocol):
    """Whatever carries a survey to a customer. One implementation ships."""

    async def post(self, dispatch: Dispatch) -> PostResult:
        """Put ``dispatch`` in front of the customers in its chat."""
        ...

    async def refresh(self, update: CounterUpdate) -> bool:
        """Update the answer counter on a message already posted."""
        ...

    async def remove(self, removal: MessageRemoval) -> PostResult:
        """Take a message this product posted back out of the chat."""
        ...


class LoggingSurveyTransport:
    """Records the intent, delivers nothing, and says so. The release-1 answer.

    Every method returns a "not delivered" result. ``SurveyService`` reads
    that and leaves the row where it is — ``pending`` for a post, and
    ``message_deleted_at`` untouched for a removal — so the queue is still
    accurate the day a real transport is wired in.

    ⚠️ **No token, no deep link and no chat title is ever logged.** The token is
    an access key: whoever reads it out of a log file can answer that group's
    survey. Only the survey id and the chat id are recorded, which is enough to
    find the row and not enough to use it.
    """

    async def post(self, dispatch: Dispatch) -> PostResult:
        log.info(
            "survey_post_unavailable",
            survey_id=str(dispatch.survey_id),
            chat_id=dispatch.chat_id,
            reason="no_telegram_bot",
        )
        return PostResult(delivered=False, reason="no_telegram_bot")

    async def refresh(self, update: CounterUpdate) -> bool:
        log.info(
            "survey_refresh_unavailable",
            survey_id=str(update.survey_id),
            chat_id=update.chat_id,
            response_count=update.response_count,
            reason="no_telegram_bot",
        )
        return False

    async def remove(self, removal: MessageRemoval) -> PostResult:
        log.info(
            "survey_remove_unavailable",
            survey_id=str(removal.survey_id),
            chat_id=removal.chat_id,
            reason="no_telegram_bot",
        )
        return PostResult(delivered=False, reason="no_telegram_bot")


_transport: SurveyTransport = LoggingSurveyTransport()


def get_transport() -> SurveyTransport:
    """The process-wide transport. Call it as ``transport.get_transport()``.

    Called through the module rather than bound at import, for the reason
    ``tests/test_layering.py::test_nothing_binds_a_patchable_singleton_directly``
    gives about ``push.get_sender``: a name bound at import cannot be
    redirected, and a test that cannot redirect it silently exercises the real
    one.
    """
    return _transport


def set_transport(transport: SurveyTransport) -> None:
    """Swap the implementation. ``main.py`` wires a real one when it exists."""
    global _transport
    _transport = transport


__all__ = [
    "CounterUpdate",
    "Dispatch",
    "LoggingSurveyTransport",
    "MessageRemoval",
    "PostResult",
    "SurveyTransport",
    "get_transport",
    "set_transport",
]
