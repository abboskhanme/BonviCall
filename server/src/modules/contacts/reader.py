"""Turning an uploaded contacts file into records — no database, no session.

Ported from BonviZvonki ``modules/clients/application/contacts.py`` (the
reading half: ``_decode``, ``_read_csv``, ``read_contacts_file``,
``_looks_like_header``, ``_header_columns``, ``_content_columns``,
``_pick_columns``, ``prepare_rows``, ``parse_contact``). Every measured number
in the comments is theirs.

It lives beside ``rules.py`` rather than inside it because it needs
``core.phone.phone_key``, and a ``rules.py`` imports nothing from the project
(CONVENTIONS.md §2, ``tests/test_layering.py::test_rules_modules_are_pure``).
Existing modules already carry files beyond the canonical three for the same
reason — ``audio/archive.py``, ``analysis/validator.py`` — so this is the house
shape rather than a new one.

════════════════════════════════════════════════════════════════
 CSV AND TSV ONLY — THE ``.xlsx`` PATH IS DELIBERATELY NOT PORTED
════════════════════════════════════════════════════════════════

The source also reads ``.xlsx`` through ``openpyxl``. That is one new runtime
dependency for a format the measured real exports do not use: a handset export
and a Google Contacts export are both CSV, and Excel's own
"CSV (comma delimited)" save is already handled here — including the ``cp1251``
encoding it writes on a Windows machine, which is the case the source's comment
actually measured. A workbook upload is refused with a message naming the
one-click fix rather than accepted and silently mis-read.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from src.core.errors import ErrorCode, ValidationError
from src.core.phone import phone_key
from src.modules.contacts.rules import ParsedContact, extract_code, glued_candidates

#: Header words to look for. The list is wide: the export may come from a
#: handset, from Google Contacts or from a spreadsheet somebody assembled by
#: hand, and each writes its headers differently.
NAME_HEADERS: tuple[str, ...] = (
    "name",
    "nom",
    "ism",
    "имя",
    "фио",
    "контакт",
    "contact",
    "display name",
    "first name",
    "mijoz",
    "клиент",
)
PHONE_HEADERS: tuple[str, ...] = (
    "phone",
    "telefon",
    "tel",
    "raqam",
    "номер",
    "телефон",
    "phone 1 - value",
    "mobile",
    "мобильный",
)

#: At most this many rows are read out of a file. The bound is not about
#: memory, it is about the WRONG FILE: if somebody uploads a 200,000-row export
#: of something else, an immediate, comprehensible error beats a server that
#: sits and thinks.
MAX_ROWS = 50_000

#: Sniffed against this much of the file. 4 KiB is several dozen rows of a
#: contacts export — enough for the delimiter to be unambiguous and small
#: enough that a 10 MB upload does not get scanned twice.
SNIFF_BYTES = 4096

#: How many digits a cell needs before the column-guesser will believe it is a
#: phone number. A row-number column is shorter than this, which is exactly why
#: the threshold exists.
PHONE_DIGITS_HINT = 7

#: Extensions this reader refuses, with the reason above.
WORKBOOK_SUFFIXES: tuple[str, ...] = (".xlsx", ".xlsm", ".xls", ".ods")


def _decode(payload: bytes) -> str:
    """Work out the text encoding.

    ⚠️ The ``cp1251`` fallback is MANDATORY. The contact list holds Cyrillic
    names ("Азиз Ака Метан") and Excel on Windows saves
    "CSV (разделители — запятые)" in exactly that encoding. Read as UTF-8 the
    file either fails to decode at all or the names turn to mojibake.
    """
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    # Every candidate refused it. Replacing the bad bytes keeps the numbers —
    # which are ASCII and are what the key is built from — readable, and the
    # damaged names are visible in the preview rather than hidden behind a 422.
    return payload.decode("utf-8", errors="replace")


def _rows_from_csv(payload: bytes) -> list[tuple[Any, ...]]:
    text = _decode(payload)
    sample = text[:SNIFF_BYTES]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        # A single-column file exists too, and then there is no delimiter to
        # find. Semicolon wins where it is commoner, which is the Excel case.
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [tuple(row) for row in reader if any(cell.strip() for cell in row)]


def read_contacts_file(payload: bytes, *, filename: str) -> list[tuple[Any, ...]]:
    """The uploaded bytes as rows. Raises :class:`ValidationError` on refusal."""
    if not payload:
        raise ValidationError(ErrorCode.VALIDATION_ERROR, detail={"field": "file"})
    if (filename or "").lower().endswith(WORKBOOK_SUFFIXES):
        raise ValidationError(
            ErrorCode.VALIDATION_ERROR,
            detail={"field": "file", "reason": "workbook_not_supported"},
        )
    rows = _rows_from_csv(payload)
    if not rows:
        raise ValidationError(
            ErrorCode.VALIDATION_ERROR, detail={"field": "file", "reason": "no_rows"}
        )
    if len(rows) > MAX_ROWS:
        raise ValidationError(
            ErrorCode.VALIDATION_ERROR,
            detail={"field": "file", "reason": "too_many_rows", "rows": len(rows)},
        )
    return rows


def _cells(row: Sequence[Any]) -> list[str]:
    return [" ".join(str(cell or "").split()).lower() for cell in row]


def looks_like_header(row: Sequence[Any]) -> bool:
    """Whether the first row names its columns rather than holding data."""
    return any(
        cell in NAME_HEADERS
        or cell in PHONE_HEADERS
        or any(cell.startswith(head) for head in PHONE_HEADERS)
        for cell in _cells(row)
    )


def header_columns(row: Sequence[Any]) -> tuple[int | None, list[int]]:
    """Choose the columns from the header names.

    ⚠️ THERE IS NOT ONE PHONE COLUMN. A real export arrives as ``Telefon 1``,
    ``Telefon 2``, ``Telefon 3`` and taking only the first silently loses the
    second number. Measured: in a 9,103-row file 70 rows carry a second number,
    and 5 of those are CODED customers — i.e. exactly the valuable ones.

    ⚠️ Exact match for the name column, prefix match for the phone columns.
    The other way round, a header reading "Nomer" would look like "nom" and the
    phone column would be read as the name.
    """
    cells = _cells(row)
    phones = [
        index
        for index, cell in enumerate(cells)
        if cell and any(cell == head or cell.startswith(head) for head in PHONE_HEADERS)
    ]
    name = next(
        (
            index
            for index, cell in enumerate(cells)
            if cell in NAME_HEADERS and index not in phones
        ),
        None,
    )
    return name, phones


def content_columns(
    rows: Sequence[Sequence[Any]], width: int
) -> tuple[int | None, list[int]]:
    """Find the columns by their CONTENT — when the header did not help.

    The phone column is the one whose values are mostly long digit runs, the
    name column the one with the most letters. Relying on the header alone
    means an unfamiliar export is silently read wrong.

    ⚠️ A row-number column is not mistaken for a phone: the threshold is
    :data:`PHONE_DIGITS_HINT` digits and a row number is shorter.
    """
    digit_score = [0] * width
    alpha_score = [0] * width
    for row in rows:
        for index in range(width):
            text = str(row[index] or "") if index < len(row) else ""
            if not text.strip():
                continue
            digits = sum(char.isdigit() for char in text)
            letters = sum(char.isalpha() for char in text)
            if digits >= PHONE_DIGITS_HINT and digits >= letters:
                digit_score[index] += 1
            if letters:
                alpha_score[index] += 1

    phones = [index for index in range(width) if digit_score[index] > 0]
    name = max(
        (index for index in range(width) if index not in phones),
        key=lambda index: alpha_score[index],
        default=None,
    )
    return name, phones


def pick_columns(rows: Sequence[Sequence[Any]]) -> tuple[int, list[int]]:
    """The name and phone columns: ``(name, [phone…])``.

    Header first, content second, and the two COMPLETE each other: where the
    header only identified the phone columns, the name is found by content.
    """
    if not rows:
        raise ValidationError(
            ErrorCode.VALIDATION_ERROR, detail={"field": "file", "reason": "no_rows"}
        )

    width = max(len(row) for row in rows)
    if width < 2:
        raise ValidationError(
            ErrorCode.VALIDATION_ERROR,
            detail={"field": "file", "reason": "two_columns_required"},
        )

    header = looks_like_header(rows[0])
    body = rows[1:] if header else rows
    if not body:
        body = rows

    name, phones = header_columns(rows[0]) if header else (None, [])
    if name is None or not phones:
        guess_name, guess_phones = content_columns(body, width)
        name = name if name is not None else guess_name
        phones = phones or guess_phones

    if not phones:
        raise ValidationError(
            ErrorCode.VALIDATION_ERROR,
            detail={"field": "file", "reason": "no_phone_column"},
        )
    if name is None:
        raise ValidationError(
            ErrorCode.VALIDATION_ERROR,
            detail={"field": "file", "reason": "no_name_column"},
        )
    return name, phones


def parse_contact(*, name: str | None, phone: str | None) -> ParsedContact | None:
    """Analyse one cell pair. ``None`` — the number cannot be a key.

    ⚠️ The key is built with ``core.phone.phone_key`` — the SAME function that
    generates ``calls.remote_number_key`` (CONVENTIONS.md §7). The source has
    its own copy of this rule in three places and its own comment about why
    that is dangerous; here there is one. A looser rule would produce contact
    keys that do not match call keys, which breaks the very bridge this file
    exists to build. Side benefit, and the source names it: foreign and junk
    numbers ("0000…", "999999999" — 9 digits but no call will ever carry it)
    are filtered at this line.
    """
    key = phone_key(phone)
    if key is None:
        return None

    raw = " ".join((name or "").split())
    code, human = extract_code(raw)
    return ParsedContact(
        phone_key=key,
        code=code,
        name=human,
        raw_name=raw,
        phone=" ".join((phone or "").split()) or None,
        candidates=() if code else glued_candidates(raw),
    )


@dataclass(slots=True)
class Prepared:
    """Everything the file said, grouped by number. No decision taken yet."""

    candidates: dict[str, list[ParsedContact]] = field(default_factory=dict)
    """Number -> EVERY record the file holds for it, in file order.

    ⚠️ One cannot be chosen here: the right choice depends on whether the code
    is in the partner catalogue, and this function never looks at a database.
    The choice is ``rules.choose_contact``.
    """
    read: int = 0
    """Rows with any content in them."""
    no_phone: int = 0
    """Rows with no number written at all.

    ⚠️ Counted SEPARATELY from "bad number", and the difference is large.
    Measured on a real export: of 9,103 rows, 7,316 have NO number (the export
    did not give one) and only 11 have a number that is unusable. Adding the
    two together would produce the false conclusion "7,327 bad rows" — the
    first is a shortcoming of the phone's export, the second is genuinely worth
    checking.
    """
    bad_phone: int = 0
    """A number is present but no key could be built (foreign, a service
    number like ``101``, a junk value)."""
    no_name: int = 0
    """A number but no name — such a row gives nothing: no code, no name."""
    duplicates: int = 0
    """Extra records beyond the first for a number already seen."""


def prepare_rows(rows: Sequence[Sequence[Any]]) -> Prepared:
    """Analyse the rows and group them by number.

    ⚠️ ONE ROW IS SEVERAL CONTACTS. In a handset export one person's two or
    three numbers sit in adjacent columns. Each number gets its own contact
    (the key is the number), but the name and code are shared.

    ⚠️ ONE NUMBER IS SEVERAL NAMES. This is ordinary: every employee names the
    company line their own way. Measured — in a 9,103-row file, 38 numbers
    carry more than two different names, of which 18 are the warehouse/office
    line ending ``*700``. One number appeared under seven names.

    So NO CHOICE IS MADE here — everything is kept, and the decision is taken
    in ``rules.choose_contact`` together with the catalogue check.
    """
    name_index, phone_indices = pick_columns(rows)
    body = rows[1:] if looks_like_header(rows[0]) else rows

    prepared = Prepared()
    for row in body:
        name = str(row[name_index] or "") if name_index < len(row) else ""
        numbers = [
            str(row[index] or "").strip()
            for index in phone_indices
            if index < len(row) and str(row[index] or "").strip()
        ]
        if not name.strip() and not numbers:
            continue
        prepared.read += 1

        if not numbers:
            prepared.no_phone += 1
            continue
        if not name.strip():
            # A nameless contact gives nothing: no code and no name. If the
            # number is in the partner catalogue it is found there anyway.
            prepared.no_name += 1
            continue

        for number in numbers:
            parsed = parse_contact(name=name, phone=number)
            if parsed is None:
                prepared.bad_phone += 1
                continue
            bucket = prepared.candidates.setdefault(parsed.phone_key, [])
            if bucket:
                prepared.duplicates += 1
            bucket.append(parsed)

    return prepared


__all__ = [
    "MAX_ROWS",
    "NAME_HEADERS",
    "PHONE_HEADERS",
    "WORKBOOK_SUFFIXES",
    "Prepared",
    "content_columns",
    "header_columns",
    "looks_like_header",
    "parse_contact",
    "pick_columns",
    "prepare_rows",
    "read_contacts_file",
]
