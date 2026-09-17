"""Surveys ORM models — the Telegram group directory and the CSAT it carries.

Ported from BonviZvonki ``modules/groups/infrastructure/models.py`` and
``modules/surveys/infrastructure/models.py``.

═══ Why ONE module and not two ═════════════════════════════════════════════
BonviZvonki ships ``groups`` and ``surveys`` as two 4-layer modules. Here they
are one, and the reason is checkable rather than aesthetic:

``surveys.group_id`` is a foreign key into ``telegram_groups``, so a ``surveys``
module may read the group model (CONVENTIONS.md §2, "FK targets"). The reverse
is not true — ``telegram_groups`` has no foreign key into ``surveys`` — and yet
the group row's whole panel presentation is survey data: ``last_survey_at``,
``survey_count``, ``response_count``, and the "can this group be sent a survey"
rule. Split, ``groups/service.py`` would import ``SurveyModel`` with no foreign
key to justify it and ``tests/test_layering.py::
test_a_module_only_imports_models_it_has_a_foreign_key_into`` would fail — or
the two services would import each other, which is a circular import wearing a
layering diagram.

A group exists in order to be surveyed. One module, three tables, extra files
beside the canonical three for the reason ``analysis`` and ``audio`` already
carry them (§3).

═══ What was DROPPED from the source, and why ══════════════════════════════
``surveys.client_id UUID NULL REFERENCES clients(id)``. BonviZvonki's survey
table serves two flows: an older one keyed on a customer record, and the group
flow. In the group flow ``client_id`` is **always NULL** — the docstring there
says so: "we do not know who is sitting in the group and we do not need to".
This product has no ``clients`` table and this port creates none, so the column
and its foreign key are gone rather than left dangling. Nothing in the group
flow read it.

``survey_responses.comment_sentiment`` is also dropped: nothing in the source
writes it. It is a ``String(16)`` that is NULL on every row, waiting for a
sentiment classifier that was never built.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UUIDMixin
from src.modules.surveys.rules import (
    BIND_SOURCES,
    BOT_STATUSES,
    CSAT_MAX,
    CSAT_MIN,
    RESOLUTIONS,
    SURVEY_CHANNELS,
    SURVEY_STATUSES,
    SURVEY_TOKEN_MAX_LEN,
)


def _sql_values(values: frozenset[str]) -> str:
    """``{'a','b'}`` -> ``'a', 'b'`` for a CHECK constraint, sorted for stability.

    Sorted because the constraint text lands in the migration and in
    ``alembic check``'s comparison; an unordered set would render differently
    on two runs of the same code and report a schema drift that is not one.
    """
    return ", ".join(f"'{value}'" for value in sorted(values))


class TelegramGroupModel(Base, UUIDMixin, TimestampMixin):
    """One Telegram chat that customers sit in, bound to one salesperson.

    The bot registers the group itself when it is added to it; an admin then
    binds a salesperson to it in the panel. Until that binding exists the group
    receives nothing, which is the intended behaviour and not a fault — see
    ``rules.dispatch_block``.

    ⚠️ **Never infer what a group is for from ``member_count``.** BonviZvonki's
    predecessor had a ``member_count <= 2`` -> "junk group" rule and it was
    wrong: a group can hold several people and no customer at all (an internal
    group, an organisers' group), and the bot cannot see who is inside. The
    rule that replaced it is the one this port keeps: **a working group is one
    an admin bound an employee to.** Marking a group as junk is releasing its
    employee, and ``member_count`` stays what it is — decoration.
    """

    __tablename__ = "telegram_groups"

    chat_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        unique=True,
        doc=(
            "Telegram's own chat identifier, a negative number for a group. "
            "BIGINT and not INTEGER: supergroup ids do not fit in 32 bits, and "
            "the overflow is silent on the way in."
        ),
    )
    title: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
        doc="The chat title as Telegram last reported it. Decoration for the panel.",
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        doc=(
            "The salesperson answerable for this group. NULL means nobody is, "
            "and the group therefore receives no survey — the single silent "
            "failure this feature has, which is why the panel puts the "
            "unbound set at the TOP of the page rather than at the bottom. "
            "SET NULL and not CASCADE: deleting an employee must not delete "
            "the customers' group with them."
        ),
    )
    member_count: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc=(
            "Telegram's approximate member count. Information only — it "
            "classifies NOTHING (see the class docstring). NULL when the bot "
            "has not been able to ask."
        ),
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.true(),
        doc="False parks the group: it stays listed and stops being surveyed.",
    )
    bound_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc=(
            "When an employee was attached. NULL exactly when ``agent_id`` is "
            "NULL — a timestamp rather than a flag, so the panel answers "
            "'when?' as well as 'whether?' (§6)."
        ),
    )
    last_survey_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc=(
            "When a survey was last created for this group. The cadence and "
            "the suppression window are both measured from here, so it is "
            "written when the survey row is CREATED and not when the transport "
            "claims delivery: a transport that cannot deliver must not be able "
            "to re-open the window every minute."
        ),
    )
    bot_status: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        server_default="member",
        doc=(
            "member | administrator | left | kicked, from Telegram's "
            "``my_chat_member`` update. ``left``/``kicked`` is the only state "
            "in which the panel offers to delete the row."
        ),
    )
    bound_by: Mapped[str | None] = mapped_column(
        sa.String(16),
        nullable=True,
        doc=(
            "auto | manual — who made the binding. NULL when there is none. "
            "⚠️ Automatic binding NEVER touches a ``manual`` row. Without that "
            "rule the bot's next pass silently undoes what an admin just "
            "corrected, and the admin has no way to see that it happened."
        ),
    )

    __table_args__ = (
        # A String + CHECK rather than a PostgreSQL native enum. Three of these
        # would mean three entries in `core/enums.py::PG_ENUM_TYPES`, and
        # §10 requires native enums for wire vocabulary shared across the three
        # platforms (`capture_route`, `audio_missing_reason`, ...). These are
        # panel-only. The precedent is `call_analysis_state.failure_stage`,
        # which is `String(16)` with exactly this constraint shape.
        sa.CheckConstraint(
            f"bot_status IN ({_sql_values(BOT_STATUSES)})",
            name="bot_status_known",
        ),
        sa.CheckConstraint(
            f"bound_by IS NULL OR bound_by IN ({_sql_values(BIND_SOURCES)})",
            name="bound_by_known",
        ),
        # "Bound" is one fact, held in two columns, so the database holds them
        # together. BonviZvonki has rows with an agent and no `bound_at`,
        # because one write path forgot the second column; the panel then shows
        # a bound group whose binding has no date.
        sa.CheckConstraint(
            "(agent_id IS NULL) = (bound_at IS NULL)",
            name="bound_has_a_time",
        ),
        # The page's own query: one employee's groups, newest binding first.
        sa.Index("ix_telegram_groups_agent", "agent_id", "is_active"),
        # The unbound bucket, which the page opens with. Partial, because it is
        # the only value ever asked for and the index then stays small on a
        # table where almost every row IS bound.
        sa.Index(
            "ix_telegram_groups_unbound",
            "created_at",
            postgresql_where=sa.text("agent_id IS NULL"),
        ),
    )


class SurveyModel(Base, UUIDMixin, TimestampMixin):
    """One survey invitation: a group, an employee, and a period being rated.

    The row is created by the panel (one group, or the broadcast) and is then
    picked up by whatever is carrying messages to Telegram. In this deployment
    that is :class:`~src.modules.surveys.transport.LoggingSurveyTransport`,
    which delivers nothing and says so, so a row here sits at ``pending``.
    """

    __tablename__ = "surveys"

    group_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("telegram_groups.id", ondelete="CASCADE"),
        nullable=False,
        doc=(
            "The chat this invitation belongs in. NOT NULL here where "
            "BonviZvonki has it nullable: theirs also serves a per-customer "
            "flow keyed on ``client_id``, and this port has only the group "
            "flow (see the module docstring)."
        ),
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        doc=(
            "Who is being rated. Copied from the group at creation and never "
            "re-read: re-binding the group tomorrow must not silently move "
            "yesterday's ratings onto a different employee."
        ),
    )
    chat_message_id: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        nullable=True,
        doc=(
            "The message the bot posted, so it can edit its response counter "
            "and later delete exactly that message. NULL until something "
            "actually posts — which, with the logging transport, is never."
        ),
    )
    response_count: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
        doc=(
            "Denormalised count of ``survey_responses``. Kept so the posted "
            "message can show 'N answered' without counting rows on every "
            "edit; ``SurveyService`` is the only writer."
        ),
    )
    message_deleted_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc=(
            "'Done with this message.' Set when the survey message has been "
            "removed from the chat — and ALSO when removing it failed for "
            "good, e.g. past Telegram's 48-hour own-message delete limit. "
            "Both cases must stop the row being queued again, or the cleanup "
            "queue fills with messages that can never be deleted and retries "
            "them forever. Which of the two happened is in the log."
        ),
    )
    token: Mapped[str] = mapped_column(
        sa.String(SURVEY_TOKEN_MAX_LEN),
        nullable=False,
        unique=True,
        doc=(
            "The deep-link secret: ``t.me/<bot>?start=srv_<token>``. It is a "
            "real access key — whoever holds it can answer this survey — so it "
            "comes from ``secrets``, never ``random`` (``rules.new_token``)."
        ),
    )
    period_start: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        doc="Start of the window being rated. Half-open with ``period_end`` (§6).",
    )
    period_end: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        doc="EXCLUSIVE end of the rated window.",
    )
    channel: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        server_default="telegram_group",
        doc="telegram_group | sms. Only the first is implemented.",
    )
    status: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        server_default="pending",
        doc=(
            "pending -> sent -> opened -> completed, or expired / failed. "
            "``pending`` is where every row stays while the transport is the "
            "logging one, and that is the honest reading of 'not delivered'."
        ),
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc="When the transport confirmed the message was posted.",
    )
    opened_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="First time the link was followed."
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, doc="When the first answer arrived."
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        doc=(
            "After this the token stops being accepted. Held on the row and "
            "not computed from ``created_at`` at read time, so shortening the "
            "TTL setting cannot retroactively close surveys already in flight."
        ),
    )
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        doc="When a reminder went out. At most one, and none in this deployment.",
    )

    __table_args__ = (
        sa.CheckConstraint(
            f"status IN ({_sql_values(SURVEY_STATUSES)})", name="survey_status_known"
        ),
        sa.CheckConstraint(
            f"channel IN ({_sql_values(SURVEY_CHANNELS)})", name="survey_channel_known"
        ),
        # A half-open range that is empty or backwards is a bug in whoever
        # built it, and it would make every "responses in this period" figure
        # wrong without ever raising anything.
        sa.CheckConstraint("period_end > period_start", name="period_is_forward"),
        sa.CheckConstraint("response_count >= 0", name="response_count_not_negative"),
        # The dispatch queue's own read: the oldest pending row first.
        sa.Index(
            "ix_surveys_pending",
            "created_at",
            postgresql_where=sa.text("status = 'pending'"),
        ),
        # The cleanup queue: posted, not yet removed. Partial for the same
        # reason — a survey whose message is already gone is never asked for.
        sa.Index(
            "ix_surveys_cleanup",
            "sent_at",
            postgresql_where=sa.text(
                "message_deleted_at IS NULL AND chat_message_id IS NOT NULL"
            ),
        ),
        sa.Index("ix_surveys_group", "group_id", sa.text("created_at DESC")),
        sa.Index("ix_surveys_agent", "agent_id", sa.text("created_at DESC")),
        sa.Index("ix_surveys_expiry", "expires_at"),
    )


class SurveyResponseModel(Base, UUIDMixin, TimestampMixin):
    """One customer's answer. Anonymous, and anonymous by construction.

    ⚠️ **There is no unique index on ``survey_id`` alone**, and the absence is
    deliberate. BonviZvonki had one — one survey, one answer — and the group
    flow broke it: thirty customers answer the same posted message. The rule
    that replaced it is the composite unique below.
    """

    __tablename__ = "survey_responses"

    survey_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("surveys.id", ondelete="CASCADE"),
        nullable=False,
        doc="The invitation answered.",
    )
    respondent_hash: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        doc=(
            "``sha256(survey.token + ':' + telegram_user_id)``, computed by "
            "the BOT. The server never sees a Telegram identifier, so it "
            "cannot store one even by accident. Every survey has a different "
            "token, so one person's hashes across two surveys do not link: "
            "'what did this customer say last time' has no answer, and that is "
            "the design, not a gap in it. NULL is legal — an answer that "
            "arrived without one — and PostgreSQL treats NULLs as distinct in "
            "a unique index, so those rows do not collide with each other."
        ),
    )
    csat: Mapped[int] = mapped_column(
        sa.SmallInteger,
        nullable=False,
        doc="1..5 stars. The headline number, and the only mandatory answer.",
    )
    resolution: Mapped[str | None] = mapped_column(
        sa.String(16),
        nullable=True,
        doc=(
            "Question 2 — 'was your problem solved?': yes | partial | no. "
            "NULL when the customer skipped it, which is a real and common "
            "answer and must not be read as 'no'."
        ),
    )
    comment: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        doc=(
            "Free text. NULL means the customer wrote none — it never means "
            "'withheld by a setting'. Withholding happens on the way OUT, in "
            "``SurveyService``, so the stored row stays the truth."
        ),
    )
    red_flags: Mapped[list[str]] = mapped_column(
        postgresql.JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
        doc=(
            "Ticked misconduct keys from ``rules.RED_FLAGS``. Keys and not "
            "labels: an existing key is NEVER renamed, because the stored "
            "rows would lose their meaning; a new criterion is a new key. "
            "Empty list = none ticked."
        ),
    )
    responded_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        doc="When the customer answered. Ordering and the date filter use it.",
    )
    response_time_sec: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        doc=(
            "Seconds from the survey being posted to this answer. NULL when "
            "the survey was never posted, which is every row while the "
            "transport is the logging one."
        ),
    )

    __table_args__ = (
        # One person answers one survey once. NULL hashes are distinct in
        # PostgreSQL, so answers that carry no hash are unaffected.
        sa.UniqueConstraint(
            "survey_id", "respondent_hash", name="uq_response_per_respondent"
        ),
        sa.CheckConstraint(
            f"csat BETWEEN {CSAT_MIN} AND {CSAT_MAX}", name="csat_range"
        ),
        sa.CheckConstraint(
            f"resolution IS NULL OR resolution IN ({_sql_values(RESOLUTIONS)})",
            name="resolution_known",
        ),
        # `red_flags` is an ARRAY of keys. Stored as a JSON object or a JSON
        # string it would still insert, and `jsonb_array_elements_text` would
        # then fail at read time — the rubric table learned the same lesson
        # (migration 012's comment on `blocks`).
        sa.CheckConstraint(
            "jsonb_typeof(red_flags) = 'array'", name="red_flags_is_an_array"
        ),
        sa.CheckConstraint(
            "response_time_sec IS NULL OR response_time_sec >= 0",
            name="response_time_not_negative",
        ),
        sa.Index("ix_survey_responses_survey", "survey_id"),
        sa.Index("ix_survey_responses_time", sa.text("responded_at DESC")),
        # The feedback list's keyset sort is (responded_at DESC, id DESC) and
        # the index carries `id` so the seek does not fall back to a sort.
        sa.Index(
            "ix_survey_responses_keyset", sa.text("responded_at DESC"), sa.text("id DESC")
        ),
    )
