"""Analysis ORM models (SPEC-ANALYTICS §2.2).

Four tables, and **not one column on an existing one**. BonviZvonki writes the
transcript onto ``calls.transcript`` and the pipeline stage onto
``calls.status``; here both are rows of their own, so deploying this feature
cannot lock, rewrite or widen the busiest table in the product. The state row
*is* the status.

Analysis output is **derived data**: it is recomputed, not archived. None of
these tables has a soft delete, and ``ON DELETE CASCADE`` on ``call_id`` is the
correct declaration even though it is theoretical — ``calls`` answers 405 to
``DELETE`` for every role. Retention is the other way round: when the audio
expires at twelve months the transcript is what remains, and it is a hundredth
of the size, so ``audio_retention`` does not touch these rows (§2.3).

Money is integer **micro-USD** (1 USD = 1,000,000). No float, no ``Decimal``,
and ``NULL``/``0`` in a cost column means *not priced* — never "free" (§11.1).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UUIDMixin
from src.core.enums import (
    AiRole,
    AnalysisFailure,
    AnalysisStage,
    CallSentiment,
    TranscriptQuality,
    pg_enum,
)


class CallTranscriptModel(Base, UUIDMixin, TimestampMixin):
    """One row per transcribed call."""

    __tablename__ = "call_transcripts"

    call_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        doc="One transcript per call. The UNIQUE is what makes a re-run idempotent.",
    )
    text: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        doc=(
            "Verbatim, in the '[MM:SS] SPEAKER_0: ...' form the prompt demands. The "
            "timestamps are not decoration: phase 2's click-a-line-to-seek and the "
            "red-flag timeline both read them."
        ),
    )
    language: Mapped[str | None] = mapped_column(
        sa.String(8),
        nullable=True,
        doc=(
            "What was asked of the provider (analysis.asr_language), or NULL when the "
            "provider was left to detect it."
        ),
    )
    provider: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, doc="Registry key of the vendor that produced it."
    )
    model: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        doc="Model name as sent. Stored per row: a settings change must not re-label old work.",
    )
    char_count: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        doc="Denormalised so a list can show size without loading the text.",
    )
    word_count: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        doc=(
            "rules.count_words() — '[MM:SS]' and 'SPEAKER_n:' stripped first. Stored "
            "because the review rule and the panel must agree on one number."
        ),
    )
    audio_bytes: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        doc="Bytes handed to the provider. Half of the cost measurement (§11.1).",
    )
    audio_duration_ms: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc="call_audio.duration_ms at transcription time — the ASR billing unit.",
    )
    asr_ms: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, doc="Wall clock of the provider call."
    )
    transcribed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, doc="When the provider answered."
    )

    __table_args__ = (
        # No full-text index in phase 1: transcript search is phase 2, and an
        # unused GIN index on a growing TEXT column is write cost for nothing.
        sa.Index("ix_call_transcripts_time", sa.text("transcribed_at DESC")),
    )


class CallScoreModel(Base, UUIDMixin, TimestampMixin):
    """One row per scored call — the rubric's verdict and the evidence for it."""

    __tablename__ = "call_scores"

    call_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        doc="One score per call, which is what makes re-running idempotent.",
    )
    overall_score: Mapped[int] = mapped_column(
        sa.SmallInteger, nullable=False, doc="0-100, recomputed by the validator."
    )
    blocks: Mapped[dict[str, Any]] = mapped_column(
        postgresql.JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
        doc=(
            "FLAT {block_key: int}. Nothing nested and no _meta: a nested object 500s "
            "the analytics cut and blanks the React page."
        ),
    )
    block_details: Mapped[dict[str, Any]] = mapped_column(
        postgresql.JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
        doc=(
            "{blocks: {...evidence per criterion...}, meta: {...}} — how the number was "
            "reached, so 'why 78?' is answerable without paying to re-run."
        ),
    )
    red_flags: Mapped[list[Any]] = mapped_column(
        postgresql.JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
        doc="[{type, severity, timestamp, quote}]. Empty list = none found.",
    )
    outcome_signal: Mapped[dict[str, Any] | None] = mapped_column(
        postgresql.JSONB,
        nullable=True,
        doc="{type, products, confidence} — what the conversation ended in, when it said.",
    )
    sentiment: Mapped[CallSentiment | None] = mapped_column(
        pg_enum(CallSentiment, "call_sentiment"),
        nullable=True,
        doc="The model's reading of the conversation; NULL when it offered none.",
    )
    transcript_quality: Mapped[TranscriptQuality] = mapped_column(
        pg_enum(TranscriptQuality, "transcript_quality"),
        nullable=False,
        doc="The model's assessment of its input. The review rule reads it.",
    )
    coaching_note: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, doc="One paragraph the manager can hand to the employee."
    )
    confidence_pct: Mapped[int] = mapped_column(
        sa.SmallInteger,
        nullable=False,
        doc=(
            "0-100. Integer, not float (§10): it is compared against a threshold in "
            "Python, in SQL and in TypeScript, and float rounds differently in each."
        ),
    )
    needs_review: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("false"),
        doc="Set by rules.decide(); the review queue is this column.",
    )
    review_reasons: Mapped[list[Any]] = mapped_column(
        postgresql.JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
        doc=(
            "[{code, params}] — the panel renders the sentence from uz.json, so the "
            "reason is not a formatted string in a column. Empty list = no review."
        ),
    )
    rubric_version: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        doc=(
            "'v1' in phase 1. Stored per score so a rubric change never silently "
            "re-bases yesterday's numbers."
        ),
    )
    provider: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, doc="Registry key of the vendor that scored it."
    )
    model: Mapped[str] = mapped_column(sa.String(64), nullable=False, doc="Model name as sent.")
    llm_calls: Mapped[int] = mapped_column(
        sa.SmallInteger,
        nullable=False,
        server_default=sa.text("1"),
        doc="Includes the invalid-response retries (analysis.invalid_retries).",
    )
    prompt_tokens: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc="As reported by the provider; NULL when it reports nothing. The LLM billing unit.",
    )
    completion_tokens: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True, doc="The other half of the LLM billing unit."
    )
    cost_micro_usd: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        nullable=True,
        doc=(
            "Measured units x the admin-entered price. NULL while the price is unset — "
            "null means 'not priced', never 'free'."
        ),
    )
    scored_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, doc="When the model answered."
    )

    __table_args__ = (
        sa.CheckConstraint(
            "overall_score BETWEEN 0 AND 100",
            name="overall_score_range",
        ),
        # The same rule on the other number the panel draws as a bar. Their
        # BLOCK_MAX was once written twice, diverged 25 vs 15, and produced a
        # 167 % bar in front of a manager; a range this narrow belongs in the
        # database rather than in whichever writer runs next.
        sa.CheckConstraint(
            "confidence_pct BETWEEN 0 AND 100",
            name="confidence_pct_range",
        ),
        sa.Index("ix_call_scores_overall", "overall_score"),
        sa.Index(
            "ix_call_scores_review",
            sa.text("scored_at DESC"),
            postgresql_where=sa.text("needs_review"),
        ),
        sa.Index("ix_call_scores_time", sa.text("scored_at DESC")),
    )


class CallAnalysisStateModel(Base, UUIDMixin, TimestampMixin):
    """One row per call the pipeline has touched — queued, running or finished.

    Singular mass noun, following the existing ``device_health``: the table is
    the pipeline's state, not a list of states.

    Separate from ``calls`` on purpose. Everything here is the analysis
    subsystem's own bookkeeping, it changes several times per call, and putting
    it on ``calls`` would mean an UPDATE on the product's central table for
    every stage boundary of a feature that is off by default.
    """

    __tablename__ = "call_analysis_state"

    call_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        doc="One state row per call; dispatch inserts with ON CONFLICT DO NOTHING.",
    )
    stage: Mapped[AnalysisStage] = mapped_column(
        pg_enum(AnalysisStage, "analysis_stage"),
        nullable=False,
        server_default=AnalysisStage.QUEUED.value,
        doc="Where the call stands. The claim query reads it with (stage, queued_at).",
    )
    attempts: Mapped[int] = mapped_column(
        sa.SmallInteger,
        nullable=False,
        server_default=sa.text("0"),
        doc="How many times a run has started on this call, successful or not.",
    )
    asr_calls: Mapped[int] = mapped_column(
        sa.SmallInteger,
        nullable=False,
        server_default=sa.text("0"),
        doc=(
            "Requests that actually reached a provider, i.e. that cost money. A re-run "
            "of a completed call must not increase it, and a test asserts that."
        ),
    )
    llm_calls: Mapped[int] = mapped_column(
        sa.SmallInteger,
        nullable=False,
        server_default=sa.text("0"),
        doc="The same count for the scoring half.",
    )
    queued_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        doc="Claim order. Oldest first, so a backlog drains in the order it arrived.",
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc=(
            "When a run last touched the row. analysis_stale_reset reads it; NULL is "
            "left alone, because that row never ran."
        ),
    )
    transcribed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Stage 1 finished."
    )
    scored_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="Stage 2 finished."
    )
    failure_code: Mapped[AnalysisFailure | None] = mapped_column(
        pg_enum(AnalysisFailure, "analysis_failure"),
        nullable=True,
        doc="Why the call stopped. NOT NULL exactly when the stage is failed or skipped.",
    )
    failure_stage: Mapped[str | None] = mapped_column(
        sa.String(16),
        nullable=True,
        doc="transcribe | score — which half spent the money before it stopped.",
    )
    failure_detail: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        doc=(
            "The provider's own message, passed through errors.redact(). Technical "
            "detail in whatever language the vendor used; the Uzbek headline the panel "
            "shows comes from failure_code."
        ),
    )
    duration_ms: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True, doc="End-to-end wall clock for the run."
    )
    cost_micro_usd: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        server_default=sa.text("0"),
        doc=(
            "The run's measured cost. The monthly cap sums this over a Tashkent "
            "calendar month; 0 also means 'not priced' (§11.1)."
        ),
    )

    __table_args__ = (
        # The house idiom, copied from calls.audio_reason_present: a stopped
        # call always carries a reason, and a running one never does. A
        # database fact rather than a habit — the panel renders the reason and
        # the retry job filters on it.
        sa.CheckConstraint(
            "(stage IN ('failed', 'skipped')) = (failure_code IS NOT NULL)",
            name="stopped_has_reason",
        ),
        sa.CheckConstraint(
            "failure_stage IS NULL OR failure_stage IN ('transcribe', 'score')",
            name="failure_stage_known",
        ),
        sa.Index("ix_analysis_state_claim", "stage", "queued_at"),
        sa.Index(
            "ix_analysis_state_failure",
            "failure_code",
            postgresql_where=sa.text("stage = 'failed'"),
        ),
    )


class AiProviderCooldownModel(Base, TimestampMixin):
    """A role sitting out after a quota or an outage. At most two rows, ever.

    No ``UUIDMixin``: the role *is* the identity, exactly as ``app_settings``
    uses its key. Per role and not per provider, because one account can serve
    both roles against different models and different quotas.

    A table rather than BonviZvonki's Redis key with a TTL: this survives a
    restart, and the status endpoint can read it — which is the thing an admin
    most needs when the queue stops.
    """

    __tablename__ = "ai_provider_cooldowns"

    role: Mapped[AiRole] = mapped_column(
        pg_enum(AiRole, "ai_role"),
        primary_key=True,
        doc="asr | llm. One row per role; starting a cooldown upserts it.",
    )
    until_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        doc=(
            "Past this, the road is open. A LONGER existing value is never shortened: "
            "two workers hitting 429 seconds apart would otherwise let the second "
            "one's short window cancel the first one's daily quota."
        ),
    )
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        doc="When it began, so the panel can say how long this has been going on.",
    )
    reason_code: Mapped[AnalysisFailure] = mapped_column(
        pg_enum(AnalysisFailure, "analysis_failure"),
        nullable=False,
        doc="The failure that opened it — a daily quota and a 503 read very differently.",
    )
    detail: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, doc="The vendor's message, redacted."
    )
