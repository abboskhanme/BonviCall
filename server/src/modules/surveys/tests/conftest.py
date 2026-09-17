"""Factories for the surveys module.

Module-local rather than added to ``server/conftest.py``. The house rule is
that test data is created only through a factory (§13), and the root conftest
is where the shared ones live — but three of these tables are this module's
alone, nothing outside it builds a survey, and two other ports are appending to
the root file at the same time. A module-scoped ``conftest.py`` is a pytest
feature rather than a workaround, and it keeps the shared file out of a
three-way merge.

Everything else — ``db``, ``admin``, ``manager``, ``sales``, ``agent_factory``,
``truncate_all``, ``frozen_clock`` — comes from the root conftest unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.settings_keys import SettingKey
from src.modules.settings.models import AppSettingModel
from src.modules.surveys import rules
from src.modules.surveys.models import (
    SurveyModel,
    SurveyResponseModel,
    TelegramGroupModel,
)


@pytest.fixture
def group_factory(db: AsyncSession, agent_factory) -> Callable[..., Any]:
    """Create a Telegram group, bound to an agent unless told otherwise.

    Bound by default because an unbound group is the exceptional case — the
    one the panel warns about — and a factory whose default is the exception
    makes every ordinary test set up the ordinary case by hand.
    """
    counter = {"n": 0}

    async def _create(**overrides: Any) -> TelegramGroupModel:
        counter["n"] += 1
        agent = overrides.pop("agent", "unset")
        if agent == "unset":
            agent = await agent_factory()
        bound_at = None
        agent_id = None
        if agent is not None:
            agent_id = agent.id
            # `bound_has_a_time` is a CHECK: the two columns move together.
            bound_at = overrides.pop("bound_at", clock.now())
        else:
            overrides.pop("bound_at", None)
        group = TelegramGroupModel(
            chat_id=overrides.pop("chat_id", -1000000000000 - counter["n"]),
            title=overrides.pop("title", f"Mijoz {counter['n']}"),
            agent_id=agent_id,
            bound_at=bound_at,
            bot_status=overrides.pop("bot_status", "member"),
            bound_by=overrides.pop("bound_by", "manual" if agent_id else None),
            **overrides,
        )
        db.add(group)
        await db.flush()
        return group

    return _create


@pytest.fixture
def survey_factory(db: AsyncSession, group_factory) -> Callable[..., Any]:
    """Create a survey for a group, defaulting to a live pending one."""

    async def _create(**overrides: Any) -> SurveyModel:
        group = overrides.pop("group", None)
        if group is None:
            group = await group_factory()
        now = overrides.pop("now", clock.now())
        period = rules.survey_period(now, rules.DEFAULT_PERIOD_DAYS)
        survey = SurveyModel(
            group_id=group.id,
            agent_id=overrides.pop("agent_id", group.agent_id),
            token=overrides.pop("token", rules.new_token()),
            period_start=overrides.pop("period_start", period.start),
            period_end=overrides.pop("period_end", period.end),
            status=overrides.pop("status", "pending"),
            expires_at=overrides.pop("expires_at", rules.token_expiry(now)),
            **overrides,
        )
        db.add(survey)
        await db.flush()
        return survey

    return _create


@pytest.fixture
def response_factory(db: AsyncSession, survey_factory) -> Callable[..., Any]:
    """Create one customer answer, with a distinct respondent hash each time."""
    counter = {"n": 0}

    async def _create(**overrides: Any) -> SurveyResponseModel:
        counter["n"] += 1
        survey = overrides.pop("survey", None)
        if survey is None:
            survey = await survey_factory()
        response = SurveyResponseModel(
            survey_id=survey.id,
            respondent_hash=overrides.pop(
                "respondent_hash",
                rules.respondent_hash(survey.token, counter["n"]),
            ),
            csat=overrides.pop("csat", 5),
            responded_at=overrides.pop("responded_at", clock.now()),
            red_flags=overrides.pop("red_flags", []),
            **overrides,
        )
        db.add(response)
        survey.response_count += 1
        await db.flush()
        return response

    return _create


@pytest.fixture
def set_setting(db: AsyncSession) -> Callable[..., Any]:
    """Change one seeded setting for the duration of a test.

    A direct UPDATE rather than the settings API: the API writes an audit row
    and needs an actor, and none of that is what these tests are about.
    """

    async def _set(key: str, value: Any) -> None:
        await db.execute(
            sa.update(AppSettingModel)
            .where(AppSettingModel.key == key)
            .values(value=value)
        )
        await db.flush()

    return _set


@pytest.fixture
def surveys_on(set_setting) -> Callable[..., Any]:
    """Turn the feature on. **Every test that dispatches must ask for this.**

    The flag is seeded off, so a test that forgets gets a 409 rather than a
    silent pass — which is the behaviour the flag is for.
    """

    async def _enable() -> None:
        await set_setting(SettingKey.SURVEY_ENABLED, True)

    return _enable


@pytest.fixture
def days_ago() -> Callable[[float], Any]:
    """An instant N days before now, for the cadence and suppression tests."""

    def _at(days: float):
        return clock.now() - timedelta(days=days)

    return _at
