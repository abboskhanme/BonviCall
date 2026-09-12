"""Turning a MoiZvonki event into BonviCall's own facts (T-MZ).

Pure, and separate from the database on purpose: every rule below decides
something a person will later read off a call card — which direction it was,
whether it was answered, when it started — and a rule that can only be tested
by posting a webhook is a rule nobody tests.

═══ The provider's event ══════════════════════════════════════════════════
::

    {"event": {"event_type": 4, "event_pbx_call_id": "...", "direction": 1,
               "client_number": "998901112233", "answered": true,
               "duration": 42, "recording": "https://...", "db_call_id": "..."}}

``event_type``: 1 start · 2 answer · 4 finish · 32 SMS (ignored).
``direction``:  0 incoming · 1 outgoing.

⚠️ **Only ``call.finish`` carries the truth.** On an outgoing call the provider
sends ``call.answer`` immediately after ``call.start`` whether or not anybody
picked up, so the answered flag and the duration are read from the finish event
and the answer time is computed backwards from it. A handset with no signal
may deliver *only* ``call.finish``, which is why that one event has to be
sufficient on its own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.core.enums import CallDirection, CallDisposition

#: The same namespace the Android client derives ``client_call_id`` from
#: (``domain/ClientCallId.kt``). Shared so a provider-sourced call and a
#: handset-sourced one can never collide, and so a replayed webhook produces
#: the same id — which is what makes ingest idempotent without a new column.
CLIENT_CALL_ID_NAMESPACE = uuid.UUID("8f6e5a30-0d7e-5c9b-9d3f-6f1c0a5d4b21")

#: Event types worth a row. 32 is SMS and is deliberately dropped: this product
#: records calls, and a message logged as a call would corrupt every rate the
#: gap report computes.
EVENT_START = 1
EVENT_ANSWER = 2
EVENT_FINISH = 4
CALL_EVENTS = frozenset({EVENT_START, EVENT_ANSWER, EVENT_FINISH})

#: Candidate fields naming the employee's own line, best first.
#:
#: ⚠️ **This is the one thing the ported integration could not tell us.**
#: WunderkindLC runs one operator on one account, so its webhook handler never
#: needed to ask whose call an event was and reads none of these. BonviCall has
#: forty agents and must. The provider's cabinets have not been consistent
#: about the name, so several are tried and the raw payload is logged the first
#: time none of them matches — the field is then read off a real event rather
#: than guessed twice.
OPERATOR_FIELDS: tuple[str, ...] = (
    "user_number",
    "internal_number",
    "operator_number",
    "line_number",
    "user_name",
    "user_id",
    "operator",
)


def client_call_id_for(pbx_call_id: str) -> uuid.UUID:
    """The idempotency key for a provider call.

    Derived rather than stored in a new column: ``calls.client_call_id`` is
    already the unique upsert key, already a UUIDv5, and already carries
    exactly this meaning. A ``provider_call_id`` column would be a second
    identity for the same row and a migration for nothing.
    """
    return uuid.uuid5(CLIENT_CALL_ID_NAMESPACE, f"moizvonki:{pbx_call_id}")


@dataclass(frozen=True)
class ProviderEvent:
    """One webhook event, after parsing and before any database work."""

    event_type: int
    pbx_call_id: str
    direction: CallDirection
    client_number: str
    answered: bool
    duration_sec: int
    recording_url: str | None
    db_call_id: str | None

    #: Whichever field the cabinet uses to say WHOSE call this was. See
    #: [OPERATOR_FIELDS]. ``None`` on a cabinet that does not send one, which
    #: is not fatal — the call is still ingested, against the line the
    #: ``client_number`` resolves to.
    operator_hint: str | None

    #: Every key the event carried, kept only so the first unresolved call can
    #: be logged in full and the real field name read off it rather than
    #: guessed a second time.
    raw_keys: tuple[str, ...]

    @property
    def is_final(self) -> bool:
        """Only the finish event may set a disposition or a duration."""
        return self.event_type == EVENT_FINISH


def parse_event(body: dict[str, Any]) -> ProviderEvent | None:
    """Read the envelope, or ``None`` when it is not a call event we keep.

    Returning ``None`` rather than raising is deliberate: the caller answers
    200 to everything it understands *and* everything it does not, because a
    4xx makes the provider retry a payload that will never become valid, for
    ever.
    """
    event = body.get("event")
    if not isinstance(event, dict):
        return None

    event_type = _as_int(event.get("event_type"))
    if event_type not in CALL_EVENTS:
        return None

    pbx_call_id = str(event.get("event_pbx_call_id") or "").strip()
    if not pbx_call_id:
        # Without it there is no identity, so there is nothing to upsert on.
        return None

    recording = str(event.get("recording") or "").strip()
    return ProviderEvent(
        event_type=event_type,
        pbx_call_id=pbx_call_id,
        # 1 is outgoing; anything else — including a missing field — is
        # incoming, because an unknown direction filed as outgoing would
        # inflate the one number this product is judged on.
        direction=(
            CallDirection.OUTGOING
            if _as_int(event.get("direction")) == 1
            else CallDirection.INCOMING
        ),
        client_number=str(event.get("client_number") or "").strip(),
        answered=bool(event.get("answered")),
        duration_sec=max(0, _as_int(event.get("duration"))),
        recording_url=recording if recording.lower().startswith("http") else None,
        db_call_id=str(event.get("db_call_id") or "").strip() or None,
        operator_hint=_first_present(event, OPERATOR_FIELDS),
        raw_keys=tuple(sorted(event.keys())),
    )


def _first_present(event: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = str(event.get(field) or "").strip()
        if value:
            return value
    return None


def disposition_for(event: ProviderEvent) -> CallDisposition:
    """What the call card will say.

    ⚠️ **Unanswered is not one value.** ``calls`` carries a CHECK constraint
    making ``missed``/``rejected`` incoming-only and ``no_answer``
    outgoing-only, so a single "unanswered" would be rejected by the database
    on half the rows. The constraint is right: "they did not pick up" and "we
    did not reach them" are different facts about different people, and UC-11
    counts them separately.

    ``rejected`` is never produced here. The provider reports one boolean and
    does not distinguish a decline from an unanswered ring; inventing that
    distinction would put a fact on the card that nobody measured.
    """
    if event.answered:
        return CallDisposition.ANSWERED
    if event.direction is CallDirection.OUTGOING:
        return CallDisposition.NO_ANSWER
    return CallDisposition.MISSED


def answered_at_for(event: ProviderEvent, ended_at: datetime) -> datetime | None:
    """When the conversation actually began.

    Computed backwards from the end, because the provider's own
    ``call.answer`` fires on an outgoing call before anybody has picked up —
    using it would report every unanswered call as answered the instant it was
    dialled.
    """
    if not event.answered:
        return None
    return ended_at - timedelta(seconds=event.duration_sec)


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
