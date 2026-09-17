"""The two routes a customer's phone calls. **This router is not mounted** —
see ``src/api/webapp/__init__.py`` for why, and for what turning it on needs.

Ported from BonviZvonki ``modules/surveys/presentation/webapp_router.py``.

⚠️ **The survey token is never a path or body parameter.** It arrives inside
``initData.start_param``, where Telegram's signature covers it. A token in the
path would let anyone pair their own genuine, correctly signed ``initData``
with some other group's token and answer that group's survey — the whole point
of signing it is lost the moment it travels beside the signature instead of
inside it.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.core.deps import SessionDep
from src.modules.surveys import rules, webapp
from src.modules.surveys.schemas import (
    RedFlagOption,
    WebAppOpenRequest,
    WebAppOpenResponse,
    WebAppSubmitRequest,
    WebAppSubmitResponse,
)
from src.modules.surveys.service import SurveyService

router = APIRouter(prefix="/surveys", tags=["Survey Mini App"])


@router.post("/open", response_model=WebAppOpenResponse)
async def open_survey(
    session: SessionDep, body: WebAppOpenRequest
) -> WebAppOpenResponse:
    """What the customer is being asked, and whether they have already answered.

    Answers 503 ``bot_not_configured`` in this deployment, every time.
    """
    data = webapp.verify_init_data(body.init_data, webapp.configured_bot_token())
    token = webapp.survey_token(data)
    survey, agent_name, already = await SurveyService(session).open(
        token, telegram_user_id=data.telegram_user_id
    )
    return WebAppOpenResponse(
        agent_name=agent_name,
        period_start=survey.period_start,
        period_end=survey.period_end,
        already_rated=already,
        red_flags=[
            RedFlagOption(key=key, label=label) for key, label in rules.RED_FLAGS
        ],
    )


@router.post("/submit", response_model=WebAppSubmitResponse)
async def submit_survey(
    session: SessionDep, body: WebAppSubmitRequest
) -> WebAppSubmitResponse:
    """Stars, ticks and comment in one write.

    One call rather than the source's ``rate`` then ``detail``: that pair looks
    the survey up twice and leaves a window in which the stars are stored and
    the comment is not — a window a customer closing the sheet lands in.

    The Telegram user id is turned into ``sha256(token + ':' + id)`` here and
    then dropped. It is never stored, never logged, and never in a traceback
    (``InitData.__repr__`` redacts it).
    """
    data = webapp.verify_init_data(body.init_data, webapp.configured_bot_token())
    token = webapp.survey_token(data)
    outcome = await SurveyService(session).submit(
        token,
        respondent_hash=rules.respondent_hash(token, data.telegram_user_id),
        csat=body.csat,
        comment=body.comment,
        red_flags=body.red_flags,
    )
    return WebAppSubmitResponse(
        ok=outcome.accepted,
        agent_name=outcome.agent_name,
        response_count=outcome.response_count,
    )
