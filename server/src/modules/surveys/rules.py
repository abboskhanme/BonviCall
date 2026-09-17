"""Survey rules — pure functions, no session, no framework (CONVENTIONS.md §2).

Everything here is decidable without a database, which is what makes the
cadence window, the suppression window, the Telegram delete limit and the
rating-readiness gate testable as arithmetic rather than through five fixtures.

Ported from BonviZvonki ``modules/surveys/domain/entities.py``,
``modules/groups/domain/entities.py`` and the settings resolvers in
``modules/surveys/application/services.py``. Every measured number is kept, and
the reason each one is what it is is kept with it — translated, because a
comment here is English (§14). The Uzbek that stays is the ten red-flag
LABELS, and only because they are the wire contract: the key is what is stored
and the label is what a customer reads, and re-typing them here in English
would mean the panel and the bot showed different words for the same tick box.
Those labels are also the single reason this file is listed as an exception to
§14 in the module's own docstring rather than silently containing Uzbek.

⚠️ **This file may not import anything from ``src``**, and
``tests/test_layering.py::test_rules_modules_are_pure`` says so.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

# ═══ Vocabulary ════════════════════════════════════════════════════════════
#
# Plain strings in frozensets rather than PostgreSQL native enums. §10 requires
# a native enum for vocabulary the three PLATFORMS share (`capture_route`,
# `audio_missing_reason`); these are panel-only, and a native enum would mean
# three more entries in `core/enums.py::PG_ENUM_TYPES`, a file outside this
# port's remit. `call_analysis_state.failure_stage` set the precedent: a
# `String(16)` with a CHECK naming the legal values.

#: The bot's own membership of a chat, from Telegram's ``my_chat_member``.
BOT_STATUSES: frozenset[str] = frozenset(
    {"member", "administrator", "left", "kicked"}
)

#: The bot is out of the chat: nothing can be sent, and the row may be deleted.
GONE_BOT_STATUSES: frozenset[str] = frozenset({"left", "kicked"})

#: Who attached the employee. ``manual`` is load-bearing — see :func:`autobind_decision`.
BIND_SOURCES: frozenset[str] = frozenset({"auto", "manual"})

SURVEY_STATUSES: frozenset[str] = frozenset(
    {"pending", "sent", "opened", "completed", "expired", "failed"}
)

#: Nothing moves a survey out of these two.
TERMINAL_SURVEY_STATUSES: frozenset[str] = frozenset({"completed", "expired"})

SURVEY_CHANNELS: frozenset[str] = frozenset({"telegram_group", "sms"})

RESOLUTIONS: frozenset[str] = frozenset({"yes", "partial", "no"})

CSAT_MIN = 1
CSAT_MAX = 5

#: Matches the ``surveys.token`` column width.
SURVEY_TOKEN_MAX_LEN = 64

#: A respondent hash is a full SHA-256 hex digest. Pinned at exactly 64 and not
#: "between 16 and 64" as BonviZvonki's request schema has it: a producer that
#: sent a truncated hash would never collide with a full one for the same
#: person, and `uq_response_per_respondent` would stop deduplicating silently —
#: which is the precise failure the anonymous-hash design exists to prevent.
RESPONDENT_HASH_LEN = 64

#: Comment ceiling on the wire. The customer-facing app caps itself lower (500)
#: so the counter is reachable; this is the server's own bound.
COMMENT_MAX_LEN = 2000


# ═══ Measured constants ════════════════════════════════════════════════════

#: Fallback cadence: a group is asked once every 14 days.
#: ⚠️ A FALLBACK, not the source of truth — the admin owns ``survey.period_days``.
DEFAULT_PERIOD_DAYS = 14

#: Fallback suppression window: not asked again inside 10 days.
DEFAULT_SUPPRESSION_DAYS = 10

#: Fallback rating gate.
#:
#: ⚠️ **Never read this constant directly to decide whether a rating is ready.**
#: BonviZvonki's own comment records what happens: the admin sets 8 in Settings,
#: the code keeps comparing against the constant, and the setting "looks like it
#: works" while affecting nothing. ``resolve_min_responses`` is the only reader.
DEFAULT_MIN_RESPONSES = 5

#: How long a deep-link token is accepted.
SURVEY_TOKEN_TTL_DAYS = 7

#: Fallback: how long the survey message stays in the group.
DEFAULT_MESSAGE_TTL_HOURS = 24

#: ⚠️ **A Telegram restriction, not a setting.** A bot cannot delete its own
#: message more than 48 hours after sending it. A larger configured value would
#: promise "it will be removed" while the message stays in the customer's group
#: for ever.
TELEGRAM_DELETE_LIMIT_HOURS = 48

#: The ceiling actually applied to ``survey.message_ttl_hours``.
#:
#: 47 and not 48, and this is a FIX to the source. BonviZvonki clamps to exactly
#: ``TELEGRAM_DELETE_LIMIT_HOURS``; the cleanup queue then becomes eligible at
#: ``sent_at + 48h``, which is the exact instant Telegram stops permitting the
#: delete. The documented maximum was the one value guaranteed to fail. One
#: hour of margin costs nothing and makes the maximum work.
MESSAGE_TTL_CEILING_HOURS = TELEGRAM_DELETE_LIMIT_HOURS - 1

#: Largest bulk patch accepted in one request, and therefore the chunk size the
#: panel splits a selection into.
BULK_GROUP_LIMIT = 200

#: Ceiling on one bot worklist page. BonviZvonki has none on any of the three,
#: and polls them repeatedly against ~1000 groups.
WORKLIST_LIMIT = 200

#: Candidate Telegram user ids accepted by one autobind call.
AUTOBIND_CANDIDATE_LIMIT = 200


# ═══ The red-flag registry ═════════════════════════════════════════════════
#
# One flat list, multi-select. Not split into categories: the customer ticks
# whatever applies in a private chat.
#
# This is the SINGLE SOURCE. Neither the bot nor the panel keeps a copy —
# `GET /surveys/red-flags` returns this list, so a new criterion appears
# everywhere without a frontend deploy.
#
# ⚠️ **A key here is NEVER renamed**, only added to. The keys are stored in
# `survey_responses.red_flags`, and renaming one silently changes what every
# historical answer meant.

RED_FLAGS: tuple[tuple[str, str], ...] = (
    ("rude", "Qo'pol muomala qildi"),
    ("no_answer", "Telefonni ko'tarmadi"),
    ("late_reply", "Juda kech javob berdi"),
    ("broken_promise", "Va'da berib bajarmadi"),
    ("wrong_price", "Narxni noto'g'ri aytdi"),
    ("late_delivery", "Yetkazib berish kechikdi"),
    ("wrong_order", "Buyurtma xato keldi"),
    ("bad_quality", "Tovar sifati yomon"),
    ("no_document", "Hujjat berilmadi yoki kechikdi"),
    ("pushy", "Keraksiz mahsulotni majburladi"),
)

RED_FLAG_LABELS: dict[str, str] = dict(RED_FLAGS)


class UnknownRedFlag(ValueError):
    """Raised by :func:`normalize_red_flags`; the caller turns it into a 422."""

    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        super().__init__(", ".join(sorted(set(keys))))


def normalize_red_flags(keys: list[str] | None) -> list[str]:
    """Validate the ticked keys and drop duplicates, keeping the order.

    Order is kept because the sequence the customer ticked in carries a little
    information and costs nothing to preserve. An unknown key raises rather
    than being dropped: silently discarding it would store an answer that does
    not say what the customer said.
    """
    if not keys:
        return []
    unknown = [key for key in keys if key not in RED_FLAG_LABELS]
    if unknown:
        raise UnknownRedFlag(unknown)
    seen: dict[str, None] = {}
    for key in keys:
        seen.setdefault(key, None)
    return list(seen)


# ═══ Tokens and the anonymous hash ═════════════════════════════════════════


def new_token() -> str:
    """A fresh deep-link token: ``t.me/<bot>?start=srv_<token>``.

    ``secrets`` and never ``random``: this token is a real access key — whoever
    holds it can answer that group's survey — and ``random`` is seeded
    predictably.

    BonviZvonki writes ``secrets.token_urlsafe(24)[:64]``; the slice is a no-op
    because 24 bytes render as 32 characters, so it is dropped here rather than
    copied as decoration that implies a truncation that never happens.
    """
    return secrets.token_urlsafe(24)


def respondent_hash(token: str, telegram_user_id: int) -> str:
    """``sha256(token + ':' + telegram_user_id)`` — the anonymous dedup key.

    ⚠️ This must stay **byte-for-byte identical** to whatever the bot computes.
    If the two ever disagree, ``uq_response_per_respondent`` stops deduplicating
    and one person can rate the same survey repeatedly, with nothing raising.

    The server never receives a Telegram identifier in normal operation — the
    bot hashes it — so this function exists for the Mini App path, where the
    signed ``initData`` carries the id and the hash is computed here and then
    immediately forgotten.
    """
    digest = hashlib.sha256(f"{token}:{telegram_user_id}".encode()).hexdigest()
    return digest[:RESPONDENT_HASH_LEN]


# ═══ Settings resolvers ════════════════════════════════════════════════════
#
# Each takes the raw settings value and answers with something usable. They are
# here and not in the service because "a text value in a numeric setting falls
# back to the default" is a rule worth testing without a database.


def resolve_positive_int(value: object, fallback: int) -> int:
    """A positive int from a settings value, or ``fallback``.

    Text, ``0`` and negatives all fall back. BonviZvonki's reason, kept: a
    rating that appears after one response is exactly as wrong as one that
    never appears, so a nonsense threshold must land on the documented default
    rather than on whatever ``int()`` happened to produce.
    """
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def resolve_message_ttl_hours(value: object) -> int:
    """Hours the survey message stays in the group. ``0`` means never remove it.

    Clamped to :data:`MESSAGE_TTL_CEILING_HOURS`. An admin who types 1000 is
    silently lowered rather than refused, because the alternative is a settings
    page that rejects a number and a message that stays in the customer's group
    for ever either way.
    """
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_MESSAGE_TTL_HOURS
    if parsed <= 0:
        return 0
    return min(parsed, MESSAGE_TTL_CEILING_HOURS)


def as_bool(value: object) -> bool:
    """A boolean from JSONB, from an int, or from the strings people type.

    ``app_settings.value`` is JSONB and holds a real boolean, so this is mostly
    ``bool(value)``. The string arm is kept because a value that arrives as
    ``"false"`` — which is truthy in Python — would turn a feature flag that is
    off into one that is on, and that is the single worst direction for this
    particular flag to fail in.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on", "ha"}
    return False


# ═══ Eligibility: may this group be surveyed right now? ════════════════════


@dataclass(frozen=True)
class Block:
    """Why a group is not being surveyed. ``reason`` is machine, stable."""

    reason: str
    #: True when ``force=True`` clears it. Structural blocks never are.
    bypassable: bool


#: A group with no employee: we would not know whose rating this is.
BLOCK_NOT_BOUND = "group_not_bound"
#: Parked, or the bot is out of the chat.
BLOCK_INACTIVE = "group_inactive"
#: Asked too recently.
BLOCK_SUPPRESSED = "survey_suppressed"


def structural_block(
    *, agent_id_present: bool, is_active: bool, bot_status: str
) -> Block | None:
    """The blocks ``force=True`` does **not** clear.

    Kept separate from the temporal one on purpose. "Send to everyone now"
    means ignore the calendar; it does not mean invent an employee to attribute
    a rating to, or post into a chat the bot was thrown out of.
    """
    if not agent_id_present:
        return Block(BLOCK_NOT_BOUND, bypassable=False)
    if not is_active or bot_status in GONE_BOT_STATUSES:
        return Block(BLOCK_INACTIVE, bypassable=False)
    return None


def days_since(last: datetime, now: datetime) -> int:
    """Whole days between two instants, never negative.

    ``(now - last).days`` — which is what BonviZvonki uses — floors toward
    negative infinity, so a ``last`` a few seconds in the future (clock skew
    between the app server and the database, or a row written by a concurrent
    transaction) yields ``-1`` and the customer-facing sentence reads "the last
    survey was created -1 days ago, 11 days remain". Computed from seconds and
    floored at zero instead.
    """
    elapsed = (now - last).total_seconds()
    if elapsed <= 0:
        return 0
    return int(elapsed // 86_400)


def suppression_block(
    last: datetime | None, now: datetime, window_days: int
) -> Block | None:
    """The temporal block: asked inside the window, so not asked again.

    ``None`` when there is no previous survey, or the window has passed, or the
    window is zero. Cleared by ``force=True``.
    """
    if last is None or window_days <= 0:
        return None
    if days_since(last, now) >= window_days:
        return None
    return Block(BLOCK_SUPPRESSED, bypassable=True)


def days_remaining(last: datetime, now: datetime, window_days: int) -> int:
    """How many whole days until this group may be asked again. Never negative."""
    return max(0, window_days - days_since(last, now))


# ═══ Automatic binding ═════════════════════════════════════════════════════

#: The admin holds this row; automation did not touch it.
AUTOBIND_MANUAL = "manual"
#: An employee was recognised in the chat (or the previous one was kept).
AUTOBIND_MATCHED = "matched"
#: Nobody was recognised and the row was not bound before.
AUTOBIND_NO_AGENT = "no_agent"


@dataclass(frozen=True)
class AutobindDecision:
    """What automatic binding decided, and why."""

    #: ``None`` leaves whatever is already on the row.
    agent_id: object | None
    reason: str
    #: False means "write nothing", which is what ``manual`` requires.
    write: bool


def autobind_decision(
    *, bound_by: str | None, current_agent_id: object | None, matched_agent_id: object | None
) -> AutobindDecision:
    """Decide a binding without touching the database.

    ⚠️ **``manual`` is checked FIRST and wins outright.** This is the most
    infuriating class of bug the source names: without it, the bot's next pass
    silently undoes the correction an admin just made, and the admin has no way
    to see that it happened — the row simply drifts back overnight.

    When nobody is recognised but the row already has an employee, the employee
    is KEPT. Today perhaps only the customer wrote in the chat; that is not
    evidence the salesperson changed.
    """
    if bound_by == AUTOBIND_MANUAL:
        return AutobindDecision(agent_id=None, reason=AUTOBIND_MANUAL, write=False)
    if matched_agent_id is not None:
        return AutobindDecision(
            agent_id=matched_agent_id, reason=AUTOBIND_MATCHED, write=True
        )
    if current_agent_id is not None:
        return AutobindDecision(agent_id=None, reason=AUTOBIND_MATCHED, write=False)
    return AutobindDecision(agent_id=None, reason=AUTOBIND_NO_AGENT, write=False)


# ═══ The rating, and when it may be shown ══════════════════════════════════


@dataclass(frozen=True)
class Rating:
    """The headline figure and whether it is allowed to be shown yet."""

    average: float | None
    count: int
    ready: bool
    min_responses: int


def rating(total: int, average: float | None, min_responses: int) -> Rating:
    """Average, but only once enough answers exist to mean anything.

    ⚠️ ``average`` is ``None`` — never ``0.0`` — while ``ready`` is False. A
    zero would be read as "rated badly" by every chart that draws it, and the
    whole point of the gate is that one customer's bad morning must not become
    an employee's published score.
    """
    if total < min_responses or average is None:
        return Rating(
            average=None, count=total, ready=False, min_responses=min_responses
        )
    return Rating(
        average=round(float(average), 2),
        count=total,
        ready=True,
        min_responses=min_responses,
    )


def distribution(counts: dict[int, int]) -> dict[str, int]:
    """``{"1": n, ... "5": n}`` with every star present, zero-filled.

    Filled rather than sparse so the panel's bar chart has five bars whatever
    came back; a missing key would render as a gap that reads like a bug.
    """
    return {str(star): counts.get(star, 0) for star in range(CSAT_MIN, CSAT_MAX + 1)}


def response_rate(sent: int, answered: int) -> float | None:
    """Percentage of surveys sent in the window that were answered in it.

    ⚠️ **The two halves are counted on different clocks, deliberately.** The
    denominator is surveys whose ``sent_at`` falls in the window; the numerator
    is how many of *those* got an answer whose ``responded_at`` also falls in
    it. BonviZvonki's earlier version used ``status == completed`` for the
    numerator, which produced ``count: 0`` next to ``response_rate: 100.0``
    whenever a survey went out on one day and was answered on the next.

    ``None`` and not ``0.0`` when nothing was sent: there is no basis to
    compute a rate from, and 0 % reads as "nobody answered".
    """
    if sent <= 0:
        return None
    return round(answered * 100.0 / sent, 1)


# ═══ Windows ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Period:
    """A half-open instant range ``[start, end)`` (§6)."""

    start: datetime
    end: datetime


def survey_period(now: datetime, period_days: int) -> Period:
    """The stretch of service a new survey asks the customer to rate."""
    return Period(start=now - timedelta(days=period_days), end=now)


#: The longest explicit feedback range. Matches ``activity.rules.MAX_WINDOW_DAYS``
#: for the reason that module gives: an explicit date pair needs its own bound
#: or one pasted URL asks for five years of ratings.
MAX_WINDOW_DAYS = 366

#: The default feedback window. Ninety days, not seven: a group is asked at
#: most every fourteen days, so a week-long window over a fleet this size
#: routinely contains nothing at all and the page reads as broken.
DEFAULT_WINDOW_DAYS = 90


@dataclass(frozen=True)
class ReportWindow:
    """One feedback window, resolved to whole Asia/Tashkent calendar days.

    ``since``/``until`` are the half-open instants the SQL uses; ``date_from``
    and ``date_to`` are the inclusive local dates the answer is labelled with.
    """

    since: datetime
    until: datetime
    date_from: date
    date_to: date
    days: int


class WindowInvalid(ValueError):
    """The range cannot be built. ``field_name`` says which bound is at fault.

    A plain ``ValueError`` rather than an ``AppError``: this module imports
    nothing from the project, and the router turns it into the 400.
    """

    def __init__(self, field_name: str) -> None:
        self.field_name = field_name
        super().__init__(field_name)


def report_window(
    *,
    days: int,
    date_from: date | None,
    date_to: date | None,
    today: date,
    zone: tzinfo,
) -> ReportWindow:
    """Whole local days, half-open instants, ``date_to`` inclusive.

    The same definition ``activity.rules.activity_window`` uses, and for the
    same reasons — it is not re-derived here, it is the house rule applied to a
    second report.

    What it FIXES against BonviZvonki's ``_period`` is specific and was
    measured there: theirs takes ``datetime`` bounds and does not align them to
    local days, so the frontend's local midnight arrives as ``T19:00:00Z`` in
    UTC+5 — the PREVIOUS day — and silently adds a whole extra day to the
    range. One agent's rating for one day came out as 3.8 on the ratings page
    and 3.0 on the dashboard: a 0.8 gap on a five-point scale, from nothing but
    a timezone. Their patch for it was to special-case a ``date_to`` whose time
    is exactly midnight and stretch it by ``+1 day - 1 microsecond``, which
    then makes a caller who genuinely means that instant lose a day instead.

    Calendar ``date`` bounds delete the whole class of problem: ``until`` is
    local midnight AFTER ``date_to``, so inclusivity is structural.
    """
    if date_from is None and date_to is None:
        date_to = today
        date_from = date_to - timedelta(days=days - 1)
    elif date_from is None:
        assert date_to is not None
        date_from = date_to - timedelta(days=days - 1)
    elif date_to is None:
        date_to = max(today, date_from)

    assert date_from is not None and date_to is not None
    if date_from > date_to:
        raise WindowInvalid("date_from")
    span = (date_to - date_from).days + 1
    if span > MAX_WINDOW_DAYS:
        raise WindowInvalid("date_from")

    since = datetime.combine(date_from, time.min, tzinfo=zone)
    until = datetime.combine(date_to, time.min, tzinfo=zone) + timedelta(days=1)
    return ReportWindow(
        since=since, until=until, date_from=date_from, date_to=date_to, days=span
    )


def token_expiry(now: datetime) -> datetime:
    """When a freshly minted token stops being accepted."""
    return now + timedelta(days=SURVEY_TOKEN_TTL_DAYS)


def message_delete_deadline(now: datetime, ttl_hours: int) -> datetime | None:
    """Messages posted before this instant are due for removal.

    ``None`` when the TTL is 0, which means "never remove them" and must not be
    read as "remove everything sent before now".
    """
    if ttl_hours <= 0:
        return None
    return now - timedelta(hours=ttl_hours)


def ilike_escape(needle: str) -> str:
    """Escape ``\\``, ``%`` and ``_`` before they go into an ``ILIKE`` pattern.

    Without it a customer whose group title contains ``%`` matches every row,
    and a search for ``_`` removes the filter rather than applying it. The
    source has this helper on the survey search and never applied it to the
    group search — the two sibling modules disagreed, and this port does not.

    The backslash is escaped first, or escaping the other two would double-
    escape their new backslashes.
    """
    return needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = [
    "AUTOBIND_MANUAL",
    "AUTOBIND_MATCHED",
    "AUTOBIND_NO_AGENT",
    "AUTOBIND_CANDIDATE_LIMIT",
    "BIND_SOURCES",
    "BLOCK_INACTIVE",
    "BLOCK_NOT_BOUND",
    "BLOCK_SUPPRESSED",
    "BOT_STATUSES",
    "BULK_GROUP_LIMIT",
    "COMMENT_MAX_LEN",
    "CSAT_MAX",
    "CSAT_MIN",
    "DEFAULT_MESSAGE_TTL_HOURS",
    "DEFAULT_MIN_RESPONSES",
    "DEFAULT_PERIOD_DAYS",
    "DEFAULT_SUPPRESSION_DAYS",
    "DEFAULT_WINDOW_DAYS",
    "GONE_BOT_STATUSES",
    "MAX_WINDOW_DAYS",
    "MESSAGE_TTL_CEILING_HOURS",
    "RED_FLAGS",
    "RED_FLAG_LABELS",
    "RESOLUTIONS",
    "RESPONDENT_HASH_LEN",
    "SURVEY_CHANNELS",
    "SURVEY_STATUSES",
    "SURVEY_TOKEN_MAX_LEN",
    "SURVEY_TOKEN_TTL_DAYS",
    "TELEGRAM_DELETE_LIMIT_HOURS",
    "TERMINAL_SURVEY_STATUSES",
    "WORKLIST_LIMIT",
    "AutobindDecision",
    "Block",
    "Period",
    "Rating",
    "ReportWindow",
    "UnknownRedFlag",
    "WindowInvalid",
    "as_bool",
    "autobind_decision",
    "days_remaining",
    "days_since",
    "distribution",
    "ilike_escape",
    "message_delete_deadline",
    "new_token",
    "normalize_red_flags",
    "rating",
    "report_window",
    "resolve_message_ttl_hours",
    "resolve_positive_int",
    "respondent_hash",
    "response_rate",
    "structural_block",
    "suppression_block",
    "survey_period",
    "token_expiry",
]
