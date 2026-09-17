"""Stage 2: the transcript and the pinned rubric become one ``call_scores`` row.

The rubric version is written with the score. When the rubric changes, which
criteria yesterday's number was produced against stays answerable — without it
two scores are incomparable while claiming to be comparable.

Phase 1 pins the rubric in code: ``rubric_default.DEFAULT_RUBRIC`` is the
rubric and ``RUBRIC_VERSION`` is ``"v1"``. BonviZvonki read the active row out
of a ``rubrics`` table through ``RubricService``; that table, its service and
its "the blocks must total exactly 100" validator are phase 2 and are not
ported. ``extra_rules`` — the admin's free-text additions — goes with them, so
``None`` is passed here.

Idempotent: ``call_scores.call_id`` is UNIQUE and the row is looked for before
anything is sent, so a re-run calls no model.
"""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import AiRole, AnalysisFailure
from src.core.logging import get_logger
from src.modules.analysis.config import AnalysisConfig
from src.modules.analysis.entities import (
    AnalysisError,
    ProviderCooldownActive,
    Stage,
    StageOutcome,
    StageResult,
)
from src.modules.analysis.errors import ProviderRateLimitError, redact
from src.modules.analysis.limits import (
    ProviderCooldown,
    RateLimiter,
    cooldown_detail,
    llm_cost_micro_usd,
    with_backoff,
)
from src.modules.analysis.models import CallTranscriptModel
from src.modules.analysis.rubric_default import DEFAULT_RUBRIC, RUBRIC_VERSION
from src.modules.analysis.rules import decide
from src.modules.analysis.score_writer import existing_score, save_score
from src.modules.analysis.scorer import CallContext, CallScorer
from src.modules.analysis.validator import ScoreInvalid
from src.modules.calls.models import CallModel

if TYPE_CHECKING:  # the deps dataclass lives in pipeline.py, which imports this
    from src.modules.analysis.pipeline import PipelineDeps

log = get_logger(__name__)

#: How the call is described to the model in the prompt's header.
_STARTED_FORMAT = "%d/%m/%Y %H:%M"


class ScoreStage:
    """Transcript -> a validated score. Owns the LLM limiter and cooldown."""

    def __init__(self, deps: PipelineDeps, config: AnalysisConfig) -> None:
        self._deps = deps
        self._config = config
        self._limiter = RateLimiter(AiRole.LLM.value, config.llm_rpm)
        self._cooldown = ProviderCooldown(AiRole.LLM)

    @property
    def limiter(self) -> RateLimiter:
        return self._limiter

    async def run(
        self,
        session: AsyncSession,
        call: CallModel,
        transcript: CallTranscriptModel,
        *,
        force: bool = False,
    ) -> StageOutcome:
        started = perf_counter()

        if not force:
            already = await existing_score(session, call.id)
            if already is not None:
                return StageOutcome(
                    stage=Stage.SCORE,
                    result=StageResult.SKIPPED,
                    detail=(
                        f"a score already exists: {already.overall_score} points "
                        f"({already.model}, rubric {already.rubric_version})"
                    ),
                )

        # The cooldown check first, for the same reason as in the transcribe
        # stage: with the quota spent, building the prompt is wasted work.
        # Counted SEPARATELY from ``asr`` — the two roles can be different
        # models against different quotas, and an exhausted ASR quota must not
        # stop the scoring of transcripts that already exist.
        left = await self._cooldown.remaining(session)
        if left:
            raise ProviderCooldownActive(
                cooldown_detail(AiRole.LLM, left), stage=Stage.SCORE
            )

        llm = await self._deps.llm_factory(session)

        # Same reason as in ``transcribe.py``: reading settings opens a
        # transaction and the LLM round trip is long. Waiting it out inside an
        # open transaction holds a connection and the vacuum horizon for
        # nothing.
        await session.commit()

        async def invoke(*, system: str, user: str, schema: dict[str, Any]) -> str:
            async def attempt() -> str:
                await self._limiter.acquire()
                return await llm.complete(
                    system=system, user=user, schema=schema, max_tokens=4096
                )

            try:
                return await with_backoff(
                    attempt,
                    max_retries=self._config.max_retries,
                    base_sec=self._config.backoff_base_sec,
                    max_sec=self._config.backoff_max_sec,
                    label=Stage.SCORE.value,
                    call_id=call.id,
                    max_wait_sec=self._config.max_wait_sec,
                )
            except ProviderRateLimitError as exc:
                # As in the transcribe stage: the first call to hit the limit
                # marks the role, and the next one stops at the pre-check.
                await self._cooldown.start_from(
                    session,
                    exc,
                    quota_sec=self._config.quota_cooldown_sec,
                    floor_sec=self._config.backoff_max_sec,
                    detail=redact(exc.message),
                )
                await session.commit()
                raise

        scorer = CallScorer(
            llm,
            rubric_blocks=DEFAULT_RUBRIC["blocks"],
            rubric_red_flags=DEFAULT_RUBRIC["red_flags"],
            # Phase 2, with the editable rubric: the admin's extra rules are
            # part of the rubric and therefore versioned with it.
            extra_rules=None,
            invalid_retries=self._config.invalid_retries,
            invoke=invoke,
        )

        text = transcript.text or ""
        duration_sec = call.duration_sec or 0
        try:
            outcome = await scorer.score(
                CallContext(
                    transcript=text,
                    duration_sec=duration_sec,
                    direction=str(call.direction),
                    started_at=call.started_at.strftime(_STARTED_FORMAT),
                    # A name means the number is in the contact book, i.e. a
                    # KNOWN customer — a real signal for the rubric, which does
                    # not demand a full introduction to somebody who has bought
                    # before.
                    client_label=call.contact_name,
                )
            )
        except ScoreInvalid as exc:
            # Every re-ask was spent and the arithmetic still did not hold.
            # Permanent on purpose: asking a fourth time buys the same answer
            # at the same price.
            raise AnalysisError(
                exc.message,
                failure=AnalysisFailure.SCORE_INVALID,
                stage=Stage.SCORE,
            ) from exc
        finally:
            # One leak per scored call is nothing; a worker that scores for a
            # week runs out of file descriptors. See ``BaseClient.aclose``.
            await llm.aclose()

        draft = outcome.draft

        if draft.warnings:
            # Discrepancies that did NOT change the number must not disappear
            # quietly: they are the only evidence of where the model is drifting
            # and the only input for tuning the prompt.
            log.warning(
                "analysis_score_warnings",
                call_id=str(call.id),
                warnings=draft.warnings,
            )

        review = decide(
            confidence_pct=draft.confidence_pct,
            transcript_quality=draft.transcript_quality,
            transcript_text=text,
            duration_sec=duration_sec,
            red_flag_types=[flag["type"] for flag in draft.red_flags],
            ai_score=draft.overall,
            na_over_budget=draft.na_over_budget,
        )

        # WHAT IS NOT MEASURED YET, AND WHY IT IS NOT ZERO. The LLM billing unit
        # is tokens, and phase 1's client protocol returns only the answer text
        # (``LLMClient.complete() -> str``); no vendor usage block comes back
        # through it. So both token counts are NULL, which the column documents
        # as "the provider reported nothing" — deliberately not 0, which would
        # read as "this call was free" (§11.1). ``llm_cost_micro_usd`` is called
        # anyway so the arithmetic has one home and starts working the day the
        # protocol carries usage.
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        cost = llm_cost_micro_usd(
            self._config,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        await save_score(
            session,
            call_id=call.id,
            draft=draft,
            review=review,
            provider=getattr(llm, "provider_key", "unknown"),
            model=getattr(llm, "model", "unknown"),
            rubric_version=RUBRIC_VERSION,
            llm_calls=outcome.llm_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            # NULL rather than 0 while nothing can be computed: null means "not
            # priced", 0 would mean "free".
            cost_micro_usd=cost or None,
        )

        elapsed_ms = int((perf_counter() - started) * 1000)
        log.info(
            "analysis_scored",
            call_id=str(call.id),
            model=getattr(llm, "model", "?"),
            rubric=RUBRIC_VERSION,
            score=draft.overall,
            confidence_pct=draft.confidence_pct,
            red_flags=len(draft.red_flags),
            needs_review=review.needs_review,
            review_reasons=review.codes or None,
            llm_calls=outcome.llm_calls,
            elapsed_ms=elapsed_ms,
        )

        return StageOutcome(
            stage=Stage.SCORE,
            result=StageResult.DONE,
            detail=f"{draft.overall} points, rubric {RUBRIC_VERSION}",
            provider_calls=outcome.llm_calls,
            elapsed_ms=elapsed_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
