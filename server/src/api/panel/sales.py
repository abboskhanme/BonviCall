"""Sales control for the panel — was the customer spoken to before the sale?

Ported from BonviZvonki ``modules/sales/presentation/router.py``. Ten routes
doing two jobs:

  · GETTING DATA IN — ``POST /sales/import/preview`` (an estimate, writes
    NOTHING) and ``POST /sales/import`` (the SAP export itself);
  · CONTROL — the queue, the report, the customer timeline, the decision, the
    branch map and the two exclusion switches.

⚠️ THE IMPORT IS TWO-STAGE. The file goes to ``preview`` first and the user
sees what would land; ``import`` runs only after they confirm. A one-stage
import put the wrong file into the database silently and there was no way back.

═══ ACCESS ═════════════════════════════════════════════════════════════════
Reading is ``reports:read`` — admin and manager, never ``sales``. That is not
an oversight, it is the point: this list is a check carried out ON an employee.
An employee who can see that their own sale has been flagged has the chance to
prepare before the check, which is the one thing the queue must not allow. The
registry grants a salesperson no ``reports:*`` at all, so the shape already
fits: every report on this surface is fleet-wide.

Writing is ``settings:write`` — admin only. Running an import rewrites the
register every later number is computed from, and excluding a branch or a
customer changes which sales are checked at all: both are "changes how the
system behaves", which is the line this registry already draws at
``settings:write``.

**The one imperfect fit, stated rather than hidden: the review decision uses
``calls:note``.** There is no ``sales:review`` in ``core/permissions.py`` and
that file is closed (T18 — every constant is declared up front). ``calls:note``
is the closest existing meaning — "a human writes a judgement onto a record" —
and, decisively, it is held by admin AND manager, which is who works this
queue. ``alerts:ack`` was the other candidate and reads well ("close a flagged
finding", and its comment says such a thing must not be clearable by whoever it
is inconvenient for), but it is admin-only, and with it a manager could read
the queue and never empty it. A dedicated ``sales:review`` is owed the day the
registry is next amended.

``POST /sales/digest/test`` is ``settings:write``, not the read permission:
reading a list and asking the system to emit a message outward are different
acts. In this deployment it emits nothing — the transport is a logging seam
(``modules/sales/telegram.py``) — and the endpoint is proved not to reach the
network by ``test_sales_digest.py``.
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import date
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile

from src.core.deps import PrincipalDep, SessionDep
from src.core.errors import ErrorCode, PayloadTooLargeError
from src.core.pagination import MAX_LIMIT, Cursor, clamp_limit
from src.core.permissions import Perm, require_permission
from src.modules.sales.branches import SaleBranchService, SalePartnerService
from src.modules.sales.digest import SalesDigestService
from src.modules.sales.importer import SalesImportService
from src.modules.sales.preview import SalesPreviewService
from src.modules.sales.reader import SalesFileError
from src.modules.sales.rules import (
    ClientKind,
    ComplianceRow,
    ReviewState,
    Rule,
    Verdict,
)
from src.modules.sales.schemas import (
    AgentBreakdownOut,
    AssignBranchRequest,
    ComplianceItem,
    ComplianceListResponse,
    ComplianceSummaryResponse,
    ComplianceTimelineResponse,
    DigestTestResponse,
    ImportPreviewResponse,
    ImportReportResponse,
    PartnerExclusionRequest,
    PartnerExclusionResponse,
    PreviewDayCount,
    PreviewTypeCount,
    PreviewWarningOut,
    ReviewSaleRequest,
    SaleBranchListResponse,
    SaleBranchOut,
    SaleReviewOut,
    TimelineClientOut,
    TimelineEventOut,
)
from src.modules.sales.service import ComplianceFilter, ComplianceService, SalesScope
from src.modules.sales.service import SaleReviewService as ReviewWriter
from src.modules.sales.timeline import DEFAULT_MAX_CLIENTS, SalesTimelineService

router = APIRouter(prefix="/sales", tags=["Sales control"])

_read = require_permission(Perm.REPORTS_READ)
_write = require_permission(Perm.SETTINGS_WRITE)
#: See the module docstring: the closest existing constant for "a human records
#: a judgement about a record", and the one both roles that work this queue
#: hold.
_review = require_permission(Perm.CALLS_NOTE)

#: The largest upload accepted.
#
# Measured: the biggest real export (the contractor catalogue, 3,746 rows) is
# 394 KB. 20 MB is ample for a year's register. A ceiling MUST exist —
# ``openpyxl`` opens the file into memory and a few hundred megabytes would
# kill the process.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

#: The only accepted extension.
#
# ⚠️ ``.xls`` (the old binary format) and ``.csv`` are refused DELIBERATELY:
# ``openpyxl`` cannot read them and the failure would be unintelligible ("File
# is not a zip file"). SAP exports both as ``.xlsx``, so the user loses nothing.
ALLOWED_SUFFIX = ".xlsx"

#: Content types an ``.xlsx`` arrives as.
#
# The real one, plus the two a browser or a command-line client sends when it
# declines to guess. Anything ELSE is refused before the bytes are parsed —
# a ``text/csv`` upload is a mistake worth catching at the door.
ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
        "",
    }
)


async def _upload(file: UploadFile) -> tuple[str, bytes]:
    """Check the upload and read it into memory.

    BOTH routes go through exactly this check: with the limit or the extension
    enforced on only one of them, a file that passed the estimate would be
    refused unexpectedly at the import.
    """
    name = (file.filename or "").strip()
    if not name.lower().endswith(ALLOWED_SUFFIX):
        raise SalesFileError(detail={"reason": "not_xlsx", "filename": name or None})
    if (file.content_type or "") not in ALLOWED_CONTENT_TYPES:
        raise SalesFileError(
            detail={"reason": "wrong_content_type", "content_type": file.content_type}
        )

    # One byte more than the limit, so a file EXACTLY at the limit passes and a
    # larger one is detected.
    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise PayloadTooLargeError(
            ErrorCode.PAYLOAD_TOO_LARGE, detail={"max_bytes": MAX_UPLOAD_BYTES}
        )
    if not payload:
        raise SalesFileError(detail={"reason": "empty_file", "filename": name or None})
    return name, payload


# ══════════════════════════════════════════════════════════════
#  Import
# ══════════════════════════════════════════════════════════════


@router.post(
    "/import/preview",
    response_model=ImportPreviewResponse,
    summary="What the import would do — writes nothing",
    dependencies=[Depends(_write)],
)
async def import_preview(
    session: SessionDep,
    file: Annotated[UploadFile, File(description="The `.xlsx` export.")],
) -> ImportPreviewResponse:
    """Read the file and say what would happen. **NOTHING IS WRITTEN.**

    The sequence is: file -> this estimate -> the user confirms -> the SAME file
    goes to ``POST /sales/import``. Cancel, and the database is untouched —
    which is a test, not a promise.
    """
    name, payload = await _upload(file)
    preview = await SalesPreviewService(session).build(BytesIO(payload), filename=name)
    return ImportPreviewResponse(
        kind=preview.kind,
        filename=preview.filename,
        rows=preview.rows,
        date_from=preview.date_from,
        date_to=preview.date_to,
        by_type=[PreviewTypeCount(**asdict(row)) for row in preview.by_type],
        by_day=[PreviewDayCount(**asdict(row)) for row in preview.by_day],
        new_rows=preview.new_rows,
        existing_rows=preview.existing_rows,
        unknown_partners=preview.unknown_partners,
        unknown_partner_count=preview.unknown_partner_count,
        unmatched_branches=preview.unmatched_branches,
        without_phone=preview.without_phone,
        warnings=[PreviewWarningOut(**item) for item in preview.warnings],
    )


@router.post(
    "/import",
    response_model=ImportReportResponse,
    summary="Load a SAP export (register / catalogue / balance)",
    dependencies=[Depends(_write)],
)
async def import_sales(
    session: SessionDep,
    file: Annotated[UploadFile, File(description="The `.xlsx` export.")],
) -> ImportReportResponse:
    """The file's KIND is read from its header; its name is ignored.

    Users name the same export differently every time ("Workbook3", "wb3",
    "savdo kunlik"), and trusting the name leads quietly to the wrong import.
    """
    name, payload = await _upload(file)
    report = await SalesImportService(session).import_file(
        BytesIO(payload), filename=name
    )
    return ImportReportResponse(
        kind=report.kind.value,
        source=report.source,
        read=report.read,
        created=report.created,
        updated=report.updated,
        skipped=report.skipped,
        unknown_partner=report.unknown_partner,
        unknown_op_type=report.unknown_op_type,
        inactive_skipped=report.inactive_skipped,
        inactive_deactivated=report.inactive_deactivated,
        phones_filled=report.phones_filled,
        linked_sales=report.linked_sales,
        attributed_sales=report.attributed_sales,
        unmatched_branches=report.unmatched_branches,
    )


# ══════════════════════════════════════════════════════════════
#  The shared filter
# ══════════════════════════════════════════════════════════════

#: The description of ``out_of_scope``, written ONCE and shared by three
#: routes. Three copies drift, and one parameter would then be documented three
#: different ways.
_SCOPE_HELP = (
    "The 'out of scope' section. false (default) — the MAIN list: a sale shows "
    "when neither its branch nor its customer is excluded | true — ONLY the "
    "excluded: branch OR customer out of sales control."
)

_KIND_HELP = (
    "regular — regular customers (default; shared codes are EXCLUDED) | "
    "walk_in — shared codes only, where the measure is the ticket limit rather "
    "than the rules."
)

DateFrom = Annotated[
    date | None, Query(description="Asia/Tashkent calendar date, inclusive.")
]
DateTo = Annotated[
    date | None, Query(description="Asia/Tashkent calendar date, INCLUSIVE.")
]


async def compliance_filter(
    session: SessionDep,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    agent_id: Annotated[list[uuid.UUID] | None, Query(description="Employees.")] = None,
    branch: Annotated[list[str] | None, Query(description="SAP branches.")] = None,
    search: Annotated[
        str | None,
        Query(description="Customer name, code, phone digits or operation number."),
    ] = None,
    client_kind: Annotated[ClientKind, Query(description=_KIND_HELP)] = ClientKind.REGULAR,
    out_of_scope: Annotated[bool, Query(description=_SCOPE_HELP)] = False,
) -> ComplianceFilter:
    """The window every sales-control surface shares.

    ⚠️ The walk-in codes, the ticket limit, the window length and BOTH exclusion
    lists are read from the database on every request, inside
    ``SalesScope.resolve``. Taking them from the caller instead would let the
    list be computed against one set of codes and the report against another —
    both numbers sit on one screen, and the difference destroys confidence
    immediately.

    The bounds are calendar ``date`` values, so "up to the 16th" includes the
    whole of the 16th by construction: ``sales.occurred_on`` is itself a date,
    because SAP gives a sale no clock. The half-open pair lives on the CALL
    side, where the values are instants (``service.day_start``).
    """
    return await SalesScope(session).resolve(
        since=date_from,
        until=date_to,
        agent_ids=list(agent_id) if agent_id else None,
        branches=list(branch) if branch else None,
        search=search,
        client_kind=client_kind.value,
        out_of_scope=out_of_scope,
    )


FilterDep = Annotated[ComplianceFilter, Depends(compliance_filter)]


def _item(row: ComplianceRow) -> ComplianceItem:
    """One row as its wire shape."""
    verdict = row.verdict
    return ComplianceItem(
        id=row.id,
        occurred_on=row.occurred_on,
        external_id=row.external_id,
        doc_number=row.doc_number,
        partner_code=row.partner_code,
        partner_name=row.partner_name,
        phone=row.phone,
        phone_key=row.phone_key,
        branch=row.branch,
        direction=row.direction,
        agent_id=row.agent_id,
        agent_name=row.agent_name,
        amount=row.amount,
        currency=row.currency,
        amount_usd=row.amount_usd,
        partner_excluded=row.partner_excluded,
        over_limit=row.over_limit,
        verdict=verdict.verdict,
        broken_rules=verdict.broken_rules,
        skip_reason=verdict.skip_reason,
        last_call_at=verdict.last_call_at,
        last_call_agent=verdict.last_call_agent,
        last_call_id=verdict.last_call_id,
        days_before=verdict.days_before,
        previous_sale_on=verdict.previous_sale_on,
        calls_between=verdict.calls_between,
        calls_total=verdict.calls_total,
        review=SaleReviewOut(**asdict(row.review)) if row.review else None,
    )


# ══════════════════════════════════════════════════════════════
#  The queue
# ══════════════════════════════════════════════════════════════


@router.get(
    "/compliance",
    response_model=ComplianceListResponse,
    summary="The review queue — sales and their verdicts",
    dependencies=[Depends(_read)],
)
async def compliance(
    session: SessionDep,
    scope: FilterDep,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
    with_total: bool = False,
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    verdict: Annotated[
        Verdict | None, Query(description="ok | suspicious | not_checkable")
    ] = None,
    review: Annotated[
        ReviewState | None,
        Query(
            description=(
                "new — undecided (DEFAULT) | justified | confirmed | all — every "
                "sale regardless of a decision."
            )
        ),
    ] = ReviewState.NEW,
    rule: Annotated[Rule | None, Query(description="R1 | R2 | R3")] = None,
    over_limit: Annotated[
        bool | None,
        Query(
            description=(
                "Only meaningful with client_kind=walk_in: true — over the "
                "ticket limit, false — under it, omitted — everything."
            )
        ),
    ] = None,
) -> ComplianceListResponse:
    """The verdict is recomputed on EVERY request and is stored nowhere.

    A call can synchronise after the sale, and a flag written at import time
    would by then be a lie that nobody would recompute.

    ⚠️ ``review`` defaults to ``new``. That IS the review queue: a sale that has
    been decided leaves the list, or the manager sees the rows they have
    already dealt with again every day and the queue never ends. ``justified``
    and ``confirmed`` are the archive; ``all`` is everything.

    Paged by cursor, ordered ``occurred_on, id``. An ``OFFSET`` is wrong here
    for a reason specific to this list: deciding on a sale removes it from the
    default set, every later page shifts by one, and a sale is never seen at
    all.
    """
    scope.verdict = verdict.value if verdict else None
    scope.review = review.value if review else None
    scope.rule = rule.value if rule else None
    scope.over_limit = over_limit

    page = await ComplianceService(session).page(
        scope,
        limit=clamp_limit(limit, MAX_LIMIT),
        cursor=Cursor.decode(cursor) if cursor else None,
        with_total=with_total,
        order=order,
    )
    return ComplianceListResponse(
        items=[_item(row) for row in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        total=page.total,
        window_days=scope.window_days,
    )


@router.get(
    "/compliance/summary",
    response_model=ComplianceSummaryResponse,
    summary="The three class counts and the per-employee cut",
    dependencies=[Depends(_read)],
)
async def compliance_summary(
    session: SessionDep, scope: FilterDep
) -> ComplianceSummaryResponse:
    """All three counts — nothing is hidden.

    ⚠️ ``verdict`` / ``rule`` / ``review`` ARE DELIBERATELY NOT PARAMETERS HERE.
    With the report following the list's filter, choosing "suspicious" would
    drop two of the three cards to zero and "how many could not be checked" —
    the measure of SAP's own data quality — would have no answer.
    """
    result = await ComplianceService(session).summary(scope)
    return ComplianceSummaryResponse(
        total=result.total,
        ok=result.ok,
        suspicious=result.suspicious,
        not_checkable=result.not_checkable,
        new=result.new,
        justified=result.justified,
        confirmed=result.confirmed,
        window_days=result.window_days,
        over_limit=result.over_limit,
        over_limit_amount=result.over_limit_amount,
        walk_in_limit=result.walk_in_limit,
        agents=[AgentBreakdownOut(**asdict(row)) for row in result.agents],
    )


@router.get(
    "/compliance/timeline",
    response_model=ComplianceTimelineResponse,
    summary="By customer — the conversation/sale sequence",
    dependencies=[Depends(_read)],
)
async def compliance_timeline(
    session: SessionDep,
    scope: FilterDep,
    only_suspicious: Annotated[
        bool,
        Query(
            description=(
                "true (default) — only customers with at least ONE suspicious "
                "sale. The chain is still complete: such a customer's clean "
                "sales stay in it."
            )
        ),
    ] = True,
    max_clients: Annotated[
        int,
        Query(ge=1, le=1000, description="How many customers. Cut -> `truncated=true`."),
    ] = DEFAULT_MAX_CLIENTS,
) -> ComplianceTimelineResponse:
    """"Which customers has this employee worked with, and how did it go."

    The queue returns SALE rows; this returns a CUSTOMER cut, with the whole
    period's chain beside each one — call, sale, call…

    ⚠️ ``verdict`` / ``rule`` / ``review`` are deliberately absent. The chain is
    a SEQUENCE, and removing some of its sales would falsify the history: the
    pattern a manager reads is "sold after talking, then sold without talking",
    and that needs the complete row. The selection is made at customer level
    (``only_suspicious``).

    ⚠️ On one day the CONVERSATION comes before the SALE — a sale has no time,
    and the rules read it the same way.
    """
    result = await SalesTimelineService(session).build(
        scope, only_suspicious=only_suspicious, max_clients=max_clients
    )
    return ComplianceTimelineResponse(
        window_days=result.window_days,
        truncated=result.truncated,
        clients=[
            TimelineClientOut(
                partner_code=client.partner_code,
                partner_name=client.partner_name,
                phone=client.phone,
                agents=client.agents,
                sales_count=client.sales_count,
                suspicious_count=client.suspicious_count,
                amount_usd=client.amount_usd,
                calls_count=client.calls_count,
                events=[
                    TimelineEventOut(**asdict(event)) for event in client.events
                ],
            )
            for client in result.clients
        ],
    )


# ══════════════════════════════════════════════════════════════
#  Branch -> employee
# ══════════════════════════════════════════════════════════════


@router.get(
    "/branches",
    response_model=SaleBranchListResponse,
    summary="The branch map, with its evidence",
    dependencies=[Depends(_read)],
)
async def branches(session: SessionDep) -> SaleBranchListResponse:
    """Busiest branch first — that is where the linking should start.

    Excluded branches are in this list too (``excluded``): otherwise they could
    never be put back.
    """
    rows = await SaleBranchService(session).list_branches()
    return SaleBranchListResponse(
        items=[SaleBranchOut(**asdict(row)) for row in rows], total=len(rows)
    )


@router.put(
    "/branches/{branch}",
    response_model=SaleBranchOut,
    summary="Link an employee to a branch, or take the branch out of scope",
    dependencies=[Depends(_write)],
)
async def assign_branch(
    branch: str, payload: AssignBranchRequest, session: SessionDep
) -> SaleBranchOut:
    """Two separate actions on one route — both optional.

    · ``agent_id`` — link by hand (or unlink with ``null``). A manual link is
      not changed by later imports, and this branch's sales MOVE to the new
      employee at once; without that, correcting a wrong link would leave the
      old sales on the old employee and the report would be a lie.
    · ``excluded`` — take the branch out of sales control, or put it back. Its
      sales STAY IN THE DATABASE and only move section.

    ⚠️ SENT TOGETHER, THE ORDER MATTERS: link first, then exclude. The answer
    comes from the LAST action, so the other way round the employee on the
    screen would be stale.
    """
    # ⚠️ ``agent_id: null`` is a full value ("unlink"), which is different from
    # "not sent" — hence ``model_fields_set`` rather than a None test. The
    # service sequences the two writes and owns the transaction (§2).
    row = await SaleBranchService(session).apply(
        branch,
        agent_id=payload.agent_id,
        set_agent="agent_id" in payload.model_fields_set,
        excluded=payload.excluded,
    )
    return SaleBranchOut(**asdict(row))


# ══════════════════════════════════════════════════════════════
#  Customer -> out of scope
# ══════════════════════════════════════════════════════════════


@router.put(
    "/partners/{code}/exclusion",
    response_model=PartnerExclusionResponse,
    summary="Take a customer out of sales control, or put them back",
    dependencies=[Depends(_write)],
)
async def partner_exclusion(
    code: str, payload: PartnerExclusionRequest, session: SessionDep
) -> PartnerExclusionResponse:
    """For rows that are contractors in SAP but not BUYERS.

    Our own departments, the warehouse, internal supply: a transfer between
    them is booked as a sale and comes out permanently suspicious — "was the
    customer called before the sale?" is meaningless for our own warehouse.

    ⚠️ NO SALE IS DELETED. An excluded customer's sales leave the main list, the
    report's counts and the WALK-IN section, and appear in the out-of-scope
    section. Put them back and the whole history returns at once, with no
    re-import.

    ⚠️ ``code`` is the SAP code and its ``К`` is CYRILLIC (``К02711``); it
    arrives URL-encoded. A code that is not found is a **404**: one typed with
    the Latin letter, or an obsolete one, must not quietly get "done" for an
    answer.
    """
    row = await SalePartnerService(session).exclude(code, payload.excluded)
    return PartnerExclusionResponse(**asdict(row))


# ══════════════════════════════════════════════════════════════
#  The daily message — MANUAL TEST ONLY
# ══════════════════════════════════════════════════════════════


@router.post(
    "/digest/test",
    response_model=DigestTestResponse,
    summary="Assemble the daily message now (test)",
    dependencies=[Depends(_write)],
)
async def digest_test(session: SessionDep) -> DigestTestResponse:
    """Assemble the message and hand it to the transport seam.

    ``sales.digest_enabled`` is NOT checked — that is the whole point of the
    button: see the text before turning the switch on. The row lands with
    ``kind='test'`` and has no effect on the scheduled message.

    ⚠️ **THIS REACHES NO NETWORK.** The only transport implementation in this
    repository writes a log line and returns "not sent"
    (``modules/sales/telegram.py``); there is no bot token here and no HTTP
    client in that path. The answer therefore carries the TEXT and
    ``sent=false``, which is the honest report and is exactly what the button
    is for.
    """
    outcome = await SalesDigestService(session).run(manual=True)
    return DigestTestResponse(
        sent=outcome.sent,
        reason=outcome.reason,
        text=outcome.text,
        day=outcome.day,
        chat_id=outcome.chat_id,
        error=outcome.error,
        counts=outcome.counts,
        chars=len(outcome.text),
    )


# ══════════════════════════════════════════════════════════════
#  The decision
# ══════════════════════════════════════════════════════════════


@router.post(
    "/{sale_id}/review",
    response_model=SaleReviewOut,
    summary="Record a decision on a sale (justified / confirmed)",
    dependencies=[Depends(_review)],
)
async def review_sale(
    sale_id: uuid.UUID,
    payload: ReviewSaleRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> SaleReviewOut:
    """ONE decision per sale — a repeat overwrites it.

    A decided sale leaves the review queue (the default ``review=new`` filter)
    but does not disappear: ``review=justified`` or ``review=confirmed`` brings
    it back.

    Changing your mind is normal, so the table holds the LAST decision rather
    than a history — a second row would show the sale twice in the list.
    """
    result = await ReviewWriter(session).save(
        sale_id,
        status=payload.status,
        reason=payload.reason,
        note=payload.note,
        user_id=principal.id,
    )
    return SaleReviewOut(**asdict(result))
