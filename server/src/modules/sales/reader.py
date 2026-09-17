"""Reading the SAP Excel exports. **Writes nothing** — it cleans and returns.

Ported from BonviZvonki ``modules/sales/application/reader.py``.

Three different files arrive and they LOOK IDENTICAL (``.xlsx``, one sheet,
``Sheet1``). Only the HEADER ROW tells them apart, so the kind is decided on
that and never on the file name — users name the file differently every time
("Workbook3.xlsx", "wb1.xlsx", "savdo kunlik.xlsx").

⚠️ THIS MODULE CONTAINS THREE TRAPS and all three were measured on real data:

  1. MONEY ARRIVES IN TWO GENERATIONS and they share one column — in the OLD
     export the figure is text (``"1 950,000"``), in the NEW one a plain number
     (``1230.0``). Only the CELL FORMAT tells them apart (see
     ``rules.parse_amount`` and ``rules.LegacyThousands``).
  2. DATES ARE TEXT: ``dd.mm.yyyy``, with no time.
  3. PHONE NUMBERS COME IN TEN FORMATS, and sometimes are not phone numbers at
     all (``@EadTrader``).

════════════════════════════════════════════════════════════════
 WHY openpyxl
════════════════════════════════════════════════════════════════

``openpyxl==3.1.5`` (newest stable; the project pins exact versions). It is not
merely the popular choice — it is the only one that can read this file
correctly. Trap 1 is detectable ONLY through ``cell.number_format``, and the
faster readers (``python-calamine``, ``xlsx2csv``) hand back values with the
formats discarded. With them, every amount in the old export would be a
thousand times too large, silently: 146 $ where the document says 146,000 $.
``pandas`` would bring a numeric stack this server has no other use for.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from openpyxl import load_workbook

from src.core.errors import AppError, ErrorCode
from src.modules.sales.rules import (
    LEGACY_THOUSANDS_FORMAT,
    LegacyThousands,
    SaleOpType,
    clean_text,
    matchable_phone,
    op_type_from_sap,
    parse_amount,
    parse_date,
)


class SalesFileError(AppError):
    """422 — the upload is not one of the exports we know.

    ⚠️ THE EXPLANATION TRAVELS IN ``detail``, NOT IN THE MESSAGE. BonviZvonki
    writes a whole Uzbek sentence into the exception — "this is the contractor
    catalogue, not the sales register; upload it in the right place" — which is
    genuinely the right thing to tell the user and the wrong place to keep it:
    Uzbek text inside a ``.py`` file is legal in exactly three files here
    (CONVENTIONS.md §14). So the code stays ``validation_error``, the Uzbek
    comes from ``core/messages_uz.py``, and ``detail.reason`` names the failure
    so the panel can render the sentence that actually helps:

      ``unreadable_file``      — not an ``.xlsx``, or corrupt;
      ``unrecognised_export``  — no header we know;
      ``column_missing``       — the export's shape changed (``detail.column``);
      ``wrong_export_kind``    — a real export, in the wrong place
                                 (``detail.found`` / ``detail.expected``).
    """

    status_code = 422
    code = ErrorCode.VALIDATION_ERROR


class SalesFileKind(StrEnum):
    """The export kinds this server accepts."""

    REGISTER = "register"
    """`savdo kunlik.xlsx` — the operations register."""

    CATALOG = "catalog"
    """`Workbook3.xlsx` — the contractor catalogue."""

    BALANCE = "balance"
    """`Workbook1/2.xlsx` — the customer balance report."""


#: The header columns that identify a kind. ALL of them must be present.
#
# Deliberately few: a SAP export may gain a column over time and the import
# must not fall over when it does.
_SIGNATURES: dict[SalesFileKind, tuple[str, ...]] = {
    SalesFileKind.REGISTER: ("тип", "номер операции", "дата регистрации"),
    SalesFileKind.CATALOG: ("код бп", "название бп", "код группы"),
    SalesFileKind.BALANCE: ("kod", "klient nomi", "tel raqami"),
}

#: How many leading rows are searched for the header.
#
# In practice it is always row 1, but SAP can prepend a title block (report
# name, period) — the file must still be recognised when it does.
_HEADER_SCAN_ROWS = 5


@dataclass(frozen=True, slots=True)
class SalesWorkbook:
    """A sheet that has been read: its kind, its normalised header, its rows."""

    kind: SalesFileKind
    header: list[str]
    rows: list[tuple[Any, ...]]


def _normalise_header(value: Any) -> str:
    return " ".join(str(value or "").split()).lower()


def _cell_value(cell: Any) -> Any:
    """The cell's value, carrying the OLD-GENERATION marker where it applies.

    :class:`~src.modules.sales.rules.LegacyThousands` is applied only when both
    hold: the cell format is ``#,##0`` AND the value is a whole number.
    Everything else comes back as itself — text, a ``General`` number, a date.

    ⚠️ ``type(...) is`` IS DELIBERATE, not ``isinstance``: ``bool`` is a child
    of ``int`` and ``True`` must not be marked as money. The format is asked for
    only on numeric cells — ``number_format`` consults the style table on every
    call and asking per cell slows the file down noticeably.
    """
    value = cell.value
    if type(value) is int or (type(value) is float and value.is_integer()):
        if cell.number_format == LEGACY_THOUSANDS_FORMAT:
            return LegacyThousands(value)
    return value


def _match_kind(header: Sequence[str]) -> SalesFileKind | None:
    present = set(header)
    for kind, needed in _SIGNATURES.items():
        if all(name in present for name in needed):
            return kind
    return None


def read_workbook(source: Any, *, filename: str = "") -> SalesWorkbook:
    """Read the file and decide its kind FROM THE HEADER.

    ``source`` is a path, bytes or a file object.

    ⚠️ ``read_only=True`` — turning a 3746-row catalogue into a full object
    tree costs hundreds of megabytes. ``data_only=True`` — we want the computed
    values, not the formulas.

    ⚠️ ROWS ARE READ AS CELL OBJECTS (no ``values_only``). One reason only:
    which generation an amount belongs to can be answered by
    ``cell.number_format`` and by nothing else, and that does not travel beside
    the value. The cell objects are NOT kept — :func:`_cell_value` returns a
    plain value immediately, so ``read_only``'s memory win survives. Measured on
    a 12,591-row file: 0.56 s -> 0.65 s.
    """
    try:
        workbook = load_workbook(source, read_only=True, data_only=True)
    except Exception as exc:  # the library raises a different class per corruption
        raise SalesFileError(
            detail={"reason": "unreadable_file", "filename": filename or None}
        ) from exc

    try:
        sheet = workbook[workbook.sheetnames[0]]
        kind: SalesFileKind | None = None
        header: list[str] = []
        rows: list[tuple[Any, ...]] = []
        scanned = 0

        for raw in sheet.iter_rows():
            if kind is None:
                # Rows BEFORE the header (a report title, a period) are not
                # data and are collected nowhere.
                if scanned >= _HEADER_SCAN_ROWS:
                    break
                scanned += 1
                candidate = [_normalise_header(cell.value) for cell in raw]
                kind = _match_kind(candidate)
                if kind is not None:
                    header = candidate
                continue
            values = tuple(_cell_value(cell) for cell in raw)
            if any(value is not None for value in values):
                rows.append(values)

        if kind is None:
            raise SalesFileError(
                detail={
                    "reason": "unrecognised_export",
                    "filename": filename or None,
                    # What the panel tells the user to look for. The header
                    # names are SAP's, so they are data and travel as data.
                    "expected_headers": ["Номер операции", "Код БП", "Kod"],
                }
            )
        return SalesWorkbook(kind=kind, header=header, rows=rows)
    finally:
        workbook.close()


def _column(header: Sequence[str], *needles: str) -> int:
    """The index of a column, found in the header.

    ⚠️ EXACT EQUALITY FIRST, THEN A SUBSTRING. The catalogue has ``Актив`` and
    ``Неактив`` side by side: a substring search finds ``актив`` inside
    ``неактив`` and marks an active customer inactive.

    The substring pass is mandatory elsewhere: ``Хақдор ($)`` and
    ``Хақдор (cўм)`` — the ``с`` in the second is a LATIN letter in the real
    export — so looking the column up by its full name would be brittle.
    """
    if len(needles) == 1:
        for index, name in enumerate(header):
            if name == needles[0]:
                return index
    for index, name in enumerate(header):
        if all(needle in name for needle in needles):
            return index
    raise SalesFileError(
        detail={"reason": "column_missing", "column": " + ".join(needles)}
    )


def _cell(row: Sequence[Any], index: int) -> Any:
    return row[index] if index < len(row) else None


# ══════════════════════════════════════════════════════════════
#  The register — `savdo kunlik.xlsx`
# ══════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class RegisterRow:
    """One operation, cleaned."""

    external_id: str
    doc_number: str | None
    op_type: SaleOpType
    op_type_raw: str | None
    occurred_on: date | None
    branch: str | None
    direction: str | None
    partner_code: str | None
    partner_name: str | None
    amount: Decimal | None
    amount_usd: Decimal | None
    currency: str


def parse_register(book: SalesWorkbook) -> list[RegisterRow]:
    """The register sheet as :class:`RegisterRow` values."""
    head = book.header
    col_type = _column(head, "тип")
    col_op = _column(head, "номер операции")
    col_branch = _column(head, "подразделение")
    col_direction = _column(head, "направление")
    col_doc = _column(head, "док")
    col_date = _column(head, "дата регистрации")
    col_code = _column(head, "код заказчика")
    col_name = _column(head, "название заказчика")
    # ⚠️ `Хақдор` is what is owed TO the company (a sale, an outgoing payment),
    # `Қарздор` what is claimed FROM it (an incoming payment, a purchase). Only
    # ONE side is filled on any row.
    col_credit_usd = _column(head, "хақдор", "$")
    col_credit_native = _column(head, "хақдор", "ў")
    col_debit_usd = _column(head, "қарздор", "$")
    col_debit_native = _column(head, "қарздор", "ў")
    col_currency = _column(head, "валюта")

    result: list[RegisterRow] = []
    for row in book.rows:
        external_id = clean_text(_cell(row, col_op), limit=32)
        if not external_id:
            continue

        credit_usd = parse_amount(_cell(row, col_credit_usd))
        credit_native = parse_amount(_cell(row, col_credit_native))
        debit_usd = parse_amount(_cell(row, col_debit_usd))
        debit_native = parse_amount(_cell(row, col_debit_native))

        # Whichever side is filled is the one taken. When both are zero (it
        # happens on `Бух.оп`) `Хақдор` wins: a zero-amount row must still be
        # stored.
        if credit_usd or credit_native:
            usd, native = credit_usd, credit_native
        elif debit_usd or debit_native:
            usd, native = debit_usd, debit_native
        else:
            usd, native = credit_usd, credit_native

        currency = clean_text(_cell(row, col_currency), limit=8) or "USD"
        # ⚠️ The `(cўм)` column is really THE DOCUMENT'S OWN CURRENCY: so'm on a
        # UZS document, yuan on CNY, dirham on AED. On a dollar document it is
        # zero, and then the `($)` column is the document amount.
        amount = native if currency.upper() != "USD" and native else usd

        op_raw = clean_text(_cell(row, col_type))
        result.append(
            RegisterRow(
                external_id=external_id,
                doc_number=clean_text(_cell(row, col_doc), limit=32),
                op_type=op_type_from_sap(op_raw),
                op_type_raw=op_raw,
                occurred_on=parse_date(_cell(row, col_date)),
                branch=clean_text(_cell(row, col_branch), limit=128),
                direction=clean_text(_cell(row, col_direction), limit=64),
                partner_code=clean_text(_cell(row, col_code), limit=16),
                partner_name=clean_text(_cell(row, col_name), limit=255),
                amount=amount,
                amount_usd=usd,
                currency=currency.upper(),
            )
        )
    return result


# ══════════════════════════════════════════════════════════════
#  The catalogue — `Workbook3.xlsx`
# ══════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class CatalogRow:
    """One contractor."""

    code: str
    name: str
    group_name: str | None
    branch: str | None
    phone: str | None
    matchable_phone: str | None
    is_active: bool
    telegram_link: str | None


#: The values of `Актив` that mean "yes".
_YES = frozenset({"да", "yes", "ha", "true", "1", "+"})


def parse_catalog(book: SalesWorkbook) -> list[CatalogRow]:
    """The catalogue sheet as :class:`CatalogRow` values."""
    head = book.header
    col_name = _column(head, "название бп")
    col_code = _column(head, "код бп")
    col_group = _column(head, "код группы")
    col_phone = _column(head, "тел")
    col_branch = _column(head, "подразделение")
    col_active = _column(head, "актив")
    col_link = _column(head, "линк")

    result: list[CatalogRow] = []
    for row in book.rows:
        code = clean_text(_cell(row, col_code), limit=16)
        if not code:
            continue
        phone = clean_text(_cell(row, col_phone), limit=64)
        active = clean_text(_cell(row, col_active))
        result.append(
            CatalogRow(
                code=code,
                name=clean_text(_cell(row, col_name), limit=255) or code,
                group_name=clean_text(_cell(row, col_group), limit=64),
                branch=clean_text(_cell(row, col_branch), limit=128),
                phone=phone,
                matchable_phone=matchable_phone(phone),
                is_active=(active or "").lower() in _YES,
                telegram_link=clean_text(_cell(row, col_link), limit=255),
            )
        )
    return result


# ══════════════════════════════════════════════════════════════
#  The balance report — `Workbook1/2.xlsx`
# ══════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class BalanceRow:
    """One row of the balance report.

    ⚠️ ``Kod`` IS NOT UNIQUE here: a row is customer x branch x product line.
    That is why no contractor is ever CREATED from this file — only a missing
    phone number is taken from it.
    """

    code: str
    name: str | None
    branch: str | None
    phone: str | None
    matchable_phone: str | None


def parse_balance(book: SalesWorkbook) -> list[BalanceRow]:
    """The balance sheet as :class:`BalanceRow` values."""
    head = book.header
    col_code = _column(head, "kod")
    col_name = _column(head, "klient nomi")
    col_branch = _column(head, "bo'lim")
    col_phone = _column(head, "tel raqami")

    result: list[BalanceRow] = []
    for row in book.rows:
        code = clean_text(_cell(row, col_code), limit=16)
        if not code:
            continue
        phone = clean_text(_cell(row, col_phone), limit=64)
        result.append(
            BalanceRow(
                code=code,
                name=clean_text(_cell(row, col_name), limit=255),
                branch=clean_text(_cell(row, col_branch), limit=128),
                phone=phone,
                matchable_phone=matchable_phone(phone),
            )
        )
    return result


__all__ = [
    "BalanceRow",
    "CatalogRow",
    "RegisterRow",
    "SalesFileError",
    "SalesFileKind",
    "SalesWorkbook",
    "parse_balance",
    "parse_catalog",
    "parse_register",
    "read_workbook",
]
