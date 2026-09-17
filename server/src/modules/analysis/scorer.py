"""Transcript -> a validated score.

This layer knows nothing about the database and nothing about the queue: text
goes in, a ``ScoreDraft`` comes out. That is what lets a test call it with a
stub LLM and no pipeline, no session and no vendor key.

Rate limiting and transport retries live in the pipeline; what arrives here is
a ready ``invoke`` callable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from src.core.logging import get_logger
from src.modules.analysis.prompt import (
    build_retry_prompt,
    build_schema,
    build_system_prompt,
    build_user_prompt,
)

# ``providers.types`` holds protocols only and imports no vendor SDK, so this
# costs nothing at start-up: each client imports its SDK inside the call
# (SPEC-ANALYTICS §4.3).
from src.modules.analysis.providers.types import LLMClient
from src.modules.analysis.validator import (
    ScoreDraft,
    ScoreInvalid,
    na_budget,
    validate,
)

log = get_logger(__name__)

#: The score JSON is not long, but every criterion needs its evidence.
MAX_TOKENS = 4096

Invoke = Callable[..., Awaitable[str]]


@dataclass(slots=True)
class CallContext:
    """The call as the LLM sees it — text only, never audio."""

    transcript: str
    duration_sec: int
    direction: str
    started_at: str
    client_label: str | None = None
    """The customer's name — a signal for IS THIS CUSTOMER KNOWN. ``None`` means
    the number is not in the contact book."""


@dataclass(slots=True)
class ScoringOutcome:
    draft: ScoreDraft
    llm_calls: int
    attempts: int


class CallScorer:
    """Score one call against the active rubric."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        rubric_blocks: list[dict[str, Any]],
        rubric_red_flags: list[dict[str, Any]],
        extra_rules: str | None = None,
        invalid_retries: int = 1,
        invoke: Invoke | None = None,
    ) -> None:
        self._llm = llm
        self._blocks = rubric_blocks
        self._red_flags = rubric_red_flags
        self._extra_rules = extra_rules
        self._invalid_retries = max(0, invalid_retries)
        self._invoke = invoke or self._direct_invoke

        # The rubric-dependent half is built once and does NOT change — that is
        # exactly what prompt caching requires.
        self._system = build_system_prompt(rubric_blocks, rubric_red_flags, extra_rules)
        self._schema = build_schema(rubric_blocks, rubric_red_flags)

    @property
    def system_prompt(self) -> str:
        return self._system

    @property
    def schema(self) -> dict[str, Any]:
        return self._schema

    async def _direct_invoke(self, *, system: str, user: str, schema: dict) -> str:
        return await self._llm.complete(
            system=system, user=user, schema=schema, max_tokens=MAX_TOKENS
        )

    async def score(self, context: CallContext) -> ScoringOutcome:
        # The `na` budget depends on the length of the call and it is needed in
        # TWO places: in the prompt (so the model knows the limit up front) and
        # in the validator (so the limit is actually applied). It comes from one
        # source — otherwise the model would see one limit and be checked
        # against another.
        budget = na_budget(context.duration_sec)
        base_user = build_user_prompt(
            transcript=context.transcript,
            duration_sec=context.duration_sec,
            direction=context.direction,
            started_at=context.started_at,
            client_label=context.client_label,
            na_budget=budget,
        )

        calls = 0
        last_error: ScoreInvalid | None = None

        for attempt in range(self._invalid_retries + 1):
            user = base_user
            if last_error is not None:
                user = base_user + build_retry_prompt(last_error.message)
            # On the last attempt the `na` budget is SOFT: rejecting has no
            # meaning left — the call would end up unscored and the money
            # already paid would be wasted. The score is accepted, and
            # `na_over_budget` lifts it into the review queue.
            is_last = attempt == self._invalid_retries

            raw = await self._invoke(
                system=self._system, user=user, schema=self._schema
            )
            calls += 1

            try:
                draft = validate(
                    raw,
                    rubric_blocks=self._blocks,
                    rubric_red_flags=self._red_flags,
                    duration_sec=context.duration_sec,
                    enforce_na_budget=not is_last,
                )
            except ScoreInvalid as exc:
                last_error = exc
                log.warning(
                    "score.invalid",
                    attempt=attempt + 1,
                    model=getattr(self._llm, "model", "?"),
                    reason=exc.message,
                )
                continue

            return ScoringOutcome(draft=draft, llm_calls=calls, attempts=attempt + 1)

        assert last_error is not None
        raise last_error
