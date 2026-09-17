"""The client directory's own wire types.

Defined here and not imported from ``calls``: §2.1 rule 3 says what crosses
back out of a read-only module is that module's own schema, never a foreign
entity.

Ported from BonviZvonki ``modules/clients/presentation/router.py``
(``ClientListItem``, ``PaginatedClients``, ``ClientAgentItem``,
``ClientDetail``, ``ClientCallItem``, ``PaginatedClientCalls``). Field
descriptions are English because they become the OpenAPI document and therefore
the panel's generated types (CONVENTIONS.md §14); theirs are Uzbek.

Dropped against theirs, and why:

* ``code_source`` — ``contact`` or ``sap``, i.e. *which of the two catalogues
  produced this code*. There is one source here until the ``sales`` module
  lands, so the field would carry one value forever and answer nothing.
  **SALES SEAM.**
* ``main_agent_color`` / ``agent_color`` — BonviCall's ``agents`` table has no
  colour column, and inventing one for a chip would be a schema change made by
  a list page.
* ``answered: bool | None`` on a call row — ``calls.disposition`` is a NOT NULL
  enum here with a CHECK on the direction/disposition pairs, so the tri-state
  is unrepresentable and the enum says more (``activity.rules`` explains the
  same substitution in full).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from src.core.enums import CallDirection, CallDisposition, CallType


class ClientRowOut(BaseModel):
    """One customer in the directory — one phone number and its history."""

    phone_key: str = Field(
        description=(
            "The last-9 matching key (`calls.remote_number_key`, N37). The "
            "identifier for both the list and the card, and the same value "
            "`MissedClientRow.phone_key` carries."
        )
    )
    name: str | None = Field(
        description=(
            "The uploaded contact list first, the handset's own resolution as "
            "the fallback. Null — nobody has ever named this number."
        )
    )
    phone: str | None
    code: str | None = Field(
        description=(
            "The customer code read out of the contact name. Null — the "
            "dictionary holds no code for this number."
        )
    )

    calls_total: int
    inbound: int
    outbound: int
    missed: int = Field(
        description=(
            "Incoming and unanswered — the company's responsibility. The same "
            "definition the activity report uses: `rejected` counts here with "
            "`missed`, because the phone rang and there was no conversation."
        )
    )
    missed_rate: float | None = Field(
        description="Missed as a percent of incoming. Null when there were none."
    )
    talk_seconds: int

    first_call_at: datetime | None = Field(
        description=(
            "Null — there was no contact inside the chosen period. That is not "
            "the same as an unknown customer: the card still opens and shows "
            "zeros."
        )
    )
    last_call_at: datetime | None

    agent_count: int = Field(description="How many employees have spoken to them.")
    main_agent_id: uuid.UUID | None
    main_agent_name: str | None = Field(
        description="Whoever spoke to them most. The list shows this one and `+N`."
    )

    avg_score: float | None
    scored: int = Field(
        description="How many conversations were scored — what the average is over."
    )


class ClientPageResponse(BaseModel):
    """One keyset page of the directory."""

    items: list[ClientRowOut]
    next_cursor: str | None = Field(
        description="Opaque. Pass it back as `cursor`; null means this is the last page."
    )
    has_more: bool
    total: int | None = Field(
        description=(
            "How many customers the filter matches. Only the FIRST page asks "
            "for it (`with_total`), so every later page answers null — a count "
            "over a grouped aggregate is affordable once per filter change and "
            "not once per page."
        )
    )
    date_from: date | None
    date_to: date | None = Field(description="Inclusive, Asia/Tashkent.")


class ClientAgentRow(BaseModel):
    """An employee who spoke to this customer."""

    agent_id: uuid.UUID
    full_name: str
    calls: int
    last_call_at: datetime


class ClientDetailResponse(BaseModel):
    """The card: the same aggregate as the list row, plus who spoke to them."""

    client: ClientRowOut
    agents: list[ClientAgentRow] = Field(
        description="Employees who spoke to this customer, most first."
    )
    scope: str = Field(
        description=(
            "The cut the customer was actually FOUND in. It can differ from the "
            "one asked for: a card link with no `scope` on it would otherwise "
            "never open an internal number. The panel echoes it so the two "
            "lists below the card are asked with the same cut."
        )
    )
    # SALES SEAM: BonviZvonki's card carries a sales tab here
    # (`GET /clients/{key}/sales`, gated separately on `sales:read`). That
    # endpoint and this field arrive with the `sales` module; nothing in this
    # port creates, reads or references a `sales*` table.


class ClientCallRow(BaseModel):
    """One conversation with this customer."""

    id: uuid.UUID
    started_at: datetime
    received_at: datetime = Field(
        description=(
            "Shown beside `started_at` because the two differ whenever a phone "
            "was off or a recovery sweep found an old call (SPEC §3.12)."
        )
    )
    duration_sec: int
    direction: CallDirection
    disposition: CallDisposition
    call_type: CallType
    has_audio: bool
    agent_id: uuid.UUID
    agent_name: str
    score: int | None
    red_flag_count: int
    needs_review: bool


class ClientCallsResponse(BaseModel):
    """One keyset page of this customer's conversations, newest first."""

    items: list[ClientCallRow]
    next_cursor: str | None
    has_more: bool
    total: int | None


__all__ = [
    "ClientAgentRow",
    "ClientCallRow",
    "ClientCallsResponse",
    "ClientDetailResponse",
    "ClientPageResponse",
    "ClientRowOut",
]
