"""Pure enrolment rules — no session, no framework (§2).

The code alphabet and the MSISDN match rule are here because both have a
failure mode that a database test hides: a code nobody can read aloud, and
"I don't know" being treated as "yes".
"""

from __future__ import annotations

import re

#: Crockford base32 without ``I L O U``. The code is read aloud over the phone
#: and typed by a salesperson, and those four glyphs are where that fails —
#: 1/I, 0/O and the ones people spell out differently in Uzbek and Russian.
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

CODE_LENGTH = 8

#: The matching key is the last nine digits (N37).
PHONE_KEY_DIGITS = 9

_NON_DIGIT = re.compile(r"\D")


def normalise_code(raw: str) -> str:
    """Uppercase, strip separators, and fold the glyphs people confuse.

    An agent reading ``K7M4-PQ2X`` off a screen may type a lowercase l for 1 or
    an O for 0. Those characters are not in the alphabet, so folding them is
    unambiguous and turns a support call into a successful enrolment.
    """
    folded = raw.strip().upper().replace("-", "").replace(" ", "")
    return (
        folded.replace("I", "1")
        .replace("L", "1")
        .replace("O", "0")
        .replace("U", "V")
    )


def msisdn_matches(line1_number: str | None, registered_key: str) -> bool:
    """Route 1's match rule (UC-04, SPEC §9.1).

    **``None``, empty, whitespace or fewer than nine digits is never a match.**
    That is stated as an explicit requirement and asserted by a test, because
    the failure it prevents — treating "I don't know" as "yes" — would attribute
    a phone to a number it does not hold.
    """
    if not line1_number or not line1_number.strip():
        return False
    digits = _NON_DIGIT.sub("", line1_number)
    if len(digits) < PHONE_KEY_DIGITS:
        return False
    return digits[-PHONE_KEY_DIGITS:] == registered_key


def display_number(e164: str) -> str:
    """``+998901112233`` → ``+998 90 111-22-33`` — how it is read aloud."""
    digits = _NON_DIGIT.sub("", e164)
    if len(digits) != 12:
        return e164
    return f"+{digits[:3]} {digits[3:5]} {digits[5:8]}-{digits[8:10]}-{digits[10:]}"
