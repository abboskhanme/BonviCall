"""Phone number normalisation — the ONE implementation (CONVENTIONS.md §7, N37).

Semantics are deliberately identical to BonviZvonki so that release 2 can join
the two datasets on the same key (REQUIREMENTS.md §5.4).

The rule that matters: the matching key is the LAST 9 DIGITS. Anything shorter
is never a key. BonviZvonki learned this the hard way — a 7-digit value matches
the tail of almost any number, and strangers were classified as colleagues.
"""

from __future__ import annotations

import re

from sqlalchemy import case, func
from sqlalchemy.sql.elements import ColumnElement

#: The only place this number appears. Three copies is how one rule becomes two.
PHONE_KEY_DIGITS = 9

#: Uzbekistan. Release 1 serves one country; see the note in ``to_e164``.
COUNTRY_CODE = "998"

#: Fewer digits than this is a PBX extension, not a phone number.
EXTENSION_MAX_DIGITS = 6

_NON_DIGIT = re.compile(r"\D")


def _digits(raw: str | None) -> str:
    """Every digit in ``raw``, in order. Empty string for None/blank."""
    if not raw:
        return ""
    return _NON_DIGIT.sub("", raw)


def phone_key(raw: str | None) -> str | None:
    """The join key: the last 9 digits, or None if there are fewer than 9.

    This is the value stored, indexed and matched on. Never compare raw numbers.
    """
    digits = _digits(raw)
    if len(digits) < PHONE_KEY_DIGITS:
        return None
    return digits[-PHONE_KEY_DIGITS:]


def to_e164(raw: str | None) -> str | None:
    """Display/storage form: ``+998XXXXXXXXX``. None when there is no key.

    Release 1 assumes Uzbek numbers: the national part is the last 9 digits and
    the country code is prepended. That is correct for every number a Bonvi
    salesperson dials today and it keeps the trunk-prefix and operator-code
    formats in ``contract/phone-vectors.json`` collapsing to one value. If the
    company ever calls abroad, this function needs a real country-code parse —
    ``phone_key`` does not, which is why the key is the last 9 digits and not
    this.
    """
    key = phone_key(raw)
    if key is None:
        return None
    return f"+{COUNTRY_CODE}{key}"


def is_extension(raw: str | None) -> bool:
    """True for a short internal number (``700``, ``*700``) — a PBX extension.

    An extension is not a phone number and must never be given a phone key.
    """
    digits = _digits(raw)
    return 0 < len(digits) < EXTENSION_MAX_DIGITS


def phone_key_sql(column: ColumnElement) -> ColumnElement:
    """``phone_key`` expressed in SQL — the SAME rule, for indexes and joins.

    Used for the ``calls`` phone index in the T19 migration. If this and
    :func:`phone_key` ever disagree, the join silently returns nothing, which is
    the worst possible failure: no error, no rows, no clue.
    """
    digits = func.regexp_replace(column, r"[^0-9]", "", "g")
    return case(
        (
            func.length(digits) >= PHONE_KEY_DIGITS,
            func.right(digits, PHONE_KEY_DIGITS),
        ),
        else_=None,
    )


__all__ = [
    "PHONE_KEY_DIGITS",
    "COUNTRY_CODE",
    "phone_key",
    "to_e164",
    "is_extension",
    "phone_key_sql",
]
