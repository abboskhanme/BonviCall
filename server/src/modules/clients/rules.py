"""The client directory's vocabulary, window and cursor — pure, no database.

Ported from BonviZvonki ``modules/clients/application/directory.py`` (the
enums, the dataclasses and the filter) and from
``modules/clients/presentation/router.py`` (``_inclusive_end``,
``_key_or_error``). Nothing here imports the ORM, FastAPI or another module, so
every rule below is exercised by ``tests/test_clients_rules.py`` with no
session and no clock (CONVENTIONS.md §2).

════════════════════════════════════════════════════════════════
 WHAT A "CLIENT" IS HERE
════════════════════════════════════════════════════════════════

**One phone number and every conversation held with it.** Not a row in a
catalogue — BonviCall has no customer catalogue, and BonviZvonki's is empty
(0 rows, and not one ``calls.client_id`` set). The only reliable evidence
about a customer is the calls themselves.

THE KEY IS THE LAST 9 DIGITS. One person arrives as "+998 90 123-45-67",
"998901234567" and "901234567"; in Uzbekistan the last nine are unique, so the
grouping is on those (N37, CONVENTIONS.md §7). BonviCall already stores that
key on every call as ``calls.remote_number_key``, generated and indexed by the
database, so this module never writes the rule out again.

⚠️ ONE CONSEQUENCE OF THAT, STATED BECAUSE IT IS A REAL DIFFERENCE. The source
deliberately lets a SHORT PBX extension (``700``) be its own key: shorter than
nine, so nothing is trimmed off. BonviCall's key is NULL below nine digits, on
purpose and with its own measured reason — a 4-to-7-digit value matches the
tail of almost any number and marked strangers as colleagues (N37). So an
internal extension has no key here and **cannot appear in this directory at
all**. That is the right trade: the directory is about customers, and a column
that groups every long number under "700" is worse than one that omits the
switchboard.

INTERNAL CONVERSATIONS ARE OUT BY DEFAULT. Talking to a colleague is not a
customer; :class:`ClientScope` is how they are looked at separately. The filter
leans on ``calls.call_type``, which BonviCall decides from the line directory
at ingest (UC-25) and re-decides in the ``reclassify_calls`` job.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from enum import StrEnum
from typing import Any
from uuid import UUID


class ClientScope(StrEnum):
    """Who is in the list.

    ``CLIENTS`` is the default: everything except internal conversations. It is
    deliberately NOT a strict "external only" filter — unclassified rows
    (``call_type = 'unknown'``) can exist and being unclassified does not mean
    "not a customer", it means not yet decided. Hiding them quietly would make
    the list incomplete.

    ⚠️ The source has to write this as ``call_type IS NULL OR call_type <>
    'internal'`` and carries a comment about why: in SQL ``NULL <> 'internal'``
    is NULL, so unclassified rows vanish silently. BonviCall's ``call_type`` is
    a NOT NULL enum defaulting to ``unknown`` (UC-25 — an empty line directory
    yields ``unknown``, never ``external``), so the plain inequality is correct
    here and the NULL guard is dropped rather than translated.
    """

    CLIENTS = "clients"
    INTERNAL = "internal"
    ALL = "all"


class ClientSort(StrEnum):
    """What the directory is ordered by."""

    LAST_CALL = "last_call"
    CALLS = "calls"
    MISSED = "missed"
    TALK = "talk"
    SCORE = "score"
    NAME = "name"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


#: The page size the directory serves when the caller names none, and the
#: ceiling it will not go past. Same shape as ``core.pagination`` uses for
#: rows; a smaller ceiling than ``/calls`` because every row here is a grouped
#: aggregate over an unbounded number of calls, not a single row.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

#: The longest explicit range the directory will build, for the reason
#: ``activity.rules.MAX_WINDOW_DAYS`` gives: one pasted URL must not ask for a
#: decade. Same number, deliberately.
MAX_WINDOW_DAYS = 366


class WindowInvalid(ValueError):
    """The date range cannot be built. ``field_name`` says which bound is at fault.

    A plain ``ValueError`` rather than an ``AppError``: this module imports
    nothing from the project and the router turns it into the 400. Same shape
    as ``activity.rules.WindowInvalid``.
    """

    def __init__(self, field_name: str) -> None:
        self.field_name = field_name
        super().__init__(field_name)


class CursorInvalid(ValueError):
    """The cursor is not one this server issued."""


@dataclass(frozen=True, slots=True)
class ClientWindow:
    """The period the directory is asked about — whole Asia/Tashkent days.

    ⚠️ BOTH BOUNDS MAY BE ABSENT, and that is the difference from
    ``activity.rules.Window``. The activity report always covers a stated
    period, so its window is always bounded. The directory's natural default is
    "everything we have ever seen", because its first question is *who are our
    customers* rather than *what happened last week*. A window that silently
    defaulted to seven days would answer a different question than the one the
    page asks.

    ``since``/``until`` are the half-open instants the SQL uses;
    ``date_from``/``date_to`` are the inclusive local dates the answer is
    labelled with.
    """

    since: datetime | None
    until: datetime | None
    """**Exclusive** upper bound: local midnight AFTER ``date_to``."""
    date_from: date | None
    date_to: date | None
    """Inclusive — the last day the reader asked for."""

    @property
    def bounded(self) -> bool:
        return self.since is not None or self.until is not None


def client_window(
    *, date_from: date | None, date_to: date | None, zone: tzinfo
) -> ClientWindow:
    """Calendar dates to half-open instants. Either bound may be omitted.

    The CONVERSION is character for character the one
    ``activity.rules.activity_window`` performs — local midnight for the lower
    bound, local midnight after ``date_to`` for the upper — and
    ``tests/test_clients_rules.py`` asserts the two agree on a bounded range,
    so the two implementations cannot drift apart unnoticed. What differs is
    only what happens when a bound is missing, and that difference is the whole
    reason this function exists (see :class:`ClientWindow`).

    ⚠️ ``date_to`` is INCLUSIVE by construction. The source's router has an
    ``_inclusive_end`` helper because its filter is ``started_at <= date_to``
    and a bare date meant midnight, so "up to the 16th" lost the whole of the
    16th; its own comment warns that the helper must stay identical to the one
    in the analytics router or the two sections report different numbers for
    the same period. Taking calendar ``date`` values here and making ``until``
    exclusive deletes the helper and the risk with it.
    """
    if date_from is not None and date_to is not None:
        if date_from > date_to:
            raise WindowInvalid("date_from")
        if (date_to - date_from).days + 1 > MAX_WINDOW_DAYS:
            raise WindowInvalid("date_from")

    since = (
        datetime.combine(date_from, time.min, tzinfo=zone)
        if date_from is not None
        else None
    )
    until = (
        datetime.combine(date_to, time.min, tzinfo=zone) + timedelta(days=1)
        if date_to is not None
        else None
    )
    return ClientWindow(since=since, until=until, date_from=date_from, date_to=date_to)


@dataclass(frozen=True, slots=True)
class ClientFilter:
    """ONE filter for the list and for the card.

    ⚠️ Both must see the same window. If the card says "12 calls" where the
    list said something else, the reader has no way to know which to believe —
    and the tool built to prove a number is what destroys trust in it.
    """

    window: ClientWindow
    agent_ids: list[UUID] | None = None
    scope: ClientScope = ClientScope.CLIENTS
    search: str | None = None

    def widened(self) -> ClientFilter:
        """The same filter with the scope opened to everything.

        ⚠️ THE AGENT AND DATE CONDITIONS SURVIVE. Only ``scope`` changes — a
        salesperson's ``agent_ids`` stays pinned to themselves, so widening the
        cut can never open a colleague's customer.
        """
        return ClientFilter(
            window=self.window,
            agent_ids=self.agent_ids,
            scope=ClientScope.ALL,
            search=self.search,
        )


def is_client_key(raw: str) -> bool:
    """Whether a path segment can be a directory key at all.

    The key never reaches SQL as text (it is a bound parameter), but an exact
    shape shows the mistake early: ``/clients/undefined`` should get a
    comprehensible answer rather than an empty page.
    """
    cleaned = raw.strip()
    return bool(cleaned) and cleaned.isdigit()


def escape_like(text: str) -> str:
    """Turn ``ILIKE`` metacharacters into ordinary ones.

    Somebody typing ``%`` means the character, not the wildcard. Unescaped, a
    single ``%`` would match everything and switch the search off entirely.
    """
    for sign in ("\\", "%", "_"):
        text = text.replace(sign, f"\\{sign}")
    return text


def search_digits(text: str) -> str:
    """Only the digits of a search box, so "90 123" finds "+998 90 123 45 67"."""
    return "".join(char for char in text if char.isdigit())


# ── The cursor ────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DirectoryCursor:
    """The keyset marker for a page of the directory.

    ⚠️ IT IS NOT ``core.pagination.Cursor``, and the reason is structural
    rather than stylistic: that class ties the sort value to a ``uuid.UUID``
    row id, and **a grouped aggregate has no row id**. The group key IS the
    identity here — one row per phone key, by construction — so the phone key
    is what breaks the tie. The wire shape is deliberately the same
    (``{"k": [sort_value, tiebreak]}``, base64url, unpadded) so the two are
    visibly one idea rather than two.

    Keyset rather than ``OFFSET``, for the reason ``core/pagination.py`` gives
    and which applies here with more force: the aggregate is recomputed per
    page, so a call arriving mid-pass shifts every later page by one and the
    same customer is served twice.
    """

    sort_value: Any
    key: str
    """The group key — the customer's phone key."""

    def encode(self) -> str:
        payload = {"k": [_json_safe(self.sort_value), self.key]}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def decode(value: str) -> DirectoryCursor:
        try:
            padded = value + "=" * (-len(value) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            sort_value, key = payload["k"]
        except (ValueError, KeyError, TypeError, binascii.Error) as exc:
            # A tampered or truncated cursor is a client bug, not a server one,
            # and it is never answered by silently restarting from page one:
            # restarting is how a reader ends up paging the same rows forever.
            raise CursorInvalid("cursor") from exc
        if not isinstance(key, str):
            raise CursorInvalid("cursor")
        return DirectoryCursor(sort_value=sort_value, key=key)


def _json_safe(value: Any) -> Any:
    """Cursor values travel as JSON, so a datetime becomes ISO-8601."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


# ── The rows ──────────────────────────────────────────────────


@dataclass(slots=True)
class ClientRow:
    """One customer in the directory."""

    phone_key: str
    """The last 9 digits — the identifier for the list AND for the card.

    Named exactly as ``activity.schemas.MissedClientRow.phone_key`` names the
    same value, so the "customers who could not get through" list links
    straight into this card. Two names for one key is how two sections stop
    being able to point at each other.
    """
    name: str | None
    """The name to show.

    ⚠️ THE ORDER IS: the uploaded contact list first, the handset's own
    resolution last. The source states the reason for putting the provider's
    name last — it is frozen at the first synchronisation and may be stale.
    BonviCall's ``calls.contact_name`` is worse than stale: it is whatever
    *that one employee* had in *their* phone, so the same customer reads
    differently on two salespeople's calls (L3 — decoration, never identity).
    The uploaded dictionary is the one answer everybody sees.
    """
    phone: str | None
    code: str | None
    """The customer code, where the contact list carried one. None — unknown."""
    calls_total: int
    inbound: int
    outbound: int
    missed: int
    """Incoming and unanswered. The SAME definition the activity report uses:
    ``rejected`` counts here with ``missed`` — the phone rang and there was no
    conversation."""
    talk_seconds: int
    first_call_at: datetime | None
    """None — there was no contact inside the chosen period.

    No such row appears in the LIST (a group is built from at least one call),
    but one does on the CARD: a period is chosen there and an empty period does
    NOT mean "customer not found".
    """
    last_call_at: datetime | None
    agent_count: int
    main_agent_id: UUID | None
    main_agent_name: str | None
    avg_score: float | None
    scored: int
    """How many conversations were scored — what the average is over."""

    @property
    def missed_rate(self) -> float | None:
        """Missed as a percent of incoming. None when there were none.

        None rather than zero: "no incoming calls" and "no missed calls out of
        many" are different answers and the panel renders the first as a dash.
        """
        if not self.inbound:
            return None
        return round(self.missed / self.inbound * 100, 1)


@dataclass(slots=True)
class ClientAgent:
    """An employee who spoke to this customer."""

    agent_id: UUID
    full_name: str
    calls: int
    last_call_at: datetime


@dataclass(slots=True)
class ClientCall:
    """One conversation with this customer."""

    call_id: UUID
    started_at: datetime
    received_at: datetime
    duration_sec: int
    direction: str
    disposition: str
    call_type: str
    has_audio: bool
    agent_id: UUID
    agent_name: str
    score: int | None
    red_flag_count: int
    needs_review: bool


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "MAX_WINDOW_DAYS",
    "ClientAgent",
    "ClientCall",
    "ClientFilter",
    "ClientRow",
    "ClientScope",
    "ClientSort",
    "ClientWindow",
    "CursorInvalid",
    "DirectoryCursor",
    "SortOrder",
    "WindowInvalid",
    "client_window",
    "escape_like",
    "is_client_key",
    "search_digits",
]
