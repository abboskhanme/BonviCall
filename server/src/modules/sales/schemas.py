"""Sales control's wire types.

Ported from BonviZvonki ``modules/sales/presentation/router.py`` (the Pydantic
classes it declares inline). Field descriptions are English here because they
become the OpenAPI document and therefore the panel's generated types
(CONVENTIONS.md §14); theirs are Uzbek.

Two things are deliberately not the shape they have there:

* **Warnings are codes, not sentences.** Theirs formats a whole Uzbek sentence
  per warning inside the service. The panel owns user-facing copy, so a warning
  is ``{"code": …, "count": …}`` and the sentence is written once, in
  ``uz.json``.
* **The list is cursor-paged**, like every other list on this surface
  (``items`` / ``next_cursor`` / ``has_more`` / ``total``), rather than
  ``page``/``page_size``. ``ComplianceService.page`` says why an ``OFFSET`` is
  wrong for a queue whose rows leave it as they are reviewed.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.modules.sales.rules import (
    ClientKind,
    ReviewState,
    Rule,
    SaleReviewReason,
    SaleReviewStatus,
    Verdict,
)

# ══════════════════════════════════════════════════════════════
#  Import: the estimate and the report
# ══════════════════════════════════════════════════════════════


class PreviewTypeCount(BaseModel):
    """One slice: the operation type (register) or the group/branch."""

    type: str = Field(description="The machine value the panel translates from.")
    label: str = Field(
        description=(
            "The word SAP itself printed, e.g. `Продажа`. Deliberately the "
            "source language: the reader compares this count against the same "
            "report inside SAP, and a translated word makes that impossible. "
            "It is also the fallback for a type SAP invents tomorrow."
        )
    )
    count: int
    amount_usd: float | None = Field(
        default=None, description="Null when this slice carries no money at all."
    )


class PreviewDayCount(BaseModel):
    """One day's slice — filled for the register only."""

    day: date
    count: int
    amount_usd: float | None = None


class PreviewWarningOut(BaseModel):
    """A machine-readable warning. The panel owns the sentence."""

    code: str = Field(
        description=(
            "`rows_without_date` | `rows_without_partner_code` | "
            "`rows_without_amount` | `duplicate_keys_in_file` | "
            "`unknown_operation_types` | `contractors_without_usable_phone` | "
            "`inactive_contractors` | `codes_absent_from_catalogue`"
        )
    )
    count: int = Field(description="How many rows. A zero-count warning is never sent.")


class ImportPreviewResponse(BaseModel):
    """What the import WOULD do. Nothing has been written when this is returned.

    Writing happens only when the user confirms and sends the SAME file to
    `POST /sales/import`.
    """

    kind: Literal["register", "catalog", "balance"] = Field(
        description="Decided from the file's HEADER, never from its name."
    )
    filename: str
    rows: int = Field(description="Meaningful rows in the file.")
    date_from: date | None = None
    date_to: date | None = None
    by_type: list[PreviewTypeCount] = Field(default_factory=list)
    by_day: list[PreviewDayCount] = Field(default_factory=list)
    new_rows: int = Field(
        description=(
            "Keys not yet in the database. `0` means the file has already been "
            "uploaded. NOT comparable with `rows`: a key repeats inside a file "
            "(measured: 2,383 distinct operation numbers in 2,384 rows)."
        )
    )
    existing_rows: int = Field(
        description="Keys already present — they are overwritten, not duplicated."
    )
    unknown_partners: list[str] = Field(
        default_factory=list, description="At most 20 codes; the count is separate."
    )
    unknown_partner_count: int
    unmatched_branches: list[str] = Field(
        default_factory=list,
        description=(
            "Branches linked to no employee, by NAME. Nothing is written here — "
            "a branch reaches `sale_branches` only during the real import."
        ),
    )
    without_phone: int = Field(
        description="Rows with no usable number — outside sales control."
    )
    warnings: list[PreviewWarningOut] = Field(default_factory=list)


class ImportReportResponse(BaseModel):
    """What the import did. Every number answers a SEPARATE question."""

    kind: Literal["register", "catalog", "balance"]
    source: str
    read: int
    created: int
    updated: int
    skipped: int = Field(
        description="Rows with no customer code or no date — not storable."
    )
    unknown_partner: int = Field(
        description=(
            "Codes absent from the catalogue. The sale is STORED; it simply has "
            "no catalogue row behind it, so the rules cannot check it."
        )
    )
    unknown_op_type: int = Field(
        description="A SAP type we do not know. Stored as `other`, checked by no rule."
    )
    inactive_skipped: int = Field(
        description="Contractors the file marks inactive — not written as active."
    )
    inactive_deactivated: int = Field(
        description=(
            "Catalogue rows this file marked inactive. MARKED, never deleted: "
            "deleting would take the `excluded_at` decision with it."
        )
    )
    phones_filled: int = Field(
        description="Numbers taken from the balance report that the catalogue lacked."
    )
    linked_sales: int = Field(
        description="Sales whose branch link was restored after the map changed."
    )
    attributed_sales: int = Field(
        description="Sales whose attributed conversation changed because of this import."
    )
    unmatched_branches: list[str] = Field(
        description=(
            "By NAME, not as a count: nothing can be done with '7 branches were "
            "not linked', while a list of names starts the work."
        )
    )


# ══════════════════════════════════════════════════════════════
#  The queue
# ══════════════════════════════════════════════════════════════


class SaleReviewOut(BaseModel):
    """The human's decision — the only subjective value in this module."""

    status: SaleReviewStatus
    reason: SaleReviewReason | None = Field(
        default=None, description="Only ever set together with `justified`."
    )
    note: str | None = None
    reviewed_by: str | None = Field(
        default=None,
        description="Null when the account has since been removed; the decision stays.",
    )
    reviewed_at: datetime | None = None


class ComplianceItem(BaseModel):
    """One sale: the SAP fact, the verdict, and THE EVIDENCE.

    The evidence fields (`last_call_at` … `calls_total`) are not optional
    decoration. The manager re-derives the number by hand, so every suspicious
    row has to carry "when was the last conversation, with whom, how many days
    before" beside it. Without that the list is not believed.
    """

    id: uuid.UUID
    occurred_on: date = Field(
        description="A DATE with no time — SAP gives no clock for a sale."
    )
    external_id: str = Field(description="SAP's `Номер операции` — the import key.")
    doc_number: str | None = Field(
        default=None,
        description=(
            "SAP's `Номер документа` — the piece of paper the manager searches "
            "for. NOT interchangeable with `external_id`."
        ),
    )

    partner_code: str = Field(description="The customer. A customer IS the code.")
    partner_name: str | None = None
    phone: str | None = Field(
        default=None, description="As SAP wrote it — for display, never for matching."
    )
    phone_key: str | None = Field(
        default=None, description="The last-9 key the match was made on (N37)."
    )
    branch: str | None = None
    direction: str | None = Field(default=None, description="SAP's product line.")
    agent_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Whoever SPOKE to the customer, else whoever holds the branch. "
            "Null when neither is known — that sale belongs to nobody yet."
        ),
    )
    agent_name: str | None = None
    amount: float | None = Field(
        default=None, description="In the document's own currency."
    )
    currency: str
    amount_usd: float | None = Field(
        default=None,
        description=(
            "The same amount in dollars, straight from SAP. Stored as `numeric`; "
            "every comparison against a threshold happens in SQL, so no client "
            "ever has to compare money as a float."
        ),
    )

    partner_excluded: bool = Field(
        description=(
            "The customer is out of sales control. Does not affect the verdict "
            "— it is for the BUTTON: without it the card would open saying "
            "'Exclude' even for a customer already excluded, and there would be "
            "no way back from the screen."
        )
    )
    over_limit: bool = Field(
        description=(
            "A walk-in sale over the single-ticket limit. ALWAYS false in the "
            "regular-customer section: a large sale to a regular customer is a "
            "normal event."
        )
    )

    verdict: Verdict
    broken_rules: list[Rule] = Field(
        description="Always in this order (R1, R2, R3) so badges do not move about."
    )
    skip_reason: str | None = Field(
        default=None,
        description=(
            "`generic_code` — a shared code, many customers behind one; "
            "`no_phone` — no usable number anywhere. Set only with "
            "`not_checkable`, which is NOT a kind of `ok`."
        ),
    )

    last_call_at: datetime | None = Field(
        default=None,
        description=(
            "The nearest conversation before the sale (or on its own day). NOT "
            "bounded by the window: a conversation nine days ago is still shown, "
            "because that number is what explains the rule."
        ),
    )
    last_call_agent: str | None = None
    last_call_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "The call row itself, so the panel can open the recording. "
            "BonviZvonki shows a date and a name with nothing behind them."
        ),
    )
    days_before: int | None = Field(
        default=None, description="Days before the sale. `0` — the same day."
    )
    previous_sale_on: date | None = Field(
        default=None,
        description="This customer's previous sale. Null — a FIRST sale, so R2 is silent.",
    )
    calls_between: int = Field(
        description="Conversations between the previous sale and this one (R2)."
    )
    calls_total: int = Field(
        description=(
            "Conversations in the WHOLE history, the period included and not "
            "bounded by it — R3 is the harshest signal and is stated in its "
            "most cautious form."
        )
    )

    review: SaleReviewOut | None = None


class ComplianceListResponse(BaseModel):
    """A cursor page of the review queue.

    ``total`` is computed only when asked: the three class counts live on
    `GET /sales/compliance/summary`, which deliberately ignores the verdict
    filters, so the FILTERED count is the one thing the list has to supply.
    """

    items: list[ComplianceItem]
    next_cursor: str | None
    has_more: bool
    total: int | None = None
    window_days: int = Field(
        description="Which window the verdicts were computed with — shown on the screen."
    )


class AgentBreakdownOut(BaseModel):
    """One employee's slice of the report."""

    agent_id: uuid.UUID | None = Field(
        default=None, description="Null — sales whose branch is linked to nobody."
    )
    agent_name: str | None = None
    sales: int
    ok: int
    suspicious: int
    not_checkable: int
    new: int = Field(description="Suspicious and not yet decided — the work queue.")
    justified: int
    confirmed: int
    over_limit: int = 0
    over_limit_amount: float = 0.0


class ComplianceSummaryResponse(BaseModel):
    """The three class counts and the per-employee cut.

    The verdict filters are deliberately absent from this endpoint: all three
    counts have to stay on the screen, or choosing "suspicious" would drop two
    of the three cards to zero and "how many could not be checked" — the
    measure of SAP's own data quality — would have no answer.
    """

    total: int
    ok: int
    suspicious: int
    not_checkable: int
    new: int
    justified: int
    confirmed: int
    window_days: int
    over_limit: int = Field(
        default=0, description="Walk-in section only; always 0 for regular customers."
    )
    over_limit_amount: float = 0.0
    walk_in_limit: int = Field(
        default=0,
        description="Which limit these were computed against — stated, not implied.",
    )
    agents: list[AgentBreakdownOut]


# ══════════════════════════════════════════════════════════════
#  The customer timeline
# ══════════════════════════════════════════════════════════════


class TimelineEventOut(BaseModel):
    """One event — a conversation or a sale.

    ⚠️ BOTH COME BACK AS ONE TYPE (told apart by `kind`) AND ALREADY ORDERED.
    As two lists, interleaving them would fall to the panel, and the rule "on
    one day the conversation comes before the sale" would have to be written a
    second time there.
    """

    kind: Literal["call", "sale"]
    at: datetime = Field(
        description=(
            "A call: the real instant. A sale: 00:00 of that Asia/Tashkent day, "
            "because SAP gives a sale no time."
        )
    )
    agent_name: str | None = None

    # calls only
    call_id: uuid.UUID | None = None
    direction: str | None = None
    answered: bool | None = None
    duration_sec: int | None = None
    has_audio: bool | None = Field(
        default=None, description="Whether the conversation can be listened to."
    )

    # sales only
    sale_id: uuid.UUID | None = None
    external_id: str | None = None
    doc_number: str | None = None
    amount: float | None = None
    currency: str | None = None
    amount_usd: float | None = None
    verdict: Verdict | None = None
    broken_rules: list[Rule] = Field(default_factory=list)
    days_before: int | None = None


class TimelineClientOut(BaseModel):
    partner_code: str
    partner_name: str | None = None
    phone: str | None = Field(
        default=None,
        description=(
            "The SAP card's number, for display. Not the matching key: the "
            "chain covers every number known for this customer."
        ),
    )
    agents: list[str] = Field(default_factory=list)
    sales_count: int
    suspicious_count: int
    amount_usd: float
    calls_count: int
    events: list[TimelineEventOut] = Field(default_factory=list)


class ComplianceTimelineResponse(BaseModel):
    window_days: int
    truncated: bool = Field(
        description=(
            "Whether `max_clients` cut the list. Stated, or the list would "
            "silently be incomplete."
        )
    )
    clients: list[TimelineClientOut] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════
#  The branch map and the exclusions
# ══════════════════════════════════════════════════════════════


class SaleBranchOut(BaseModel):
    branch: str
    agent_id: uuid.UUID | None = None
    agent_name: str | None = None
    matched_automatically: bool = Field(
        description=(
            "True — the system matched it by name; false — a person set it, or "
            "it is not linked yet."
        )
    )
    sales: int = Field(
        description="Sales behind this branch — how much the linking matters."
    )
    excluded: bool = Field(
        description=(
            "Out of sales control. Its sales move to their own section and are "
            "NOT deleted. An excluded branch STAYS in this list, or it could "
            "never be put back."
        )
    )


class SaleBranchListResponse(BaseModel):
    """The whole map, busiest branch first."""

    items: list[SaleBranchOut]
    total: int


class AssignBranchRequest(BaseModel):
    """One change to the map. BOTH fields are optional.

    They answer SEPARATE questions and do not substitute for one another —
    "who is responsible" and "is this branch checked at all" — so a field that
    is not sent is NOT touched. `agent_id: null` is a full value ("unlink"),
    which is different from "not sent".
    """

    agent_id: uuid.UUID | None = Field(
        default=None, description="The employee. `null` unlinks."
    )
    excluded: bool | None = Field(
        default=None,
        description=(
            "`true` — take the branch out of sales control (its sales move to "
            "the out-of-scope section and are NOT deleted); `false` — put it "
            "back (the whole history returns with no re-import); omitted — "
            "leave it alone."
        ),
    )


class PartnerExclusionRequest(BaseModel):
    """Exclude a customer or put them back — one key, and it is REQUIRED.

    Unlike `AssignBranchRequest` there is only one action here, so an optional
    field would let an empty body answer "I did nothing" silently.
    """

    excluded: bool = Field(
        description=(
            "true — take the customer out of sales control (their sales move to "
            "the out-of-scope section and are NOT deleted) | false — put them "
            "back."
        )
    )


class PartnerExclusionResponse(BaseModel):
    code: str
    name: str
    excluded: bool
    sales: int = Field(
        description=(
            "Sales carrying this code. The REAL number comes back even after "
            "exclusion — which is what proves nothing was deleted."
        )
    )


# ══════════════════════════════════════════════════════════════
#  The review, and the digest
# ══════════════════════════════════════════════════════════════


class ReviewSaleRequest(BaseModel):
    status: SaleReviewStatus
    reason: SaleReviewReason | None = Field(
        default=None,
        description=(
            "Only with `justified`: walked in / Telegram / a visit / a contract. "
            "Sent with `confirmed` it is REFUSED rather than dropped — a field "
            "that looks accepted and is not is how a panel ships a dead control."
        ),
    )
    note: str | None = None


class DigestTestResponse(BaseModel):
    """The answer to the "test message" button.

    ⚠️ `text` IS ALWAYS RETURNED, even when nothing was sent. That is the whole
    point of the button: see what would go out BEFORE turning the switch on. An
    unfilled setting comes back as `sent=false` with a `reason` rather than an
    error — showing the text and saying "now name a chat" is more use than a
    422.

    ⚠️ IN THIS DEPLOYMENT NOTHING IS EVER SENT. The only transport
    implementation writes a log line, so `sent` is false with
    `reason="send_failed"` and `error="no_transport_configured"` once a chat is
    configured. That is deliberate and is not a fault to be fixed by the panel.
    """

    sent: bool
    reason: str | None = Field(
        default=None,
        description=(
            "`disabled` — the switch is off (scheduled runs only) | `no_chat` — "
            "no chat configured | `no_sales` — no sales in the database | "
            "`no_new_import` — nothing new since the last message (scheduled "
            "runs only) | `send_failed` — the transport refused it."
        ),
    )
    text: str
    day: date | None = Field(
        default=None,
        description=(
            "Which day the message covers — the last IMPORTED day, not "
            "yesterday: the export arrives by hand and is usually behind."
        ),
    )
    chat_id: str | None = None
    error: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    chars: int = Field(description="Message length. The transport's limit is 4096.")


__all__ = [
    "AgentBreakdownOut",
    "AssignBranchRequest",
    "ClientKind",
    "ComplianceItem",
    "ComplianceListResponse",
    "ComplianceSummaryResponse",
    "ComplianceTimelineResponse",
    "DigestTestResponse",
    "ImportPreviewResponse",
    "ImportReportResponse",
    "PartnerExclusionRequest",
    "PartnerExclusionResponse",
    "PreviewDayCount",
    "PreviewTypeCount",
    "PreviewWarningOut",
    "ReviewSaleRequest",
    "ReviewState",
    "SaleBranchListResponse",
    "SaleBranchOut",
    "SaleReviewOut",
    "TimelineClientOut",
    "TimelineEventOut",
]
