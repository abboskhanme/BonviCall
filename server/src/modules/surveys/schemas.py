"""Wire types for groups and surveys.

Field descriptions are English: they become the OpenAPI document and therefore
the panel's generated TypeScript (CONVENTIONS.md §14). BonviZvonki's are Uzbek.

Ported from BonviZvonki ``modules/groups/presentation/router.py`` and
``modules/surveys/presentation/router.py``.

Dropped against theirs, and why:

* ``GroupsTree.empty`` — a leftover bucket from the abandoned "classify a group
  by its member count" rule. The panel already ignores it, and its own api.ts
  says so: "an old contract field. The panel does not use it."
* ``TreeAgentNode.avatar_url`` — ``agents`` here has ``color`` and no avatar
  column, so the field would be ``null`` on every row for ever.
* ``FeedbackItem.agent_id`` is kept but ``client_id`` is not: there is no
  customer record in this product, and the rating is anonymous anyway.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from src.modules.surveys.rules import (
    BULK_GROUP_LIMIT,
    COMMENT_MAX_LEN,
    CSAT_MAX,
    CSAT_MIN,
    RESPONDENT_HASH_LEN,
)

# ═══ Groups ════════════════════════════════════════════════════════════════


class GroupResponse(BaseModel):
    """One Telegram group as the panel's list and detail render it."""

    id: uuid.UUID
    chat_id: int = Field(
        description="Telegram's own chat id. Negative for a group; 64-bit."
    )
    title: str
    agent_id: uuid.UUID | None = Field(
        description=(
            "The salesperson answerable for this chat. Null means nobody is, "
            "and this group therefore receives nothing."
        )
    )
    agent_name: str | None
    agent_color: str | None = Field(
        description="The agent's avatar colour. Decoration, never identity."
    )
    member_count: int | None = Field(
        description=(
            "Telegram's approximate count. Information only — it classifies "
            "NOTHING. A chat with four people in it may hold no customer at "
            "all, and the bot cannot see who is inside."
        )
    )
    is_active: bool
    bot_status: str = Field(description="member | administrator | left | kicked.")
    bound_by: str | None = Field(
        description=(
            "auto | manual. A `manual` row is one an admin holds: automatic "
            "binding never touches it again, and the panel shows a badge so "
            "the admin knows which rows they are holding."
        )
    )
    bound_at: datetime | None
    last_survey_at: datetime | None
    survey_count: int = Field(description="Surveys ever created for this group.")
    response_count: int = Field(description="Answers ever collected from it.")


class GroupPageResponse(BaseModel):
    """One keyset page of groups (§4.0).

    Keyset and not ``page``/``page_size`` as BonviZvonki has it: an offset page
    over a table somebody is actively re-binding skips and repeats rows, and
    this list is exactly the one an admin pages through while editing it.
    """

    items: list[GroupResponse]
    next_cursor: str | None = Field(
        description="Opaque marker for the next page; null on the last one."
    )
    has_more: bool


class TreeAgentNode(BaseModel):
    """One employee node of the group tree, with its counts.

    ``enrolled`` is **not** ported. In BonviZvonki it means "this employee has
    sent their phone number to the bot", which is what lets the bot recognise
    them in a chat, and it is read off ``agents.telegram_user_id``. This
    product has no Telegram identity for an agent and this port does not invent
    one, so the field would have been either always-false — a warning banner
    over every employee, which is the "banner that is always red" this repo
    already deleted once — or hard-coded true, which is a field that says
    nothing. The panel's enrolment notice and its three-step instruction modal
    go with it.
    """

    agent_id: uuid.UUID
    full_name: str
    color: str | None
    group_count: int
    response_count: int


class TreeBucket(BaseModel):
    """The groups that sit outside every node."""

    group_count: int
    response_count: int


class GroupTreeResponse(BaseModel):
    """The page's skeleton: one light aggregate, drawn without opening a node.

    ⚠️ The counts are always of ACTIVE groups and the tree takes no parameters.
    The panel's "show inactive too" switch therefore changes the leaves and
    never the node counts — deliberately, so a node count keeps one meaning:
    "groups that are working".
    """

    agents: list[TreeAgentNode]
    unassigned: TreeBucket = Field(
        description=(
            "Groups no employee is bound to. The panel puts this at the TOP of "
            "the page and opens it when it is non-empty: these groups receive "
            "nothing and nothing anywhere raises an error about it."
        )
    )


class GroupPatchRequest(BaseModel):
    """Change one group. Unset fields are left alone."""

    agent_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Setting this marks the row `manual`, so automatic binding stops "
            "touching it. Explicit null releases the employee."
        ),
    )
    is_active: bool | None = None


class BulkPatchRequest(BaseModel):
    """The same change applied to many groups at once."""

    group_ids: list[uuid.UUID] = Field(min_length=1, max_length=BULK_GROUP_LIMIT)
    agent_id: uuid.UUID | None = None
    is_active: bool | None = None


class BulkPatchResponse(BaseModel):
    updated: int


# ═══ Dispatching a survey ══════════════════════════════════════════════════


class DispatchRequest(BaseModel):
    """Ask for a survey in one group."""

    force: bool = Field(
        default=False,
        description=(
            "Ignore the suppression window. It never clears a structural "
            "block: an unbound group or a chat the bot is out of is refused "
            "whatever this says, because there would be no employee to "
            "attribute the rating to."
        ),
    )


class DispatchResponse(BaseModel):
    survey_id: uuid.UUID
    status: str
    reused: bool = Field(
        description=(
            "True when a survey was already queued for this group and that one "
            "was returned instead of a second being created. Not an error — it "
            "is what stops the same chat receiving two identical messages."
        )
    )
    delivered: bool = Field(
        description=(
            "Whether the transport actually posted it. **False in this "
            "deployment, always**: there is no Telegram bot, the shipped "
            "transport is a logging one, and the row stays `pending`."
        )
    )


class BroadcastRequest(BaseModel):
    force: bool = Field(
        default=True,
        description=(
            "Defaults to true, unlike the single-group send. The whole point "
            "of the button is 'send to everyone now'; silently sending nothing "
            "because of a ten-day window would be the broken behaviour."
        )
    )


class BroadcastSkip(BaseModel):
    """One group the broadcast passed over, and why."""

    group_id: uuid.UUID
    title: str
    reason: str = Field(
        description="group_not_bound | group_inactive | survey_suppressed."
    )


class BroadcastResponse(BaseModel):
    """What the broadcast did. The three numbers always account for every group.

    ``created + reused + len(skipped) == total_groups`` is an invariant, and a
    test asserts it. "8 sent" on its own made an admin go and count rows on the
    groups page to find out what happened to the rest.
    """

    created: int
    reused: int = Field(description="Groups that already had an unsent survey queued.")
    skipped: list[BroadcastSkip]
    total_groups: int
    delivered: int = Field(
        description=(
            "How many were actually posted. **Zero in this deployment** — see "
            "`DispatchResponse.delivered`."
        )
    )


# ═══ Feedback ══════════════════════════════════════════════════════════════


class RedFlagOption(BaseModel):
    """One misconduct criterion. The registry is the server's, never copied.

    The label is Uzbek because it is what a customer reads in their own chat;
    the key is what is stored. A key is never renamed, only added to, or every
    historical answer changes meaning.
    """

    key: str
    label: str


class FeedbackItem(BaseModel):
    """One customer's answer.

    ⚠️ **Never present for a `sales` caller**, whatever the access setting
    says — see `SurveyService.feedback`.
    """

    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    csat: int = Field(description="1..5 stars.")
    resolution: str | None = Field(
        description=(
            "yes | partial | no, or null when the customer skipped the "
            "question. Null is a real answer and must not be read as `no`."
        )
    )
    comment: str | None = Field(
        description="Null means no comment was written, or comments are withheld."
    )
    red_flags: list[str] = Field(
        description="Ticked criterion KEYS; labels come from /surveys/red-flags."
    )
    responded_at: datetime


class FeedbackResponse(BaseModel):
    """The rating page: the headline, the shape of it, and the rows behind it."""

    average: float | None = Field(
        description=(
            "Null while `ready` is false — never 0.0. A zero would be drawn as "
            "'rated badly' by every chart, and the gate exists so one "
            "customer's bad morning does not become a published score."
        )
    )
    count: int
    ready: bool = Field(description="True once `count >= min_responses`.")
    min_responses: int = Field(
        description="The threshold in force, from `survey.min_responses`."
    )
    distribution: dict[str, int] = Field(
        description='{"1".."5"} -> answers, zero-filled so the chart has five bars.'
    )
    response_rate: float | None = Field(
        description=(
            "Percent of surveys SENT in the window that were ANSWERED in it. "
            "Null when none were sent — not 0, which reads as 'nobody "
            "answered'."
        )
    )
    items: list[FeedbackItem] = Field(
        description=(
            "Empty for a `sales` caller, always. One group is one customer, so "
            "a single visible row identifies who wrote it."
        )
    )
    items_withheld: bool = Field(
        description=(
            "True when rows exist but are not being returned to this caller. "
            "Lets the panel say 'your average, without the individual "
            "ratings' rather than rendering an empty list that reads as 'no "
            "customer has ever rated you'."
        )
    )


# ═══ The customer-facing Mini App (NOT MOUNTED — see api/webapp/) ══════════


class WebAppOpenRequest(BaseModel):
    """Telegram's signed ``initData``, verbatim.

    The survey token is **not** a separate field: it rides inside
    ``initData.start_param``, covered by Telegram's HMAC. A token in the path
    or the body would let anyone pair their own genuine ``initData`` with
    another group's token.
    """

    init_data: str = Field(max_length=4096)


class WebAppOpenResponse(BaseModel):
    agent_name: str
    period_start: datetime
    period_end: datetime
    already_rated: bool
    red_flags: list[RedFlagOption]


class WebAppSubmitRequest(BaseModel):
    init_data: str = Field(max_length=4096)
    csat: int = Field(ge=CSAT_MIN, le=CSAT_MAX)
    comment: str | None = Field(default=None, max_length=COMMENT_MAX_LEN)
    red_flags: list[str] = Field(default_factory=list)


class WebAppSubmitResponse(BaseModel):
    ok: bool
    agent_name: str
    response_count: int


class BotRateRequest(BaseModel):
    """A rating relayed by the bot, which has already hashed the respondent."""

    respondent_hash: str = Field(
        min_length=RESPONDENT_HASH_LEN,
        max_length=RESPONDENT_HASH_LEN,
        pattern="^[0-9a-f]+$",
        description=(
            "A full SHA-256 hex digest. Pinned at exactly 64 characters, where "
            "BonviZvonki accepts 16-64: a producer sending a truncated hash "
            "would never collide with a full one for the same person, and the "
            "unique index would stop deduplicating with nothing raising."
        ),
    )
    csat: int = Field(ge=CSAT_MIN, le=CSAT_MAX)


class BotDetailRequest(BaseModel):
    """The optional second half of an answer: the comment and the ticks."""

    respondent_hash: str = Field(
        min_length=RESPONDENT_HASH_LEN,
        max_length=RESPONDENT_HASH_LEN,
        pattern="^[0-9a-f]+$",
    )
    comment: str | None = Field(default=None, max_length=COMMENT_MAX_LEN)
    red_flags: list[str] | None = Field(
        default=None,
        description=(
            "Null leaves whatever was stored. Explicit `[]` clears it. "
            "BonviZvonki assigns unconditionally, so a retry carrying only "
            "ticks destroys the comment the customer had already sent."
        ),
    )


class BotRateResponse(BaseModel):
    accepted: bool
    response_count: int
    already_rated: bool


__all__ = [
    "BotDetailRequest",
    "BotRateRequest",
    "BotRateResponse",
    "BroadcastRequest",
    "BroadcastResponse",
    "BroadcastSkip",
    "BulkPatchRequest",
    "BulkPatchResponse",
    "DispatchRequest",
    "DispatchResponse",
    "FeedbackItem",
    "FeedbackResponse",
    "GroupPageResponse",
    "GroupPatchRequest",
    "GroupResponse",
    "GroupTreeResponse",
    "RedFlagOption",
    "TreeAgentNode",
    "TreeBucket",
    "WebAppOpenRequest",
    "WebAppOpenResponse",
    "WebAppSubmitRequest",
    "WebAppSubmitResponse",
]
