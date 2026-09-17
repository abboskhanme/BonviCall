"""Reading a customer code out of a contact name — pure, no database.

Ported from BonviZvonki ``modules/clients/domain/contacts.py``. Every rule,
every regular expression and every measured number below is theirs; the
comments are translated (CONVENTIONS.md §14) and the reasoning is kept
verbatim, because each line of it was bought with a real file of real
contacts.

════════════════════════════════════════════════════════════════
 WHY THIS MODULE EXISTS
════════════════════════════════════════════════════════════════

The salespeople renamed the contacts in their own phones to ``"K00150 Elyor
aka"`` — one purpose: to tie a conversation to the customer CODE in the
accounting system. The upstream call provider never sees that name:

  · a contact is frozen with whatever name it had at the first
    synchronisation — a later rename on the handset never reaches it;
  · a re-import does not overwrite, it DUPLICATES. Measured: 90 contacts
    imported twice became 270, i.e. three records per number — one with the
    old name and two with the new.

So the name is not taken from the provider. The list is uploaded here
separately and a customer's identity is decided **by number**, in this file.

BonviCall inherits the same problem from a different direction:
``calls.contact_name`` is resolved on the handset from that one employee's own
contacts, so the same customer reads as ``"Anvar do'kon"`` on one salesperson's
calls and as nothing at all on another's. A central number→name dictionary is
the fix, and it is this module's output.

⚠️ THE MOST EXPENSIVE DETAIL IN THE PORT IS A LETTER. On the handsets the
codes are written with a LATIN ``K`` (U+004B); the accounting catalogue uses a
CYRILLIC ``К`` (U+041A). On screen the two are identical. Compared directly,
NOT ONE of 43 codes was found and the system sat there quietly reporting "no
match". Measured: after transliteration, 43 of 43 were found.

════════════════════════════════════════════════════════════════
 THE SEAM — THE PARTNER CATALOGUE IS NOT HERE YET
════════════════════════════════════════════════════════════════

In the source, three of the decisions below consult the SAP partner catalogue
(``src.modules.sales``): a code is only trusted once the catalogue confirms it,
a glued-on code is only accepted once the catalogue confirms it, and
:func:`suggest_kind` asks whether the number is in the catalogue at all.

**BonviCall has no ``sales`` module yet — it is being ported separately — and
nothing here reads a ``sales*`` table.** The confirmation set is therefore
threaded through as a parameter (``verified``/``known_in_catalogue``) which
today arrives empty from ``service.py``. Every rule that depends on it is
marked ``SALES SEAM`` below. When the partner catalogue lands, exactly those
call sites change and not one rule in this file does.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

#: A customer code is one CYRILLIC letter plus five digits. Measured: of the
#: 3,746 partners in the catalogue, 3,744 are exactly that shape (``К`` 3,286,
#: ``П`` 373, ``Й`` 85); the remaining 2 are older rows with no letter at all.
CODE_DIGITS = 5

#: The Cyrillic twin of a Latin letter. **Only letters whose SHAPE is
#: identical**: ``K`` -> ``К``. There is no Latin lookalike for ``П`` or ``Й``
#: (Latin ``P`` is Cyrillic ``Р``, i.e. a different letter), so those are not
#: transliterated. Adding a wrong pair would corrupt a real code.
LOOKALIKE: dict[str, str] = {"K": "К"}

#: The pattern a code is searched with. Nothing alphanumeric may precede the
#: letter — otherwise the ``k`` inside ``"Ilyosaka"`` would be read as the
#: start of a code.
#:
#: ⚠️ At least THREE digits are required. With ``\d{1,}`` a plain note like
#: ``"K 2 dona"`` would become a code; every real code carries five, and three
#: is the allowance for one typed short.
_CODE = re.compile(
    r"(?<![0-9A-Za-zА-Яа-яЁёЎўҚқҒғҲҳ])([KkКкЙйПп])[\s.\-_]?([0-9]{3,6})(?![0-9])"
)

#: A code written GLUED to a word: ``"Bobur Xatirchik02121"``. This pattern
#: ignores what precedes the letter and is therefore unreliable on its own —
#: ``"Blok 123"`` matches it too.
#:
#: ⚠️ SALES SEAM. It is accepted **only when confirmed** against the partner
#: catalogue. Used unconfirmed, a number inside an ordinary note becomes a
#: customer code and the conversation is attached to a stranger. Such a record
#: does exist in the real list, measured — dropping the pattern would lose a
#: genuine code.
_GLUED_CODE = re.compile(r"([KkКк])([0-9]{4,6})(?![0-9])")

#: Trimmed off the ends of the name once the code has been cut out of it.
_TRIM = " \t-–—_·,.:;|/\\"


class ContactKind(StrEnum):
    """Whose contact this is — a PERSON confirms it, the system only suggests.

    ⚠️ The field exists because an employee's phone holds everything mixed
    together: customers, colleagues, warehouses and PRIVATE acquaintances.
    Leaving them all in one list labelled "customer" does two kinds of damage —
    a private person's name leaks into company reports, and a conversation with
    a colleague gets scored as a sales conversation.

    **Stored as ``String(16)``, not as a PostgreSQL enum.** Adopted from the
    source with its reason: a new kind must not require an ``ALTER TYPE`` on a
    live database. CONVENTIONS.md §10 requires a native enum for the four
    vocabularies the *device* contract depends on; this is not one of them — it
    is panel-only, it never crosses the device or service surface, and the
    closed set is enforced where it is read, by this enum, in ``schemas.py``.
    """

    #: A real customer. The name and the code are used everywhere.
    CLIENT = "client"
    #: A colleague, a warehouse, an internal line. Not a customer.
    INTERNAL = "internal"
    #: A private acquaintance — neither customer nor colleague. The name is
    #: NEVER shown in a report.
    PERSONAL = "personal"
    #: Not decided yet. The name is used as a fallback; no code.
    UNKNOWN = "unknown"


#: The kinds that are allowed to give a customer a name and a code.
#:
#: ⚠️ ``personal`` and ``internal`` are EXCLUDED. A private acquaintance's name
#: must not surface in a report — they are not a customer and putting their
#: name in the company's numbers is wrong — and a colleague is not a customer
#: either. Both still appear on the contacts page itself: that page answers a
#: different question.
NAMING_KINDS: tuple[ContactKind, ...] = (ContactKind.CLIENT, ContactKind.UNKNOWN)


class ImportMode(StrEnum):
    """What to take OUT of the file.

    ⚠️ THIS CHOICE IS MANDATORY. What gets uploaded is a full export of an
    employee's phone, and it contains everything: customers, colleagues,
    family, friends, the taxi driver, the doctor. Measured — about 9,000
    contacts collected from 6-7 employees, of which only a small part are
    customers. Taking all of them does two kinds of damage: strangers' names
    end up stored in the company's database, and the customer list disappears
    among them.
    """

    #: Only the ones tied to the partner catalogue — a code was found, or the
    #: number is in the catalogue. The source's default: safe and precise.
    #:
    #: ⚠️ SALES SEAM. With no catalogue this currently means the same thing as
    #: ``CODED``, which is why :data:`DEFAULT_IMPORT_MODE` is ``CODED`` — a
    #: default that silently means something other than its name is worse than
    #: one that says what it does.
    KNOWN = "known"
    #: Only the ones with a code written in the name.
    CODED = "coded"
    #: Everything, private contacts included. Chosen deliberately.
    ALL = "all"


#: The mode an upload uses when the caller names none.
#:
#: The source defaults to ``KNOWN`` with a stated reason: if the default were
#: "everything", the very first upload would put strangers' names into the
#: database and getting them out again is hard. That reason is unchanged. The
#: VALUE changes only because ``KNOWN`` cannot yet mean what it says (see
#: above), and ``CODED`` is the narrower of the two — which is the direction
#: the source's argument points.
DEFAULT_IMPORT_MODE = ImportMode.CODED


@dataclass(frozen=True, slots=True)
class ParsedContact:
    """One contact row, analysed."""

    phone_key: str
    """The comparable part of the number — the last 9 digits (N37)."""
    code: str | None
    """The customer code, transliterated to Cyrillic. None — no code in the name."""
    name: str | None
    """The human name with the code cut out. None — the name was only a code."""
    raw_name: str
    """The name exactly as the phone had it — stored untouched, for checking."""
    phone: str | None
    """The number as the file wrote it, for display."""
    candidates: tuple[tuple[str, str | None], ...] = ()
    """Codes glued to a word: ``(code, cleaned name)``.

    ⚠️ SALES SEAM — accepted only if the partner catalogue confirms them; see
    ``_GLUED_CODE``. Empty is the ordinary case.
    """


def normalize_code(letter: str, digits: str) -> str:
    """Bring ``letter + digits`` into the catalogue's own shape.

    ⚠️ The digits are left-padded with zeros to five: ``K124`` -> ``К00124``.
    The code is exactly five wide, so that is the only sensible reading. A
    wrong guess does not stay hidden — it shows up in the upload preview as a
    code the catalogue does not know.

    A run LONGER than five is left ALONE: shortening it could manufacture some
    other customer's code.
    """
    head = LOOKALIKE.get(letter.upper(), letter.upper())
    body = digits.zfill(CODE_DIGITS) if len(digits) <= CODE_DIGITS else digits
    return f"{head}{body}"


def extract_code(name: str | None) -> tuple[str | None, str | None]:
    """Pull the code out of a name. Returns ``(code, name without the code)``.

    ⚠️ The code may be at the START of the name or at the END — both occur in
    the real list (``"K00150 Elyor aka"`` 34 times, ``"Ilyosaka K02404"`` 9
    times). Supporting only one of the two would have left a fifth of the list
    quietly without a code.

    Where a name holds SEVERAL codes the FIRST is taken: the second is usually
    a note (``"K00150 eski K00151"``) and there is no way to know which one is
    current — and choosing wrong attaches the conversation to the wrong
    customer.
    """
    text = " ".join((name or "").split())
    if not text:
        return None, None

    match = _CODE.search(text)
    if match is None:
        return None, text or None

    code = normalize_code(match.group(1), match.group(2))
    rest = (text[: match.start()] + " " + text[match.end() :]).strip(_TRIM)
    return code, " ".join(rest.split()) or None


def glued_candidates(name: str) -> tuple[tuple[str, str | None], ...]:
    """Codes glued to a word: ``(code, name with the code cut out)``.

    Only consulted when no clear code was found, and the result is unusable
    until the partner catalogue has confirmed it (SALES SEAM).
    """
    found: list[tuple[str, str | None]] = []
    for match in _GLUED_CODE.finditer(name):
        code = normalize_code(match.group(1), match.group(2))
        rest = (name[: match.start()] + " " + name[match.end() :]).strip(_TRIM)
        found.append((code, " ".join(rest.split()) or None))
    return tuple(found)


def resolve_code(
    contact: ParsedContact, verified: frozenset[str]
) -> tuple[str | None, str | None]:
    """A contact's FINAL code and name.

    A clear code wins. Otherwise a glued-on candidate is considered, and it is
    taken **only if the partner catalogue confirms it** (SALES SEAM — see
    ``_GLUED_CODE``; ``verified`` is empty until the ``sales`` module lands, so
    today this returns the clear code or nothing).
    """
    if contact.code is not None:
        return contact.code, contact.name
    for code, cleaned in contact.candidates:
        if code in verified:
            return code, cleaned
    return None, contact.name


def choose_contact(
    bucket: Sequence[ParsedContact], verified: frozenset[str]
) -> ParsedContact:
    """Pick ONE record for a number out of everything the file said about it.

    Order:

      1. **A record whose code the catalogue CONFIRMS.** The code is the whole
         point of the upload — but only a real code is.
      2. **The most frequently written name.** With no code to go on, whatever
         most of the employees called this number wins: six people's wording is
         more trustworthy than one person's.
      3. A tie is broken by the file's own order.

    ⚠️ THE WORD "CONFIRMS" IN RULE 1 IS THE WHOLE RULE. It used to be simply
    "a record with a code wins", and one real case exposed that:
    ``+998 95 173 07 00`` is a warehouse line, written in the file under seven
    different names (``"Asosiy Ombor Zakas"``, ``"Конт Офес"`` twice,
    ``"Rizoxon Rejalashtirish"`` …). One employee had written a WRONG code
    against it (``К028890`` — catalogue codes are 5 digits, this has 6), and
    that record won, turning the warehouse into a customer called "Аюбхон".

    ⚠️ SALES SEAM: ``verified`` is empty today, so rule 1 never fires and rule
    2 decides every number. That is the SAFE half of the pair — the failure
    above was caused by rule 1 firing on an unconfirmed code, which cannot
    happen while the set is empty.
    """
    pick = next((row for row in bucket if row.code in verified), None)
    if pick is not None:
        return pick
    names = Counter(row.raw_name for row in bucket)
    top = names.most_common(1)[0][0]
    return next(row for row in bucket if row.raw_name == top)


def suggest_kind(
    *, code: str | None, known_in_catalogue: bool, calls: int
) -> ContactKind:
    """SUGGEST what kind of contact this is — a proposal, never a decision.

    ⚠️ The guess is never applied on its own: it is shown in the upload preview
    and an admin confirms it. Applied automatically, both mistakes would be
    expensive — a real customer filed as "private" drops out of the reports,
    and a colleague gets scored as a sales conversation.

    The rules are simply ordered:
      · has a code and the catalogue knows it -> definitely a customer;
      · has a code the catalogue does NOT know -> undecided: the code may be
        mistyped, and calling it a customer would set the mistake in stone;
      · NO code, but the number is in the catalogue -> a customer anyway. The
        catalogue supplies the code; the employee simply never wrote it on the
        handset. Measured: 21 such contacts on one phone;
      · no code and no calls at all -> most likely a private acquaintance;
      · anything else -> undecided.

    ⚠️ SALES SEAM: ``known_in_catalogue`` is ``False`` for every contact until
    the ``sales`` module lands, so today the chain reduces to
    "code -> unknown, no code and no calls -> personal, otherwise unknown".
    Nothing is ever auto-classified ``client``, which is the conservative end
    of the rule and the one an admin has to opt into.
    """
    if code is not None:
        return ContactKind.CLIENT if known_in_catalogue else ContactKind.UNKNOWN
    if known_in_catalogue:
        return ContactKind.CLIENT
    if calls == 0:
        return ContactKind.PERSONAL
    return ContactKind.UNKNOWN


def selected_by(mode: ImportMode, *, code: str | None, in_catalogue: bool) -> bool:
    """Does this row fall inside the chosen mode?"""
    if mode is ImportMode.ALL:
        return True
    if mode is ImportMode.CODED:
        return code is not None
    return code is not None or in_catalogue


__all__ = [
    "CODE_DIGITS",
    "DEFAULT_IMPORT_MODE",
    "LOOKALIKE",
    "NAMING_KINDS",
    "ContactKind",
    "ImportMode",
    "ParsedContact",
    "choose_contact",
    "extract_code",
    "glued_candidates",
    "normalize_code",
    "resolve_code",
    "selected_by",
    "suggest_kind",
]
