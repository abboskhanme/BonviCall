"""What the import WILL do, before it does it. Writes nothing.

Ported from BonviZvonki ``modules/sales/application/preview.py``.

WHY IT EXISTS. The file used to go straight into the database and the user saw
what had landed only AFTERWARDS. Two mistakes went through silently:

  · THE WRONG FILE — last week's export, or another department's — and the
    sales were already stored, with no way back;
  · A REPEAT UPLOAD — the report said "0 new", but seeing that required the
    import to have RUN.

The order is now: ``POST /sales/import/preview`` reads the file, ASKS the
database only, and says what would happen. When the user confirms, the SAME
file goes to ``POST /sales/import``.

⚠️ THERE MUST BE NO ``INSERT``, ``UPDATE`` OR ``commit`` IN THIS MODULE, and
the condition itself is a test: a row count taken before and after a preview
must be equal. That is also why ``SalesImportService._resolve_branches`` is not
reused here — it WRITES unmatched branches into ``sale_branches``.

⚠️ ONE QUERY PER KIND OF LOOKUP. Asking the database about each of a file's
2,383 operation numbers separately takes tens of seconds, and the estimate
would be slower than the import it is estimating.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.agents.models import AgentModel
from src.modules.sales.models import SaleBranchModel, SaleModel, SalePartnerModel
from src.modules.sales.reader import (
    SalesFileKind,
    SalesWorkbook,
    parse_balance,
    parse_catalog,
    parse_register,
    read_workbook,
)
from src.modules.sales.rules import (
    SAP_OP_TYPE_LABELS,
    SaleOpType,
    normalise_branch,
)

#: How many unknown codes are listed on the screen.
#
# The LIST is what is useful (a count cannot be acted on), but 500 codes would
# bury the dialog. The full number travels separately in
# ``unknown_partner_count`` so the text can say "20 of them are shown".
MAX_UNKNOWN_PARTNERS = 20

#: Rows with no group or branch are gathered under this label.
_NO_GROUP = "—"


@dataclass(frozen=True, slots=True)
class PreviewTypeRow:
    """One slice: the operation type (register), or the group/branch."""

    type: str
    label: str
    count: int
    amount_usd: float | None = None


@dataclass(frozen=True, slots=True)
class PreviewDayRow:
    """One day's slice — the register only."""

    day: date
    count: int
    amount_usd: float | None = None


@dataclass(slots=True)
class SalesPreview:
    """The estimate shown before confirmation.

    The numbers answer SEPARATE questions and are not added up: ``rows`` counts
    meaningful rows in the FILE, while ``new_rows``/``existing_rows`` count
    DISTINCT KEYS against the database. The two need not be equal, and that is
    normal — a key repeats inside a file (measured: 2,383 distinct operation
    numbers in 2,384 rows).
    """

    kind: str
    filename: str
    rows: int = 0

    date_from: date | None = None
    date_to: date | None = None

    by_type: list[PreviewTypeRow] = field(default_factory=list)
    by_day: list[PreviewDayRow] = field(default_factory=list)

    new_rows: int = 0
    """Keys NOT in the database (``external_id`` for a register, ``code`` else)."""

    existing_rows: int = 0
    """Keys already there — they are overwritten, no duplicate appears."""

    unknown_partners: list[str] = field(default_factory=list)
    unknown_partner_count: int = 0

    unmatched_branches: list[str] = field(default_factory=list)
    """Branches linked to no employee, BY NAME.

    ⚠️ Nothing is written here (this is the difference from the import): a
    branch only reaches ``sale_branches`` during the real import."""

    without_phone: int = 0
    """Rows from which no usable number could be taken — outside sales control."""

    warnings: list[str] = field(default_factory=list)
    """Machine-readable warnings, ``{"code": …, "count": …}``-shaped.

    ⚠️ CODES, NOT SENTENCES. BonviZvonki formats a whole Uzbek sentence here
    ("{n} rows had no date — they will not be stored"), which is the right
    thing to show and the wrong place to keep it: the panel owns user-facing
    copy and Uzbek in a ``.py`` file is legal in three files (CONVENTIONS.md
    §14). A code plus its count carries the same information and can be
    translated once.
    """


#: Every warning this module can emit. Named so the panel has a closed set to
#: translate and a reviewer can see the whole vocabulary in one place.
class PreviewWarning:
    NO_DATE = "rows_without_date"
    """Will not be stored — ``occurred_on`` is NOT NULL."""
    NO_CODE = "rows_without_partner_code"
    """Will not be stored — the rules need a customer."""
    NO_AMOUNT = "rows_without_amount"
    """Stored; the amount simply could not be read."""
    DUPLICATE_KEY = "duplicate_keys_in_file"
    """The last occurrence of each is what gets written."""
    UNKNOWN_OP_TYPE = "unknown_operation_types"
    """Stored as ``other`` and taking part in no rule."""
    WITHOUT_PHONE = "contractors_without_usable_phone"
    """No number, or a foreign or fabricated one — outside sales control."""
    INACTIVE = "inactive_contractors"
    """Not written as active; existing rows are marked inactive, never deleted."""
    CODE_NOT_IN_CATALOGUE = "codes_absent_from_catalogue"
    """The balance report creates no contractor, so these rows are ignored."""


class SalesPreviewService:
    """Reads a file and reports what the import would do. **Read-only.**"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build(self, source: Any, *, filename: str = "") -> SalesPreview:
        """Read the file and work out what would happen. WRITES NOTHING.

        The kind is decided from the HEADER, exactly as the import decides it,
        so the kind shown in the estimate is the kind that gets written. An
        unrecognised file raises 422 here, and the user can never carry a wrong
        file as far as the confirmation step.
        """
        book = read_workbook(source, filename=filename)
        if book.kind is SalesFileKind.REGISTER:
            return await self._register(book, filename)
        if book.kind is SalesFileKind.CATALOG:
            return await self._catalog(book, filename)
        return await self._balance(book, filename)

    # ── Register ──────────────────────────────────────────────

    async def _register(self, book: SalesWorkbook, filename: str) -> SalesPreview:
        rows = parse_register(book)
        preview = SalesPreview(
            kind=book.kind.value, filename=filename or "register", rows=len(rows)
        )

        type_count: Counter[SaleOpType] = Counter()
        type_sum: defaultdict[SaleOpType, Decimal] = defaultdict(Decimal)
        day_count: Counter[date] = Counter()
        day_sum: defaultdict[date, Decimal] = defaultdict(Decimal)

        no_date = no_amount = no_code = 0
        for row in rows:
            type_count[row.op_type] += 1
            if row.amount_usd is None:
                no_amount += 1
            else:
                type_sum[row.op_type] += row.amount_usd

            if row.occurred_on is None:
                no_date += 1
            else:
                day_count[row.occurred_on] += 1
                if row.amount_usd is not None:
                    day_sum[row.occurred_on] += row.amount_usd

            if not row.partner_code:
                no_code += 1

        if day_count:
            preview.date_from = min(day_count)
            preview.date_to = max(day_count)

        # Types by COUNT: `Продажа` has to be on the first line — the whole
        # meaning of the estimate is in that number.
        preview.by_type = [
            PreviewTypeRow(
                type=op_type.value,
                label=SAP_OP_TYPE_LABELS.get(op_type, op_type.value),
                count=count,
                amount_usd=_money(type_sum.get(op_type)),
            )
            for op_type, count in sorted(
                type_count.items(), key=lambda pair: (-pair[1], pair[0])
            )
        ]
        # Days by TIME: it is read as a chart.
        preview.by_day = [
            PreviewDayRow(
                day=day, count=day_count[day], amount_usd=_money(day_sum.get(day))
            )
            for day in sorted(day_count)
        ]

        ids = {row.external_id for row in rows}
        known_ids = await self._existing(SaleModel.external_id, ids)
        preview.existing_rows = len(known_ids)
        preview.new_rows = len(ids) - len(known_ids)

        codes = {row.partner_code for row in rows if row.partner_code}
        phones = await self._partner_phones(codes)
        unknown = sorted(codes - phones.keys())
        preview.unknown_partner_count = len(unknown)
        preview.unknown_partners = unknown[:MAX_UNKNOWN_PARTNERS]
        preview.without_phone = sum(
            1 for row in rows if phones.get(row.partner_code or "") is None
        )

        branches = await self._match_branches({r.branch for r in rows if r.branch})
        preview.unmatched_branches = sorted(
            name for name, agent_id in branches.items() if agent_id is None
        )

        preview.warnings = _warnings(
            (no_date, PreviewWarning.NO_DATE),
            (no_code, PreviewWarning.NO_CODE),
            (no_amount, PreviewWarning.NO_AMOUNT),
            (len(rows) - len(ids), PreviewWarning.DUPLICATE_KEY),
            (type_count.get(SaleOpType.OTHER, 0), PreviewWarning.UNKNOWN_OP_TYPE),
        )
        return preview

    # ── Catalogue ─────────────────────────────────────────────

    async def _catalog(self, book: SalesWorkbook, filename: str) -> SalesPreview:
        """The contractor catalogue.

        No dates and no money, so ``by_day`` is empty and ``by_type`` shows the
        GROUP slice (``Клиенты``, ``Поставщики импорт``…). Control applies to
        ``Клиенты`` only, which makes that the most meaningful number here.
        """
        rows = parse_catalog(book)
        preview = SalesPreview(
            kind=book.kind.value, filename=filename or "catalogue", rows=len(rows)
        )

        preview.by_type = _label_rows(
            Counter(row.group_name or _NO_GROUP for row in rows)
        )

        codes = {row.code for row in rows}
        known = await self._existing(SalePartnerModel.code, codes)
        preview.existing_rows = len(known)
        preview.new_rows = len(codes) - len(known)

        preview.without_phone = sum(1 for row in rows if row.matchable_phone is None)
        inactive = sum(1 for row in rows if not row.is_active)

        preview.warnings = _warnings(
            (len(rows) - len(codes), PreviewWarning.DUPLICATE_KEY),
            (preview.without_phone, PreviewWarning.WITHOUT_PHONE),
            (inactive, PreviewWarning.INACTIVE),
        )
        return preview

    # ── Balance report ────────────────────────────────────────

    async def _balance(self, book: SalesWorkbook, filename: str) -> SalesPreview:
        """The balance report — only a MISSING phone number is taken from it.

        ⚠️ ``new_rows`` here does NOT mean "new contractors will be added": no
        contractor is ever created from this file (it has no ``Код группы``).
        Rows whose code is not in the database are simply ignored, and the
        warning says exactly that.
        """
        rows = parse_balance(book)
        preview = SalesPreview(
            kind=book.kind.value, filename=filename or "balance report", rows=len(rows)
        )

        # ``Kod`` is NOT unique in this file (a row is customer x branch x
        # product line), so the slice is taken by BRANCH — that one really does
        # divide the rows.
        preview.by_type = _label_rows(
            Counter(row.branch or _NO_GROUP for row in rows)
        )

        codes = {row.code for row in rows}
        known = await self._existing(SalePartnerModel.code, codes)
        preview.existing_rows = len(known)
        preview.new_rows = len(codes) - len(known)

        unknown = sorted(codes - known)
        preview.unknown_partner_count = len(unknown)
        preview.unknown_partners = unknown[:MAX_UNKNOWN_PARTNERS]
        preview.without_phone = sum(1 for row in rows if row.matchable_phone is None)

        preview.warnings = _warnings(
            (len(unknown), PreviewWarning.CODE_NOT_IN_CATALOGUE),
            (preview.without_phone, PreviewWarning.WITHOUT_PHONE),
        )
        return preview

    # ── Database questions — READS ONLY ───────────────────────

    async def _existing(self, column: Any, keys: set[str]) -> set[str]:
        """Which of the file's keys already exist. ⚠️ ONE ``SELECT``."""
        if not keys:
            return set()
        return set(await self.session.scalars(select(column).where(column.in_(keys))))

    async def _partner_phones(self, codes: set[str]) -> dict[str, str | None]:
        """``code -> phone_key`` for the codes in this file only.

        Not the whole catalogue: the estimate has to feel instant, and unlike
        the import, waiting here looks unexplained.
        """
        if not codes:
            return {}
        result = await self.session.execute(
            select(SalePartnerModel.code, SalePartnerModel.phone_key).where(
                SalePartnerModel.code.in_(codes)
            )
        )
        return {code: key for code, key in result.all()}

    async def _match_branches(
        self, names: set[str]
    ) -> dict[str, uuid.UUID | None]:
        """Branch -> employee, WITHOUT writing anything.

        The same rule as ``SalesImportService._resolve_branches`` (an existing
        decision first, then the normalised name), minus its third step —
        adding an unmatched branch to the table. Otherwise the promise "nothing
        is written" would be broken: a user who cancels would still have left
        new rows in ``sale_branches``.
        """
        if not names:
            return {}

        existing = {
            branch: agent_id
            for branch, agent_id in (
                await self.session.execute(
                    select(SaleBranchModel.branch, SaleBranchModel.agent_id).where(
                        SaleBranchModel.branch.in_(sorted(names))
                    )
                )
            ).all()
        }

        agents = (
            await self.session.execute(
                select(AgentModel.id, AgentModel.full_name).where(
                    AgentModel.archived_at.is_(None)
                )
            )
        ).all()
        by_name: dict[str, uuid.UUID | None] = {}
        for agent_id, full_name in agents:
            key = normalise_branch(full_name)
            by_name[key] = None if key in by_name else agent_id

        return {
            name: existing[name]
            if name in existing
            else by_name.get(normalise_branch(name))
            for name in names
        }


# ══════════════════════════════════════════════════════════════
#  Small helpers
# ══════════════════════════════════════════════════════════════


def _money(value: Decimal | None) -> float | None:
    """An amount for JSON. Zero IS a number — not ``null``.

    ⚠️ ``None`` and ``0`` mean different things here: the first is "there is no
    amount at all" (payment rows), the second is "the amount is zero". They
    render differently.
    """
    return None if value is None else round(float(value), 2)


def _label_rows(counts: Counter[str]) -> list[PreviewTypeRow]:
    """A named slice (group, branch) in the ``by_type`` shape."""
    return [
        PreviewTypeRow(type=name, label=name, count=count)
        for name, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def _warnings(*items: tuple[int, str]) -> list[dict[str, object]]:
    """A warning whose count is ZERO IS NOT EMITTED.

    "0 rows had no date" is not information, and it would hide a real warning
    from the reader.
    """
    return [{"code": code, "count": count} for count, code in items if count > 0]


__all__ = [
    "MAX_UNKNOWN_PARTNERS",
    "PreviewDayRow",
    "PreviewTypeRow",
    "PreviewWarning",
    "SalesPreview",
    "SalesPreviewService",
]
