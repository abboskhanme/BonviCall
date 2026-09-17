"""The rubric: reading the active one, and publishing the next one.

Ported from BonviZvonki's ``scoring/application/rubric_service.py``, which is
the only part of that module BonviCall did not take in phase 1 (§2.5). Three
things are kept exactly as they were, because each one records a failure that
happened there:

1. **The blocks total exactly 100, and each block totals its own maximum.** A
   rubric that does not is refused and never reaches the table — a score is a
   percentage of a maximum, and a maximum nobody checked is a number that
   cannot be compared with yesterday's.
2. **A red-flag key is ``[a-z][a-z0-9_]{1,31}``, once.** The key goes into the
   prompt ("only these keys"), into the answer validator and into the panel's
   labels. A key with a space or a Cyrillic letter is one the model cannot echo
   back, so a single bad key makes EVERY answer fail validation — one careless
   save stops all scoring.
3. **``extra_rules`` is capped.** That text is sent on every single call, so its
   length is money (``prompt.MAX_EXTRA_RULES``).

Two things are deliberately different:

* **Reading never writes.** ``get_active()`` there inserted the default rubric
  on first read, so a GET was a write and its router called ``session.commit()``
  after a read. Here an empty table simply means "the pinned default is the
  rubric" (:func:`_from_default`), which is also what makes a database nobody
  seeded keep scoring.
* **The server invents no display text.** Their ``create_version`` defaulted the
  name to ``f"Rubrika v{n}"`` — Uzbek in a ``.py`` file, which CONVENTIONS.md
  §14 allows in exactly six files and this is not one of them. The name is the
  caller's, and the panel pre-fills it from ``uz.json``.

Versioning is the reason the table exists: **publishing writes a new row and
never touches the old one**, so ``call_scores.rubric_version`` keeps meaning
what it says — the version named there can still be read, criterion by
criterion, when somebody disputes a number months later.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import ConflictError, ErrorCode, NotFoundError, ValidationError
from src.modules.analysis.models import RubricModel
from src.modules.analysis.prompt import (
    MAX_EXTRA_RULES,
    build_system_prompt,
    split_system_prompt,
)
from src.modules.analysis.rubric_default import (
    DEFAULT_RUBRIC,
    DEFAULT_RUBRIC_VERSION,
    version_label,
)
from src.modules.analysis.schemas import (
    PromptSection,
    RubricBlock,
    RubricPromptResponse,
    RubricRedFlag,
    RubricResponse,
    RubricVersionSummary,
)

#: What every rubric's blocks must add up to. The score is expressed out of this
#: number on every screen and in every export.
TOTAL_POINTS = 100

#: The shape a red-flag key may take.
#
# WHY IT IS STRICT. The key appears in three places at once: the prompt's "only
# these keys" list, ``validator._validate_red_flags`` and the panel's labels. A
# key the model cannot reproduce verbatim makes the WHOLE answer invalid, so one
# bad key stops scoring for every call until somebody publishes a fix.
RED_FLAG_KEY = re.compile(r"[a-z][a-z0-9_]{1,31}")

#: Characters per token in Uzbek and code-switched Uzbek/Russian text. Used for
#: ONE number on one screen — "this prompt costs roughly N tokens per call" — so
#: an order of magnitude is the answer wanted, not an invoice. The exact ratio
#: is the vendor's and differs per model.
CHARS_PER_TOKEN = 3.3


@dataclass(frozen=True)
class ActiveRubric:
    """The rubric a score is about to be produced against.

    A value object rather than the ORM row, because it has two sources: the
    active ``rubrics`` row, or — when the table is empty —
    ``rubric_default.DEFAULT_RUBRIC``. Everything downstream (the prompt, the
    JSON schema, the validator, ``call_scores.rubric_version``) reads the same
    five fields whichever it was, and ``stored`` is how a reader tells them
    apart without guessing.
    """

    version: int
    name: str
    description: str | None
    blocks: list[dict[str, Any]]
    red_flags: list[dict[str, Any]]
    extra_rules: str | None
    #: ``False`` means this is the pinned default and no row exists yet.
    stored: bool
    id: uuid.UUID | None = None
    created_at: datetime | None = None

    @property
    def label(self) -> str:
        """``"v3"`` — exactly what is written to ``call_scores.rubric_version``."""
        return version_label(self.version)


def _from_default() -> ActiveRubric:
    """The pinned rubric, as if it were the active row.

    **This is the fallback that keeps an unseeded database scoring.** It is not
    a degraded mode: until somebody publishes, the constant *is* the rubric, and
    it is the same rubric migration 012 seeds — so the scores either way are the
    same scores, under the same label.
    """
    return ActiveRubric(
        version=DEFAULT_RUBRIC_VERSION,
        name=str(DEFAULT_RUBRIC["name"]),
        description=DEFAULT_RUBRIC.get("description"),
        blocks=list(DEFAULT_RUBRIC["blocks"]),
        red_flags=list(DEFAULT_RUBRIC["red_flags"]),
        # The default carries no admin instructions: they are something a person
        # writes, and nobody has written any yet.
        extra_rules=None,
        stored=False,
    )


def _from_row(row: RubricModel) -> ActiveRubric:
    return ActiveRubric(
        version=row.version,
        name=row.name,
        description=row.description,
        blocks=list(row.blocks or []),
        red_flags=list(row.red_flags or []),
        extra_rules=row.extra_rules,
        stored=True,
        id=row.id,
        created_at=row.created_at,
    )


# --- Rows and value objects, as the panel reads them -------------------------
#
# The mapping lives here rather than in the router, so the router stays the thin
# shell CONVENTIONS.md §2 asks for and so a test can assert the wire shape
# without an HTTP client.


def rubric_response(source: RubricModel | ActiveRubric) -> RubricResponse:
    """One rubric, whether it came from a row or from the pinned default."""
    active = source if isinstance(source, ActiveRubric) else _from_row(source)
    return RubricResponse(
        id=active.id,
        version=active.version,
        label=active.label,
        name=active.name,
        description=active.description,
        # The default is what scores while nothing is published, so it *is* the
        # active rubric; `stored` is what tells the editor it is not a row.
        is_active=source.is_active if isinstance(source, RubricModel) else True,
        stored=active.stored,
        blocks=[RubricBlock.model_validate(block) for block in active.blocks],
        red_flags=[RubricRedFlag.model_validate(flag) for flag in active.red_flags],
        extra_rules=active.extra_rules,
        extra_rules_limit=MAX_EXTRA_RULES,
        created_at=active.created_at,
    )


def prompt_preview(active: ActiveRubric) -> RubricPromptResponse:
    """The system prompt as the model will receive it, split into its sections.

    ═══════════════════════════════════════════════════════════════════════════
    **WHY THIS ENDPOINT EXISTS.** The admin edits text that decides how people
    are scored. Without seeing what actually reaches the model they work blind:
    they repeat an instruction that is already there — paying for the tokens on
    every call — or write one that contradicts it and cannot understand why
    nothing changed.

    **WHY IT IS READ-ONLY.** The language rules, the scoring order and the
    RESPONSE FORMAT are fixed: break them and every answer fails validation,
    i.e. one edit stops all scoring. They are shown, and cannot be touched.

    Built from ``prompt._sections``, the SAME function ``build_system_prompt``
    uses. Two builders would drift and the screen would show one prompt while
    the model received another — a bug with no symptom.
    ═══════════════════════════════════════════════════════════════════════════
    """
    sections = split_system_prompt(active.blocks, active.red_flags, active.extra_rules)
    full = build_system_prompt(active.blocks, active.red_flags, active.extra_rules)
    return RubricPromptResponse(
        rubric_version=active.version,
        rubric_label=active.label,
        sections=[PromptSection(**part) for part in sections],
        full_text=full,
        char_count=len(full),
        approx_tokens=round(len(full) / CHARS_PER_TOKEN),
        extra_rules_limit=MAX_EXTRA_RULES,
    )


def version_summary(row: RubricModel) -> RubricVersionSummary:
    return RubricVersionSummary(
        version=row.version,
        label=version_label(row.version),
        name=row.name,
        is_active=row.is_active,
        created_at=row.created_at,
    )


def validate_rubric(
    blocks: list[dict[str, Any]], red_flags: list[dict[str, Any]]
) -> None:
    """Refuse a rubric that cannot produce a comparable score.

    Raises :class:`ValidationError` (422) with a machine ``reason`` in the
    detail and the numbers that failed; the panel renders the Uzbek sentence
    from ``uz.json``, exactly as it does for ``review_reasons`` — a column or a
    payload never carries display copy (§1.6).
    """
    if not blocks:
        raise ValidationError(detail={"reason": "rubric_no_blocks"})

    total = 0
    for block in blocks:
        block_max = int(block.get("max") or 0)
        criteria = block.get("criteria") or []
        label = str(block.get("label") or block.get("key") or "?")
        if not criteria:
            raise ValidationError(
                detail={"reason": "rubric_block_empty", "block": label}
            )

        criteria_sum = sum(int(c.get("points") or 0) for c in criteria)
        if criteria_sum != block_max:
            # The block maximum is what a block's score is a percentage OF. If
            # the criteria cannot reach it, every call loses points nobody can
            # earn; if they overshoot it, a block can read 120 %.
            raise ValidationError(
                detail={
                    "reason": "rubric_block_mismatch",
                    "block": label,
                    "criteria_sum": criteria_sum,
                    "block_max": block_max,
                }
            )
        total += block_max

    if total != TOTAL_POINTS:
        raise ValidationError(
            detail={
                "reason": "rubric_total_not_100",
                "total": total,
                "expected": TOTAL_POINTS,
            }
        )

    seen: set[str] = set()
    for flag in red_flags:
        label = str(flag.get("label") or "?")
        if int(flag.get("penalty") or 0) > 0:
            # A red flag is a penalty. A positive number would ADD points for
            # swearing at a customer.
            raise ValidationError(
                detail={"reason": "rubric_flag_penalty_positive", "flag": label}
            )

        key = str(flag.get("type") or "").strip()
        if not RED_FLAG_KEY.fullmatch(key):
            raise ValidationError(
                detail={"reason": "rubric_flag_key_invalid", "flag": label, "key": key}
            )
        if key in seen:
            raise ValidationError(
                detail={"reason": "rubric_flag_key_duplicate", "key": key}
            )
        seen.add(key)


def clean_extra_rules(text: str | None) -> str | None:
    """Trim the admin's instructions, or refuse them for being too long.

    Empty and ``NULL`` are one thing — "no instructions" — because an empty
    string would leave the prompt with a heading and nothing under it, and a
    model handed an empty section invents what was supposed to be in it.

    The ceiling exists because this text is added to EVERY call's prompt, so its
    length converts directly into money (``prompt.MAX_EXTRA_RULES``). Without
    one, somebody pastes a staff handbook and nothing stops them.
    """
    value = (text or "").strip()
    if not value:
        return None
    if len(value) > MAX_EXTRA_RULES:
        raise ValidationError(
            detail={
                "reason": "rubric_extra_rules_too_long",
                "length": len(value),
                "limit": MAX_EXTRA_RULES,
            }
        )
    return value


class RubricService:
    """Read the active rubric; publish the next version of it."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- Reading ----------------------------------------------------------

    async def active(self) -> ActiveRubric:
        """The rubric new scores are produced against.

        The active row, or the pinned default when the table is empty. **Never
        writes** — see the module docstring.
        """
        row = await self.active_row()
        return _from_default() if row is None else _from_row(row)

    async def active_row(self) -> RubricModel | None:
        """The active row itself, or ``None`` when nothing has been published."""
        return (
            await self.session.execute(
                select(RubricModel).where(RubricModel.is_active.is_(True))
            )
        ).scalar_one_or_none()

    async def versions(self) -> list[RubricModel]:
        """Every published version, newest first. Nothing is ever deleted."""
        return list(
            (
                await self.session.execute(
                    select(RubricModel).order_by(RubricModel.version.desc())
                )
            )
            .scalars()
            .all()
        )

    async def get_version(self, version: int) -> RubricModel:
        row = (
            await self.session.execute(
                select(RubricModel).where(RubricModel.version == version)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError()
        return row

    # --- Writing ----------------------------------------------------------

    async def publish(
        self,
        *,
        name: str,
        blocks: list[dict[str, Any]],
        red_flags: list[dict[str, Any]],
        extra_rules: str | None = None,
        description: str | None = None,
        user_id: uuid.UUID | None = None,
    ) -> RubricModel:
        """Validate, then write the NEXT version and make it the active one.

        **The previous version is not touched beyond ``is_active``.** Every
        score already produced points at it by name, and a rubric that could be
        edited in place would re-base yesterday's numbers without changing the
        string that claims they are comparable.
        """
        validate_rubric(blocks, red_flags)
        cleaned = clean_extra_rules(extra_rules)

        highest = await self.session.scalar(select(func.max(RubricModel.version)))
        next_version = (highest or 0) + 1

        # The deactivation comes first: the partial unique index allows exactly
        # one `is_active = true` row, and PostgreSQL checks it at the end of
        # each statement.
        await self.session.execute(
            update(RubricModel)
            .where(RubricModel.is_active.is_(True))
            .values(is_active=False)
        )

        row = RubricModel(
            version=next_version,
            name=name.strip(),
            description=(description or "").strip() or None,
            is_active=True,
            blocks=blocks,
            red_flags=red_flags,
            extra_rules=cleaned,
            created_by=user_id,
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            # Two admins pressed save in the same second: the second one's
            # version number is already taken. A 409 tells them to reload and
            # look at what the first one published — which is the only safe
            # answer, because silently renumbering would publish an edit made
            # against a rubric that is no longer the active one.
            await self.session.rollback()
            raise ConflictError(
                ErrorCode.CONFLICT,
                detail={"reason": "rubric_version_taken", "version": next_version},
            ) from exc

        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def activate(self, version: int) -> RubricModel:
        """Go back to an earlier version.

        Kept from BonviZvonki because it is the undo for a bad edit, and the
        only one: a published version cannot be deleted. The rolled-back-to
        version keeps its own number, so scores produced before and after the
        round trip carry the same label and really were produced by the same
        rubric.
        """
        row = await self.get_version(version)
        if row.is_active:
            return row
        await self.session.execute(
            update(RubricModel)
            .where(RubricModel.is_active.is_(True))
            .values(is_active=False)
        )
        row.is_active = True
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(row)
        return row
