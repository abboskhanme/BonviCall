"""Sales control — the vocabulary, the arithmetic and the file cleaning. Pure.

Ported from BonviZvonki ``modules/sales/domain/entities.py`` and the value
parsers of ``modules/sales/application/reader.py``. Every measured number in
the comments is theirs, taken against real SAP exports, and is kept because
re-learning it costs another quarter of wrong rows in front of a manager.

Nothing here imports the ORM, FastAPI or any other module (CONVENTIONS.md §2),
so every rule below is exercised by ``tests/test_sales_rules.py`` with no
session, no container and no clock. ``service.py`` issues the SQL and hands the
counts in; ``reader.py`` opens the workbook and hands the cell values in.

════════════════════════════════════════════════════════════════
 THE QUESTION, AND WHY THE ANSWER IS NEVER STORED
════════════════════════════════════════════════════════════════

One question: **was the sale agreed with the customer, or did it just appear?**
That is, is there a conversation of ours beside the SAP sale. If there is not,
that is **not an accusation** — it is a row in a review queue.

⚠️ THE VERDICT IS NEVER WRITTEN TO A TABLE. It is recomputed on every request.
A call can synchronise *after* the sale (a handset out of coverage delivers a
backlog days later, R7), and a "suspicious" flag written at import time would
by then be a lie that nobody would ever recompute. The only subjective thing in
the database is the human's decision (``sale_reviews``).

THE RULES, applied to ``op_type = 'sale'`` rows only:

  R1 — no conversation with this customer on the sale day or in the N days
       before it (N is ``sales.window_days``, default 3);
  R2 — no conversation at all between this customer's previous sale and this
       one (NOT applied to a first sale — there is nothing to compare);
  R3 — never spoken to this customer at all, in the whole history.

THREE CLASSES — nothing is hidden:

  ``ok``            — no rule broken;
  ``suspicious``    — a rule broken, and checking was possible;
  ``not_checkable`` — checking was impossible (a shared code, or a customer
                      with no usable number). This does **not** mean clean; it
                      is a third number on the screen.

TWO UNITS OF TIME, AND HOW THEY ARE RECONCILED:

  1. A SALE HAS NO CLOCK. SAP's ``Дата регистрации`` carries a date and no
     time, so the window is measured in whole days: the sale day plus the N
     before it (N+1 days). The screen says so out loud.
  2. A CALL HAS A CLOCK, and it is stored in UTC. The comparison is therefore
     done against **Asia/Tashkent** midnights (``service.py``): in UTC the day
     boundary falls at 05:00 local, and a 19:00 conversation would land on the
     next day and fall out of the window. Same rule as ``modules/activity``.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from uuid import UUID

# ══════════════════════════════════════════════════════════════
#  A note on the Cyrillic literals in this file (CONVENTIONS.md §14)
# ══════════════════════════════════════════════════════════════
#
# ``Продажа``, ``К00001`` and the rest are **SAP's own vocabulary**, not
# language: they are the bytes the export file contains and the codes the
# accounting system issues. Translating them would not localise anything — it
# would stop the import matching, exactly as translating
# ``contract/phone-vectors.json`` would stop the phone tests testing anything.
# They are therefore data, in the same category §14 grants to the model prompts
# and to provider fixtures. Every comment, docstring and identifier here is
# English.


# ══════════════════════════════════════════════════════════════
#  Operation type
# ══════════════════════════════════════════════════════════════


class SaleOpType(StrEnum):
    """``sales.op_type``.

    The rules are applied to :attr:`SALE` and to nothing else. The other types
    are stored **deliberately**: a payment or a return is part of the
    relationship with that customer and belongs on the customer's timeline.
    """

    SALE = "sale"
    PAYMENT_IN = "payment_in"
    PURCHASE = "purchase"
    PAYMENT_OUT = "payment_out"
    SALE_CANCEL = "sale_cancel"
    ACCOUNTING = "accounting"

    OTHER = "other"
    """A type SAP has and we do not know — **the row must not vanish**.

    Dropping an unrecognised row was tried and is silent data loss: the report
    says "read 2384" while the database holds 2300 and nobody ever notices the
    difference. ``other`` is counted separately in the import report
    (``unknown_op_type``) and takes part in no rule.

    It is also what makes a *closed* enum safe here: a new SAP type never needs
    a migration, because it lands in this member.
    """


#: SAP's ``Тип`` column -> our type.
#
# ⚠️ ``Исходящие платежи платежи`` is the REAL value in the export, with the
# word written twice (measured: 146 rows spell it exactly so). The written
# specification says ``Исходящие платежи``. Both spellings are kept, so the
# import works whether or not the export is ever fixed.
_OP_TYPES: dict[str, SaleOpType] = {
    "продажа": SaleOpType.SALE,
    "входящие платежи": SaleOpType.PAYMENT_IN,
    "закупка": SaleOpType.PURCHASE,
    "исходящие платежи": SaleOpType.PAYMENT_OUT,
    "исходящие платежи платежи": SaleOpType.PAYMENT_OUT,
    "отмена продажа": SaleOpType.SALE_CANCEL,
    "отмена продажи": SaleOpType.SALE_CANCEL,
    "бух.оп": SaleOpType.ACCOUNTING,
    "бух.оп.": SaleOpType.ACCOUNTING,
}


#: The word SAP printed for each type — for the pre-import estimate.
#
# ⚠️ DELIBERATELY THE SOURCE LANGUAGE, and it is data rather than user-facing
# copy: the reader compares the count beside it against the same report inside
# SAP, and a translated word makes that comparison impossible. The panel
# translates from the machine ``type`` key; this is the fallback, so that a
# type SAP invents tomorrow still shows something a person recognises.
SAP_OP_TYPE_LABELS: dict[SaleOpType, str] = {
    SaleOpType.SALE: "Продажа",
    SaleOpType.PAYMENT_IN: "Входящие платежи",
    SaleOpType.PURCHASE: "Закупка",
    SaleOpType.PAYMENT_OUT: "Исходящие платежи",
    SaleOpType.SALE_CANCEL: "Отмена продажи",
    SaleOpType.ACCOUNTING: "Бух.оп",
    SaleOpType.OTHER: "Прочее",
}


def op_type_from_sap(value: str | None) -> SaleOpType:
    """SAP's ``Тип`` text as one of ours. Unknown becomes :attr:`SaleOpType.OTHER`.

    The caller counts the ``OTHER`` rows into its report, and the row is stored
    either way.
    """
    key = " ".join((value or "").split()).lower()
    return _OP_TYPES.get(key, SaleOpType.OTHER)


# ══════════════════════════════════════════════════════════════
#  The verdict vocabulary
# ══════════════════════════════════════════════════════════════


class Verdict(StrEnum):
    """The three classes. ``not_checkable`` is not a kind of ``ok``."""

    OK = "ok"
    SUSPICIOUS = "suspicious"
    NOT_CHECKABLE = "not_checkable"


class Rule(StrEnum):
    """Which rule was broken. Always reported in this order (R1, R2, R3)."""

    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


class SkipReason(StrEnum):
    """Why checking was impossible."""

    GENERIC_CODE = "generic_code"
    """A shared code — many customers behind one code (``К00001`` and friends)."""

    NO_PHONE = "no_phone"
    """No usable number anywhere for this customer. See :func:`matchable_phone`."""


class ClientKind(StrEnum):
    """Sales control is split into **two separate sections**.

    ⚠️ WHY THEY CANNOT BE MIXED. A walk-in buyer is never written into the
    catalogue by name and number — they pass under one of a few shared codes
    (``sales.walk_in_codes``). For a sale under such a code the question "was
    this customer spoken to first?" is meaningless: one code, a hundred people.
    They used to sit in the same list as regular customers and were counted as
    ``not_checkable``, which wrote "could not be checked" into an employee's
    column — when what it actually described was the KIND OF WORK, not the
    quality of our data.

    Measured (24.08.2026): 718 sales and $531,432 under ``К00001`` alone — a
    sizeable share of what looked like the regular-customer list.

    · :attr:`REGULAR` — regular customers. Shared codes are EXCLUDED.
    · :attr:`WALK_IN` — shared codes only. The rules do not apply; the measure
      is different — is any single ticket over the limit.
    """

    REGULAR = "regular"
    WALK_IN = "walk_in"


class ReviewState(StrEnum):
    """Where a sale sits in the review queue.

    :attr:`NEW` — nobody has decided yet. The list shows exactly these by
    default: a sale that has been looked at must not be back at the top of the
    queue tomorrow, or the queue never ends.
    """

    NEW = "new"
    JUSTIFIED = "justified"
    CONFIRMED = "confirmed"

    ALL = "all"
    """Everything, decided or not.

    ⚠️ DELIBERATELY ITS OWN VALUE rather than "leave ``review`` empty". A
    manager does ask for "show me every decision" (the justified-sales figure
    is read off that list), and that has to be an explicit CHOICE. An absent
    parameter means "the user did not choose", and then the default is ``new``.
    """


class SaleReviewStatus(StrEnum):
    """``sale_reviews.status`` — the only subjective value in the database."""

    JUSTIFIED = "justified"
    CONFIRMED = "confirmed"


class SaleReviewReason(StrEnum):
    """Why a sale was justified. Only meaningful with ``justified``."""

    WALK_IN = "walk_in"
    TELEGRAM = "telegram"
    VISIT = "visit"
    CONTRACT = "contract"
    OTHER = "other"


# ══════════════════════════════════════════════════════════════
#  Settings and their bounds
# ══════════════════════════════════════════════════════════════

#: Used when ``sales.window_days`` is unreadable or absent.
DEFAULT_WINDOW_DAYS = 3

#: A sane ceiling for the window. Without one, ``99999`` typed into the setting
#: switches the whole of sales control off silently — every sale would find
#: some conversation somewhere in its window.
MAX_WINDOW_DAYS = 365

#: Used when ``sales.walk_in_limit_usd`` is unreadable. Whole dollars: every
#: value in ``app_settings`` is an int, a bool or a string, because
#: ``value_type`` decides which editor the panel renders and it has no float.
DEFAULT_WALK_IN_LIMIT_USD = 2000

#: ``Разовый клиент`` — the shared code most walk-in sales are booked under.
#
# Roughly 29 % of all sales carry it and none of them identifies a real person.
WALK_IN_PARTNER_CODE = "К00001"

#: SHARED CODES — many people behind one code.
#
# For these the question "was this customer spoken to?" has no meaning at all,
# so the rules do not check them and the sale falls into ``not_checkable``
# (``skip_reason = "generic_code"``). ⚠️ That is NOT "clean" — the third class
# is its own number on the screen.
#
# Measured (22.08.2026, 1039 sales):
#   · ``К00001`` "Разовый клиент"                        — 152 sales
#   · ``К02370`` "Салл сентр"                            —  20 sales
#   · ``К03223`` "Разовый клиент — Тошкент телефон савдо" —   2 sales
#
# ⚠️ The leading letter is CYRILLIC ``К`` (U+041A), not Latin ``K``. SAP writes
# it that way; spelled with the Latin letter this list would silently stop
# matching anything.
#
# A new shared code is added here. Moving the list into a setting was
# considered and rejected: it changes about once a year, and a setting filled
# in wrongly would silently empty a whole section of the product. It IS
# overridable through ``sales.walk_in_codes`` for the deployment that needs it
# — this is the floor that list falls back to.
GENERIC_PARTNER_CODES: frozenset[str] = frozenset(
    {WALK_IN_PARTNER_CODE, "К02370", "К03223"}
)

#: The ``Код группы`` value that means "a customer". Everything else — supplier,
#: founder, transport — is outside sales control.
CLIENT_GROUP = "Клиенты"


def parse_partner_codes(raw: object) -> frozenset[str]:
    """A settings value as a set of SAP codes. **Never returns empty.**

    ⚠️ THE SEPARATOR IS FREE. An admin pastes this list out of SAP or out of a
    chat message, where the separator may be a comma, a semicolon or a plain
    newline. Demanding one exact character leads to the list being read HALF
    silently: one unrecognised code puts hundreds of sales in the wrong section
    and nobody sees it.

    ⚠️ CASE IS NOT CHANGED. The code starts with a Cyrillic ``К`` and neither
    ``upper()`` nor ``lower()`` brings that any closer to a Latin ``K`` — so
    normalising buys nothing and risks corrupting a real SAP code. Only the
    surrounding whitespace is stripped.

    An empty result would silently switch a whole section off, so the built-in
    :data:`GENERIC_PARTNER_CODES` is used instead.
    """
    return frozenset(_split_codes(raw)) or GENERIC_PARTNER_CODES


def parse_optional_codes(raw: object) -> frozenset[str]:
    """The same, except that **an empty list is a real answer** — and the default.

    ⚠️ That difference from :func:`parse_partner_codes` is deliberate. An empty
    walk-in list breaks the product, so it falls back; an empty *internal*
    list simply means "exclude nobody", which is the normal state. Falling back
    to the built-in list there would silently drop a real customer out of sales
    control.
    """
    return frozenset(_split_codes(raw))


def _split_codes(raw: object) -> set[str]:
    if isinstance(raw, list | tuple | set | frozenset):
        parts: list[str] = [str(item) for item in raw]
    else:
        text = str(raw or "")
        for sign in (";", "\n", "\r", "\t", "|"):
            text = text.replace(sign, ",")
        parts = text.split(",")
    return {part.strip() for part in parts if part and part.strip()}


def clamp_window_days(raw: object) -> int:
    """``sales.window_days`` as a usable number of days.

    A broken value must not stop the whole section: hand-typed text falls back
    to the default, and the result is held inside ``0..MAX_WINDOW_DAYS``.
    """
    try:
        days = int(float(raw))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_DAYS
    return max(0, min(days, MAX_WINDOW_DAYS))


def clamp_walk_in_limit(raw: object) -> int:
    """``sales.walk_in_limit_usd`` as whole dollars.

    A negative limit is meaningless — it would mark EVERY sale as over the
    limit — so it clamps at zero, and an unreadable value falls back.
    """
    try:
        limit = int(float(raw))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_WALK_IN_LIMIT_USD
    return max(0, limit)


# ══════════════════════════════════════════════════════════════
#  Matching a SAP branch name to an employee name
# ══════════════════════════════════════════════════════════════

#: One sound, several spellings. Key — what SAP or our own roster writes;
#: value — the single form.
#
# ⚠️ THE DIRECTION MATTERS. The written specification said "ж → дж", but that
# cannot be executed literally: the ``ж`` inside ``Джиззах`` is replaced too and
# the result is ``дджиззах`` — the substitution DESTROYS ITSELF. So the reverse
# direction was chosen: ``дж → ж``. The outcome is the same (``Жиззах`` and
# ``Джиззах`` collapse onto one form) and the operation is IDEMPOTENT: applying
# it any number of times gives the same answer.
_LETTER_FOLDS: tuple[tuple[str, str], ...] = (
    ("дж", "ж"),
    ("ё", "е"),
    ("й", "и"),
    ("ъ", ""),
    ("ь", ""),
)


def _collapse_repeats(text: str) -> str:
    """Runs of one character down to a single one.

    ⚠️ WITHOUT THIS, ``Навоий`` AND ``Навои`` DO NOT MATCH. After ``й → и`` the
    first is ``навоии`` and the second ``навои`` — one letter apart, and the
    branch would never be linked. It is the commonest difference in SAP: in the
    Russian spelling of Uzbek names the final ``й`` is there or not at random.

    Applied to BOTH sides (branch name and employee name), so it only removes a
    difference — it never creates a new collision.
    """
    result: list[str] = []
    for char in text:
        if not result or result[-1] != char:
            result.append(char)
    return "".join(result)


def normalise_branch(name: str | None) -> str:
    """The comparable form of a branch or employee name.

    ``Навоий`` -> ``навои``, ``Жиззах`` -> ``жизах``, ``  Тошкент `` ->
    ``тошкент``.

    Used to link SAP's ``Подразделение`` to ``agents.full_name``. The lookup is
    on EXACT equality of these forms: fuzzy matching is deliberately absent —
    booking a sale to the wrong employee is worse than leaving it unassigned,
    because after that nobody ever checks it.
    """
    text = " ".join((name or "").split()).lower()
    for source, target in _LETTER_FOLDS:
        text = text.replace(source, target)
    return _collapse_repeats(text)


# ══════════════════════════════════════════════════════════════
#  Cleaning the values SAP puts in the cells
# ══════════════════════════════════════════════════════════════

#: SAP always writes money to three decimal places.
_DECIMALS = Decimal("0.001")

#: The OLD generation's money-cell format — "no decimals shown".
#
# ⚠️ THIS EXACT STRING IS THE ONLY THING that separates the two generations of
# export. Measured over the ``Хақдор ($)`` column, across every numeric cell:
#
#     savdo kunlik.xlsx (old)            649 cells -> ALL ``#,##0``
#     клиент харакати общий (new)     12,591 cells -> ALL ``General``
#     Workbook3.xlsx (old catalogue)     257 cells -> ``#,##0``
#     Mijozlar ruyxati.xlsx (new)          0 money cells with ``#,##0``
#
# The new catalogue does contain three ``#,##0`` cells, but all three are in the
# phone column, where no money is read — so the marker separates money cells
# cleanly.
LEGACY_THOUSANDS_FORMAT = "#,##0"


class LegacyThousands(int):
    """An OLD-export money cell that Excel read wrongly.

    Importing the text ``"561,000"``, Excel took the comma for a thousands
    separator and stored 561000 rather than 561. The ``#,##0`` format on the
    cell is the residue of exactly that: Excel marked it "a whole number with
    no decimals". A value written with a space, ``"1 950,000"``, did not look
    like a number at all and stayed text — which is why one column of one file
    carries two different meanings side by side.

    Verified — such cells are ALWAYS a factor of 1000 too large:

        UZS document:  ($) cell 8333   <-> (сўм) text ``100 000,000``
                       8333/1000 = 8.333 $ ~ 100,000 so'm (rate ~12,000)
        AED document:  ($) cell 136240 <-> (дирҳам) cell 500000
                       136.240 $ ~ 500 dirham (rate 3.67)

    ⚠️ SUBCLASSING ``int`` IS DELIBERATE. The marker is applied while the cell
    is being read, so it also appears outside the money columns (in the new
    catalogue, on a phone number). Because it is still an ``int``, every other
    reader treats it as an ordinary number and the marker's effect is confined
    to :func:`parse_amount`.
    """

    __slots__ = ()


def parse_amount(value: Any) -> Decimal | None:
    """A money cell as a :class:`~decimal.Decimal`. ``"1 950,000"`` -> ``1950.000``.

    ⚠️ THERE ARE TWO GENERATIONS OF EXPORT and they arrive in the same column.
    Which rule applies is decided by the TYPE OF THE CELL:

      · TEXT (``"1 950,000"``) — the space is a thousands separator and the
        comma a decimal point -> 1950.000. Most old-export money looks like this.

      · :class:`LegacyThousands` — an old-export cell Excel mis-read (a ``#,##0``
        whole number) -> divided by 1000. The marker is applied in ``reader.py``.

      · A PLAIN NUMBER (``1230.0``, ``256``, ``0.0``) — the NEW export, already
        correct -> taken UNCHANGED.

    ⚠️ THE LAST BRANCH IS A REWRITE. Every numeric cell used to be divided by
    1000, and on the new export that shrank every amount by a factor of a
    thousand: 146,000 $ became 146 $, and 256 $ became 0. All 12,591 money
    cells in the new file are numbers and all of them are ``General``, so the
    old rule corrupted every single one.
    """
    if value is None or isinstance(value, bool):
        return None

    # ⚠️ ``LegacyThousands`` is a child of ``int``, so it must be tested BEFORE
    # the general numeric branch below.
    if isinstance(value, LegacyThousands):
        return (Decimal(int(value)) / 1000).quantize(_DECIMALS)

    if isinstance(value, int | float | Decimal):
        return Decimal(str(value)).quantize(_DECIMALS)

    text = str(value).strip().replace("\xa0", "").replace(" ", "")
    if not text:
        return None
    # The comma is the decimal point. Thousands spaces were removed above, so a
    # full stop does not occur here.
    try:
        return Decimal(text.replace(",", ".")).quantize(_DECIMALS)
    except (InvalidOperation, ValueError):
        return None


#: How a date may be written. The first is SAP's real format; the rest are
#: insurance for a file a user opened in Excel and saved again.
_DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y")


def parse_date(value: Any) -> date | None:
    """``"20.08.2026"`` -> ``date(2026, 8, 20)``. Unrecognised -> ``None``.

    ⚠️ THERE IS NO TIME PART in the export. If Excel turned the cell into a date
    (a ``datetime``) the time reads 00:00 and that is FABRICATED — so only the
    date is taken, and the whole module measures its window in whole days
    because of it.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()  # noqa: DTZ007 — a date, no clock
        except ValueError:
            continue
    return None


#: The digits after a ``+`` in the raw text — where the country code is read
#: from. ``\s*`` is needed: the catalogue also contains ``(+ 9989) 1234567``.
_PLUS_COUNTRY = re.compile(r"\+\s*(\d+)")

#: Uzbekistan's international code.
_UZ_COUNTRY_CODE = "998"

#: How many digits a ``+CC`` number needs before it counts as foreign. Shorter
#: than this and it is a local number with a stray ``+``.
_FOREIGN_MIN_DIGITS = 11

#: The length of the matching key. It is NOT re-derived here — the key itself is
#: produced by the database from ``core.phone.phone_key_sql`` — but the foreign
#: and fake tests below need to look at the same tail the key will be cut from.
_KEY_DIGITS = 9


def matchable_phone(value: Any) -> str | None:
    """The raw number, but only if we are willing to MATCH calls on it.

    Returns the number unchanged when it is usable, and ``None`` when it is
    not. The last-9 key itself is never computed here: it is a GENERATED column
    produced by ``core.phone.phone_key_sql``, so the sales key and
    ``calls.remote_number_key`` cannot drift apart (CONVENTIONS.md §7).
    This function only decides WHICH raw value is eligible to have a key at all.

    SAP writes phone numbers ten different ways — ``(+99890) 1234567``,
    ``998901234567``, ``(90) 123-45-67``, ``(+ 9989) 1234567`` — and the last-9
    rule folds all of them onto one key. Some cells hold a Telegram handle
    instead (``@EadTrader``); those have no digits and are refused.

    ⚠️ "THE LAST 9 DIGITS" IS NOT APPLIED UNCONDITIONALLY. Two kinds of value in
    the catalogue produce a wrong key, and both do damage:

      · FOREIGN NUMBERS — ``(+971) …``, ``(+992) …``, ``(+7701) …``. Their last
        nine digits can COINCIDENTALLY look like an Uzbek number, and the sale
        would then be linked to a STRANGER's calls. Filtering by customer group
        is not enough: measured — 75 such rows, 25 of them inside ``Клиенты``
        (the rest mostly ``Поставщики импорт``).

      · FAKE NUMBERS — ``(0000) 000-00-03``, ``(0500) 000-00-01``,
        ``(99) 999-99-99``, ``(+99811) 1111111``. They count as "has a phone",
        then no call is ever found, and the customer becomes SUSPICIOUS FOR NO
        REASON — the exact false signal this product exists to prevent.
        Measured: 33 rows (20 starting with a zero, 13 a single repeated digit).

    Together 108 contractors lose their key (3531 -> 3423): coverage falls from
    94.3 % to 91.4 %. That is NOT a loss — those 108 keys were wrong anyway;
    they led either to a stranger's calls or to nowhere.

    The three tests are DELIBERATELY NARROW: killing an honest number is worse
    than a false key, because the customer would then drop out of sales control
    silently. Borderline values that are kept: ``(+99888) 8999998``,
    ``(+99899) 5555559``, ``0901234567`` (written with a trunk zero), and the
    landline ``(71) 200-00-00``.
    """
    raw = str(value or "")
    digits = "".join(char for char in raw if char.isdigit())
    if len(digits) < _KEY_DIGITS:
        return None

    # ── 1. A foreign number ───────────────────────────────────
    #
    # The raw text carries ``+CC`` and CC is not ``998``. The digit-count test
    # is MANDATORY: a short local number written with a plus (``(+90) 1234567``)
    # must not be mistaken for an international one. Measured: of 3446 rows
    # containing a ``+``, 92 had a code other than 998, and 76 of those had 11
    # or more digits — that is, were genuinely international.
    match = _PLUS_COUNTRY.search(raw)
    if match is not None:
        country = match.group(1)[:3]
        if (
            len(country) == 3
            and country != _UZ_COUNTRY_CODE
            and len(digits) >= _FOREIGN_MIN_DIGITS
        ):
            return None

    tail = digits[-_KEY_DIGITS:]

    # ── 2. Starts with a zero ─────────────────────────────────
    #
    # The national part of an Uzbek number NEVER starts with a zero: mobile
    # prefixes are 33/88/90/91/93/94/95/97/98/99 and landline codes 71/62/…
    # A "last nine digits" beginning with a zero means the value is incomplete
    # or was made up.
    if tail.startswith("0"):
        return None

    # ── 3. One digit repeated ─────────────────────────────────
    #
    # ``999999999``, ``111111111``, ``333333333`` — values typed to fill an
    # empty cell.
    if len(set(tail)) == 1:
        return None

    return raw


def clean_text(value: Any, *, limit: int | None = None) -> str | None:
    """A cell as tidy text, or ``None``. Collapses whitespace, trims to ``limit``."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    return text[:limit] if limit else text


# ══════════════════════════════════════════════════════════════
#  The shapes the service hands back
# ══════════════════════════════════════════════════════════════


@dataclass(slots=True)
class SaleVerdict:
    """One sale's verdict **and its evidence**.

    ⚠️ The evidence fields are not a nicety — they are a REQUIREMENT. The
    manager re-derives the number by hand, so every suspicious row must carry
    "when was the last conversation, with whom, how many days before" beside
    it. Without that the list is not believed, least of all in front of the
    person it is about.
    """

    sale_id: UUID
    verdict: str
    broken_rules: list[str]
    skip_reason: str | None

    last_call_at: datetime | None
    """The nearest conversation BEFORE the sale (or on the sale day).

    ⚠️ NOT BOUNDED BY THE WINDOW: with a 3-day window, a conversation 9 days
    ago must still be visible — that number is precisely what explains the rule.
    """

    last_call_agent: str | None
    last_call_id: UUID | None
    """The call row itself, so the panel can open the recording. BonviZvonki
    shows the date and the name and there is nothing to click: it has no
    recordings. This product does."""

    days_before: int | None
    """How many days before the sale. ``0`` — the same day."""

    previous_sale_on: date | None
    """R2: this customer's previous sale date. ``None`` — first sale."""

    calls_between: int
    calls_total: int


@dataclass(slots=True)
class SaleReview:
    """The human's decision — the only subjective row in the database."""

    status: str
    reason: str | None
    note: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None


@dataclass(slots=True)
class ComplianceRow:
    """One sale in the queue: the SAP fact, the verdict, and the decision."""

    id: UUID
    occurred_on: date
    external_id: str
    doc_number: str | None
    """SAP's ``Номер документа``.

    ⚠️ NOT INTERCHANGEABLE with ``external_id`` (``Номер операции``): the
    operation number is our idempotency key, the document number is the piece
    of paper the manager searches for inside SAP. Both are on the screen, so
    the evidence can be checked by hand.
    """

    partner_code: str
    partner_name: str | None
    phone: str | None
    phone_key: str | None
    branch: str | None
    direction: str | None
    agent_id: UUID | None
    agent_name: str | None
    amount: float | None
    currency: str
    amount_usd: float | None
    verdict: SaleVerdict
    review: SaleReview | None

    partner_excluded: bool = False
    """The customer is OUT OF SCOPE (``sale_partners.excluded_at``).

    ⚠️ Does not affect the verdict — it is for the screen. The button on the
    sale card has to KNOW the customer's state, otherwise it opens saying
    "Exclude" even for a customer who is already excluded, and there is no way
    back from the screen.

    ⚠️ ``False`` for a code that is not in the catalogue at all — there is no
    row to carry the flag.
    """

    over_limit: bool = False
    """A walk-in sale over the single-ticket limit.

    ⚠️ ALWAYS ``False`` in the regular-customer section: there is no notion of
    a limit there. A large sale to a regular customer is a normal event; under
    a shared code it is either a regular customer booked wrongly or a case
    worth checking.
    """


@dataclass(slots=True)
class AgentBreakdown:
    """The per-employee cut.

    ``agent_id = None`` — sales whose branch is linked to nobody. They come
    back as their OWN row rather than vanishing quietly.
    """

    agent_id: UUID | None
    agent_name: str | None
    sales: int
    ok: int
    suspicious: int
    not_checkable: int
    new: int
    """Suspicious and not yet looked at — the manager's work queue."""
    justified: int
    confirmed: int

    over_limit: int = 0
    """Walk-in sales over the limit (always 0 in the regular section)."""
    over_limit_amount: float = 0.0


@dataclass(slots=True)
class ComplianceSummary:
    """The counts behind the cards, and the per-employee cut."""

    total: int
    ok: int
    suspicious: int
    not_checkable: int
    new: int
    justified: int
    confirmed: int
    window_days: int
    agents: list[AgentBreakdown] = field(default_factory=list)

    # ── For the walk-in section ───────────────────────────────
    #
    # ⚠️ In the regular-customer section these are ALWAYS zero and the panel
    # does not draw them. They were deliberately not split into a second
    # response type: both sections must eat from one contract, or they drift
    # apart over time and one sale ends up counted twice, differently.
    over_limit: int = 0
    over_limit_amount: float = 0.0
    """Their dollar total — "how much money went past the limit"."""
    walk_in_limit: int = DEFAULT_WALK_IN_LIMIT_USD
    """Which limit the figures were computed against — written out on the
    screen, because otherwise the number belongs to no threshold anybody knows."""


__all__ = [
    "CLIENT_GROUP",
    "DEFAULT_WALK_IN_LIMIT_USD",
    "DEFAULT_WINDOW_DAYS",
    "GENERIC_PARTNER_CODES",
    "LEGACY_THOUSANDS_FORMAT",
    "MAX_WINDOW_DAYS",
    "SAP_OP_TYPE_LABELS",
    "WALK_IN_PARTNER_CODE",
    "AgentBreakdown",
    "ClientKind",
    "ComplianceRow",
    "ComplianceSummary",
    "LegacyThousands",
    "ReviewState",
    "Rule",
    "SaleOpType",
    "SaleReview",
    "SaleReviewReason",
    "SaleReviewStatus",
    "SaleVerdict",
    "SkipReason",
    "Verdict",
    "clamp_walk_in_limit",
    "clamp_window_days",
    "clean_text",
    "escape_html",
    "matchable_phone",
    "normalise_branch",
    "op_type_from_sap",
    "parse_amount",
    "parse_date",
    "parse_optional_codes",
    "parse_partner_codes",
]


def escape_html(text: str | None) -> str:
    """Text that is safe inside a Telegram HTML message.

    Customer names contain ``&`` and ``<`` (``ООО "Bonvi" & Co``). Unescaped,
    Telegram rejects the WHOLE message — one customer's name would stop the
    daily digest arriving at all.
    """
    return html.escape(text or "", quote=False)
