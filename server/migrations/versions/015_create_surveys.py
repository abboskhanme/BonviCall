"""Create the Telegram group directory and the customer satisfaction survey.

═══ What this does, and what it deliberately does not ═════════════════════
Three new tables and seven new ``app_settings`` rows. **No ``ALTER TABLE`` on
anything that exists, no enum touched, no data rewritten.** Deploying this to a
running system adds tables nothing reads yet and a feature flag that is off, so
the day it ships it changes no behaviour at all.

``survey.enabled`` is seeded **false** for the same reason ``analysis.enabled``
and ``enrolment.callback_enabled`` are: this feature writes messages into
Telegram chats that real customers are sitting in. Nothing may start doing that
because a migration ran. Turning it on is one row, and that row is also the
rollback.

``survey.auto_send`` is seeded false separately, and the second switch is not
redundant: the first asks "may surveys exist at all", the second asks "may they
go out with nobody watching". They are different decisions and one does not
imply the other.

═══ No PostgreSQL enum types ══════════════════════════════════════════════
``bot_status``, ``bound_by``, ``status``, ``channel`` and ``resolution`` are
``VARCHAR`` with a CHECK naming the legal values, not native enums — so this
revision declares no ``PG_ENUMS`` block and
``test_migration_enum_table_matches_core_enums`` is unaffected.

CONVENTIONS.md §10 requires a native enum for vocabulary the three PLATFORMS
share (``capture_route``, ``audio_missing_reason``, ``enrolment_stage``,
``alert_severity``); none of these leaves the panel. The precedent for the
shape is ``call_analysis_state.failure_stage``, a ``String(16)`` with exactly
this constraint, added by revision 010.

═══ No `clients` foreign key ══════════════════════════════════════════════
BonviZvonki's ``surveys`` table carries ``client_id UUID REFERENCES
clients(id)`` because it also serves an older per-customer flow. In the group
flow — the only one ported — that column is NULL on every row by construction.
It is dropped rather than left as a dangling reference into a table this
revision does not own.

Revision ID: 015
Revises: 014
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The settings this revision seeds, with their documented defaults.
#:
#: Written out LITERALLY rather than imported from ``core/settings_keys.py``:
#: a migration must keep meaning what it meant when it ran, and a reviewer must
#: be able to read the seeded values in the diff. Revision 012 imports its seed
#: for a reason that does not apply here (220 lines of Uzbek rubric in a file
#: where Uzbek is not allowed); seven short rows are not that case.
#:
#: ``description_uz`` is Uzbek because an admin reads it on the settings page —
#: the same exception every other settings seed takes (§14).
SETTINGS: tuple[tuple[str, object, str, str], ...] = (
    (
        "survey.enabled",
        False,
        "bool",
        "So'rovnoma yuborish yoqilganmi? BOSH kalit. O'chirilgan bo'lsa "
        "birorta so'rovnoma yaratilmaydi — «Barchasiga so'rovnoma» tugmasi "
        "ham, bitta guruhga yuborish ham ishlamaydi. Yig'ilgan baholarni "
        "ko'rish esa ishlayveradi.",
    ),
    (
        "survey.auto_send",
        False,
        "bool",
        "So'rovnomalar odam aralashuvisiz, jadval bo'yicha yuborilsinmi? "
        "Bu alohida qaror: «So'rovnoma yoqilgan» degani hali «o'zi yuborsin» "
        "degani emas. O'chirilgan bo'lsa so'rovnoma FAQAT qo'lda yuboriladi.",
    ),
    (
        "survey.period_days",
        14,
        "int",
        "Kadans: bitta guruh shuncha kunda bir martadan ko'p so'ralmaydi.",
    ),
    (
        "survey.suppression_days",
        10,
        "int",
        "Takror so'ramaslik oynasi. Oxirgi so'rovnomadan shuncha kun "
        "o'tmaguncha guruhga yangisi yuborilmaydi. «Barchasiga so'rovnoma» "
        "tugmasi aynan shu qoidani chetlab o'tadi.",
    ),
    (
        "survey.min_responses",
        5,
        "int",
        "O'rtacha bahoni ko'rsatish uchun kerakli minimal javob soni. "
        "Shundan kam bo'lsa raqam o'rniga «yig'ilmoqda» yoziladi — bitta "
        "mijozning kayfiyati xodimning bahosini belgilab qo'ymasligi uchun.",
    ),
    (
        "survey.message_ttl_hours",
        24,
        "int",
        "Guruhdagi so'rovnoma xabari necha soatdan keyin o'chirilsin? "
        "0 — hech qachon. Telegram botga o'z xabarini 48 soatdan keyin "
        "o'chirishga ruxsat bermaydi, shuning uchun katta qiymat 47 ga "
        "tushiriladi.",
    ),
    (
        "access.sales_client_rating",
        "score_only",
        "string",
        "Savdo xodimi o'z client baholarini ko'radimi? "
        "hidden — yo'q, faqat rahbariyat ko'radi; "
        "score_only — o'rtacha ball va yulduzlar taqsimoti; "
        "full — shu bilan bir xil. Xodimga alohida baholar HECH QACHON "
        "ko'rsatilmaydi: bitta guruh — bitta mijoz, ya'ni bitta qator kim "
        "baho qo'yganini oshkor qilardi.",
    ),
)

_settings_table = sa.table(
    "app_settings",
    sa.column("key", sa.String),
    sa.column("value", postgresql.JSONB),
    sa.column("value_type", sa.String),
    sa.column("description_uz", sa.Text),
)


def upgrade() -> None:
    op.create_table(
        "telegram_groups",
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("member_count", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_survey_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bot_status", sa.String(length=16), server_default="member", nullable=False),
        sa.Column("bound_by", sa.String(length=16), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "bot_status IN ('administrator', 'kicked', 'left', 'member')",
            name=op.f("ck_telegram_groups_bot_status_known"),
        ),
        sa.CheckConstraint(
            "bound_by IS NULL OR bound_by IN ('auto', 'manual')",
            name=op.f("ck_telegram_groups_bound_by_known"),
        ),
        # "Bound" is one fact held in two columns, so the database holds them
        # together. BonviZvonki has rows with an agent and no `bound_at`,
        # because one write path forgot the second column.
        sa.CheckConstraint(
            "(agent_id IS NULL) = (bound_at IS NULL)",
            name=op.f("ck_telegram_groups_bound_has_a_time"),
        ),
        # SET NULL, not CASCADE: removing an employee must not remove the
        # customers' group along with them.
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_telegram_groups_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_groups")),
        sa.UniqueConstraint("chat_id", name=op.f("uq_telegram_groups_chat_id")),
    )
    op.create_index("ix_telegram_groups_agent", "telegram_groups", ["agent_id", "is_active"])
    # The bucket the page opens with. Partial, so it stays small on a table
    # where almost every row is bound.
    op.create_index(
        "ix_telegram_groups_unbound",
        "telegram_groups",
        ["created_at"],
        postgresql_where=sa.text("agent_id IS NULL"),
    )

    op.create_table(
        "surveys",
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("chat_message_id", sa.BigInteger(), nullable=True),
        sa.Column("response_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("message_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("channel", sa.String(length=16), server_default="telegram_group", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "channel IN ('sms', 'telegram_group')",
            name=op.f("ck_surveys_survey_channel_known"),
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'expired', 'failed', 'opened', 'pending', 'sent')",
            name=op.f("ck_surveys_survey_status_known"),
        ),
        # An empty or backwards period would make every "answers in this
        # period" figure wrong without anything raising.
        sa.CheckConstraint("period_end > period_start", name=op.f("ck_surveys_period_is_forward")),
        sa.CheckConstraint("response_count >= 0", name=op.f("ck_surveys_response_count_not_negative")),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["telegram_groups.id"],
            name=op.f("fk_surveys_group_id_telegram_groups"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_surveys_agent_id_agents"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_surveys")),
        sa.UniqueConstraint("token", name=op.f("uq_surveys_token")),
    )
    # The dispatch queue. Partial, because a survey that is no longer pending
    # is never asked for by it.
    op.create_index(
        "ix_surveys_pending",
        "surveys",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    # The cleanup queue: posted, not yet removed.
    op.create_index(
        "ix_surveys_cleanup",
        "surveys",
        ["sent_at"],
        postgresql_where=sa.text("message_deleted_at IS NULL AND chat_message_id IS NOT NULL"),
    )
    op.create_index("ix_surveys_group", "surveys", ["group_id", sa.text("created_at DESC")])
    op.create_index("ix_surveys_agent", "surveys", ["agent_id", sa.text("created_at DESC")])
    op.create_index("ix_surveys_expiry", "surveys", ["expires_at"])

    op.create_table(
        "survey_responses",
        sa.Column("survey_id", sa.UUID(), nullable=False),
        sa.Column("respondent_hash", sa.String(length=64), nullable=True),
        sa.Column("csat", sa.SmallInteger(), nullable=False),
        sa.Column("resolution", sa.String(length=16), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "red_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_time_sec", sa.Integer(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("csat BETWEEN 1 AND 5", name=op.f("ck_survey_responses_csat_range")),
        sa.CheckConstraint(
            "resolution IS NULL OR resolution IN ('no', 'partial', 'yes')",
            name=op.f("ck_survey_responses_resolution_known"),
        ),
        # `red_flags` is an ARRAY of keys. Stored as a JSON object or a JSON
        # string it would still insert, and `jsonb_array_elements_text` would
        # then fail at read time — revision 012 learned the same lesson on the
        # rubric's `blocks`.
        sa.CheckConstraint(
            "jsonb_typeof(red_flags) = 'array'",
            name=op.f("ck_survey_responses_red_flags_is_an_array"),
        ),
        sa.CheckConstraint(
            "response_time_sec IS NULL OR response_time_sec >= 0",
            name=op.f("ck_survey_responses_response_time_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["survey_id"],
            ["surveys.id"],
            name=op.f("fk_survey_responses_survey_id_surveys"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_survey_responses")),
        # ⚠️ NOT a unique on `survey_id` alone. BonviZvonki had one — one
        # survey, one answer — and the group flow broke it: thirty customers
        # answer the same posted message. NULL hashes are distinct in
        # PostgreSQL, so answers carrying none do not collide with each other.
        sa.UniqueConstraint(
            "survey_id", "respondent_hash", name=op.f("uq_response_per_respondent")
        ),
    )
    op.create_index("ix_survey_responses_survey", "survey_responses", ["survey_id"])
    op.create_index("ix_survey_responses_time", "survey_responses", [sa.text("responded_at DESC")])
    # The feedback list's keyset sort, carrying `id` so the seek does not fall
    # back to a sort. BonviZvonki has no index on `responded_at` at all, and
    # five separate queries filter and order by it.
    op.create_index(
        "ix_survey_responses_keyset",
        "survey_responses",
        [sa.text("responded_at DESC"), sa.text("id DESC")],
    )

    op.bulk_insert(
        _settings_table,
        [
            {
                "key": key,
                "value": value,
                "value_type": value_type,
                "description_uz": description,
            }
            for key, value, value_type, description in SETTINGS
        ],
    )


def downgrade() -> None:
    """Drop the three tables and the seven settings rows.

    The tables go in dependency order. Every index on them goes with them, so
    they are not dropped separately.
    """
    op.execute(
        sa.delete(_settings_table).where(
            _settings_table.c.key.in_([key for key, _, _, _ in SETTINGS])
        )
    )
    op.drop_table("survey_responses")
    op.drop_table("surveys")
    op.drop_table("telegram_groups")
