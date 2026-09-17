"""Stage 1: the recording becomes one ``call_transcripts`` row.

The chain is ``AudioService.analysis_source()`` -> an ``AsyncIterator[bytes]``
-> the ASR client.

**What is different here, and why the ported comments were replaced rather than
translated.** BonviZvonki never owned the bytes: its contract's first rule was
that audio is stored neither on disk nor in the database, so this file opened a
MoiZvonki HTTP stream, counted the bytes as they went past and refused to let
anything materialise. Those comments, copied across, would read as a rule about
BonviCall — and the next person would obey a constraint that does not exist
while missing the one that does.

The real rule here is narrower and stricter: **the file may be opened, but only
by ``modules/audio/``** (SPEC §6, CONVENTIONS.md §2). This module receives a
callable and never a path, never a storage key, and never imports the storage
class; ``test_pipeline_shape`` asserts it over every file in the module.

Idempotent: a call that already has a transcript row does not reach the
provider, so a second run spends nothing.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from time import perf_counter
from typing import IO, TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.enums import AiRole, AnalysisFailure
from src.core.errors import GoneError, NotFoundError
from src.core.logging import get_logger
from src.core.storage import CHUNK_BYTES
from src.modules.analysis.config import AnalysisConfig
from src.modules.analysis.entities import (
    AnalysisError,
    NotAnalysable,
    ProviderCooldownActive,
    Stage,
    StageOutcome,
    StageResult,
    TranscriptEmpty,
)
from src.modules.analysis.errors import ProviderRateLimitError, redact
from src.modules.analysis.limits import (
    ProviderCooldown,
    RateLimiter,
    cooldown_detail,
    with_backoff,
)
from src.modules.analysis.models import CallTranscriptModel
from src.modules.analysis.providers.base import MAX_AUDIO_MB
from src.modules.analysis.providers.types import Transcript
from src.modules.analysis.rules import count_words
from src.modules.audio.service import AnalysisSource, AudioNotAnalysable, AudioService
from src.modules.calls.models import CallModel

if TYPE_CHECKING:  # the deps dataclass lives in pipeline.py, which imports this
    from src.modules.analysis.pipeline import PipelineDeps

log = get_logger(__name__)

#: The size the pipeline refuses before a byte is read. The same number the
#: client would enforce mid-stream (``providers/base.MAX_AUDIO_MB``), applied
#: earlier: BonviCall knows the size from ``call_audio`` in advance, so nothing
#: has to be allocated to discover it. The in-client guard stays as the second
#: line of defence, for a file that lies about its length (§3.1).
MAX_AUDIO_BYTES = MAX_AUDIO_MB * 1024 * 1024


async def stream_bytes(
    source: AnalysisSource, chunk_bytes: int = CHUNK_BYTES
) -> AsyncIterator[bytes]:
    """The recording as an async stream, read off the event loop.

    ``source.open()`` and every ``read()`` go through ``asyncio.to_thread``: a
    synchronous file read on the event loop blocks every other call in flight,
    and with ``analysis.concurrency`` calls running that is the difference
    between two providers working in parallel and two working in turn.

    Because this is a plain ``AsyncIterator[bytes]``, the
    ``ASRClient.transcribe`` signature is unchanged and all three provider
    clients came across untouched (§3.1).
    """
    handle: IO[bytes] = await asyncio.to_thread(source.open)
    try:
        while True:
            chunk = await asyncio.to_thread(handle.read, chunk_bytes)
            if not chunk:
                return
            yield chunk
    finally:
        await asyncio.to_thread(handle.close)


async def existing_transcript(
    session: AsyncSession, call_id: uuid.UUID
) -> CallTranscriptModel | None:
    return (
        await session.execute(
            select(CallTranscriptModel).where(CallTranscriptModel.call_id == call_id)
        )
    ).scalar_one_or_none()


async def save_transcript(
    session: AsyncSession,
    *,
    call_id: uuid.UUID,
    transcript: Transcript,
    text: str,
    language: str | None,
    audio_bytes: int,
    audio_duration_ms: int | None,
    asr_ms: int,
) -> CallTranscriptModel:
    """Write the transcript. An existing row is overwritten, never duplicated.

    ``call_transcripts.call_id`` is UNIQUE, so the idempotency is a database
    fact rather than a habit of this function; the function only decides which
    of the two it is doing.
    """
    row = await existing_transcript(session, call_id)
    if row is None:
        row = CallTranscriptModel(call_id=call_id)
        session.add(row)

    row.text = text
    row.language = language
    row.provider = (transcript.provider or "unknown")[:32]
    row.model = (transcript.model or "unknown")[:64]
    row.char_count = len(text)
    # ``rules.count_words`` and not ``text.split()``: the service tokens
    # ('[MM:SS]', 'SPEAKER_n:') are roughly two fake words per line, which is
    # what once stopped the short-transcript review rule firing on exactly the
    # shortest — that is, the most suspect — conversations.
    row.word_count = count_words(text)
    row.audio_bytes = audio_bytes
    row.audio_duration_ms = audio_duration_ms
    row.asr_ms = asr_ms
    row.transcribed_at = clock.now()

    await session.flush()
    return row


class TranscribeStage:
    """Recording -> text. Owns the ASR rate limiter and the ASR cooldown."""

    def __init__(self, deps: PipelineDeps, config: AnalysisConfig) -> None:
        self._deps = deps
        self._config = config
        self._limiter = RateLimiter(AiRole.ASR.value, config.asr_rpm)
        self._cooldown = ProviderCooldown(AiRole.ASR)

    @property
    def limiter(self) -> RateLimiter:
        return self._limiter

    async def _source(
        self, session: AsyncSession, call_id: uuid.UUID
    ) -> AnalysisSource:
        """Locate the recording, translating the audio module's four refusals.

        **Both limits are passed.** ``AudioService.analysis_source`` defaults
        them to ``None``, which means "do not judge" — that module holds no
        analysis policy and reads no ``analysis.*`` setting, so leaving either
        out silently disables a guard that looks present from the outside.
        """
        try:
            return await AudioService(session).analysis_source(
                call_id,
                min_duration_ms=self._config.min_duration_sec * 1000,
                max_bytes=MAX_AUDIO_BYTES,
            )
        except GoneError as exc:
            # Retention took the blob. ``calls.has_audio`` is still true — the
            # row records that there WAS a recording — so this is the only
            # place the difference is visible.
            raise NotAnalysable(
                "the recording was deleted by retention",
                failure=AnalysisFailure.AUDIO_EXPIRED,
                stage=Stage.TRANSCRIBE,
            ) from exc
        except NotFoundError as exc:
            raise NotAnalysable(
                "no recording is stored for this call",
                failure=AnalysisFailure.NO_AUDIO,
                stage=Stage.TRANSCRIBE,
            ) from exc
        except AudioNotAnalysable as exc:
            # ``.failure`` is written verbatim: the audio module already chose
            # the ``AnalysisFailure`` member, and a second mapping table here
            # would be one more thing to keep in step with it.
            raise AnalysisError(
                exc.detail, failure=exc.failure, stage=Stage.TRANSCRIBE
            ) from exc

    async def run(
        self, session: AsyncSession, call: CallModel, *, force: bool = False
    ) -> tuple[StageOutcome, CallTranscriptModel]:
        """The transcript row, or an exception. Never a ``None`` row."""
        started = perf_counter()

        # --- Idempotency: nothing already paid for is paid for twice --------
        existing = await existing_transcript(session, call.id)
        if existing is not None and not force:
            return (
                StageOutcome(
                    stage=Stage.TRANSCRIBE,
                    result=StageResult.SKIPPED,
                    detail=f"a transcript already exists ({existing.char_count} chars)",
                ),
                existing,
            )

        # --- The cooldown check, BEFORE the audio is opened -----------------
        #
        # The order is the whole point. Below this line the recording is opened
        # and megabytes are posted to a vendor; with the quota already spent the
        # answer is known in advance. Measured on the version that checked
        # afterwards: ~36,000 pointless uploads against an exhausted quota.
        left = await self._cooldown.remaining(session)
        if left:
            raise ProviderCooldownActive(
                cooldown_detail(AiRole.ASR, left), stage=Stage.TRANSCRIBE
            )

        source = await self._source(session, call.id)
        asr = await self._deps.asr_factory(session)
        language = self._config.asr_language

        # LET GO OF THE DATABASE. The two lines above read settings, and a read
        # opens a transaction. The provider call below — retries included, up to
        # ``max_wait_sec`` — would then sit inside it, and ``pg_stat_activity``
        # would show the worker "idle in transaction" for 37 seconds while
        # another query waited on ``Lock: transactionid``. Nothing is written
        # here, so this commit is cheap: it closes the transaction, releases the
        # connection and stops holding back vacuum.
        await session.commit()

        calls_made = 0

        async def attempt() -> Transcript:
            nonlocal calls_made
            await self._limiter.acquire()
            # A fresh handle per attempt, deliberately: a stream somebody
            # already read to the end is not a retry. Re-opening a local file
            # costs nothing, which is the whole difference from the version
            # that had to download it again (§3.3).
            result = await asr.transcribe(
                stream_bytes(source),
                filename=source.filename,
                language=language,
            )
            # Counted only AFTER an answer: a 429 was refused, not billed, so
            # recording it as a provider call would overstate what was spent.
            calls_made += 1
            return result

        try:
            transcript = await with_backoff(
                attempt,
                max_retries=self._config.max_retries,
                base_sec=self._config.backoff_base_sec,
                max_sec=self._config.backoff_max_sec,
                label=Stage.TRANSCRIBE.value,
                call_id=call.id,
                max_wait_sec=self._config.max_wait_sec,
            )
        except ProviderRateLimitError as exc:
            # THE COOLDOWN STARTS HERE. The first call to hit the limit marks
            # it for the whole fleet, and every later stage stops at the
            # pre-check above without sending a byte. The error is not
            # swallowed: this call is still recorded with its own real reason.
            await self._cooldown.start_from(
                session,
                exc,
                quota_sec=self._config.quota_cooldown_sec,
                floor_sec=self._config.backoff_max_sec,
                detail=redact(exc.message),
            )
            await session.commit()
            raise
        finally:
            # The Gemini client memoises an ``httpx.AsyncClient`` inside the
            # SDK. A stage that returns without closing it leaks a connection
            # pool per scored call — nothing for one call, a worker out of file
            # descriptors after a week.
            await asr.aclose()

        text = (transcript.text or "").strip()
        if not text:
            raise TranscriptEmpty(
                "the provider returned an empty transcript: no speech was found "
                "in the recording, or the file is damaged",
                stage=Stage.TRANSCRIBE,
            )

        elapsed_ms = int((perf_counter() - started) * 1000)
        row = await save_transcript(
            session,
            call_id=call.id,
            transcript=transcript,
            text=text,
            language=language,
            audio_bytes=source.bytes,
            # From ``call_audio``, not from the provider's own guess: it is the
            # unit ASR is billed in, and it has to agree with what the gap
            # report and the player already show.
            audio_duration_ms=source.duration_ms,
            asr_ms=elapsed_ms,
        )

        log.info(
            "analysis_transcribed",
            call_id=str(call.id),
            provider=getattr(asr, "provider_key", "?"),
            model=getattr(asr, "model", "?"),
            chars=len(text),
            words=row.word_count,
            audio_kb=round(source.bytes / 1024, 1),
            elapsed_ms=elapsed_ms,
        )

        return (
            StageOutcome(
                stage=Stage.TRANSCRIBE,
                result=StageResult.DONE,
                detail=f"{len(text)} chars",
                provider_calls=calls_made,
                elapsed_ms=elapsed_ms,
                audio_bytes=source.bytes,
            ),
            row,
        )
