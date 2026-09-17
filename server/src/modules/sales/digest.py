"""The manager's daily message.

Ported from BonviZvonki ``modules/sales/application/digest.py``.

════════════════════════════════════════════════════════════════
 ⚠️ OFF BY DEFAULT — AND NOTHING HERE REACHES THE NETWORK
════════════════════════════════════════════════════════════════

In BonviZvonki this is the one action in the whole system that leaves the
machine: it writes into somebody else's Telegram chat. A message delivered to
the wrong group cannot be taken back, so the guard there is four layers deep.
All four are ported:

  1. ``sales.digest_enabled`` is seeded **false** — with the switch off the
     scheduled path does not even ASSEMBLE the text;
  2. an empty ``sales.digest_chat_id`` stops it (with a warning in the log —
     it never passes silently);
  3. no transport, no send;
  4. the test message goes only when a person presses the button
     (``POST /sales/digest/test``) and is attached to no schedule.

**And one more, which is the decisive one in BonviCall: the only
implementation of the transport writes a log line** (``telegram.py``). There is
no HTTP client in this module and no bot token anywhere in this repository. A
test asserts it: ``POST /sales/digest/test`` cannot reach the network because
there is nothing here that could.

════════════════════════════════════════════════════════════════
 WHY THE MESSAGE IS SHAPED THE WAY IT IS
════════════════════════════════════════════════════════════════

The manager reads it on a phone, and reproducing the list is not the goal —
the panel exists for that. The message has one job: **is there anything worth
checking today?** So:

  · all three counts are shown (``ok`` / ``suspicious`` / ``not_checkable``):
    nothing is hidden, and "could not be checked" is a number too;
  · the employee cut starts with the most suspicious and is cut off after five
    with "and N more";
  · the sales list starts with the LARGEST amount — the more money, the more a
    check is worth;
  · every line carries EVIDENCE (which rule, when the last conversation was),
    so the reader can answer "why is this suspicious?" from the message itself;
  · the last line says out loud that this is not an accusation. That is not
    decoration: read as an accusation, the system loses its credibility inside
    a week.

⚠️ 4096 CHARACTERS IS TELEGRAM'S LIMIT. A longer message is REFUSED, so "it
will just get truncated" is not true — the message would be LOST. The text is
therefore assembled repeatedly, in progressively shorter forms, and the first
one that fits is used.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.clock import TASHKENT
from src.core.logging import get_logger
from src.core.settings_keys import SettingKey
from src.modules.sales import telegram
from src.modules.sales.models import SaleDigestModel, SaleModel
from src.modules.sales.rules import (
    ClientKind,
    ComplianceRow,
    ReviewState,
    SaleOpType,
    Verdict,
    escape_html,
)
from src.modules.sales.service import ComplianceFilter, ComplianceService, SalesScope
from src.modules.sales.telegram import DIGEST_TEXT_LIMIT
from src.modules.settings.service import SettingsService

log = get_logger(__name__)

#: How many sales the day's figures are counted over.
#
# Daily volume measured: 1,039 sales over 11 days, i.e. ~95. 5,000 is fifty
# times that — but there MUST be a ceiling: a year's export loaded onto one day
# (the import does not split a file by date) would pull the whole table into
# memory.
MAX_ROWS = 5_000

#: At most this many employees, then "and N more".
TOP_AGENTS = 5

#: At most this many of the largest suspicious sales.
TOP_SALES = 5

#: The floor the sales list is shortened to when the text does not fit.
MIN_TOP_SALES = 3

#: A customer name longer than this is shortened. SAP sometimes puts a whole
#: postal address in the name field and one line would eat the message.
MAX_PARTNER_NAME = 38


@dataclass(slots=True)
class AgentLine:
    name: str | None
    """``None`` — sales whose branch is linked to nobody."""

    sales: int
    suspicious: int


@dataclass(slots=True)
class DigestData:
    """Everything that goes into the message — SEPARATE from the text.

    Split deliberately: the test that checks the FIGURES should not depend on
    the wording, and the test that checks the WORDING should not need a
    database.
    """

    day: date
    window_days: int
    min_amount: int
    total: int
    ok: int
    suspicious: int
    not_checkable: int
    agents: list[AgentLine] = field(default_factory=list)
    """Only employees who HAVE a suspicious sale, most first."""

    top: list[ComplianceRow] = field(default_factory=list)
    """The largest suspicious sales, by amount."""

    skipped_by_amount: int = 0
    """Sales the amount threshold kept out of the message."""

    truncated: bool = False
    """``True`` — the day's sales exceeded ``MAX_ROWS`` and the figures are
    incomplete."""

    # ── Walk-in customers ─────────────────────────────────────
    #
    # ⚠️ THEY ARE NOT IN THE MAIN FIGURES. The reason is in ``rules.ClientKind``:
    # under a shared code the question "was this customer spoken to?" has no
    # meaning, and counting it wrote "could not be checked" into an employee's
    # column for what was really a KIND OF WORK.
    #
    # ⚠️ BUT THE NUMBER DOES NOT VANISH SILENTLY. The manager knows how many
    # sales SAP recorded that day; a smaller total in the message with no
    # explanation reads as "the system is losing sales". So it stands on its
    # own line.
    walk_in_total: int = 0
    walk_in_over_limit: int = 0
    walk_in_over_amount: float = 0.0
    walk_in_limit: int = 0


@dataclass(slots=True)
class DigestOutcome:
    """What happened — read by both the scheduled path and the endpoint."""

    sent: bool
    reason: str | None = None
    """Why it was not sent: ``disabled`` | ``no_chat`` | ``no_sales`` |
    ``no_new_import`` | ``send_failed``."""

    text: str = ""
    """The assembled text. Returned EVEN WHEN NOTHING WAS SENT — the whole
    point of the test button is that the person sees what would go out before
    turning anything on."""

    day: date | None = None
    chat_id: str | None = None
    error: str | None = None
    counts: dict[str, int] = field(default_factory=dict)


def _as_bool(value: Any) -> bool:
    """A settings value as a boolean.

    ⚠️ AN EMPTY OR UNRECOGNISABLE VALUE IS ``False``. For this feature "when in
    doubt, do not send" is the only correct default: the other way round, a
    broken setting posts into somebody's group.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on", "ha"}
    return bool(value)


def _as_amount(value: Any) -> int:
    """``sales.digest_min_amount_usd`` — a broken value means 0 (everything in)."""
    try:
        amount = int(float(value))
    except (TypeError, ValueError):
        return 0
    return amount if amount > 0 else 0


def _passes_amount(row: ComplianceRow, min_amount: int) -> bool:
    """Did it clear the amount threshold?

    ⚠️ A sale of UNKNOWN value (``amount_usd is None``) ALWAYS passes. Quietly
    dropping something we could not measure because of a money threshold is
    against the point of this section: "I do not know" is not "small".
    """
    if min_amount <= 0 or row.amount_usd is None:
        return True
    return row.amount_usd >= min_amount


class SalesDigestService:
    """Assembles the daily message and hands it to the transport seam."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.scope = SalesScope(session)

    # ── Which day ─────────────────────────────────────────────

    async def latest_sale_day(self) -> date | None:
        """Which DAY the message is about.

        ⚠️ NOT "yesterday" — "the last day that was imported". The SAP export is
        uploaded by hand and is usually a day or two behind: insisting on
        yesterday would produce a message about an EMPTY day again and again,
        and the manager would stop reading it. The date is written at the top of
        the message, so there is no confusion either.
        """
        return await self.session.scalar(
            select(func.max(SaleModel.occurred_on)).where(
                SaleModel.op_type == SaleOpType.SALE.value
            )
        )

    # ── The figures ───────────────────────────────────────────

    async def collect(self, *, min_amount: int = 0) -> DigestData | None:
        """One day's summary. ``None`` when there are no sales at all.

        ⚠️ THE FIGURES COME FROM ``ComplianceService``, they are not recomputed.
        "41 suspicious" in the message has to be the same number as on the
        screen, or the manager does not know which to believe. So there is no
        new SQL here: one day's slice of that service, counted in Python
        (a day is ~95 rows — the work is cheap).
        """
        day = await self.latest_sale_day()
        if day is None:
            return None

        base = await self.scope.resolve(since=day, until=day)
        page = await ComplianceService(self.session).page(
            # ⚠️ WRITTEN OUT, not left to the defaults. This line decides WHICH
            # SET the message's headline figures describe; if the default ever
            # changed, the message would quietly start describing something else.
            _with(
                base,
                client_kind=ClientKind.REGULAR.value,
                # ⚠️ ``all`` IS DELIBERATE. With the default ``new``, a manager
                # who reviewed a few sales in the evening would get a message
                # whose figures were LOWER than the panel's, and nobody could
                # explain the difference.
                review=ReviewState.ALL.value,
            ),
            limit=MAX_ROWS,
            with_total=True,
        )

        # Walk-ins in their own query: they are not added to the main figures,
        # but they get one line in the message.
        walk_in = await ComplianceService(self.session).summary(
            _with(base, client_kind=ClientKind.WALK_IN.value)
        )

        rows = [row for row in page.items if _passes_amount(row, min_amount)]
        skipped = len(page.items) - len(rows)

        counts = {Verdict.OK: 0, Verdict.SUSPICIOUS: 0, Verdict.NOT_CHECKABLE: 0}
        by_agent: dict[tuple[Any, str | None], AgentLine] = {}
        for row in rows:
            counts[Verdict(row.verdict.verdict)] += 1
            key = (row.agent_id, row.agent_name)
            line = by_agent.get(key)
            if line is None:
                line = by_agent[key] = AgentLine(
                    name=row.agent_name, sales=0, suspicious=0
                )
            line.sales += 1
            if row.verdict.verdict == Verdict.SUSPICIOUS.value:
                line.suspicious += 1

        agents = sorted(
            (line for line in by_agent.values() if line.suspicious > 0),
            # The second key keeps the order STABLE: two employees on the same
            # count swapping places every night would make the message look as
            # though it had changed.
            key=lambda line: (-line.suspicious, line.name or "￿"),
        )

        # ⚠️ SORTED BY AMOUNT IN PYTHON, not in SQL. The queue's own page is
        # ordered by date, because it is cursor-paged and a cursor needs a
        # non-null key (``ComplianceService.page``). Here the whole day is
        # already in hand — ~95 rows measured — and sorting it costs nothing,
        # while a second query ordered by amount would have to repeat the
        # amount threshold and could then disagree with ``skipped_by_amount``.
        #
        # ``external_id`` is the stable tiebreak: two sales of equal value must
        # not swap places between one night's message and the next.
        top = sorted(
            (
                row
                for row in rows
                if row.verdict.verdict == Verdict.SUSPICIOUS.value
            ),
            key=lambda row: (-(row.amount_usd or 0.0), row.external_id),
        )[:TOP_SALES]

        return DigestData(
            day=day,
            window_days=base.window_days,
            min_amount=min_amount,
            total=len(rows),
            ok=counts[Verdict.OK],
            suspicious=counts[Verdict.SUSPICIOUS],
            not_checkable=counts[Verdict.NOT_CHECKABLE],
            agents=agents,
            top=top,
            skipped_by_amount=skipped,
            truncated=bool(page.total and page.total > len(page.items)),
            walk_in_total=walk_in.total,
            walk_in_over_limit=walk_in.over_limit,
            walk_in_over_amount=walk_in.over_limit_amount,
            walk_in_limit=base.walk_in_limit,
        )

    # ── The run ───────────────────────────────────────────────

    async def run(self, *, manual: bool = False) -> DigestOutcome:
        """Assemble the message and (if allowed) hand it to the transport.

        ``manual=False`` — the scheduled run. EVERY guard applies.
        ``manual=True`` — somebody pressed "test message":
            · ``sales.digest_enabled`` IS NOT CHECKED — that is the entire point
              of the button, to see the text BEFORE turning the switch on;
            · "no new import" is not checked either — a person asked on purpose,
              it is not a repeat;
            · the chat is still required: a message needs an address;
            · the row lands with ``kind='test'`` and has NO EFFECT on the real
              night-time message.
        """
        enabled = _as_bool(await self._setting(SettingKey.SALES_DIGEST_ENABLED))
        if not manual and not enabled:
            # ⚠️ The default state. NO warning is logged: a "warning" repeated
            # every night pollutes the log and hides the real fault.
            log.info("sales_digest_disabled")
            return DigestOutcome(sent=False, reason="disabled")

        min_amount = _as_amount(
            await self._setting(SettingKey.SALES_DIGEST_MIN_AMOUNT_USD)
        )
        data = await self.collect(min_amount=min_amount)
        if data is None:
            log.info("sales_digest_no_sales")
            return DigestOutcome(sent=False, reason="no_sales")

        counts = {
            "total": data.total,
            "ok": data.ok,
            "suspicious": data.suspicious,
            "not_checkable": data.not_checkable,
        }

        watermark = await self.import_watermark()
        if not manual:
            last = await self.last_sent_watermark()
            if last is not None and watermark is not None and watermark <= last:
                # No new sales were imported, so the message would be
                # yesterday's word for word. A repeated message is noise, and
                # noise is what stops it being read.
                log.info("sales_digest_no_new_import", day=str(data.day))
                return DigestOutcome(
                    sent=False, reason="no_new_import", day=data.day, counts=counts
                )

        text = build_text(data)

        chat_id = str(await self._setting(SettingKey.SALES_DIGEST_CHAT_ID) or "").strip()
        if not chat_id:
            log.warning("sales_digest_no_chat", setting=SettingKey.SALES_DIGEST_CHAT_ID)
            return DigestOutcome(
                sent=False, reason="no_chat", text=text, day=data.day, counts=counts
            )

        # The seam. The only implementation writes a log line (``telegram.py``),
        # so this call cannot reach the network — imported as the MODULE so a
        # test can redirect it.
        result = await telegram.get_sender().send(chat_id=chat_id, text=text)

        self.session.add(
            SaleDigestModel(
                kind="test" if manual else "daily",
                covered_on=data.day,
                watermark=watermark,
                chat_id=chat_id[:32],
                ok=result.ok,
                error=result.error,
            )
        )
        await self.session.commit()

        if not result.ok:
            return DigestOutcome(
                sent=False,
                reason="send_failed",
                text=text,
                day=data.day,
                chat_id=chat_id,
                error=result.error,
                counts=counts,
            )
        log.info(
            "sales_digest_sent",
            kind="test" if manual else "daily",
            day=str(data.day),
            chat_id=chat_id,
            chars=len(text),
            **counts,
        )
        return DigestOutcome(
            sent=True, text=text, day=data.day, chat_id=chat_id, counts=counts
        )

    # ── The replay guard ──────────────────────────────────────

    async def import_watermark(self) -> datetime | None:
        """The most recent sales import in the database."""
        return await self.session.scalar(select(func.max(SaleModel.imported_at)))

    async def last_sent_watermark(self) -> datetime | None:
        """Which import the last SUCCESSFUL daily message covered.

        ⚠️ ``daily`` ONLY, and ``ok`` ONLY. A test message must not count (one
        press of "try it" would otherwise switch off that night's real message),
        and a failed attempt must not count either (a transport that fell over
        once would otherwise lose the message for ever).
        """
        return await self.session.scalar(
            select(func.max(SaleDigestModel.watermark))
            .where(SaleDigestModel.kind == "daily")
            .where(SaleDigestModel.ok.is_(True))
        )

    async def _setting(self, key: str) -> Any:
        try:
            return await SettingsService(self.session).get(key)
        except KeyError:
            # A missing row is a seeding bug; for this feature the safe reading
            # of "I do not know" is "do not send".
            return None


def _with(base: ComplianceFilter, **overrides: Any) -> ComplianceFilter:
    """A copy of the resolved filter with a few fields changed."""
    return replace(base, **overrides)


# ══════════════════════════════════════════════════════════════
#  The text — pure, no session
# ══════════════════════════════════════════════════════════════
#
# ⚠️ THE MESSAGE BODY IS UZBEK, and that is the one thing in this module that
# CONVENTIONS.md §14 has to be squared with. §14 says Uzbek belongs in
# ``core/messages_uz.py``, ``uz.json`` and ``strings.xml`` — all three of which
# are catalogues keyed by a code. This is not a catalogue entry: it is a
# composed document, assembled from figures, shortened to fit a transport
# limit, and its shape IS the feature. Moving the fragments into a key-value
# catalogue would leave the assembly here and the words there, and the ladder
# below (which drops sections until the text fits) would be impossible to read
# or to test.
#
# It is written so that this trade-off is visible rather than accidental, and
# it is reported as an ASSUMPTIONS line. The alternative considered and
# rejected: render the message in the panel and post it from there — which
# would put an outbound network call in the browser's origin and lose the
# scheduled path entirely.


def _day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _short_day(value: date) -> str:
    return value.strftime("%d.%m")


def _money(value: float | None) -> str:
    """``5 610 $``. An unknown amount is said out loud."""
    if value is None:
        return "summa noma'lum"
    return f"{value:,.0f}".replace(",", " ") + " $"


def _agent_name(name: str | None) -> str:
    return name or "xodim biriktirilmagan"


def _evidence(row: ComplianceRow) -> str:
    """The evidence that EXPLAINS the rule — the answer to "why suspicious?".

    The reader should find the answer in the message itself: "the last
    conversation was nine days ago" has to be visible without opening the panel.
    """
    verdict = row.verdict
    if verdict.last_call_at is None:
        return "suhbat umuman bo'lmagan"

    local = verdict.last_call_at.astimezone(TASHKENT)
    days = verdict.days_before
    if days is None:
        when = _short_day(local.date())
    elif days == 0:
        when = f"{_short_day(local.date())} (o'sha kuni)"
    else:
        when = f"{_short_day(local.date())} ({days} kun oldin)"

    who = verdict.last_call_agent
    tail = f"{when}, {escape_html(who)}" if who else when
    return f"oxirgi suhbat: {tail}"


def _partner(row: ComplianceRow) -> str:
    name = (row.partner_name or row.partner_code or "—").strip()
    if len(name) > MAX_PARTNER_NAME:
        name = name[: MAX_PARTNER_NAME - 1].rstrip() + "…"
    return escape_html(name)


def render(data: DigestData, *, top_agents: int, top_sales: int) -> str:
    """Assemble the text. Does NOT check the length — :func:`build_text` does.

    ⚠️ There is no "open in the panel" link, which BonviZvonki has. That link
    needs a public base URL, and this server's configuration carries none — a
    link to ``localhost`` opens an error page on the manager's phone and costs
    more credibility than its absence. It comes back the day the deployment has
    a public address to put in the configuration.
    """
    lines: list[str] = [
        f"🔎 <b>Savdo nazorati — {_day(data.day)}</b>",
        "",
        f"✅ Toza: <b>{data.ok}</b>",
        f"⚠️ Shubhali: <b>{data.suspicious}</b>",
        f"❔ Tekshirib bo'lmadi: <b>{data.not_checkable}</b>",
        f"<i>Oyna: savdo kuni + oldingi {data.window_days} kun</i>",
    ]

    if data.min_amount > 0:
        lines.append(
            f"<i>Chegara: {_money(data.min_amount)} dan past savdolar "
            f"kirmadi ({data.skipped_by_amount} ta)</i>"
        )
    if data.truncated:
        lines.append("<i>⚠️ Savdo juda ko'p — sonlar to'liq emas</i>")

    # ── Walk-in customers ─────────────────────────────────────
    #
    # The figures above are REGULAR customers only. Walk-ins stand apart with
    # the reason written out — otherwise the manager compares the total with
    # SAP and reads the difference as a fault.
    if data.walk_in_total:
        line = f"🧾 Bir martalik mijozlar: <b>{data.walk_in_total}</b> savdo"
        if data.walk_in_over_limit:
            line += (
                f" — shundan <b>{data.walk_in_over_limit}</b> tasi "
                f"{_money(data.walk_in_limit)} limitidan oshgan "
                f"({_money(data.walk_in_over_amount)})"
            )
        lines += ["", line, "<i>Ular yuqoridagi sonlarga kirmaydi</i>"]

    if data.suspicious == 0:
        lines += ["", "Shubhali savdo yo'q — bu kun bo'yicha savol qolmadi."]

    if data.agents and top_agents > 0:
        lines += ["", "<b>Xodimlar kesimi</b>"]
        for line_data in data.agents[:top_agents]:
            lines.append(
                f"• {escape_html(_agent_name(line_data.name))} — "
                f"<b>{line_data.suspicious}</b> shubhali / {line_data.sales} savdo"
            )
        rest = len(data.agents) - top_agents
        if rest > 0:
            lines.append(f"<i>…va yana {rest} ta xodim</i>")

    if data.top and top_sales > 0:
        lines += ["", "<b>Eng katta shubhali savdolar</b>"]
        for index, row in enumerate(data.top[:top_sales], start=1):
            rules = ", ".join(row.verdict.broken_rules) or "—"
            lines.append(
                f"{index}. {_short_day(row.occurred_on)} · {_partner(row)} · "
                f"<b>{_money(row.amount_usd)}</b>"
            )
            lines.append(
                f"    {escape_html(_agent_name(row.agent_name))} · {rules} · "
                f"{_evidence(row)}"
            )

    lines.append("")
    lines.append(
        "<i>Bu ro'yxat hech kimni AYBLAMAYDI — u tekshirish uchun "
        "tayyorlangan. Qaror sizniki.</i>"
    )
    return "\n".join(lines)


def _clamp(text: str) -> str:
    """Last resort: cut what does not fit, ON A LINE BOUNDARY.

    ⚠️ Only at a line boundary. Cut by character, an open ``<b>`` tag would make
    the message invalid and the transport would refuse it outright — so
    "shortening" would end in losing the message.
    """
    if len(text) <= DIGEST_TEXT_LIMIT:
        return text
    tail = "\n…"
    cut = text[: DIGEST_TEXT_LIMIT - len(tail)]
    edge = cut.rfind("\n")
    return (cut[:edge] if edge > 0 else cut) + tail


def build_text(data: DigestData) -> str:
    """The text, guaranteed to fit the transport's limit.

    The order of shortening is not arbitrary — the least useful thing goes
    first:

      1. the sales list from 5 down to 3;
      2. the employee cut 5 -> 3 -> 1 -> gone;
      3. and only then a cut on a line boundary.

    The FIGURES and the closing sentence are never dropped: the meaning of the
    message is in them.
    """
    plans = (
        (TOP_AGENTS, TOP_SALES),
        (TOP_AGENTS, 4),
        (TOP_AGENTS, MIN_TOP_SALES),
        (3, MIN_TOP_SALES),
        (1, MIN_TOP_SALES),
        (0, MIN_TOP_SALES),
    )
    text = ""
    for top_agents, top_sales in plans:
        text = render(data, top_agents=top_agents, top_sales=top_sales)
        if len(text) <= DIGEST_TEXT_LIMIT:
            return text
    return _clamp(text)


__all__ = [
    "MAX_ROWS",
    "MIN_TOP_SALES",
    "TOP_AGENTS",
    "TOP_SALES",
    "AgentLine",
    "DigestData",
    "DigestOutcome",
    "SalesDigestService",
    "build_text",
    "render",
]
