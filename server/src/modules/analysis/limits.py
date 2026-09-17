"""Every limit that stands between this module and the vendor's invoice.

Five of them, and each one exists because the one above it is not enough:

1. **The feature flag and the two monthly caps** (§4.4, §4.5) — the outermost
   ring. Nothing below this file limits anything: a loop over
   ``get_asr_client()`` would bill without bound, so "may we spend at all, and
   have we spent enough this month" is answered here, before a call is claimed.
2. **Concurrency** — ``asyncio.Semaphore`` in ``pipeline.run_batch``. Without
   it a backlog opens every call at once and throttles the vendor and the
   database together.
3. **Rate** (:class:`RateLimiter`) — requests per minute per role.
4. **Cooldown** (:class:`ProviderCooldown`) — a role that has spent its quota
   is not asked again at all, for a while. This is the one that matters most
   under a daily quota, and it is the one the rate limiter cannot do.
5. **Backoff** (:func:`with_backoff`) — when the vendor answers 429 or 503
   anyway: wait as long as the vendor asked, or exponentially with jitter, and
   never longer than one worker slot can afford.

**No Redis and no broker** (§5). BonviZvonki shared the rate window and the
cooldown through Redis because several Celery workers ran the pipeline at once.
Here ``core/jobs.py`` takes a PostgreSQL advisory lock, so exactly one
``analysis_run`` executes anywhere at a time: an in-process window is not an
approximation of the shared one, it is exact. The cooldown moves the other way
— into a table, because it must survive a restart and because the status
endpoint has to be able to read it. When the queue stops, "which role is in
cooldown and for how long" is the first thing an operator needs.

``cooldown_message()`` did not come across. It formatted an Uzbek sentence for
an admin, and user-facing wording lives in the panel's ``uz.json`` now
(CONVENTIONS.md §14); what this module writes is the English technical detail
beside the code.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.enums import AiRole, AnalysisFailure, AnalysisStage
from src.core.logging import get_logger
from src.modules.analysis.config import AnalysisConfig
from src.modules.analysis.errors import (
    ProviderError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    human_delay,
    is_daily_quota,
)
from src.modules.analysis.errors import retry_after_sec as stated_retry_after
from src.modules.analysis.models import AiProviderCooldownModel, CallAnalysisStateModel

log = get_logger(__name__)

#: One micro-USD is 1/1,000,000 of a dollar. Integer money, everywhere (§2.3).
MICRO_USD = 1_000_000


# --- Rate ------------------------------------------------------------------


class RateLimiter:
    """Requests per minute for one role, as an in-process sliding window.

    Exact rather than approximate, which the Redis version could not be: it
    counted into a fixed minute bucket with one ``INCR``, so twice the limit
    could pass across a bucket boundary. That was an acceptable trade when the
    counter had to be shared between workers; here there is only ever one
    ``analysis_run``, so the window can simply be a list of the last minute's
    timestamps.

    ``per_minute <= 0`` disables it, deliberately — that is the documented
    meaning of ``analysis.asr_rpm = 0``.
    """

    def __init__(self, name: str, per_minute: int) -> None:
        self.name = name
        self.per_minute = max(0, per_minute)
        self.waits = 0
        self.waited_sec = 0.0
        self._recent: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self.per_minute <= 0:
            return
        # The lock is held across the sleep on purpose: releasing it would let
        # every waiter recompute the same gap and wake together, which is the
        # thundering herd the limiter exists to prevent.
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._recent and now - self._recent[0] >= 60.0:
                    self._recent.popleft()
                if len(self._recent) < self.per_minute:
                    self._recent.append(now)
                    return
                # Wait for the oldest request in the window to age out, plus a
                # little jitter so two roles do not resume in lockstep.
                sleep_for = 60.0 - (now - self._recent[0]) + random.uniform(0, 0.5)
                self.waits += 1
                self.waited_sec += sleep_for
                log.info(
                    "analysis_rate_limited",
                    limiter=self.name,
                    per_minute=self.per_minute,
                    sleep_sec=round(sleep_for, 2),
                )
                await asyncio.sleep(sleep_for)


# --- Cooldown --------------------------------------------------------------


class ProviderCooldown:
    """A role that is not asked again until its quota has had time to reset.

    WHY THE RATE LIMITER IS NOT ENOUGH. It caps requests per *minute*. Gemini's
    free tier caps them per *day*: once 500 are spent the vendor answers 429 to
    everything, no matter how slowly it is asked. The limiter never trips,
    because 60 rpm was never reached — so every queued call still opens its
    audio, still posts it, still collects a 429, and still retries four times.
    Measured with 7,328 jobs queued: roughly 36,000 pointless uploads and 36,000
    pointless requests, for an answer that was known in advance.

    So the first exhausted quota writes a row here, and every later stage stops
    at the pre-check having sent nothing at all.

    Keyed by **role** and not by provider: one account can serve both roles
    against different models and different quotas, and an exhausted ASR quota
    must not stop the scoring of transcripts that already exist.

    A table rather than a Redis key with a TTL. It survives a restart, and
    ``GET /analysis/status`` can read it — which is what an operator needs at
    the moment the queue goes quiet.
    """

    def __init__(self, role: AiRole) -> None:
        self.role = role

    async def remaining(self, session: AsyncSession) -> int:
        """Seconds left, rounded up. ``0`` means the road is open."""
        until = await session.scalar(
            select(AiProviderCooldownModel.until_at).where(
                AiProviderCooldownModel.role == self.role
            )
        )
        if until is None:
            return 0
        left = (until - clock.now()).total_seconds()
        return max(0, int(left + 0.999))

    async def start(
        self,
        session: AsyncSession,
        seconds: float,
        *,
        reason: AnalysisFailure,
        detail: str | None = None,
    ) -> int:
        """Open (or extend) the cooldown. Returns the seconds now in force.

        **A longer existing cooldown is never shortened.** Two workers hitting
        429 seconds apart would otherwise let the second one's per-minute window
        cancel the first one's daily one, and the whole queue would resume into
        a quota that has not reset. The rule is expressed as the ``WHERE`` of
        the upsert rather than as a read-then-write, so two claimers racing on
        it cannot interleave.
        """
        seconds = int(max(1.0, seconds))
        now = clock.now()
        until = now + timedelta(seconds=seconds)
        statement = (
            pg_insert(AiProviderCooldownModel)
            .values(
                role=self.role,
                until_at=until,
                started_at=now,
                reason_code=reason,
                detail=detail,
            )
            .on_conflict_do_update(
                index_elements=[AiProviderCooldownModel.role],
                set_={
                    "until_at": until,
                    "started_at": now,
                    "reason_code": reason,
                    "detail": detail,
                },
                where=AiProviderCooldownModel.until_at < until,
            )
        )
        await session.execute(statement)
        await session.flush()
        left = await self.remaining(session)
        log.warning(
            "analysis_cooldown_started",
            role=str(self.role),
            asked_sec=seconds,
            seconds=left,
            reason=str(reason),
        )
        return left

    async def start_from(
        self,
        session: AsyncSession,
        exc: BaseException,
        *,
        quota_sec: int,
        floor_sec: float,
        detail: str | None = None,
    ) -> int:
        """Choose the length from the 429 itself. Two events, two prices.

        * **A daily quota is spent** — not one request is accepted until
          tomorrow, so ``quota_sec`` (half an hour by default) applies. Not
          "until midnight": an admin may raise the tier or swap the key, and the
          system should find that out by itself.
        * **A per-minute burst** — the vendor usually says how long to wait, so
          that is what is used, but never below ``floor_sec``. A two-second
          cooldown is not a cooldown.
        """
        if getattr(exc, "daily_quota", False) or is_daily_quota(exc):
            return await self.start(
                session,
                quota_sec,
                reason=AnalysisFailure.PROVIDER_RATE_LIMIT,
                detail=detail,
            )
        stated = getattr(exc, "retry_after_sec", None)
        if stated is None:
            stated = stated_retry_after(exc)
        return await self.start(
            session,
            max(float(stated or 0.0), floor_sec),
            reason=AnalysisFailure.PROVIDER_RATE_LIMIT,
            detail=detail,
        )

    async def clear(self, session: AsyncSession) -> None:
        """End the cooldown early — for an operator, and for tests."""
        row = await session.get(AiProviderCooldownModel, self.role)
        if row is not None:
            await session.delete(row)
            await session.flush()


def cooldown_detail(role: AiRole, seconds: int) -> str:
    """The English technical line that goes in ``failure_detail``.

    The Uzbek sentence a person reads is keyed off ``failure_code`` in the
    panel's ``uz.json``; this is the detail beside it.
    """
    return (
        f"the {role.value} provider is in cooldown for another "
        f"{human_delay(seconds)}; the call stays queued and is retried"
    )


# --- Backoff ---------------------------------------------------------------


def _status_of(exc: BaseException) -> int | None:
    """The HTTP status inside a **foreign** (SDK) exception.

    ONLY for exceptions that are not ours. On a :class:`ProviderError`,
    ``status_code`` is the shape of *our* answer (``502``, ``409``, ``503``),
    not the vendor's — reading it as a vendor status would make "the SDK is not
    installed" look like "the server is busy" and retry it four times.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def is_rate_limited(exc: BaseException) -> bool:
    if isinstance(exc, ProviderError):
        # Already classified by ``errors.translate()``: the type carries it.
        return isinstance(exc, ProviderRateLimitError)
    return _status_of(exc) == 429


def is_retryable(exc: BaseException) -> bool:
    """Failures where asking again can plausibly give a different answer.

    Three families, all of them "the vendor's side, temporarily":

    * 429 — the request limit;
    * 5xx — "the model is busy", which Gemini returns under ordinary load;
    * network — the connection dropped or timed out.

    WHY 5xx IS IN THE LIST. It once was not, and a single 503 marked a call
    ``failed`` outright: getting it scored then needed a person to come and
    press a button. On a hundred-call queue that is dozens of "failed" rows with
    no actual failure behind them — the model was busy for a few seconds.

    Client errors (400, 401, 404 — a wrong key, an unknown model) are excluded
    deliberately: they do not heal, and retrying only spends time and money.
    """
    if isinstance(exc, ProviderError):
        return isinstance(
            exc,
            ProviderRateLimitError | ProviderUnavailableError | ProviderNetworkError,
        )
    status = _status_of(exc)
    return status == 429 or (status is not None and status >= 500)


def _wait_for(
    exc: BaseException, attempt: int, base_sec: float, max_sec: float
) -> tuple[float, str]:
    """How long to wait before the next attempt, and why that long.

    ASK THE VENDOR FIRST. On a 429 the provider nearly always says when to come
    back — a ``Retry-After`` header, or Google's ``RetryInfo.retryDelay``. That
    value used to be ignored in favour of a blind 2/4/8/16, which is wrong in
    both directions: too early and the retry is wasted, too late and the worker
    idles.

    When the vendor says nothing, exponential with jitter. The jitter is not
    decoration — without it every waiter wakes at the same instant and collects
    the same 429 together.
    """
    stated = getattr(exc, "retry_after_sec", None)
    if stated is None:
        stated = stated_retry_after(exc)
    if stated is not None:
        # Jitter here too, but only upwards: asking again *before* the vendor
        # said to is pointless.
        return float(stated) + random.uniform(0, 0.5), "vendor"
    delay = min(base_sec * (2 ** (attempt - 1)), max_sec)
    return delay + random.uniform(0, min(1.0, base_sec)), "exponential"


async def with_backoff(
    action: Callable[[], Awaitable[Any]],
    *,
    max_retries: int,
    base_sec: float,
    max_sec: float,
    label: str,
    call_id: UUID | None = None,
    max_wait_sec: float = 60.0,
) -> Any:
    """Call ``action()``; on a transient failure wait and try again.

    TWO CASES ARE NEVER RETRIED, because the answer is known in advance:

    1. **A daily quota is spent.** The vendor will not accept a single request
       until tomorrow. Measured: ``gemini-3.1-flash-lite`` allows 500 requests a
       day on the free tier, and when it ran out 885 calls each tried five times
       and collected five 429s.
    2. **The vendor asked for longer than ``max_wait_sec``.** Sleeping inside a
       worker slot holds the slot. With two slots, a ten-minute sleep stops the
       whole queue and looks from outside like a hung worker.

    In both cases the exception travels up and the caller puts the role into
    cooldown, which is what stops the *next* call before it opens any audio.

    A NOTE ON WHAT CHANGED. BonviZvonki's third argument for not retrying was
    that every attempt re-downloaded megabytes from MoiZvonki. That is no longer
    true — the recording is a local file and a retry costs a fresh file handle
    (§3.3). The other two reasons still hold, so the code stays and this comment
    replaces the old one rather than translating it: a false justification
    attached to correct code is worse than no comment at all.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return await action()
        except Exception as exc:
            if not is_retryable(exc) or attempt > max_retries:
                raise

            if getattr(exc, "daily_quota", False) or is_daily_quota(exc):
                log.warning(
                    "analysis_quota_exhausted",
                    stage=label,
                    call_id=str(call_id) if call_id else None,
                    attempt=attempt,
                    reason=getattr(exc, "message", str(exc)),
                )
                raise

            delay, source = _wait_for(exc, attempt, base_sec, max_sec)
            if delay > max_wait_sec:
                log.warning(
                    "analysis_wait_too_long",
                    stage=label,
                    call_id=str(call_id) if call_id else None,
                    attempt=attempt,
                    asked_sec=round(delay, 2),
                    max_wait_sec=max_wait_sec,
                    reason=getattr(exc, "message", str(exc)),
                )
                raise

            log.warning(
                "analysis_backoff",
                stage=label,
                call_id=str(call_id) if call_id else None,
                attempt=attempt,
                max_retries=max_retries,
                sleep_sec=round(delay, 2),
                sleep_source=source,
                reason=getattr(exc, "message", str(exc)),
            )
            await asyncio.sleep(delay)


# --- The month, and the two caps -------------------------------------------


def month_start(moment: datetime | None = None) -> datetime:
    """The first instant of the current **Tashkent** calendar month, in UTC.

    Tashkent and not UTC because the person reading the bill lives there: a
    month that turns over at 05:00 local would put the first five hours of every
    month into the previous one's cap, and the explanation for that is longer
    than the code (§2.3).
    """
    local = (moment or clock.now()).astimezone(clock.TASHKENT)
    first = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return first.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class MonthUsage:
    """What the feature has spent this Tashkent month."""

    month_from: datetime
    calls: int
    """``call_analysis_state`` rows that reached ``completed`` this month."""
    cost_micro_usd: int


#: The two cap names, as the log line and the status endpoint spell them. The
#: alert has to say **which** cap stopped the pipeline: "raise the price cap"
#: and "raise the call cap" are different actions with different consequences.
CAP_CALLS = "monthly_max_calls"
CAP_COST = "monthly_cost_cap_micro_usd"


@dataclass(frozen=True, slots=True)
class CapState:
    """Whether the pipeline may spend, and which cap stopped it if not."""

    usage: MonthUsage
    cap_micro_usd: int
    cap_calls: int
    reached: str | None = None
    reason: str | None = None

    @property
    def blocked(self) -> bool:
        return self.reached is not None


async def month_usage(session: AsyncSession, moment: datetime | None = None) -> MonthUsage:
    """Completed calls and measured cost since the start of the Tashkent month.

    The cost is summed over **every** state row rather than only the completed
    ones: a call that failed halfway through still paid for the ASR request it
    made, and a cap that ignored that would be a cap with a hole in it.
    """
    since = month_start(moment)
    completed = await session.scalar(
        select(func.count())
        .select_from(CallAnalysisStateModel)
        .where(
            CallAnalysisStateModel.stage == AnalysisStage.COMPLETED,
            CallAnalysisStateModel.last_run_at >= since,
        )
    )
    spent = await session.scalar(
        select(func.coalesce(func.sum(CallAnalysisStateModel.cost_micro_usd), 0)).where(
            CallAnalysisStateModel.last_run_at >= since
        )
    )
    return MonthUsage(
        month_from=since, calls=int(completed or 0), cost_micro_usd=int(spent or 0)
    )


async def cap_state(
    session: AsyncSession, config: AnalysisConfig, moment: datetime | None = None
) -> CapState:
    """Check both monthly caps (§4.5).

    TWO CAPS, BECAUSE ONE OF THEM CAN BE ZERO. The money cap is measured units
    multiplied by an admin-entered price, and that price starts unset — so on
    day one every call costs 0 and the money cap can never trip. The call-count
    cap always means something, which makes it the one that actually protects
    the account until somebody types a vendor's price in. Once they have, the
    money cap becomes the real control.

    A cap of ``0`` means **stop**, not "no limit": ``analysis.monthly_max_calls
    = 20`` is how task 12 runs its twenty-call trial, and ``= 0`` has to be able
    to mean "not one more call".
    """
    usage = await month_usage(session, moment)
    reached: str | None = None
    reason: str | None = None
    if usage.calls >= config.monthly_max_calls:
        reached = CAP_CALLS
        reason = (
            f"the monthly call cap is reached: {usage.calls} of "
            f"{config.monthly_max_calls} since {usage.month_from.date()}"
        )
    elif usage.cost_micro_usd >= config.monthly_cost_cap_micro_usd:
        reached = CAP_COST
        reason = (
            f"the monthly cost cap is reached: {usage.cost_micro_usd} of "
            f"{config.monthly_cost_cap_micro_usd} micro-USD since "
            f"{usage.month_from.date()}"
        )
    return CapState(
        usage=usage,
        cap_micro_usd=config.monthly_cost_cap_micro_usd,
        cap_calls=config.monthly_max_calls,
        reached=reached,
        reason=reason,
    )


def asr_cost_micro_usd(config: AnalysisConfig, audio_duration_ms: int | None) -> int:
    """Measured audio minutes x the admin-entered price, rounded half up.

    ``0`` while the price is unset, and that zero means **not priced** rather
    than "free" — which is exactly why ``GET /analysis/status`` reports
    ``priced`` beside the number (§11.1).
    """
    price = config.price_asr_micro_usd_per_minute
    if not price or not audio_duration_ms:
        return 0
    return (audio_duration_ms * price + 30_000) // 60_000


def llm_cost_micro_usd(
    config: AnalysisConfig,
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> int:
    """Measured tokens x the two admin-entered prices, rounded half up.

    ``None`` tokens means the provider reported none, so nothing can be
    computed. It is not zero cost — it is an unmeasured one, which is the
    difference the status endpoint's ``priced`` flag exists to show.
    """
    total = 0
    if prompt_tokens and config.price_llm_micro_usd_per_1k_input_tokens:
        total += (
            prompt_tokens * config.price_llm_micro_usd_per_1k_input_tokens + 500
        ) // 1000
    if completion_tokens and config.price_llm_micro_usd_per_1k_output_tokens:
        total += (
            completion_tokens * config.price_llm_micro_usd_per_1k_output_tokens + 500
        ) // 1000
    return total
