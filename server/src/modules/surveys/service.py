"""Surveys — the ratings themselves (BonviZvonki ``modules/surveys``).

``GroupService`` (``groups.py``) produces surveys; this is the consumer half:
what a customer answered, what a manager may read of it, and the three
worklists a transport would drain.

═══ Nothing here sends anything ════════════════════════════════════════════
:meth:`SurveyService.deliver`, :meth:`refresh_counters` and
:meth:`remove_expired_messages` all go through
``src.modules.surveys.transport``, whose shipped implementation logs and
returns "not delivered". There is no HTTP client in this file and no outbound
socket anywhere in this module.

═══ The privacy rule, stated once ══════════════════════════════════════════
A rating is anonymous, and it is anonymous **by construction, not by policy**:
the bot hashes the Telegram user id with the survey's own token and the server
never sees the id. Because each survey has its own token, one person's answers
across two surveys do not link, so "what did this customer say last time" has
no answer at all.

That promise is made to the customer in their own chat, and it is what makes
:meth:`feedback` refuse to hand a salesperson the individual rows — see the
comment there. It outranks the access setting, and the setting's own docstring
in ``core/settings_keys.py`` says so.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.deps import Principal
from src.core.errors import ConflictError, ErrorCode, ForbiddenError, NotFoundError
from src.core.logging import get_logger
from src.core.permissions import Perm
from src.core.settings_keys import SettingKey
from src.modules.agents.models import AgentModel
from src.modules.settings.service import SettingsService
from src.modules.surveys import rules, transport
from src.modules.surveys.models import (
    SurveyModel,
    SurveyResponseModel,
    TelegramGroupModel,
)

log = get_logger(__name__)


@dataclass(frozen=True)
class FeedbackItem:
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    csat: int
    resolution: str | None
    comment: str | None
    red_flags: list[str]
    responded_at: datetime


@dataclass(frozen=True)
class Feedback:
    average: float | None
    count: int
    ready: bool
    min_responses: int
    distribution: dict[str, int]
    response_rate: float | None
    items: list[FeedbackItem]
    items_withheld: bool


@dataclass(frozen=True)
class RateOutcome:
    accepted: bool
    response_count: int
    already_rated: bool
    agent_name: str


class SurveyService:
    """Reading ratings, recording them, and draining the transport worklists."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = SettingsService(session)

    # ── The registry ───────────────────────────────────────────────────────

    @staticmethod
    def red_flags() -> list[tuple[str, str]]:
        """The misconduct criteria: the SINGLE source, never copied client-side.

        Served from the server so a new criterion appears in the panel and in
        the customer's chat without a frontend deploy. A key is never renamed,
        only added to — the keys are what the stored answers hold.
        """
        return list(rules.RED_FLAGS)

    # ── Reading: the ratings page ──────────────────────────────────────────

    def scope_agent(self, principal: Principal) -> uuid.UUID | None:
        """The agent a caller is narrowed to, or ``None`` for the whole fleet.

        The permission ADMITS and the query NARROWS (§11) — there is never a
        second check in a router. A caller holding ``surveys:read`` sees
        everybody; one who only holds ``surveys:read:own`` sees their own agent.

        A ``sales`` principal with no linked agent is narrowed to nothing at
        all rather than to everything. BonviZvonki states the rule as "an empty
        scope means NOTHING, not EVERYTHING", and it is the difference between
        an unlinked account seeing a blank page and seeing the whole company.
        """
        if principal.has(Perm.SURVEYS_READ):
            return None
        return principal.agent_id

    async def _sales_visibility(self) -> str:
        """``hidden`` | ``score_only`` | ``full`` from ``access.sales_client_rating``."""
        value = await self.settings.get(SettingKey.ACCESS_SALES_CLIENT_RATING)
        text = str(value or "").strip().lower()
        return text if text in {"hidden", "score_only", "full"} else "score_only"

    async def feedback(
        self,
        principal: Principal,
        window: rules.ReportWindow,
        *,
        agent_id: uuid.UUID | None = None,
        search: str | None = None,
        limit: int = 200,
    ) -> Feedback:
        """The ratings page: the headline, its shape, and the rows behind it.

        ⚠️ **A ``sales`` caller never receives ``items``, whatever the access
        setting says.** One Telegram group is one customer, so a single visible
        rating row tells the salesperson exactly which customer wrote it — and
        the anonymity was promised to that customer in their own chat. The
        setting therefore chooses between "this section is closed to you" (403)
        and "your average and your distribution, no rows"; it cannot open the
        rows, and ``full`` and ``score_only`` are indistinguishable for a
        salesperson. That is a real inconsistency in the source's own settings
        UI, which offers three options for two behaviours; the safe behaviour
        is kept and the option is documented rather than silently widened.

        ``items_withheld`` is returned so the panel can say "your average,
        without the individual ratings" instead of rendering an empty list,
        which reads as "no customer has ever rated you".
        """
        own = self.scope_agent(principal)
        is_narrowed = own is not None
        if is_narrowed:
            visibility = await self._sales_visibility()
            if visibility == "hidden":
                raise ForbiddenError()
            if principal.agent_id is None:
                # A `sales` login that was never linked to an agent. Empty
                # scope means nothing, not everything.
                raise ForbiddenError()
            agent_id = own
        min_responses = rules.resolve_positive_int(
            await self.settings.get(SettingKey.SURVEY_MIN_RESPONSES),
            rules.DEFAULT_MIN_RESPONSES,
        )

        answered = sa.and_(
            SurveyResponseModel.responded_at >= window.since,
            SurveyResponseModel.responded_at < window.until,
        )
        base = (
            sa.select(SurveyResponseModel, SurveyModel.agent_id, AgentModel.full_name)
            .join(SurveyModel, SurveyModel.id == SurveyResponseModel.survey_id)
            .join(AgentModel, AgentModel.id == SurveyModel.agent_id)
            .where(answered)
        )
        if agent_id is not None:
            base = base.where(SurveyModel.agent_id == agent_id)
        if search and search.strip():
            # Escaped, and deliberately only over the employee's name. Matching
            # the comment text would let a `score_only` caller discover that a
            # comment exists and roughly what is in it, by binary search.
            needle = f"%{rules.ilike_escape(search.strip())}%"
            base = base.where(AgentModel.full_name.ilike(needle, escape="\\"))

        aggregate = base.with_only_columns(
            sa.func.count(SurveyResponseModel.id),
            sa.func.avg(sa.cast(SurveyResponseModel.csat, sa.Numeric)),
        ).order_by(None)
        total, average = (await self.session.execute(aggregate)).one()
        total = int(total or 0)

        spread_rows = (
            await self.session.execute(
                base.with_only_columns(
                    SurveyResponseModel.csat, sa.func.count(SurveyResponseModel.id)
                )
                .group_by(SurveyResponseModel.csat)
                .order_by(None)
            )
        ).all()
        spread = rules.distribution({int(star): int(count) for star, count in spread_rows})

        rate = await self._response_rate(window, agent_id)

        items: list[FeedbackItem] = []
        if not is_narrowed and total:
            rows = (
                await self.session.execute(
                    base.order_by(
                        SurveyResponseModel.responded_at.desc(),
                        SurveyResponseModel.id.desc(),
                    ).limit(limit)
                )
            ).all()
            items = [
                FeedbackItem(
                    id=response.id,
                    agent_id=row_agent_id,
                    agent_name=agent_name,
                    csat=response.csat,
                    resolution=response.resolution,
                    comment=response.comment,
                    red_flags=list(response.red_flags or []),
                    responded_at=response.responded_at,
                )
                for response, row_agent_id, agent_name in rows
            ]

        figure = rules.rating(total, float(average) if average is not None else None, min_responses)
        return Feedback(
            average=figure.average,
            count=figure.count,
            ready=figure.ready,
            min_responses=figure.min_responses,
            distribution=spread,
            response_rate=rate,
            items=items,
            items_withheld=is_narrowed and total > 0,
        )

    async def _response_rate(
        self, window: rules.ReportWindow, agent_id: uuid.UUID | None
    ) -> float | None:
        """Sent in the window, answered in the window.

        ⚠️ **The two halves count different clocks on purpose.** The
        denominator is surveys whose ``sent_at`` falls in the window; the
        numerator is how many of *those* have an answer whose ``responded_at``
        also falls in it. BonviZvonki's earlier version used
        ``status == completed`` for the numerator and produced ``count: 0``
        beside ``response_rate: 100.0`` whenever a survey went out on one day
        and was answered on the next.
        """
        sent_in_window = sa.and_(
            SurveyModel.sent_at.is_not(None),
            SurveyModel.sent_at >= window.since,
            SurveyModel.sent_at < window.until,
        )
        answered_in_window = (
            sa.select(SurveyResponseModel.id)
            .where(
                SurveyResponseModel.survey_id == SurveyModel.id,
                SurveyResponseModel.responded_at >= window.since,
                SurveyResponseModel.responded_at < window.until,
            )
            .correlate(SurveyModel)
            .exists()
        )
        statement = sa.select(
            sa.func.count(),
            sa.func.count().filter(answered_in_window),
        ).select_from(SurveyModel).where(sent_in_window)
        if agent_id is not None:
            statement = statement.where(SurveyModel.agent_id == agent_id)
        sent, answered = (await self.session.execute(statement)).one()
        return rules.response_rate(int(sent or 0), int(answered or 0))

    # ── The transport ──────────────────────────────────────────────────────

    async def deliver(self, survey_id: uuid.UUID) -> bool:
        """Hand one queued survey to the transport. ``True`` if it was posted.

        **False in this deployment, always.** The row stays ``pending`` and
        ``sent_at`` stays NULL, which is the truthful record of "nothing was
        posted". It is emphatically not marked ``sent``: a row claiming to have
        been delivered when nothing was would show a customer group as surveyed
        on the panel, and an admin would have no way to tell that from a group
        that really was.
        """
        record = (
            await self.session.execute(
                sa.select(SurveyModel, TelegramGroupModel.chat_id, AgentModel.full_name)
                .join(TelegramGroupModel, TelegramGroupModel.id == SurveyModel.group_id)
                .join(AgentModel, AgentModel.id == SurveyModel.agent_id)
                .where(SurveyModel.id == survey_id)
            )
        ).first()
        if record is None:
            raise NotFoundError()
        survey, chat_id, agent_name = record
        if survey.status != "pending":
            return False

        result = await transport.get_transport().post(
            transport.Dispatch(
                survey_id=survey.id,
                token=survey.token,
                chat_id=chat_id,
                agent_name=agent_name,
            )
        )
        if not result.delivered:
            if result.permanent_failure:
                survey.status = "failed"
                await self.session.commit()
            return False
        survey.status = "sent"
        survey.sent_at = clock.now()
        survey.chat_message_id = result.chat_message_id
        await self.session.commit()
        return True

    async def refresh_counters(self) -> int:
        """Update the "N answered" counter on every posted survey that moved.

        Only rows that were actually posted are candidates, so with the logging
        transport this drains nothing and returns 0 — there is no message to
        edit.
        """
        rows = (
            await self.session.execute(
                sa.select(
                    SurveyModel.id,
                    TelegramGroupModel.chat_id,
                    SurveyModel.chat_message_id,
                    SurveyModel.response_count,
                )
                .join(TelegramGroupModel, TelegramGroupModel.id == SurveyModel.group_id)
                .where(
                    SurveyModel.chat_message_id.is_not(None),
                    SurveyModel.message_deleted_at.is_(None),
                    SurveyModel.response_count > 0,
                )
                .order_by(SurveyModel.sent_at)
                .limit(rules.WORKLIST_LIMIT)
            )
        ).all()
        sender = transport.get_transport()
        refreshed = 0
        for survey_id, chat_id, message_id, count in rows:
            if await sender.refresh(
                transport.CounterUpdate(
                    survey_id=survey_id,
                    chat_id=chat_id,
                    chat_message_id=message_id,
                    response_count=count,
                )
            ):
                refreshed += 1
        return refreshed

    async def remove_expired_messages(self) -> int:
        """Take posted survey messages back out of the chats once they age out.

        ⚠️ **This list is the ONLY source for a deletion.** Nothing ever
        enumerates a chat's messages: a removal names a ``(chat_id,
        chat_message_id)`` pair this product recorded when it posted, so even a
        bot shared between two applications cannot be told to delete the other
        application's message — it simply is not in this table.

        ``message_deleted_at`` is stamped on a PERMANENT failure too, not only
        on success. Otherwise a message past Telegram's 48-hour own-delete
        limit stays in the queue and is retried for ever. What actually
        happened goes in the log.
        """
        ttl = rules.resolve_message_ttl_hours(
            await self.settings.get(SettingKey.SURVEY_MESSAGE_TTL_HOURS)
        )
        deadline = rules.message_delete_deadline(clock.now(), ttl)
        if deadline is None:
            return 0

        rows = (
            await self.session.execute(
                sa.select(SurveyModel, TelegramGroupModel.chat_id)
                .join(TelegramGroupModel, TelegramGroupModel.id == SurveyModel.group_id)
                .where(
                    SurveyModel.chat_message_id.is_not(None),
                    SurveyModel.message_deleted_at.is_(None),
                    SurveyModel.sent_at.is_not(None),
                    SurveyModel.sent_at <= deadline,
                )
                .order_by(SurveyModel.sent_at)
                .limit(rules.WORKLIST_LIMIT)
            )
        ).all()
        sender = transport.get_transport()
        removed = 0
        for survey, chat_id in rows:
            assert survey.chat_message_id is not None
            result = await sender.remove(
                transport.MessageRemoval(
                    survey_id=survey.id,
                    chat_id=chat_id,
                    chat_message_id=survey.chat_message_id,
                )
            )
            if result.delivered:
                survey.message_deleted_at = clock.now()
                removed += 1
            elif result.permanent_failure:
                survey.message_deleted_at = clock.now()
                log.warning(
                    "survey_message_undeletable",
                    survey_id=str(survey.id),
                    reason=result.reason,
                )
        await self.session.commit()
        return removed

    async def expire_stale(self) -> int:
        """Move surveys past ``expires_at`` out of ``pending``/``sent``.

        Nothing in BonviZvonki does this: a status only changes when somebody
        touches the token, so a survey queued while the transport was down
        stays ``pending`` for ever, is counted as ``reused`` by every later
        broadcast, and that group is never surveyed again. The reuse query was
        fixed to ignore expired rows; this closes the rows themselves so the
        panel's status column stops lying about them.
        """
        result = await self.session.execute(
            sa.update(SurveyModel)
            .where(
                SurveyModel.status.in_(("pending", "sent", "opened")),
                SurveyModel.expires_at <= clock.now(),
            )
            .values(status="expired", updated_at=sa.func.now())
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    # ── Writing: what a customer answered ──────────────────────────────────

    async def _by_token(self, token: str) -> tuple[SurveyModel, str]:
        record = (
            await self.session.execute(
                sa.select(SurveyModel, AgentModel.full_name)
                .join(AgentModel, AgentModel.id == SurveyModel.agent_id)
                .where(SurveyModel.token == token)
            )
        ).first()
        if record is None:
            raise NotFoundError()
        survey, agent_name = record
        return survey, agent_name

    def _require_open(self, survey: SurveyModel) -> None:
        if survey.expires_at <= clock.now() or survey.status == "expired":
            raise ConflictError(ErrorCode.CONFLICT, detail={"reason": "survey_expired"})

    async def open(
        self, token: str, telegram_user_id: int | None = None
    ) -> tuple[SurveyModel, str, bool]:
        """Mark a survey opened. Returns it, the agent's name, and "already rated".

        ⚠️ A **completed** survey is never dropped back to ``opened``. It is a
        one-line guard and BonviZvonki has it on one of its two open paths and
        not the other, so following an old deep link after rating rewrites the
        status and every status-based figure with it. There is already a rating
        in that chat; returning the row to "not yet rated" misreports it.
        """
        survey, agent_name = await self._by_token(token)
        self._require_open(survey)

        already = False
        if telegram_user_id is not None:
            already = await self._has_answered(
                survey.id, rules.respondent_hash(survey.token, telegram_user_id)
            )

        if survey.status in ("pending", "sent"):
            survey.status = "opened"
            if survey.opened_at is None:
                survey.opened_at = clock.now()
            await self.session.commit()
        return survey, agent_name, already

    async def _has_answered(self, survey_id: uuid.UUID, respondent: str) -> bool:
        found = await self.session.scalar(
            sa.select(SurveyResponseModel.id)
            .where(
                SurveyResponseModel.survey_id == survey_id,
                SurveyResponseModel.respondent_hash == respondent,
            )
            .limit(1)
        )
        return found is not None

    async def rate(self, token: str, *, respondent_hash: str, csat: int) -> RateOutcome:
        """Record one customer's stars.

        ``.limit(1)`` on the duplicate check, and that is a FIX with teeth.
        BonviZvonki still uses ``scalar_one_or_none()`` there, left over from
        when one survey meant one response; in the group flow a second answer
        raises ``MultipleResultsFound`` — a **500** on an unauthenticated
        endpoint, triggerable by anyone holding a group token.

        ``response_count`` is incremented here. The source's legacy write path
        does not touch it, so the counter on the posted message under-reports
        permanently and never catches up.
        """
        survey, agent_name = await self._by_token(token)
        self._require_open(survey)

        if await self._has_answered(survey.id, respondent_hash):
            return RateOutcome(
                accepted=False,
                response_count=survey.response_count,
                already_rated=True,
                agent_name=agent_name,
            )

        now = clock.now()
        self.session.add(
            SurveyResponseModel(
                survey_id=survey.id,
                respondent_hash=respondent_hash,
                csat=csat,
                responded_at=now,
                red_flags=[],
                response_time_sec=(
                    max(0, int((now - survey.sent_at).total_seconds()))
                    if survey.sent_at is not None
                    else None
                ),
            )
        )
        survey.response_count += 1
        if survey.completed_at is None:
            survey.completed_at = now
        survey.status = "completed"
        await self.session.commit()
        return RateOutcome(
            accepted=True,
            response_count=survey.response_count,
            already_rated=False,
            agent_name=agent_name,
        )

    async def detail(
        self,
        token: str,
        *,
        respondent_hash: str,
        comment: str | None,
        red_flags: list[str] | None,
    ) -> None:
        """Attach the optional half of an answer: the comment and the ticks.

        ⚠️ **Only what was supplied is written.** BonviZvonki assigns both
        fields unconditionally, so a retry after a network timeout — or a
        second call carrying only the ticks — destroys a comment the customer
        had already sent, with nothing to say it happened. ``None`` here means
        "leave it"; an explicit empty list means "clear it".

        It also checks expiry, which the source's version does not — the one
        write path in that module with no such check.
        """
        survey, _ = await self._by_token(token)
        self._require_open(survey)

        response = await self.session.scalar(
            sa.select(SurveyResponseModel)
            .where(
                SurveyResponseModel.survey_id == survey.id,
                SurveyResponseModel.respondent_hash == respondent_hash,
            )
            .limit(1)
        )
        if response is None:
            raise NotFoundError()

        if comment is not None:
            cleaned = comment.strip()
            response.comment = cleaned or None
        if red_flags is not None:
            response.red_flags = rules.normalize_red_flags(red_flags)
        await self.session.commit()

    async def submit(
        self,
        token: str,
        *,
        respondent_hash: str,
        csat: int,
        comment: str | None,
        red_flags: list[str],
    ) -> RateOutcome:
        """Stars, comment and ticks in one write — the Mini App's whole answer.

        One method rather than the source's ``rate`` then ``detail``: that pair
        looks the survey up twice, re-reads the response row, and leaves a
        window in which a customer's stars are stored and their comment is not.
        Validation of the ticks happens BEFORE anything is written, so a 422
        never leaves half an answer behind.
        """
        flags = rules.normalize_red_flags(red_flags)
        outcome = await self.rate(token, respondent_hash=respondent_hash, csat=csat)
        if not outcome.accepted:
            return outcome
        if comment is not None or flags:
            await self.detail(
                token,
                respondent_hash=respondent_hash,
                comment=comment,
                red_flags=flags,
            )
        return outcome


__all__ = ["Feedback", "FeedbackItem", "RateOutcome", "SurveyService"]
