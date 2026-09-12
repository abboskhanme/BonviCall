"""The provider-event rules (T-MZ).

Pure tests, no database and no network: every one of these decides something a
person later reads off a call card, and the point of keeping the rules pure is
that they can be pinned here rather than through a webhook.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.core.enums import CallDirection, CallDisposition
from src.modules.telephony import rules


def event(**overrides) -> dict:
    payload = {
        "event_type": 4,
        "event_pbx_call_id": "pbx-1",
        "direction": 1,
        "client_number": "998901112233",
        "answered": True,
        "duration": 42,
        "recording": "https://cabinet.moizvonki.ru/rec/1.mp3",
        "db_call_id": "db-1",
    }
    payload.update(overrides)
    return {"event": payload}


def test_a_finish_event_is_parsed_whole() -> None:
    parsed = rules.parse_event(event())
    assert parsed is not None
    assert parsed.pbx_call_id == "pbx-1"
    assert parsed.direction is CallDirection.OUTGOING
    assert parsed.duration_sec == 42
    assert parsed.recording_url == "https://cabinet.moizvonki.ru/rec/1.mp3"
    assert parsed.is_final


def test_sms_and_unknown_events_are_dropped() -> None:
    # 32 is SMS. A message logged as a call would corrupt every rate the gap
    # report computes, and the handler must still answer 200 so the provider
    # stops retrying.
    assert rules.parse_event(event(event_type=32)) is None
    assert rules.parse_event(event(event_type=99)) is None
    assert rules.parse_event({"nothing": "useful"}) is None
    assert rules.parse_event({"event": "not-an-object"}) is None


def test_an_event_with_no_call_id_is_dropped() -> None:
    # Without it there is no identity, so there is nothing to upsert on.
    assert rules.parse_event(event(event_pbx_call_id="")) is None


def test_an_unknown_direction_is_incoming() -> None:
    # Filing an unknown direction as outgoing would inflate the one number
    # this product is judged on.
    assert rules.parse_event(event(direction=0)).direction is CallDirection.INCOMING
    parsed = rules.parse_event(event())
    assert parsed.direction is CallDirection.OUTGOING
    del_direction = event()
    del del_direction["event"]["direction"]
    assert rules.parse_event(del_direction).direction is CallDirection.INCOMING


def test_a_non_http_recording_is_not_a_recording() -> None:
    assert rules.parse_event(event(recording="")).recording_url is None
    assert rules.parse_event(event(recording="none")).recording_url is None


def test_the_idempotency_key_is_stable_and_namespaced() -> None:
    # A replayed webhook must produce the same row, and a provider call must
    # never collide with a handset one.
    first = rules.client_call_id_for("pbx-1")
    assert first == rules.client_call_id_for("pbx-1")
    assert first != rules.client_call_id_for("pbx-2")
    assert first == uuid.uuid5(rules.CLIENT_CALL_ID_NAMESPACE, "moizvonki:pbx-1")


def test_unanswered_is_a_different_word_in_each_direction() -> None:
    """``calls`` has a CHECK making these direction-specific.

    A single "unanswered" value would be refused by the database on half the
    rows — and the constraint is right: "they did not pick up" and "we did not
    reach them" are different facts about different people (UC-11).
    """
    outgoing = rules.parse_event(event(answered=False, direction=1))
    incoming = rules.parse_event(event(answered=False, direction=0))
    assert rules.disposition_for(outgoing) is CallDisposition.NO_ANSWER
    assert rules.disposition_for(incoming) is CallDisposition.MISSED
    assert rules.disposition_for(rules.parse_event(event())) is CallDisposition.ANSWERED


def test_the_answer_time_is_computed_backwards_from_the_end() -> None:
    """The provider's own ``call.answer`` fires before anybody picks up.

    Trusting it would report every unanswered outgoing call as answered the
    instant it was dialled.
    """
    ended = datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC)
    parsed = rules.parse_event(event(duration=42))
    assert rules.answered_at_for(parsed, ended).second == 18
    unanswered = rules.parse_event(event(answered=False))
    assert rules.answered_at_for(unanswered, ended) is None


def test_the_operator_hint_is_read_from_whichever_field_the_cabinet_uses() -> None:
    # The one thing the ported integration could not tell us: WunderkindLC runs
    # a single operator and never needed to ask whose call it was.
    assert rules.parse_event(event(user_number="101")).operator_hint == "101"
    assert rules.parse_event(event(internal_number="202")).operator_hint == "202"
    # Absent is not fatal, and the raw keys are kept so the real field name can
    # be read off a live event instead of guessed again.
    parsed = rules.parse_event(event())
    assert parsed.operator_hint is None
    assert "client_number" in parsed.raw_keys
