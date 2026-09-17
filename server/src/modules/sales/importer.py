"""Writing the SAP exports into the database.

Ported from BonviZvonki ``modules/sales/application/importer.py``.

Three entry points:
  · :meth:`SalesImportService.import_file` — works the kind out and dispatches
    (this is what ``POST /sales/import`` calls);
  · the register  -> ``sales``;
  · the catalogue or the balance report -> ``sale_partners``.

IDEMPOTENCY IS THE HEADLINE REQUIREMENT. Uploading one file twice — or daily
exports that overlap each other — is COMPLETELY normal. Everything therefore
goes through ``ON CONFLICT DO UPDATE``, on ``sales.external_id`` and on
``sale_partners.code``.

⚠️ THE NO-LOSS RULE. An upsert NEVER replaces a filled field with an empty one
(``coalesce``). The reason is practical: the files arrive with different
completeness — the balance report has a phone the catalogue lacks; the
catalogue is old and the register is new. A plain "overwrite" rule loses
something on every import and nobody notices.

════════════════════════════════════════════════════════════════
 WHAT CHANGED AGAINST BONVIZVONKI
════════════════════════════════════════════════════════════════

**Nothing is deleted.** Theirs DELETES every contractor SAP marks inactive,
plus every ``is_active = false`` row left over from before, with the reasoning
that inactive rows are a third of the catalogue (1,239 of 3,746) and answer no
question. Two things are wrong with deleting them here. ``sale_partners``
carries ``excluded_at`` — a HUMAN's decision to take a customer out of sales
control — and deleting the row destroys that decision silently, so a customer
who goes inactive and later comes back returns to the control list with nobody
having decided it. And this repo's own rule is that a state change is a
timestamp, never a deletion (``agents.archived_at``, ``installations.revoked_at``).
So an inactive contractor is MARKED inactive: every read of the catalogue
already filters on ``is_active`` (:func:`service.partner_phones`), which is
what their deletion was actually buying.

**``sales`` no longer carries a copy of the phone key**, so the half of
``backfill_sale_links`` that restored it is gone with it, and with it the whole
class of "the register was imported before the catalogue, so a day of sales is
invisible to the rules" defect. ``models.py`` has the argument.

**The catalogue writes ``matchable_phone``; the database derives the key.**
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.agents.models import AgentModel
from src.modules.sales.models import SaleBranchModel, SaleModel, SalePartnerModel
from src.modules.sales.reader import (
    CatalogRow,
    SalesFileError,
    SalesFileKind,
    SalesWorkbook,
    parse_balance,
    parse_catalog,
    parse_register,
    read_workbook,
)
from src.modules.sales.rules import SaleOpType, normalise_branch
from src.modules.sales.service import SalesScope, refresh_sale_attribution

#: How many rows fit in one ``INSERT``.
#
# ⚠️ THE LIMIT IS THE DATABASE'S: the PostgreSQL protocol allows 32,767
# parameters in one statement. ``sales`` has 14 written columns, so a 2,384-row
# daily export sent as one statement is 33,376 parameters and the import falls
# over with "too many arguments". The catalogue (3,746 x 9) is close to the
# line too. 500 rows leaves a safe margin for any table here.
_CHUNK = 500


@dataclass(slots=True)
class ImportReport:
    """What the import did — shown to the user.

    Every number answers a SEPARATE question, so they are not added together
    and never substitute for one another.
    """

    kind: SalesFileKind
    source: str

    read: int = 0
    """Meaningful rows read from the file."""

    created: int = 0
    updated: int = 0

    skipped: int = 0
    """Rows that could not be written: no customer code, or no date.

    NOT counted as an error — but a number above zero means the export has a
    defect and the user has to see it."""

    unknown_partner: int = 0
    """Rows whose code is absent from the catalogue.

    ⚠️ The sale is STORED anyway; it simply has no catalogue row behind it, so
    the rules cannot check it. The remedy is to upload the catalogue."""

    unknown_op_type: int = 0
    """A `Тип` SAP has and we do not. Stored with ``op_type = other``."""

    # ⚠️ THERE IS NO COUNTER FOR INTERNAL CONTRACTORS, and there must not be.
    # Their earlier version skipped those rows on import and PURGED the ones
    # already stored. The manager refused it — "do not delete them, give them
    # their own section". The import now removes nothing and passes nobody
    # over; an internal contractor is taken out of control through
    # ``sale_partners.excluded_at`` and its sales stay visible in the
    # "out of scope" section.

    inactive_skipped: int = 0
    """Contractors the file marks `Неактив` — not written as active.

    SAP exports active and inactive contractors in one list and the inactive
    ones are a third of it (measured: 1,239 of 3,746). They answer none of this
    system's questions, but they would double the catalogue and give the wrong
    answer to "how many customers do we have in SAP?"."""

    inactive_deactivated: int = 0
    """Rows already in the catalogue that this file marks inactive.

    Marked, never deleted — see the module docstring."""

    phones_filled: int = 0
    """Phone numbers taken from the balance report that the catalogue lacked."""

    linked_sales: int = 0
    """Sales whose branch link was restored after the map changed."""

    attributed_sales: int = 0
    """Sales whose attributed conversation changed as a result of this import."""

    unmatched_branches: list[str] = field(default_factory=list)
    """Branches linked to no employee — the manager has to do these by hand.

    The list comes back as NAMES rather than a count, deliberately: nothing can
    be done with "7 branches were not linked", while "Логистика, Маркетинг
    булими…" starts the work immediately."""


class SalesImportService:
    """Reads a SAP export and writes it. Owns its transaction (§2)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.scope = SalesScope(session)

    # ── Entry point ───────────────────────────────────────────

    async def import_file(self, source: Any, *, filename: str = "") -> ImportReport:
        """Dispatch on the file's KIND, which is read from its header.

        The name is never trusted: users call the same export "Workbook3",
        "wb3" and "savdo kunlik" on three different days, and trusting the name
        leads quietly to the wrong import.
        """
        book = read_workbook(source, filename=filename)
        if book.kind is SalesFileKind.REGISTER:
            report = await self._import_register(book, filename)
        elif book.kind is SalesFileKind.CATALOG:
            report = await self._import_catalog(book, filename)
        else:
            report = await self._import_balance(book, filename)

        # ⚠️ THE CATALOGUE IS ALSO WHAT TELLS US WHICH NUMBER BELONGS TO WHOM.
        # A new contractor or a changed phone means the calls have to be
        # re-attributed to sales as well, or the report stays on the old
        # picture until somebody notices the employee column is wrong.
        report.attributed_sales = await refresh_sale_attribution(
            self.session, window_days=await self.scope.window_days()
        )
        await self.session.commit()
        return report

    async def expect(
        self, source: Any, *, filename: str, kinds: Sequence[SalesFileKind]
    ) -> SalesWorkbook:
        """Read the file and insist it is one of ``kinds``.

        The refusal names what the file IS, not only what it is not: "wrong
        file" leaves the user with no idea which button to press.
        """
        book = read_workbook(source, filename=filename)
        if book.kind not in kinds:
            raise SalesFileError(
                detail={
                    "reason": "wrong_export_kind",
                    "found": book.kind.value,
                    "expected": [kind.value for kind in kinds],
                    "filename": filename or None,
                }
            )
        return book

    # ── The register -> ``sales`` ─────────────────────────────

    async def _import_register(
        self, book: SalesWorkbook, filename: str
    ) -> ImportReport:
        rows = parse_register(book)
        report = ImportReport(
            kind=book.kind, source=filename or "register", read=len(rows)
        )

        # ⚠️ INTERNAL CONTRACTORS — our own departments (logistics, the
        # warehouse, the call centre). A transfer between them is booked as a
        # sale in SAP and comes out permanently suspicious: "was the customer
        # called first?" is meaningless when the customer is our own warehouse.
        #
        # ⚠️ THEIR ROWS STILL LAND IN THE DATABASE. The settings list is only
        # copied onto the FLAG here — the customer goes out of scope
        # (``sale_partners.excluded_at``) and the sales stay visible in the
        # "out of scope" section. The import deletes nothing: deleting was
        # irreversible, and taking a code back off the list never restored the
        # old periods at all.
        await self.apply_internal_codes()

        # ⚠️ AN OUT-OF-SCOPE BRANCH DOES NOT AFFECT THE IMPORT. Every row it
        # produces is stored; the separation happens in the control QUERY. The
        # list is needed here for ONE thing only: not asking the manager to
        # link an employee to a branch they deliberately took out of scope.
        excluded = await self.scope.excluded_branches()

        branches = await self._resolve_branches({r.branch for r in rows if r.branch})
        known_codes = await self._catalogue_codes()

        now = datetime.now(UTC)
        payload: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.op_type is SaleOpType.OTHER:
                report.unknown_op_type += 1
            if not row.partner_code or row.occurred_on is None:
                # Without a code or a date the row cannot take part in any rule,
                # and ``occurred_on`` is NOT NULL — it cannot be written.
                report.skipped += 1
                continue

            if row.partner_code not in known_codes:
                report.unknown_partner += 1

            # ⚠️ One `Номер операции` occurs TWICE in a file (measured: 2,383
            # distinct in 2,384 rows). PostgreSQL cannot touch one row twice in
            # a single ``ON CONFLICT``: "cannot affect row a second time" would
            # abort the whole import. The dict keeps the last occurrence.
            payload[row.external_id] = {
                "id": uuid.uuid4(),
                "external_id": row.external_id,
                "doc_number": row.doc_number,
                "op_type": row.op_type.value,
                "occurred_on": row.occurred_on,
                "branch": row.branch,
                "direction": row.direction,
                "partner_code": row.partner_code,
                "partner_name": row.partner_name,
                "amount": row.amount,
                "amount_usd": row.amount_usd,
                "currency": row.currency,
                "agent_id": branches.get(row.branch or ""),
                "source_file": (filename or "")[:255] or None,
                "imported_at": now,
            }

        report.created, report.updated = await self._upsert_sales(
            list(payload.values())
        )
        # ⚠️ AN OUT-OF-SCOPE BRANCH IS NOT "UNLINKED". The manager took it out
        # of control on purpose; asking again to link an employee to it turns
        # the list into noise and hides the branches that genuinely need one.
        report.unmatched_branches = sorted(
            name
            for name, agent_id in branches.items()
            if agent_id is None and name not in excluded
        )
        return report

    async def _upsert_sales(self, rows: list[dict[str, Any]]) -> tuple[int, int]:
        created = updated = 0
        for start in range(0, len(rows), _CHUNK):
            chunk = rows[start : start + _CHUNK]
            statement = pg_insert(SaleModel).values(chunk)
            statement = statement.on_conflict_do_update(
                index_elements=[SaleModel.external_id],
                set_={
                    "doc_number": statement.excluded.doc_number,
                    "op_type": statement.excluded.op_type,
                    "occurred_on": statement.excluded.occurred_on,
                    "branch": statement.excluded.branch,
                    "direction": statement.excluded.direction,
                    "partner_code": statement.excluded.partner_code,
                    "partner_name": statement.excluded.partner_name,
                    "amount": statement.excluded.amount,
                    "amount_usd": statement.excluded.amount_usd,
                    "currency": statement.excluded.currency,
                    # ⚠️ ``coalesce`` — if the manager linked an employee to the
                    # branch, the next import must not replace that with an
                    # empty value.
                    "agent_id": func.coalesce(
                        statement.excluded.agent_id, SaleModel.agent_id
                    ),
                    "source_file": statement.excluded.source_file,
                    # Written explicitly: this table has no ``TimestampMixin``
                    # on purpose (models.py), and an ``onupdate`` would not fire
                    # inside ``ON CONFLICT DO UPDATE`` anyway.
                    "imported_at": func.now(),
                },
            ).returning(literal_column("(xmax = 0)").label("inserted"))

            result = await self.session.execute(statement)
            flags = [bool(row[0]) for row in result.all()]
            created += sum(flags)
            updated += len(flags) - sum(flags)
        return created, updated

    # ── The catalogue -> ``sale_partners`` ────────────────────

    async def _import_catalog(
        self, book: SalesWorkbook, filename: str
    ) -> ImportReport:
        rows = parse_catalog(book)
        report = ImportReport(
            kind=book.kind, source=filename or "catalogue", read=len(rows)
        )

        # Duplicate codes — the last occurrence wins (the preview says so too).
        # Activity is separated AFTER that: a code appearing twice in the file
        # in two different states means the last row is the truth.
        unique: dict[str, CatalogRow] = {row.code: row for row in rows}
        inactive_codes = [code for code, row in unique.items() if not row.is_active]
        report.inactive_skipped = len(inactive_codes)

        payload = [
            {
                "id": uuid.uuid4(),
                "code": row.code,
                "name": row.name,
                "group_name": row.group_name,
                "branch": row.branch,
                "phone": row.phone,
                "matchable_phone": row.matchable_phone,
                "is_active": True,
                "telegram_link": row.telegram_link,
            }
            for row in unique.values()
            if row.is_active
        ]

        for start in range(0, len(payload), _CHUNK):
            chunk = payload[start : start + _CHUNK]
            statement = pg_insert(SalePartnerModel).values(chunk)
            statement = statement.on_conflict_do_update(
                index_elements=[SalePartnerModel.code],
                set_={
                    "name": statement.excluded.name,
                    "group_name": statement.excluded.group_name,
                    "branch": statement.excluded.branch,
                    # ⚠️ ``coalesce`` — the catalogue carries a phone for 94.7 %
                    # of contractors and the rest come from the balance report.
                    # A plain overwrite would erase that fill on every catalogue
                    # import. ``phone_key`` is GENERATED and follows
                    # ``matchable_phone`` by itself.
                    "phone": func.coalesce(
                        statement.excluded.phone, SalePartnerModel.phone
                    ),
                    "matchable_phone": func.coalesce(
                        statement.excluded.matchable_phone,
                        SalePartnerModel.matchable_phone,
                    ),
                    "is_active": statement.excluded.is_active,
                    "telegram_link": func.coalesce(
                        statement.excluded.telegram_link,
                        SalePartnerModel.telegram_link,
                    ),
                    "updated_at": func.now(),
                },
            ).returning(literal_column("(xmax = 0)").label("inserted"))

            result = await self.session.execute(statement)
            flags = [bool(row[0]) for row in result.all()]
            report.created += sum(flags)
            report.updated += len(flags) - sum(flags)

        report.inactive_deactivated = await self._deactivate(inactive_codes)
        report.linked_sales = await self.backfill_sale_agents()
        return report

    async def _deactivate(self, codes: Sequence[str]) -> int:
        """Mark contractors SAP no longer lists as active.

        ⚠️ NOT A DELETE. BonviZvonki deletes these rows and also sweeps every
        ``is_active = false`` row left from before. That takes the ``excluded_at``
        decision with it — a person's decision to put a customer out of sales
        control — and a customer who goes inactive and later returns comes back
        under control with nobody having chosen it. Marking costs one boolean
        and every reader already filters on it.
        """
        changed = 0
        for start in range(0, len(codes), _CHUNK):
            chunk = codes[start : start + _CHUNK]
            result = await self.session.execute(
                update(SalePartnerModel)
                .where(
                    SalePartnerModel.code.in_(chunk),
                    SalePartnerModel.is_active.is_(True),
                )
                .values(is_active=False, updated_at=func.now())
            )
            changed += result.rowcount or 0
        return changed

    # ── The balance report -> the missing phone numbers ───────

    async def _import_balance(
        self, book: SalesWorkbook, filename: str
    ) -> ImportReport:
        """Takes ONLY a phone number the catalogue was missing.

        No contractor is ever created from this file: ``Kod`` is not unique in
        it (a row is customer x branch x product line) and it has no
        ``Код группы``, which is what decides whether a contractor is inside
        sales control at all.
        """
        rows = parse_balance(book)
        report = ImportReport(
            kind=book.kind, source=filename or "balance report", read=len(rows)
        )

        known = {
            code: phone
            for code, phone in (
                await self.session.execute(
                    select(
                        SalePartnerModel.code, SalePartnerModel.matchable_phone
                    )
                )
            ).all()
        }

        # The first usable number per code: one code repeats across rows
        # (branch x product line) and they normally carry the same number.
        fills: dict[str, tuple[str | None, str]] = {}
        seen: set[str] = set()
        for row in rows:
            if row.code not in known:
                if row.code not in seen:
                    report.unknown_partner += 1
                    seen.add(row.code)
                continue
            if known[row.code] is not None or row.matchable_phone is None:
                continue
            fills.setdefault(row.code, (row.phone, row.matchable_phone))

        codes = list(fills)
        for start in range(0, len(codes), _CHUNK):
            chunk = codes[start : start + _CHUNK]
            await self.session.execute(
                update(SalePartnerModel)
                .where(SalePartnerModel.code.in_(chunk))
                # ⚠️ The ``IS NULL`` test is REPEATED in the statement: the list
                # was built a moment ago and another import may have written a
                # number since. We do not overwrite it.
                .where(SalePartnerModel.matchable_phone.is_(None))
                .values(
                    phone=case(
                        {code: fills[code][0] for code in chunk},
                        value=SalePartnerModel.code,
                    ),
                    matchable_phone=case(
                        {code: fills[code][1] for code in chunk},
                        value=SalePartnerModel.code,
                    ),
                    updated_at=func.now(),
                )
            )
        report.phones_filled = len(fills)
        report.updated = len(fills)
        report.linked_sales = await self.backfill_sale_agents()
        return report

    # ── Links: branch -> employee ─────────────────────────────

    async def _catalogue_codes(self) -> set[str]:
        """Every code in the catalogue.

        The whole catalogue is held in memory (3,746 rows, a few hundred
        kilobytes). The alternative is a query per sale — 2,384 round trips.
        """
        return set(await self.session.scalars(select(SalePartnerModel.code)))

    async def _resolve_branches(
        self, names: set[str]
    ) -> dict[str, uuid.UUID | None]:
        """Link branch names to employees, and register new branches.

        Three steps:
          1. a branch that already has a row — THAT decision wins (the manager
             may have set it by hand);
          2. the rest are matched against ``agents.full_name`` by normalised
             name (``Навоий`` -> ``Навои``, ``Жиззах`` -> ``Джиззах``);
          3. even an unmatched branch is WRITTEN to ``sale_branches``, with an
             empty ``agent_id``.

        ⚠️ Step 3 matters: without it the manager cannot know which branches are
        unlinked, and the admin screen's list would be empty. Departments like
        `Логистика` and `Маркетинг булими` have no call records at all and have
        to be visible on purpose.
        """
        if not names:
            return {}

        # ⚠️ ``assigned_at`` IS READ TOO. Looking only at ``agent_id``, an
        # unlinked row would stay unlinked FOREVER: the import never touches an
        # existing row, so a matching employee appearing later would never be
        # re-examined. That is exactly why `Онлайн савдо` sat with no employee
        # (46 sales) although the names were byte-for-byte identical.
        existing = {
            row.branch: (row.agent_id, row.assigned_at)
            for row in (
                await self.session.execute(
                    select(
                        SaleBranchModel.branch,
                        SaleBranchModel.agent_id,
                        SaleBranchModel.assigned_at,
                    ).where(SaleBranchModel.branch.in_(sorted(names)))
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
        # Two employees whose normalised names collide — WE DO NOT GUESS.
        # Booking a sale to the wrong employee is worse than leaving it blank,
        # because after that nobody checks it.
        by_name: dict[str, uuid.UUID | None] = {}
        for agent_id, full_name in agents:
            key = normalise_branch(full_name)
            by_name[key] = None if key in by_name else agent_id

        resolved: dict[str, uuid.UUID | None] = {}
        fresh: list[dict[str, Any]] = []
        retry: list[tuple[str, uuid.UUID]] = []
        for name in sorted(names):
            if name in existing:
                agent_id, assigned_at = existing[name]
                # A person decided, or it is already linked — hands off.
                if agent_id is not None or assigned_at is not None:
                    resolved[name] = agent_id
                    continue
                # Never matched — try again.
                found = by_name.get(normalise_branch(name))
                resolved[name] = found
                if found is not None:
                    retry.append((name, found))
                continue
            agent_id = by_name.get(normalise_branch(name))
            resolved[name] = agent_id
            fresh.append(
                {
                    "branch": name,
                    "agent_id": agent_id,
                    "matched_automatically": agent_id is not None,
                }
            )

        for branch, agent_id in retry:
            await self.session.execute(
                update(SaleBranchModel)
                .where(
                    SaleBranchModel.branch == branch,
                    SaleBranchModel.agent_id.is_(None),
                    SaleBranchModel.assigned_at.is_(None),
                )
                .values(agent_id=agent_id, matched_automatically=True)
            )

        for start in range(0, len(fresh), _CHUNK):
            chunk = fresh[start : start + _CHUNK]
            # ⚠️ ``DO NOTHING``, NOT ``DO UPDATE``. If the row already exists
            # (including from a concurrent import) the manager's manual link
            # must survive.
            await self.session.execute(
                pg_insert(SaleBranchModel)
                .values(chunk)
                .on_conflict_do_nothing(index_elements=[SaleBranchModel.branch])
            )
        return resolved

    async def backfill_sale_agents(self) -> int:
        """Fill in empty branch links on ``sales`` from the current map.

        WHY IT IS NEEDED: the order of imports is in the user's hands. They may
        upload the register first and the catalogue or the branch map after, and
        the sales in between would be left with no employee. The failure would
        be SILENT — the employee column simply reads empty and every report
        under-counts.

        Only EMPTY fields are filled; an existing value is left alone. Also
        called when the manager links an employee to a branch by hand.
        """
        result = await self.session.execute(
            update(SaleModel)
            .where(SaleModel.branch == SaleBranchModel.branch)
            .where(SaleBranchModel.agent_id.is_not(None))
            .where(SaleModel.agent_id.is_(None))
            .values(agent_id=SaleBranchModel.agent_id)
        )
        return result.rowcount or 0

    async def apply_internal_codes(self) -> int:
        """Mark the codes in ``sales.internal_codes`` as out of scope.

        Called at the start of an import, so the settings list and the flag
        cannot contradict each other: a code a manager types into the list has
        to reach the control query, and that query reads only the flag.

        ⚠️ IDEMPOTENT AND ONE-WAY. A row already flagged is NOT touched —
        rewriting ``excluded_at`` on every import would make "when was this
        excluded?" always read "just now" and the column would mean nothing.
        Removing a code from the list does NOT clear the flag either: putting a
        customer back is a PERSON's action, and an import may not undo it
        quietly.

        ⚠️ A code absent from the catalogue is not flagged — there is no row to
        carry it. The next import after the catalogue arrives will flag it.

        Returns how many contractors this call newly flagged.
        """
        codes = await self.scope.internal_codes()
        if not codes:
            return 0
        result = await self.session.execute(
            update(SalePartnerModel)
            .where(
                SalePartnerModel.code.in_(sorted(codes)),
                SalePartnerModel.excluded_at.is_(None),
            )
            .values(excluded_at=datetime.now(UTC))
        )
        return result.rowcount or 0


__all__ = ["ImportReport", "SalesImportService"]
