"""The branch map, and taking a branch or a customer out of sales control.

Ported from BonviZvonki ``modules/sales/application/branches.py`` and
``application/partners.py``. The two live in one file here because they are one
mechanism seen from two sides — "who sold" and "who bought" — and the control
query merges them into ONE "out of scope" section
(``service.ComplianceFilter.out_of_scope``). Split across two files they drift.

THE BRANCH MAP. The SAP sales file has NO salesperson's name — only
``Подразделение`` (Бухоро, Мастона ёйма, Логистика…). This table is the only
route from a sale to a person by branch. The import links what it can by exact
match of normalised names; the manager sets the rest by hand. Measured
(22.08.2026): 15 of 29 branches matched automatically, 19 with the manual ones
= 88.4 % of sales.

⚠️ THE MAP HAS TO BE VISIBLE. Unless the manager can see which branch belongs
to whom — and whether the system found it or a person set it — they do not
trust the numbers in the per-employee cut. So the list carries unlinked
branches too, and the number of sales sitting behind each one.

⚠️ WHY EXCLUSION IS NOT A DELETE. Their earlier version removed the rows.
The manager refused: "take them out, but do not lose them — give them their own
section". Deleting is irreversible; putting a branch back would restore the
history only by re-importing every SAP file, and for old periods that is not
possible at all.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import NotFoundError
from src.modules.agents.models import AgentModel
from src.modules.sales.importer import SalesImportService
from src.modules.sales.models import SaleBranchModel, SaleModel, SalePartnerModel
from src.modules.sales.rules import SaleOpType
from src.modules.sales.service import SalesScope, refresh_sale_attribution


@dataclass(slots=True)
class BranchRow:
    """One branch and its evidence."""

    branch: str
    agent_id: uuid.UUID | None
    agent_name: str | None
    matched_automatically: bool
    """True — the system found it by name similarity; False — a person set it,
    or it is not linked yet."""
    sales: int
    """How many sales sit behind this branch — how much the linking matters
    (79 sales behind an unlinked branch means 79 sales with no employee)."""

    excluded: bool = False
    """The branch is OUT OF SCOPE — its sales move to their own section and are
    NOT deleted.

    ⚠️ An excluded branch STAYS in this list. Otherwise it could not be put
    back: the branch would vanish and "where did that department go?" would
    have no answer."""


@dataclass(slots=True)
class PartnerRow:
    """A customer's state after being excluded or put back."""

    code: str
    name: str
    excluded: bool

    sales: int
    """How many sales carry this code — how large the action is.
    ⚠️ The REAL number comes back even AFTER exclusion: the sales are not
    deleted, and this number is what proves it."""


class SaleBranchService:
    """The branch map and the two exclusion switches. Owns its transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── The map ───────────────────────────────────────────────

    async def list_branches(self) -> list[BranchRow]:
        """The whole map, busiest branch first.

        The order is deliberate: the manager should link the branch with the
        most sales behind it first.

        ⚠️ Excluded branches come back too, with their REAL sale counts (they
        are not deleted, only separated by the control query). Dropping them
        would make exclusion a one-way action.
        """
        counts = (
            select(SaleModel.branch.label("branch"), func.count().label("sales"))
            .where(SaleModel.op_type == SaleOpType.SALE.value)
            .where(SaleModel.branch.is_not(None))
            .group_by(SaleModel.branch)
            .subquery("branch_sales")
        )

        rows = (
            await self.session.execute(
                select(
                    SaleBranchModel.branch,
                    SaleBranchModel.agent_id,
                    SaleBranchModel.matched_automatically,
                    SaleBranchModel.excluded_at,
                    AgentModel.full_name.label("agent_name"),
                    func.coalesce(counts.c.sales, 0).label("sales"),
                )
                .select_from(SaleBranchModel)
                .outerjoin(AgentModel, AgentModel.id == SaleBranchModel.agent_id)
                .outerjoin(counts, counts.c.branch == SaleBranchModel.branch)
                .order_by(
                    func.coalesce(counts.c.sales, 0).desc(), SaleBranchModel.branch
                )
            )
        ).all()

        return [
            BranchRow(
                branch=row.branch,
                agent_id=row.agent_id,
                agent_name=row.agent_name,
                matched_automatically=row.matched_automatically,
                sales=row.sales,
                excluded=row.excluded_at is not None,
            )
            for row in rows
        ]

    # ── The one write entry point ─────────────────────────────

    async def apply(
        self,
        branch: str,
        *,
        agent_id: uuid.UUID | None,
        set_agent: bool,
        excluded: bool | None,
    ) -> BranchRow:
        """Both actions on one branch, in one transaction.

        The service owns the transaction (CONVENTIONS.md §2): the router used
        to sequence the two writes and commit, which put the ordering rule —
        and a ``.commit()`` — into a router where ``test_layering`` forbids
        both.

        ⚠️ THE ORDER MATTERS when both are sent: link first, then exclude. The
        answer is read after the LAST action, so the other way round the
        employee on the screen would be stale.

        ⚠️ ``set_agent`` rather than ``agent_id is not None``: ``null`` is a full
        value ("unlink") and is different from "not sent". Without the
        distinction a bare "just exclude it" request would quietly unlink the
        employee as well.
        """
        row: BranchRow | None = None
        if set_agent:
            row = await self._assign(branch, agent_id)
        if excluded is not None:
            row = await self._exclude(branch, excluded)
        if row is None:
            # Neither field was sent. Answer with the current state rather than
            # inventing a change — and still 404 for a branch that is not there.
            row = await self._branch_row(branch)

        # The fallback employee (``sales.agent_id``) has just moved, so the
        # derived pair has to agree with it again.
        await refresh_sale_attribution(
            self.session, window_days=await SalesScope(self.session).window_days()
        )
        await self.session.commit()
        return row

    # ── Assigning an employee ─────────────────────────────────

    async def _assign(self, branch: str, agent_id: uuid.UUID | None) -> BranchRow:
        """Link an employee to a branch BY HAND (or unlink one).

        Three things happen and all three are necessary:

          1. ``matched_automatically = False`` and ``assigned_at`` is stamped —
             this is a PERSON's decision. Later imports leave the row alone
             (``ON CONFLICT DO NOTHING``), so the system cannot quietly replace
             what the manager chose.
          2. The sales of this branch MOVE to the new employee. ⚠️
             ``backfill_sale_agents()`` alone is NOT enough: it only fills an
             EMPTY ``agent_id``, so correcting a wrong link would leave the old
             sales on the old employee and the report would become a lie. The
             map is the single source, so the sales follow it.
          3. ``backfill_sale_agents()`` still runs, for the sales that had no
             employee at all.
        """
        row = await self.session.get(SaleBranchModel, branch)
        if row is None:
            raise NotFoundError()

        if agent_id is not None:
            agent = await self.session.get(AgentModel, agent_id)
            if agent is None or agent.archived_at is not None:
                # An archived employee is a 404 exactly like a missing one: the
                # per-employee cut excludes archived people, so linking to one
                # would produce sales that belong to a row the report does not
                # contain.
                raise NotFoundError()

        row.agent_id = agent_id
        row.matched_automatically = False
        # ⚠️ This stamp tells the import "hands off". Without it, a row that was
        # never matched could not be told apart from one a person deliberately
        # cleared (``models.SaleBranchModel.assigned_at``).
        row.assigned_at = datetime.now(UTC)

        await self.session.execute(
            update(SaleModel)
            .where(SaleModel.branch == branch)
            .values(agent_id=agent_id)
        )
        await SalesImportService(self.session).backfill_sale_agents()
        return await self._branch_row(branch)

    # ── Taking a branch out of scope ──────────────────────────

    async def _exclude(self, branch: str, excluded: bool) -> BranchRow:
        """Take a branch OUT of sales control (or put it back).

        We have departments that are ours but are not selling — `Маркетинг
        булими`, `Логистика`. "Speak to the customer" has no meaning there, so
        they sat permanently at the top of the suspicious list and BURIED the
        real defects.

        ⚠️ COMPLETELY REVERSIBLE. Only one date is written here — neither the
        sales nor the import are touched:

          · the import keeps taking every row as before;
          · the control query separates them
            (``ComplianceFilter.excluded_branch_names``): out of the default
            list and out of the report's counts, and into the "out of scope"
            section when it is asked for.

        The employee link is left alone as well: if the manager puts the branch
        back, the old link should still be there rather than have to be found
        again.
        """
        row = await self.session.get(SaleBranchModel, branch)
        if row is None:
            raise NotFoundError()
        row.excluded_at = datetime.now(UTC) if excluded else None
        await self.session.flush()
        return await self._branch_row(branch)

    async def _branch_row(self, branch: str) -> BranchRow:
        """Re-read one branch, so the answer is what is actually stored."""
        for row in await self.list_branches():
            if row.branch == branch:
                return row
        raise NotFoundError()


class SalePartnerService:
    """Taking a CUSTOMER out of sales control.

    The same mechanism as a branch, seen from the other side, and deliberately
    so: in the control query the two merge into one "out of scope" section.

    WHY A CUSTOMER NEEDED IT TOO. SAP holds rows that are contractors but not
    buyers: our own departments (`Метан завод (Логистика)`, `Маркетинг булими`),
    the warehouse, the call centre, internal supply. A transfer between them is
    booked as a sale and comes out permanently suspicious — "was the customer
    called before the sale?" is meaningless for our own warehouse. Measured
    (31.08.2026): 25 contractors, 127 sales in three weeks, 102 of them
    suspicious.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exclude(self, code: str, excluded: bool) -> PartnerRow:
        """Take a customer OUT of sales control (or put them back).

        ⚠️ COMPLETELY REVERSIBLE. One date is written; neither the sales nor the
        import are touched:

          · the import keeps taking every row as before;
          · the control query separates them
            (``ComplianceFilter.excluded_partner_codes``): out of the default
            list, out of the report's counts, out of the WALK-IN section too,
            and into the "out of scope" section when it is asked for.

        ⚠️ THE DIFFERENCE FROM A BRANCH: excluding a customer DOES reach the
        walk-in section. A branch measures "who sold" and is irrelevant under a
        shared code; a customer measures "who bought", and an excluded customer
        must not be under control anywhere, or "I excluded them" is a half-done
        action.

        ``code`` is the SAP code, with a CYRILLIC ``К``. A code that is not
        found is a 404: one written with the Latin letter, or an obsolete one,
        must not quietly get "done" for an answer.
        """
        partner = await self.session.scalar(
            select(SalePartnerModel).where(SalePartnerModel.code == code)
        )
        if partner is None:
            raise NotFoundError()

        partner.excluded_at = datetime.now(UTC) if excluded else None
        await self.session.commit()

        return PartnerRow(
            code=partner.code,
            name=partner.name,
            excluded=excluded,
            sales=await self._sales_count(code),
        )

    async def _sales_count(self, code: str) -> int:
        """This code's SALES — payments and returns are not counted.

        The rules apply to ``op_type = 'sale'`` only
        (``ComplianceService._selected``), so the number on the screen has to
        be the same one.
        """
        return await self.session.scalar(
            select(func.count())
            .select_from(SaleModel)
            .where(SaleModel.partner_code == code)
            .where(SaleModel.op_type == SaleOpType.SALE.value)
        )


__all__ = [
    "BranchRow",
    "PartnerRow",
    "SaleBranchService",
    "SalePartnerService",
]
