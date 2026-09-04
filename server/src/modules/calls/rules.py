"""Pure call rules — no session, no framework, no imports from ``src`` (§2).

Only rules that must be testable without a database live here. Two qualify:
the internal/external classification of UC-25, and the audio-reason resolution
of N5. Both are decided per call at ingest and both have a failure mode that a
database test would hide behind fixtures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Below this many digits a number is a PBX extension, not a phone number.
#: The same threshold as ``core.phone.EXTENSION_MAX_DIGITS``; repeated here
#: because this module may not import anything (§2's purity check).
EXTENSION_MAX_DIGITS = 6

#: The matching key is the last nine digits (N37).
PHONE_KEY_DIGITS = 9

_NON_DIGIT = re.compile(r"\D")


@dataclass(frozen=True)
class LineDirectory:
    """Everything that makes a number "one of ours" (UC-25).

    :param registered_keys: last-9 keys of every registered number. Derived,
        never maintained by hand — BonviZvonki's hand-kept directory starved
        because somebody had to remember to update it, and 10 of 33 employees
        had an entry.
    :param exact/prefix/suffix: the admin's extras, digits only.
    """

    registered_keys: frozenset[str] = frozenset()
    exact: frozenset[str] = frozenset()
    prefix: frozenset[str] = frozenset()
    suffix: frozenset[str] = frozenset()

    @property
    def is_empty(self) -> bool:
        return not (self.registered_keys or self.exact or self.prefix or self.suffix)


def digits_of(raw: str | None) -> str:
    """Every digit in ``raw``, in order."""
    if not raw:
        return ""
    return _NON_DIGIT.sub("", raw)


def classify_call_type(remote_number: str | None, directory: LineDirectory) -> str:
    """``internal`` | ``external`` | ``unknown`` (UC-25, SPEC §10.2).

    **The empty-directory rule must never be "simplified".** BonviZvonki
    defaulted an unknown number to ``external``, an AI classifier then had to
    guess from content, and 82 of 98 calls were mislabelled. If we do not know,
    we say we do not know.

    Order matters: the directory is checked for emptiness *before* anything
    else, and a short number is internal regardless of the directory because a
    four-digit extension cannot be a customer.
    """
    if directory.is_empty:
        return "unknown"

    digits = digits_of(remote_number)
    if not digits:
        return "unknown"
    if len(digits) < EXTENSION_MAX_DIGITS:
        return "internal"

    key = digits[-PHONE_KEY_DIGITS:] if len(digits) >= PHONE_KEY_DIGITS else None
    if key is not None and key in directory.registered_keys:
        return "internal"
    if digits in directory.exact or key in directory.exact:
        return "internal"
    if any(digits.startswith(rule) for rule in directory.prefix):
        return "internal"
    if any(digits.endswith(rule) for rule in directory.suffix):
        return "internal"
    return "external"


#: UC-11's five classes are direction x disposition. The database enforces this
#: with ``ck_calls_direction_disposition``; the same rule lives here so a device
#: gets a 422 it can act on instead of a 500 it will retry forever.
VALID_DISPOSITIONS: dict[str, frozenset[str]] = {
    "incoming": frozenset({"answered", "missed", "rejected"}),
    "outgoing": frozenset({"answered", "no_answer"}),
}


def is_valid_combination(direction: str, disposition: str) -> bool:
    """Whether ``direction`` and ``disposition`` can describe the same call.

    An outgoing call cannot be "missed" and an incoming one cannot be
    "no_answer": those are the caller's word and the receiver's word for the
    same event, and mixing them means the record came from somewhere that does
    not understand the call it is describing.
    """
    return disposition in VALID_DISPOSITIONS.get(direction, frozenset())


def resolve_audio_reason(
    disposition: str,
    audio_expected: bool,
    client_reason: str | None,
) -> str | None:
    """The value ``calls.audio_missing_reason`` takes at ingest (N5, SPEC §4.4).

    Returns ``None`` only when audio is already present, which ingest never is:
    a call row always arrives before its audio (R7), so at this moment the
    answer is always a reason. The database CHECK enforces the pairing anyway.

    ``not_expected`` for an unanswered call is what keeps the gap report
    honest — an unanswered call in the denominator makes "% of answered calls
    with audio" meaningless.
    """
    if disposition != "answered":
        return "not_expected"
    if client_reason:
        return client_reason
    if audio_expected:
        return "pending_upload"
    return "recording_route_unavailable"


def clock_skew_seconds(
    received_at_epoch_ms: int, device_epoch_ms: int, device_rtt_ms: int | None = None
) -> int:
    """How far the handset's clock is from ours, in whole seconds (N36).

    Half the round trip is subtracted because the device stamped its clock
    before the request travelled. This is **evidence only**: it is shown in the
    panel and never used to rewrite ``started_at``, because a corrected
    timestamp would disagree with the device's own call log and break the
    reconciliation everything else depends on (SPEC §3.12).
    """
    transit_ms = (device_rtt_ms or 0) // 2
    return int((received_at_epoch_ms - device_epoch_ms - transit_ms) / 1000)
