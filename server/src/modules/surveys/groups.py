"""The Telegram group directory (ported from BonviZvonki ``modules/groups``).

The scale is the design constraint and it is stated in the source repeatedly:
**one group per customer, roughly a thousand of them.** Every read here is
built for that number, which is why the page leads with one light aggregate
(:meth:`GroupService.tree`) and pulls rows only for the node somebody opened.

``GroupService`` is the *producer* of surveys and owns the eligibility rules;
``SurveyService`` in ``service.py`` is the consumer. They live in one module
(see ``models.py``) and this file holds the half that is about chats rather
than ratings.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.errors import ConflictError, ErrorCode, NotFoundError
from src.core.logging import get_logger
from src.core.pagination import Cursor, Page, apply_keyset, clamp_limit
from src.core.settings_keys import SettingKey
from src.modules.agents.models import AgentModel
from src.modules.settings.service import SettingsService
from src.modules.surveys import rules
from src.modules.surveys.models import (
    SurveyModel,
    SurveyResponseModel,
    TelegramGroupModel,
)

log = get_logger(__name__)


@dataclass(frozen=True)
class GroupRow:
    """One group plus the three figures the panel shows beside it.

    A dataclass and not the ORM entity: the counts are aggregates from two
    other tables, and returning the entity would make the router ask for them
    again per row.
    """

    group: TelegramGroupModel
    agent_name: str | None
    agent_color: str | None
    survey_count: int
    response_count: int


@dataclass(frozen=True)
class AgentNode:
    agent_id: uuid.UUID
    full_name: str
    color: str | None
    group_count: int
    response_count: int


@dataclass(frozen=True)
class GroupTree:
    agents: list[AgentNode]
    unassigned_groups: int
    unassigned_responses: int


@dataclass(frozen=True)
class Skipped:
    group_id: uuid.UUID
    title: str
    reason: str


@dataclass(frozen=True)
class BroadcastOutcome:
    created: int
    reused: int
    delivered: int
    skipped: list[Skipped]
    total_groups: int


@dataclass(frozen=True)
class DispatchOutcome:
    survey_id: uuid.UUID
    status: str
    reused: bool
    delivered: bool


class GroupService:
    """Everything about a Telegram group except what a customer said in it."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = SettingsService(session)
        self._settings_cache: dict[str, Any] | None = None

    # ── Settings, read once per operation ──────────────────────────────────

    async def _survey_settings(self) -> dict[str, Any]:
        """Every survey setting this service needs, read ONCE per operation.

        Four ``SettingsService.get`` calls, memoised on the instance. Read
        through the settings **service** and not by selecting ``app_settings``
        directly: this module has no foreign key into ``settings``, so
        importing ``AppSettingModel`` is exactly the cross-module model import
        ``tests/test_layering.py`` forbids, and §2.1's projection exception is
        for modules that own no table.

        The memo is the point. BonviZvonki re-reads the whole settings table
        per resolver call — ``create_survey`` costs three full scans and the
        cadence job four, one of them duplicated because ``broadcast`` re-checks
        a flag the job has already checked. The table is tiny, so the cost is
        not the scan; it is that "how many queries does sending one survey
        make" has no stable answer.

        The raw values go through the pure resolvers in ``rules.py``, so a
        setting holding text, ``0`` or a negative lands on the documented
        default instead of on whatever ``int()`` produced.
        """
        if self._settings_cache is not None:
            return self._settings_cache
        raw = {
            key: await self.settings.get(key)
            for key in (
                SettingKey.SURVEY_ENABLED,
                SettingKey.SURVEY_AUTO_SEND,
                SettingKey.SURVEY_PERIOD_DAYS,
                SettingKey.SURVEY_SUPPRESSION_DAYS,
            )
        }
        self._settings_cache = {
            "enabled": rules.as_bool(raw[SettingKey.SURVEY_ENABLED]),
            "auto_send": rules.as_bool(raw[SettingKey.SURVEY_AUTO_SEND]),
            "period_days": rules.resolve_positive_int(
                raw[SettingKey.SURVEY_PERIOD_DAYS], rules.DEFAULT_PERIOD_DAYS
            ),
            "suppression_days": rules.resolve_positive_int(
                raw[SettingKey.SURVEY_SUPPRESSION_DAYS],
                rules.DEFAULT_SUPPRESSION_DAYS,
            ),
        }
        return self._settings_cache

    # ── Reading ────────────────────────────────────────────────────────────

    async def tree(self) -> GroupTree:
        """The page's skeleton: one employee per node, with its counts.

        ⚠️ Responses are attributed by ``surveys.agent_id`` and **not** by the
        group's current ``agent_id``. This is a FIX. BonviZvonki groups by
        ``telegram_groups.agent_id``, so re-binding a chat to a different
        employee retroactively moves every past rating onto them — and its own
        feedback page, which aggregates on ``surveys.agent_id``, then reports a
        different number for the same person. Two screens, two answers, and
        nothing says which is right.

        Counts are of ACTIVE groups only, and the endpoint takes no filter, so
        a node count keeps exactly one meaning: "groups that are working".
        """
        group_counts = (
            sa.select(
                TelegramGroupModel.agent_id.label("agent_id"),
                sa.func.count().label("groups"),
            )
            .where(
                TelegramGroupModel.is_active.is_(True),
                TelegramGroupModel.agent_id.is_not(None),
            )
            .group_by(TelegramGroupModel.agent_id)
            .subquery()
        )
        response_counts = (
            sa.select(
                SurveyModel.agent_id.label("agent_id"),
                sa.func.count(SurveyResponseModel.id).label("responses"),
            )
            .join(SurveyResponseModel, SurveyResponseModel.survey_id == SurveyModel.id)
            .group_by(SurveyModel.agent_id)
            .subquery()
        )
        rows = (
            await self.session.execute(
                sa.select(
                    AgentModel.id,
                    AgentModel.full_name,
                    AgentModel.color,
                    sa.func.coalesce(group_counts.c.groups, 0),
                    sa.func.coalesce(response_counts.c.responses, 0),
                )
                .outerjoin(group_counts, group_counts.c.agent_id == AgentModel.id)
                .outerjoin(response_counts, response_counts.c.agent_id == AgentModel.id)
                .where(AgentModel.archived_at.is_(None))
                .order_by(AgentModel.full_name)
            )
        ).all()

        unassigned_groups = (
            await self.session.scalar(
                sa.select(sa.func.count())
                .select_from(TelegramGroupModel)
                .where(
                    TelegramGroupModel.agent_id.is_(None),
                    TelegramGroupModel.is_active.is_(True),
                )
            )
        ) or 0

        return GroupTree(
            agents=[
                AgentNode(
                    agent_id=agent_id,
                    full_name=full_name,
                    color=color,
                    group_count=groups,
                    response_count=responses,
                )
                for agent_id, full_name, color, groups, responses in rows
            ],
            unassigned_groups=unassigned_groups,
            # Responses can only exist for a survey, and a survey can only
            # exist for a bound group, so this is 0 by construction. Returned
            # rather than omitted so the panel's tree totals add up without a
            # special case.
            unassigned_responses=0,
        )

    def _row_query(self) -> sa.Select:
        """Group rows joined to their agent and their two counts.

        The counts come from correlated scalar subqueries rather than two more
        joins: joining ``surveys`` and then ``survey_responses`` multiplies the
        group row by the number of surveys and then by the number of answers,
        and the ``COUNT(DISTINCT ...)`` that papers over it is slower than
        either subquery on a table of this shape.
        """
        survey_count = (
            sa.select(sa.func.count())
            .select_from(SurveyModel)
            .where(SurveyModel.group_id == TelegramGroupModel.id)
            .correlate(TelegramGroupModel)
            .scalar_subquery()
        )
        response_count = (
            sa.select(sa.func.count())
            .select_from(SurveyResponseModel)
            .join(SurveyModel, SurveyModel.id == SurveyResponseModel.survey_id)
            .where(SurveyModel.group_id == TelegramGroupModel.id)
            .correlate(TelegramGroupModel)
            .scalar_subquery()
        )
        return (
            sa.select(
                TelegramGroupModel,
                AgentModel.full_name,
                AgentModel.color,
                survey_count,
                response_count,
            )
            .outerjoin(AgentModel, AgentModel.id == TelegramGroupModel.agent_id)
        )

    @staticmethod
    def _to_row(record: sa.Row) -> GroupRow:
        group, agent_name, agent_color, surveys_, responses = record
        return GroupRow(
            group=group,
            agent_name=agent_name,
            agent_color=agent_color,
            survey_count=surveys_ or 0,
            response_count=responses or 0,
        )

    async def list_groups(
        self,
        *,
        agent_id: uuid.UUID | None = None,
        has_agent: bool | None = None,
        search: str | None = None,
        include_inactive: bool = False,
        cursor: Cursor | None = None,
        limit: int | None = None,
    ) -> Page[GroupRow]:
        """One keyset page of groups (§4.0).

        ``has_agent=False`` is a real server-side filter here. BonviZvonki has
        no such parameter, FastAPI drops the unknown query key silently, and
        its panel therefore walks every page and filters client-side — 20
        requests to answer "which groups have nobody" on a thousand rows. One
        WHERE clause replaces all of it.

        Sorted on ``(created_at DESC, id DESC)``: stable, indexed, and — unlike
        BonviZvonki's ``ORDER BY title`` — it never reorders under an admin who
        is renaming groups while paging through them.
        """
        statement = self._row_query()
        if agent_id is not None:
            statement = statement.where(TelegramGroupModel.agent_id == agent_id)
        if has_agent is True:
            statement = statement.where(TelegramGroupModel.agent_id.is_not(None))
        elif has_agent is False:
            statement = statement.where(TelegramGroupModel.agent_id.is_(None))
        if not include_inactive:
            statement = statement.where(TelegramGroupModel.is_active.is_(True))
        if search and search.strip():
            # Escaped, so a title containing `%` matches itself rather than
            # everything. The source escapes on the survey search and forgot to
            # on this one; the two sibling modules disagreed.
            needle = f"%{rules.ilike_escape(search.strip())}%"
            statement = statement.where(
                sa.or_(
                    TelegramGroupModel.title.ilike(needle, escape="\\"),
                    AgentModel.full_name.ilike(needle, escape="\\"),
                )
            )

        size = clamp_limit(limit)
        statement = apply_keyset(
            statement,
            TelegramGroupModel.created_at,
            TelegramGroupModel.id,
            cursor,
            descending=True,
        ).limit(size + 1)

        records = (await self.session.execute(statement)).all()
        has_more = len(records) > size
        records = records[:size]
        rows = [self._to_row(record) for record in records]
        next_cursor = (
            Cursor(
                sort_value=rows[-1].group.created_at, row_id=rows[-1].group.id
            ).encode()
            if has_more and rows
            else None
        )
        return Page(items=rows, next_cursor=next_cursor, has_more=has_more)

    async def get(self, group_id: uuid.UUID) -> GroupRow:
        record = (
            await self.session.execute(
                self._row_query().where(TelegramGroupModel.id == group_id)
            )
        ).first()
        if record is None:
            raise NotFoundError()
        return self._to_row(record)

    # ── Writing ────────────────────────────────────────────────────────────

    async def register(
        self,
        *,
        chat_id: int,
        title: str,
        member_count: int | None = None,
        bot_status: str = "member",
    ) -> TelegramGroupModel:
        """Upsert a chat the bot has met. **Never touches ``agent_id``.**

        ``INSERT ... ON CONFLICT DO UPDATE`` rather than BonviZvonki's
        SELECT-then-INSERT-then-``session.rollback()``-on-IntegrityError. Its
        rollback is the real hazard: the session comes from the request, so
        rolling back there discards every uncommitted write in the whole
        request and not merely the INSERT that collided. This is the idiom
        ``core/idempotency.py`` already states for the device surface (§5).
        """
        if bot_status not in rules.BOT_STATUSES:
            raise ConflictError(detail={"reason": "bot_status_unknown"})
        statement = (
            sa.dialects.postgresql.insert(TelegramGroupModel)
            .values(
                id=uuid.uuid4(),
                chat_id=chat_id,
                title=title,
                member_count=member_count,
                bot_status=bot_status,
            )
            .on_conflict_do_update(
                index_elements=[TelegramGroupModel.chat_id],
                set_={
                    "title": title,
                    "member_count": member_count,
                    "bot_status": bot_status,
                    "updated_at": sa.func.now(),
                },
            )
            .returning(TelegramGroupModel)
        )
        group = (await self.session.execute(statement)).scalar_one()
        await self.session.commit()
        return group

    async def autobind(
        self, *, chat_id: int, title: str, candidate_agent_ids: list[uuid.UUID]
    ) -> tuple[TelegramGroupModel, str]:
        """Attach an employee the bot recognised in the chat. Returns the reason.

        ⚠️ **A ``manual`` row is returned untouched, and that check comes
        first.** Without it the next automatic pass silently undoes whatever an
        admin just corrected, and the admin has no way to see that it happened:
        the row simply drifts back overnight. It is the most infuriating class
        of bug this feature has, and the guard is one line.

        Candidates arrive as agent ids because this product holds no Telegram
        identity for an employee — BonviZvonki matches ``agents.telegram_user_id``
        against the ids seen in the chat and there is no such column here. The
        DECISION is unchanged and lives in ``rules.autobind_decision``; only
        who resolves the identity moved.
        """
        group = await self.register(chat_id=chat_id, title=title)

        matched: uuid.UUID | None = None
        if candidate_agent_ids:
            matched = await self.session.scalar(
                sa.select(AgentModel.id)
                .where(
                    AgentModel.id.in_(candidate_agent_ids[: rules.AUTOBIND_CANDIDATE_LIMIT]),
                    AgentModel.is_active.is_(True),
                    AgentModel.archived_at.is_(None),
                )
                .order_by(AgentModel.created_at)
                .limit(1)
            )

        decision = rules.autobind_decision(
            bound_by=group.bound_by,
            current_agent_id=group.agent_id,
            matched_agent_id=matched,
        )
        if decision.write and decision.agent_id is not None:
            group.agent_id = decision.agent_id  # type: ignore[assignment]
            group.bound_by = "auto"
            if group.bound_at is None:
                group.bound_at = clock.now()
            await self.session.commit()
        return group, decision.reason

    async def patch(
        self,
        group_id: uuid.UUID,
        *,
        agent_id: uuid.UUID | None,
        agent_id_set: bool,
        is_active: bool | None,
    ) -> GroupRow:
        """Change one group by hand.

        ``agent_id_set`` distinguishes "leave the employee alone" from "release
        the employee" — the panel sends an explicit null for the second, and
        Pydantic cannot tell the two apart from the value alone.

        Any hand edit of the binding marks the row ``manual``, which is what
        stops automatic binding touching it again.
        """
        group = await self.session.get(TelegramGroupModel, group_id)
        if group is None:
            raise NotFoundError()
        if agent_id_set:
            await self._set_agent(group, agent_id)
        if is_active is not None:
            group.is_active = is_active
        await self.session.commit()
        return await self.get(group_id)

    async def _set_agent(
        self, group: TelegramGroupModel, agent_id: uuid.UUID | None
    ) -> None:
        if agent_id is not None:
            exists = await self.session.scalar(
                sa.select(AgentModel.id).where(
                    AgentModel.id == agent_id, AgentModel.archived_at.is_(None)
                )
            )
            if exists is None:
                # An agent the caller may not see and one that does not exist
                # answer identically (SPEC §4.1 rule 2).
                raise NotFoundError()
            group.agent_id = agent_id
            group.bound_at = clock.now()
            group.bound_by = "manual"
        else:
            group.agent_id = None
            # Kept in step with `agent_id` because the database says they must
            # be (`bound_has_a_time`). `bound_by` stays `manual`: releasing an
            # employee by hand is still a hand-held row, and automation must
            # not fill the gap back in on its next pass.
            group.bound_at = None

    async def bulk_patch(
        self,
        group_ids: list[uuid.UUID],
        *,
        agent_id: uuid.UUID | None,
        agent_id_set: bool,
        is_active: bool | None,
    ) -> int:
        """Apply one change to up to ``BULK_GROUP_LIMIT`` groups.

        Bounded by the schema rather than here, so an over-large request is a
        422 naming the field instead of a truncation nobody sees. The panel
        splits a larger selection into chunks and reports each chunk's outcome.
        """
        if agent_id_set and agent_id is not None:
            exists = await self.session.scalar(
                sa.select(AgentModel.id).where(
                    AgentModel.id == agent_id, AgentModel.archived_at.is_(None)
                )
            )
            if exists is None:
                raise NotFoundError()

        values: dict[str, Any] = {"updated_at": sa.func.now()}
        if agent_id_set:
            values["agent_id"] = agent_id
            values["bound_at"] = clock.now() if agent_id is not None else None
            values["bound_by"] = "manual" if agent_id is not None else None
        if is_active is not None:
            values["is_active"] = is_active
        if len(values) == 1:
            return 0

        result = await self.session.execute(
            sa.update(TelegramGroupModel)
            .where(TelegramGroupModel.id.in_(group_ids))
            .values(**values)
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    async def delete(self, group_id: uuid.UUID) -> None:
        """Remove a group — only once the bot is out of the chat.

        A chat the bot is still sitting in would simply be re-registered on its
        next message, so deleting it looks like it worked and then silently
        undoes itself. 409 with the reason instead.

        Surveys and their answers cascade. That is correct and deliberate: the
        rating was of a conversation in THIS chat, and there is nothing left to
        attribute it to. The panel says so before it asks.
        """
        group = await self.session.get(TelegramGroupModel, group_id)
        if group is None:
            raise NotFoundError()
        if group.bot_status not in rules.GONE_BOT_STATUSES:
            raise ConflictError(detail={"reason": "group_still_active"})
        await self.session.delete(group)
        await self.session.commit()

    # ── Creating surveys ───────────────────────────────────────────────────

    async def _require_enabled(self, settings: dict[str, Any]) -> None:
        if not settings["enabled"]:
            raise ConflictError(
                ErrorCode.CONFLICT, detail={"reason": "survey_disabled"}
            )

    async def _pending_survey(self, group_id: uuid.UUID) -> SurveyModel | None:
        """An unsent survey already queued for this group, if there is one.

        ``expires_at > now`` is part of the test, and that is a FIX.
        BonviZvonki looks only at ``status == pending``, and nothing ever moves
        a row from ``pending`` to ``expired`` in the background. A survey
        queued while the transport was down therefore stays ``pending`` past
        its seven-day expiry, is counted as ``reused`` by every later
        broadcast, and **that group never receives another survey again** — a
        permanent, silent stall with no error anywhere.
        """
        return await self.session.scalar(
            sa.select(SurveyModel)
            .where(
                SurveyModel.group_id == group_id,
                SurveyModel.status == "pending",
                SurveyModel.expires_at > clock.now(),
            )
            .order_by(SurveyModel.created_at)
            .limit(1)
        )

    def _queue(
        self, group: TelegramGroupModel, now: datetime, period_days: int
    ) -> SurveyModel:
        """Build the row. Does not flush — the caller batches."""
        period = rules.survey_period(now, period_days)
        survey = SurveyModel(
            group_id=group.id,
            agent_id=group.agent_id,
            token=rules.new_token(),
            period_start=period.start,
            period_end=period.end,
            channel="telegram_group",
            status="pending",
            expires_at=rules.token_expiry(now),
            response_count=0,
        )
        self.session.add(survey)
        # Written when the row is CREATED, not when a transport claims
        # delivery: a transport that cannot deliver must not be able to reopen
        # the cadence window on every tick.
        group.last_survey_at = now
        return survey

    async def _last_asked(self, group: TelegramGroupModel) -> datetime | None:
        """The later of the cached stamp and the real last survey.

        Both, because the cache can be stale — a row inserted by a path that
        forgot to update it, or restored from a backup — and the suppression
        rule has to keep working when it is.
        """
        newest = await self.session.scalar(
            sa.select(sa.func.max(SurveyModel.created_at)).where(
                SurveyModel.group_id == group.id
            )
        )
        stamps = [value for value in (group.last_survey_at, newest) if value is not None]
        return max(stamps) if stamps else None

    async def create_survey(
        self, group_id: uuid.UUID, *, force: bool = False
    ) -> DispatchOutcome:
        """Queue a survey for one group, and hand it to the transport.

        Order matters and is the source's: enabled -> structural block ->
        **reuse check** -> suppression -> queue. The reuse check sits before
        the suppression one so that a group with a survey already waiting gets
        that survey back rather than a second identical message.
        """
        settings = await self._survey_settings()
        await self._require_enabled(settings)

        group = await self.session.get(TelegramGroupModel, group_id)
        if group is None:
            raise NotFoundError()

        block = rules.structural_block(
            agent_id_present=group.agent_id is not None,
            is_active=group.is_active,
            bot_status=group.bot_status,
        )
        if block is not None:
            raise ConflictError(detail={"reason": block.reason})

        existing = await self._pending_survey(group.id)
        if existing is not None:
            return DispatchOutcome(
                survey_id=existing.id,
                status=existing.status,
                reused=True,
                delivered=False,
            )

        now = clock.now()
        if not force:
            last = await self._last_asked(group)
            suppressed = rules.suppression_block(
                last, now, settings["suppression_days"]
            )
            if suppressed is not None and last is not None:
                raise ConflictError(
                    detail={
                        "reason": suppressed.reason,
                        "days_since": rules.days_since(last, now),
                        "days_remaining": rules.days_remaining(
                            last, now, settings["suppression_days"]
                        ),
                    }
                )

        survey = self._queue(group, now, settings["period_days"])
        await self.session.flush()
        await self.session.commit()

        # Imported here and not at module scope: `service` imports this file
        # for nothing, but a future edit that makes it do so would turn a
        # top-level import into a cycle, and the failure mode is an
        # ImportError at startup rather than anything a test would catch.
        from src.modules.surveys.service import SurveyService

        delivered = await SurveyService(self.session).deliver(survey.id)
        return DispatchOutcome(
            survey_id=survey.id,
            status=survey.status,
            reused=False,
            delivered=delivered,
        )

    async def broadcast(
        self, *, force: bool = True, window_days: int | None = None
    ) -> BroadcastOutcome:
        """Queue a survey for every eligible group, in one pass.

        ⚠️ ``created + reused + len(skipped) == total_groups`` is an invariant
        and a test asserts it. "8 sent" on its own made an admin go and count
        rows on the groups page to work out what happened to the other 992.

        Inactive groups are loaded too, so that they appear in ``skipped`` with
        a reason rather than simply not being in any of the numbers.

        Three queries, not three per group: the settings once, every group
        once, and every live pending survey once. Per-group lookups here are
        the N+1 the source explicitly avoided and this port keeps avoiding.
        """
        settings = await self._survey_settings()
        await self._require_enabled(settings)

        now = clock.now()
        window = (
            None
            if force
            else (window_days if window_days is not None else settings["suppression_days"])
        )

        groups = list(
            (await self.session.scalars(sa.select(TelegramGroupModel))).all()
        )
        pending_rows = (
            await self.session.execute(
                sa.select(SurveyModel.group_id, SurveyModel.id)
                .where(
                    SurveyModel.status == "pending",
                    SurveyModel.expires_at > now,
                )
                .order_by(SurveyModel.created_at)
            )
        ).all()
        pending_by_group: dict[uuid.UUID, uuid.UUID] = {}
        for group_id, survey_id in pending_rows:
            pending_by_group.setdefault(group_id, survey_id)

        last_by_group: dict[uuid.UUID, datetime] = {}
        if window is not None:
            last_rows = (
                await self.session.execute(
                    sa.select(
                        SurveyModel.group_id, sa.func.max(SurveyModel.created_at)
                    ).group_by(SurveyModel.group_id)
                )
            ).all()
            last_by_group = {group_id: stamp for group_id, stamp in last_rows}

        created: list[SurveyModel] = []
        reused = 0
        skipped: list[Skipped] = []

        for group in groups:
            block = rules.structural_block(
                agent_id_present=group.agent_id is not None,
                is_active=group.is_active,
                bot_status=group.bot_status,
            )
            if block is not None:
                skipped.append(Skipped(group.id, group.title, block.reason))
                continue
            if group.id in pending_by_group:
                reused += 1
                continue
            if window is not None:
                stamps = [
                    value
                    for value in (group.last_survey_at, last_by_group.get(group.id))
                    if value is not None
                ]
                last = max(stamps) if stamps else None
                if rules.suppression_block(last, now, window) is not None:
                    skipped.append(
                        Skipped(group.id, group.title, rules.BLOCK_SUPPRESSED)
                    )
                    continue
            created.append(self._queue(group, now, settings["period_days"]))

        await self.session.flush()
        await self.session.commit()

        from src.modules.surveys.service import SurveyService

        service = SurveyService(self.session)
        delivered = 0
        for survey in created:
            if await service.deliver(survey.id):
                delivered += 1

        log.info(
            "survey_broadcast",
            created=len(created),
            reused=reused,
            skipped=len(skipped),
            delivered=delivered,
            total_groups=len(groups),
        )
        return BroadcastOutcome(
            created=len(created),
            reused=reused,
            delivered=delivered,
            skipped=skipped,
            total_groups=len(groups),
        )

    async def run_cadence(self) -> int:
        """The scheduled pass. Returns how many surveys it queued.

        ⚠️ **Two switches, and both default off.** ``survey.enabled`` asks "may
        surveys exist at all"; ``survey.auto_send`` asks "may they go out with
        nobody watching". Writing into chats real customers are sitting in
        without a human pressing anything is a separate decision and does not
        come free with turning the feature on.

        Restart-safety is the design, and it is worth stating because it is
        what makes an hourly schedule safe: this job stores "when did I last
        run" **nowhere**. The decision is recomputed from the database every
        time — has ``period_days`` passed since this group's last survey? So a
        server that reboots twice a day, a scheduler that loses its state, and
        an operator triggering it by hand all produce the same outcome: no
        group is asked twice inside its window. The protection against
        duplication is in the data, not in the schedule.
        """
        settings = await self._survey_settings()
        if not settings["enabled"]:
            log.info("survey_cadence_skipped", reason="survey.enabled=false")
            return 0
        if not settings["auto_send"]:
            log.info("survey_cadence_skipped", reason="survey.auto_send=false")
            return 0
        outcome = await self.broadcast(
            force=False, window_days=settings["period_days"]
        )
        return outcome.created


__all__ = [
    "AgentNode",
    "BroadcastOutcome",
    "DispatchOutcome",
    "GroupRow",
    "GroupService",
    "GroupTree",
    "Skipped",
]
