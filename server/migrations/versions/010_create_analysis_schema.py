"""Create the call-analysis schema (docs/SPEC-ANALYTICS.md §2).

Five native enum types, four tables and the twenty-six ``app_settings`` rows of
§4.6. **Additive only: no existing table is altered, no data is rewritten and
no lock is taken on ``calls``.** That is the point of the whole design — the
transcript and the pipeline stage are rows of their own rather than columns on
``calls``, so deploying this revision to a running system creates four empty
tables and changes nothing else.

``analysis.enabled`` is seeded **false**. Until an admin turns it on, both
worker jobs return 0 immediately and not one byte of audio leaves the host.

The vendor API key is deliberately NOT one of these rows: ``app_settings`` is
served by ``GET /api/v1/settings`` behind ``settings:read``, which a manager
holds, so a key in this table is a key every manager can read. It lives in
``core/config.py`` beside the MoiZvonki credentials (§4.2).

``description_uz`` is left NULL, as in revision 001 and for the same reason:
Uzbek text in a ``.py`` file is legal only in ``core/messages_uz.py``
(CONVENTIONS.md §14), so the settings screen's descriptions are the panel's to
supply.

Revision ID: 010
Revises: 009
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The enum types this revision creates, with their values in declaration
#: order. Written out rather than imported from ``core.enums`` because a
#: migration must keep its meaning after the application's enums have moved on;
#: ``test_migration_enum_table_matches_core_enums`` merges the ``PG_ENUMS``
#: block of every revision and compares the result with ``PG_ENUM_TYPES``.
PG_ENUMS: dict[str, tuple[str, ...]] = {
    "analysis_stage": ("queued", "transcribing", "scoring", "completed", "skipped", "failed",),
    "analysis_failure": (
        "no_audio", "audio_expired", "call_too_short", "call_type_unknown",
        "call_type_internal", "provider_rate_limit", "provider_cooldown",
        "provider_unavailable", "provider_network", "interrupted", "timeout",
        "transcript_empty", "score_invalid", "ai_not_configured", "provider_auth",
        "provider_model", "sdk_missing", "audio_too_large", "internal",
    ),
    "ai_role": ("asr", "llm",),
    "call_sentiment": ("positive", "neutral", "negative",),
    "transcript_quality": ("high", "medium", "low",),
}


#: §4.6, every key with its documented default. ``analysis.enabled`` is false
#: and both price keys are 0 — 0 means "not priced", never "free", and the
#: money cap therefore cannot trip until an admin enters a real vendor price.
#: The call-count cap is the one that protects the account on day one.
SETTINGS_SEED: tuple[tuple[str, object, str], ...] = (
    ("analysis.enabled", False, "bool"),
    # Both roles run on Gemini in phase 1: it is the only ASR tested on real
    # Uzbek calls that works, and one vendor means one SDK, one key and one
    # bill to attribute the first measured cost to. Claude arrives in phase 2
    # as a settings change, not a rewrite.
    ("analysis.asr_provider", "gemini", "string"),
    ("analysis.asr_model", "gemini-3.1-flash-lite", "string"),
    # Empty is legal and means "provider, you detect it".
    ("analysis.asr_language", "uz", "string"),
    ("analysis.llm_provider", "gemini", "string"),
    ("analysis.llm_model", "gemini-3.1-flash-lite", "string"),
    ("analysis.min_duration_sec", 30, "int"),
    ("analysis.transcribe_internal", False, "bool"),
    # Seven days, not two: a handset that spent a weekend out of coverage has
    # upload.session_ttl_days to deliver its recordings.
    ("analysis.lookback_hours", 168, "int"),
    ("analysis.max_calls_per_run", 200, "int"),
    ("analysis.concurrency", 2, "int"),
    ("analysis.asr_rpm", 60, "int"),
    ("analysis.llm_rpm", 120, "int"),
    ("analysis.max_retries", 4, "int"),
    ("analysis.backoff_base_sec", 2, "int"),
    ("analysis.backoff_max_sec", 60, "int"),
    ("analysis.max_wait_sec", 60, "int"),
    ("analysis.quota_cooldown_sec", 1800, "int"),
    ("analysis.invalid_retries", 2, "int"),
    ("analysis.call_timeout_sec", 900, "int"),
    ("analysis.retry_transient_days", 7, "int"),
    ("analysis.monthly_cost_cap_micro_usd", 50000000, "int"),
    ("analysis.monthly_max_calls", 3000, "int"),
    ("analysis.price_asr_micro_usd_per_minute", 0, "int"),
    ("analysis.price_llm_micro_usd_per_1k_input_tokens", 0, "int"),
    ("analysis.price_llm_micro_usd_per_1k_output_tokens", 0, "int"),
)

_settings_table = sa.table(
    "app_settings",
    sa.column("key", sa.String),
    sa.column("value", postgresql.JSONB),
    sa.column("value_type", sa.String),
)


def _enum(type_name: str) -> sa.Enum:
    """The type itself, for ``CREATE TYPE`` / ``DROP TYPE``."""
    return sa.Enum(*PG_ENUMS[type_name], name=type_name)


def _column_enum(type_name: str) -> postgresql.ENUM:
    """A reference to a type ``upgrade`` has already created."""
    return postgresql.ENUM(*PG_ENUMS[type_name], name=type_name, create_type=False)


def upgrade() -> None:
    for type_name in PG_ENUMS:
        _enum(type_name).create(op.get_bind(), checkfirst=False)

    op.create_table(
        "call_transcripts",
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("audio_bytes", sa.BigInteger(), nullable=False),
        sa.Column("audio_duration_ms", sa.Integer(), nullable=True),
        sa.Column("asr_ms", sa.Integer(), nullable=False),
        sa.Column("transcribed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], name=op.f("fk_call_transcripts_call_id_calls"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_transcripts")),
        sa.UniqueConstraint("call_id", name=op.f("uq_call_transcripts_call_id")),
    )
    # No full-text index: transcript search is phase 2, and an unused GIN index
    # on a growing TEXT column is write cost for nothing.
    op.create_index("ix_call_transcripts_time", "call_transcripts", [sa.text("transcribed_at DESC")], unique=False)

    op.create_table(
        "call_scores",
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("overall_score", sa.SmallInteger(), nullable=False),
        sa.Column("blocks", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("block_details", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("red_flags", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("outcome_signal", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sentiment", _column_enum("call_sentiment"), nullable=True),
        sa.Column("transcript_quality", _column_enum("transcript_quality"), nullable=False),
        sa.Column("coaching_note", sa.Text(), nullable=True),
        sa.Column("confidence_pct", sa.SmallInteger(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("review_reasons", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("rubric_version", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("llm_calls", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_micro_usd", sa.BigInteger(), nullable=True),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("confidence_pct BETWEEN 0 AND 100", name=op.f("ck_call_scores_confidence_pct_range")),
        sa.CheckConstraint("overall_score BETWEEN 0 AND 100", name=op.f("ck_call_scores_overall_score_range")),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], name=op.f("fk_call_scores_call_id_calls"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_scores")),
        sa.UniqueConstraint("call_id", name=op.f("uq_call_scores_call_id")),
    )
    op.create_index("ix_call_scores_overall", "call_scores", ["overall_score"], unique=False)
    # Partial: the review queue reads the few rows a human still has to look at.
    op.create_index("ix_call_scores_review", "call_scores", [sa.text("scored_at DESC")], unique=False, postgresql_where=sa.text("needs_review"))
    op.create_index("ix_call_scores_time", "call_scores", [sa.text("scored_at DESC")], unique=False)

    op.create_table(
        "call_analysis_state",
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("stage", _column_enum("analysis_stage"), server_default="queued", nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("asr_calls", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("llm_calls", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transcribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", _column_enum("analysis_failure"), nullable=True),
        sa.Column("failure_stage", sa.String(length=16), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("cost_micro_usd", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        # A stopped call always carries a reason, and a running one never does
        # — the same idiom as calls.audio_reason_present.
        sa.CheckConstraint("(stage IN ('failed', 'skipped')) = (failure_code IS NOT NULL)", name=op.f("ck_call_analysis_state_stopped_has_reason")),
        sa.CheckConstraint("failure_stage IS NULL OR failure_stage IN ('transcribe', 'score')", name=op.f("ck_call_analysis_state_failure_stage_known")),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], name=op.f("fk_call_analysis_state_call_id_calls"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_analysis_state")),
        sa.UniqueConstraint("call_id", name=op.f("uq_call_analysis_state_call_id")),
    )
    # The claim query's index: WHERE stage = 'queued' ORDER BY queued_at.
    op.create_index("ix_analysis_state_claim", "call_analysis_state", ["stage", "queued_at"], unique=False)
    op.create_index("ix_analysis_state_failure", "call_analysis_state", ["failure_code"], unique=False, postgresql_where=sa.text("stage = 'failed'"))

    op.create_table(
        "ai_provider_cooldowns",
        # The role is the primary key: at most two rows, ever, and an exhausted
        # ASR quota must not stop scoring transcripts that already exist.
        sa.Column("role", _column_enum("ai_role"), nullable=False),
        sa.Column("until_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason_code", _column_enum("analysis_failure"), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("role", name=op.f("pk_ai_provider_cooldowns")),
    )

    op.bulk_insert(
        _settings_table,
        [
            {"key": key, "value": value, "value_type": value_type}
            for key, value, value_type in SETTINGS_SEED
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.delete(_settings_table).where(
            _settings_table.c.key.in_([key for key, _, _ in SETTINGS_SEED])
        )
    )
    # Indexes and constraints go with their tables; nothing here is shared with
    # a table this revision did not create.
    op.drop_table("ai_provider_cooldowns")
    op.drop_table("call_analysis_state")
    op.drop_table("call_scores")
    op.drop_table("call_transcripts")
    for type_name in PG_ENUMS:
        _enum(type_name).drop(op.get_bind(), checkfirst=False)
