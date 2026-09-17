"""The contacts dictionary's wire types.

Ported from BonviZvonki ``modules/clients/presentation/contacts_router.py``
(``ContactOut``, ``PaginatedContacts``, ``ContactDetailOut``,
``ContactPreviewOut``, ``ContactImportOut``, ``ContactPatch``). Field
descriptions are English because they become the OpenAPI document and therefore
the panel's generated types (CONVENTIONS.md §14); theirs are Uzbek.

════════════════════════════════════════════════════════════════
 WHAT IS NOT HERE, AND WHY — the SALES SEAM in one list
════════════════════════════════════════════════════════════════

The source's screen is *our phonebook beside the SAP partner catalogue*.
Everything that comes from the catalogue side is absent until the ``sales``
module lands, and nothing in this port creates, reads or references a
``sales*`` table:

* ``sap_code`` / ``sap_name`` / ``sap_phone`` — the right-hand column;
* ``status`` (``matched`` / ``code_unknown`` / ``by_phone`` / ``unknown``) and
  the ``sap_only`` pseudo-status. Two of the four values are answers the
  catalogue gives; shipping a filter with unreachable options is worse than
  shipping one fewer filter. ``has_code`` is what this deployment can actually
  answer, and it is the half of the question that does not need the catalogue;
* ``PartnerOut``, ``SalesBriefOut`` and the ``sales`` field on the card —
  including its access rule, which is worth recording here because it is not
  obvious and will be needed again: sales figures require ``sales:read``
  **separately**, never inherited from the right to open the card, because that
  list is a check carried out ON a salesperson and they must not see their own
  deal flagged as suspicious;
* ``matched`` / ``code_unknown`` / ``by_phone`` / ``unknown`` counters on the
  preview and the summary.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.modules.contacts.rules import ContactKind, ImportMode


class ContactRowOut(BaseModel):
    """One row of the dictionary — one phone number, one name, maybe a code."""

    phone_key: str = Field(
        description=(
            "The last 9 digits — the one matching key in the product (N37), and "
            "the same value `calls.remote_number_key` and "
            "`ClientRowOut.phone_key` carry."
        )
    )
    phone: str | None = Field(description="As the uploaded file wrote it, for display.")
    raw_name: str = Field(
        description="The name exactly as the handset had it. Never edited."
    )
    name: str | None = Field(
        description="The human name with the code cut out. Null — the name was only a code."
    )
    code: str | None = Field(
        description="The customer code, transliterated to Cyrillic. Null — none in the name."
    )
    kind: ContactKind
    source_file: str | None = Field(description="Which upload produced this row.")
    calls: int = Field(
        default=0,
        description=(
            "How many calls this number has. Filled by the upload preview and "
            "by the card; **0 in the list**, deliberately — a per-row count "
            "over the whole calls table would make every page pay for a figure "
            "the card shows better."
        ),
    )
    code_numbers: int = Field(
        default=1,
        description=(
            "How many of OUR numbers carry this code. Two numbers for one "
            "customer is the ordinary case, not an error; without this the row "
            "reads as a duplicate."
        ),
    )


class ContactPageResponse(BaseModel):
    items: list[ContactRowOut]
    next_cursor: str | None
    has_more: bool
    total: int | None = Field(
        description="Only the first page asks for it, like every other list here."
    )


class ContactSummaryResponse(BaseModel):
    """The header counts."""

    total: int
    with_code: int
    by_kind: dict[str, int] = Field(
        description="A `ContactKind` value -> how many rows carry it. Absent kinds are 0."
    )


class ContactCallsBrief(BaseModel):
    """What this number's traffic looks like — the card's right-hand half."""

    calls_total: int
    inbound: int
    outbound: int
    missed: int
    talk_seconds: int
    first_call_at: str | None
    last_call_at: str | None
    agent_count: int
    main_agent_name: str | None


class ContactDetailResponse(BaseModel):
    """Everything known about one number."""

    phone_key: str
    contact: ContactRowOut
    other_numbers: list[ContactRowOut] = Field(
        description="Our other numbers under the same code."
    )
    calls: ContactCallsBrief | None = Field(
        description="Null — no call has ever been made to or from this number."
    )


class ContactPreviewResponse(BaseModel):
    """What an upload WOULD do. Nothing has been written."""

    file: str
    read: int = Field(description="Rows in the file with any content in them.")
    parsed: int = Field(description="Distinct numbers the file yielded.")
    no_phone: int = Field(
        description=(
            "Rows with no number at all. Counted SEPARATELY from `bad_phone` "
            "and the difference is large: measured, 7,316 of 9,103 rows had no "
            "number (the export gave none) against 11 with an unusable one. "
            "Added together they would read as '7,327 bad rows'."
        )
    )
    bad_phone: int = Field(
        description="A number is there but no key could be built (foreign, service, junk)."
    )
    no_name: int
    duplicates: int = Field(
        description=(
            "Extra records for a number already seen. Ordinary: measured, 38 "
            "numbers carried more than two different names and one carried seven."
        )
    )
    with_code: int
    created: int
    updated: int
    unchanged: int
    calls_covered: int
    suggested: dict[str, int] = Field(
        description="The suggested `ContactKind` -> how many rows. A proposal, never applied."
    )
    would_import: dict[str, int] = Field(
        description="An `ImportMode` -> how many rows it would write."
    )
    would_cover: dict[str, int] = Field(
        description=(
            "An `ImportMode` -> how many CALLS it would cover. The number the "
            "decision is actually taken on: a row count flatters the wide mode."
        )
    )
    rows: list[ContactRowOut] = Field(
        description="A sample, capped — the whole file would be megabytes."
    )


class ContactImportResponse(BaseModel):
    """What the upload DID."""

    file: str
    mode: ImportMode
    read: int
    created: int
    updated: int
    unchanged: int
    no_phone: int
    bad_phone: int
    no_name: int
    duplicates: int
    skipped_filter: int = Field(
        description="Rows left out by the chosen mode. Existing rows are never skipped."
    )


class ContactPatchRequest(BaseModel):
    """An admin's correction.

    ⚠️ The `code` is editable. A code can be mistyped on a handset, and if
    fixing one meant re-uploading the whole file nobody would ever fix one.
    """

    kind: ContactKind | None = None
    code: str | None = Field(default=None, max_length=16)
    name: str | None = Field(default=None, max_length=255)


__all__ = [
    "ContactCallsBrief",
    "ContactDetailResponse",
    "ContactImportResponse",
    "ContactPageResponse",
    "ContactPatchRequest",
    "ContactPreviewResponse",
    "ContactRowOut",
    "ContactSummaryResponse",
]
