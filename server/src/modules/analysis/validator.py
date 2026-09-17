"""Checking the LLM's answer — we do not trust it, we RECOMPUTE it.

Why this file exists: the model can answer "blocks 84, overall 96", and if that
lie reaches the database nobody notices — but the employee is scored wrongly. So:

  * the arithmetic is recomputed (criterion -> block -> overall),
  * red-flag keys are checked against the rubric,
  * invented block / criterion / flag keys are rejected.

A rejected answer is **not saved**: the call stops with ``score_invalid`` and the
reason lands in ``call_analysis_state.failure_detail``, which an admin can read.

Pure by contract (SPEC-ANALYTICS §1.1, ``tests/test_analysis_purity.py``): no
session, no ORM, no framework, no vendor key. That is what lets the ported
scoring tests run with nothing but pytest.

## SCORING WITHIN THE CRITERIA THAT WERE APPLIED (``na``)

Most customers are returning customers and they talk briefly: "send me 50".
Such a conversation demands no requirement-gathering, no product presentation
and no upsell. The rubric used to be applied in full anyway and the employee
scored 40-50 through no fault of their own — a score that said nothing about
the employee and everything about the rubric being beside the point.

Now the model marks such a criterion ``verdict: "na"`` and it **drops out** of
the arithmetic: it earns neither zero nor its maximum. The score is computed
within the criteria that were applied:

    block figure  = block_max x earned / applicable
    overall score = 100 x sum(block figures) / sum(block maxima)

So "8 out of 10" and "20 out of 25" are the same thing - 80 %.

WARNING: there are THREE guards, or ``na`` becomes a hidden way to raise the
score - and they were not designed in, they were added after MEASUREMENT: left
without a ceiling, the model dropped seven criteria in a ten-minute conversation
and gave 8 of 12 calls a flat 100.

  1. ``na`` is only allowed on a criterion the rubric marks ``optional: true``.
     Greeting, conduct, answering the question and being concrete about the
     next step are assessed in EVERY conversation.
  2. ``na`` has a BUDGET that depends on the length of the call
     (``na_budget``): in a short call there is effectively no limit, past four
     minutes it is at most 20 points. A long conversation had both the time and
     the subject matter, and there "does not apply" nearly always means "was
     not done".
  3. If the applied criteria add up to less than ``MIN_APPLICABLE_POINTS`` the
     answer is rejected. That closes the "mark everything inapplicable" road.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

#: Models sometimes wrap the JSON in ```json ... ```
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)

VALID_SENTIMENTS = ("positive", "neutral", "negative")
VALID_OUTCOMES = ("order_agreed", "follow_up", "rejected", "info_only", "unclear")
VALID_QUALITY = ("high", "medium", "low")
VALID_VERDICTS = ("pass", "partial", "fail", "na")
VALID_SCENARIOS = (
    "new_client",
    "repeat_order",
    "price_check",
    "issue",
    "personal",
    "no_content",
    "other",
)

#: The verdict that means "this does not apply to this conversation".
NOT_APPLICABLE = "na"

#: The BUDGET for ``na``, by conversation length.
#
# WHY IT DEPENDS ON LENGTH. Measured: left without a ceiling the model marked
# seven criteria "does not apply" in a TEN-MINUTE conversation and gave 8 of 12
# calls a flat 100. That is the MIRROR of the first problem: before, every call
# scored unjustifiably low; now it scored unjustifiably high. Either one makes
# the tool useless.
#
# The logic is simple: a 30-second "send me 50" has no TIME for requirement
# gathering or a presentation - they genuinely do not apply. A ten-minute
# conversation had both the time and the subject matter, and there a claim of
# "does not apply" nearly always means "the employee did not do it".
#
# Values: (seconds threshold, total points allowed to be dropped as ``na``).
NA_BUDGET: tuple[tuple[int, int], ...] = (
    (90, 100),  # short call - no practical limit
    (240, 32),  # 1.5-4 minutes - up to about a third
    (10**9, 20),  # over 4 minutes - only the genuinely beside-the-point ones
)


def na_budget(duration_sec: int) -> int:
    """Total points allowed to be marked ``na`` in a call of this length.

    Lives here rather than in ``rules.py`` although §1.1 lists it under the
    pure-rules heading: ``validate()`` is what enforces the budget, and
    ``validator.py`` may not import ``rules.py`` (both are asserted importless
    by ``tests/test_analysis_purity.py``). Two copies of this table is the
    ``BLOCK_MAX`` 25-vs-15 defect again, so there is one, and ``scorer.py``
    reads it from here to print the same number in the prompt.
    """
    for threshold, budget in NA_BUDGET:
        if duration_sec < threshold:
            return budget
    return NA_BUDGET[-1][1]


#: Below this many applied points the answer is rejected.
#
# WHY THERE IS A FLOOR. ``na`` is a useful instrument, but unsupervised it
# empties scoring of meaning: the model can mark every hard criterion "does not
# apply" and hand out 95s that nobody questions (a score going UP never
# produces a complaint).
#
# 40 sits below the sum of the always-assessed criteria in the standard rubric
# (51), so normal work never touches this floor. Touching it means the rubric
# has been all but switched off, and that is a malfunction rather than an answer.
MIN_APPLICABLE_POINTS = 40


def _round_half_up(value: float) -> int:
    """Half a point rounds UP.

    WARNING: ``round()`` is not used. Python does banker's rounding and
    ``round(12.5)`` gives 12. A score is a number about a person, and the rubric
    itself resolves doubt in the employee's favour ("in case of doubt, favour
    the employee"). One point is not much, but the rule has to point the SAME
    way every time - otherwise "why 12, I make it 12.5" has no answer.
    """
    return math.floor(value + 0.5)


class ScoreInvalid(Exception):
    """The LLM's answer does not fit the rubric — the score is NOT saved.

    A plain exception on purpose. Every ``AppError`` subclass in this product
    lives in ``core/errors.py`` (CONVENTIONS.md §9), and this module may not
    import from ``src`` at all. ``score.py`` catches it and records
    ``AnalysisFailure.SCORE_INVALID`` with ``.message`` as the detail.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(slots=True)
class ScoreDraft:
    """A checked score — ready to be written to the database."""

    overall: int
    blocks: dict[str, Any]
    block_scores: dict[str, int]
    """The block figure — computed WITHIN the applied criteria and scaled back
    to the block maximum (``max x earned / applicable``).

    WARNING: not the raw sum. This exact value is what the screen and the
    analytics cut show: "Script 22/25" reads correctly in a short call, whereas
    the raw sum would read "5/25" and make the employee look at fault. The raw
    sum is in ``blocks[key]["raw_score"]``.

    A block that is entirely ``na`` does not appear in this dict at all —
    showing it as 0 or as its maximum would both be untrue."""

    red_flags: list[dict[str, Any]]
    penalty_total: int
    outcome_signal: dict[str, Any]
    sentiment: str
    coaching_note: str
    confidence_pct: int
    """The model's confidence in its own score, 0..100.

    An **integer**, because it is compared against a threshold in Python, in SQL
    and in TypeScript, and a float rounds differently in each (§2.2). The model
    answers 0..1 and the conversion happens here, once."""

    language_detected: str
    transcript_quality: str
    applicable_points: int = 100
    """The criteria that applied to this conversation, out of 100."""
    earned_points: int = 0
    """Raw points earned across the applied criteria."""
    na_criteria: list[str] = field(default_factory=list)
    """Keys of the criteria marked as not applicable."""
    scenario: str = "other"
    """What kind of conversation this was (``repeat_order``, ``price_check``,
    ...) — NOT a score, context that explains the ``na`` decisions."""
    na_over_budget: bool = False
    """Too many criteria were marked "does not apply" in a long conversation.
    The score was accepted (the retries ran out), but a PERSON needs to see it:
    the employee may have skipped the stages and the model may have read that as
    "not required"."""
    zeroed: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def blocks_total(self) -> int:
        return sum(self.block_scores.values())

    @property
    def applicable_max(self) -> int:
        """Which maximum the figures were computed against.

        A block that is entirely ``na`` is not in this number, which is what
        lets the screen say "68 / 75" and be telling the truth."""
        return sum(
            int(block.get("max", 0))
            for block in self.blocks.values()
            if block.get("applicable_max", 0) > 0
        )


# -- Helpers ---------------------------------------------------------------


def _as_int(value: Any, *, where: str) -> int:
    if isinstance(value, bool):
        raise ScoreInvalid(f"{where}: the score must be a number")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            pass
    raise ScoreInvalid(f"{where}: '{value}' is not a score — an integer was expected")


def loads(raw: str) -> dict[str, Any]:
    """Turn the model's text answer into JSON."""
    text = (raw or "").strip()
    if not text:
        raise ScoreInvalid("the AI returned an empty answer — no score was produced")

    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # Some models write a sentence or two before the JSON — as a last
        # resort take everything from the first `{` to the last `}`
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ScoreInvalid(
                f"the AI answer could not be read as JSON: {exc.msg}"
            ) from exc
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc2:
            raise ScoreInvalid(
                f"the AI answer could not be read as JSON: {exc2.msg}"
            ) from exc2

    if not isinstance(data, dict):
        raise ScoreInvalid("the AI answer is not a JSON object")
    return data


# -- The check itself ------------------------------------------------------


def validate(
    raw: str,
    *,
    rubric_blocks: list[dict[str, Any]],
    rubric_red_flags: list[dict[str, Any]],
    duration_sec: int | None = None,
    enforce_na_budget: bool = True,
) -> ScoreDraft:
    """Check the answer against the rubric and recompute it.

    With ``duration_sec`` the ``na`` budget is checked too: criteria cannot be
    dropped wholesale in a long conversation.

    WARNING: ``enforce_na_budget=False`` is for the LAST attempt. Going over
    budget rejects the answer and the model is asked again, but once the
    attempts are exhausted rejecting has no meaning left: the call ends up not
    scored at all (measured — it happened) and the money paid three times is
    wasted too. So on the last attempt the score is ACCEPTED and the
    ``na_over_budget`` flag lifts it into the manager's review queue.
    """
    data = loads(raw)

    blocks_raw = data.get("blocks")
    if not isinstance(blocks_raw, dict):
        raise ScoreInvalid("the AI answer has no `blocks` object")

    expected_keys = {b["key"] for b in rubric_blocks}
    got_keys = set(blocks_raw)

    unknown = sorted(got_keys - expected_keys)
    if unknown:
        raise ScoreInvalid(
            f"the AI returned a block that is not in the rubric: {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(expected_keys))}"
        )
    missing = sorted(expected_keys - got_keys)
    if missing:
        raise ScoreInvalid(f"the AI answer is missing blocks: {', '.join(missing)}")

    #: Discrepancies that do NOT affect the score (for instance the model's own
    #: block total not matching the sum of its criteria). The score is kept, but
    #: the discrepancy is not lost.
    warnings: list[str] = []

    # -- Pass 1: check the criteria ----------------------------------------
    cleaned: dict[str, list[dict[str, Any]]] = {}
    for spec in rubric_blocks:
        key = spec["key"]
        label = spec.get("label", key)
        payload = blocks_raw[key]
        if not isinstance(payload, dict):
            raise ScoreInvalid(f"block '{label}' is not an object")

        criteria_clean, score = _validate_criteria(
            payload.get("criteria"), spec=spec, label=label
        )
        cleaned[key] = criteria_clean

        # WARNING: the block score is NOT taken from the model, it is computed
        # from the criteria.
        #
        # The model used to write it and the validator used to compare. Once
        # `na` existed that became a constant source of failure: after a dropped
        # criterion the model would try to "fill up" the block maximum and write
        # an inflated total, and the whole answer was rejected — measured, two
        # calls in five went unscored for exactly this reason.
        written = payload.get("score")
        if written is not None:
            try:
                if _as_int(written, where=f"block '{label}'") != score:
                    warnings.append(
                        f"'{label}': the model wrote {written}, the criteria "
                        f"add up to {score}"
                    )
            except ScoreInvalid:
                warnings.append(f"'{label}': the block score is not a number — ignored")

    # -- The `na` budget ---------------------------------------------------
    na_over_budget = _apply_na_budget(
        cleaned,
        duration_sec=duration_sec,
        enforce=enforce_na_budget,
        warnings=warnings,
    )

    # -- Pass 2: the block arithmetic --------------------------------------
    block_scores: dict[str, int] = {}
    blocks_clean: dict[str, Any] = {}
    applicable_points = 0
    earned_points = 0
    na_criteria: list[str] = []
    displayed_max = 0

    for spec in rubric_blocks:
        key = spec["key"]
        label = spec.get("label", key)
        block_max = int(spec.get("max", 0))
        criteria_clean = cleaned[key]

        block_applicable = sum(c["max"] for c in criteria_clean if c["applicable"])
        score = sum(c["score"] for c in criteria_clean if c["applicable"])

        applicable_points += block_applicable
        earned_points += score
        na_criteria.extend(c["id"] for c in criteria_clean if not c["applicable"])

        # -- The block figure ----------------------------------------------
        #
        # Not the raw sum: the share within the criteria that were applied.
        # Half of the "Script" block may not apply to a short reorder call: a
        # raw 5/25 would broadcast the lie that the employee worked badly,
        # while 22/25 tells the truth — everything that applied was done.
        if block_applicable > 0:
            display = _round_half_up(block_max * score / block_applicable)
            display = max(0, min(block_max, display))
            block_scores[key] = display
            displayed_max += block_max
        else:
            # A block that applies not at all is not shown. Writing 0 would
            # make the employee look at fault; writing the maximum would award
            # points for work nobody checked.
            display = None

        blocks_clean[key] = {
            "score": display if display is not None else 0,
            "max": block_max,
            "raw_score": score,
            "applicable_max": block_applicable,
            "label": label,
            "criteria": criteria_clean,
        }

    if applicable_points < MIN_APPLICABLE_POINTS or displayed_max == 0:
        marked = ", ".join(na_criteria) or "none"
        raise ScoreInvalid(
            f"too few criteria were applied ({applicable_points} points, at least "
            f"{MIN_APPLICABLE_POINTS} required): marked 'does not apply' — {marked}. "
            "Greeting, conduct, answering the question and being concrete about "
            "the next step are assessed in any conversation. The score was not saved."
        )

    red_flags, penalty_total, zeroed = _validate_red_flags(
        data.get("red_flags"), rubric_red_flags=rubric_red_flags
    )

    # -- The overall score -------------------------------------------------
    #
    # WARNING: NOT taken from the model, computed. The model used to return
    # `overall_score` and the validator used to check the arithmetic. There is
    # now a division in the calculation (a percentage within the applied
    # criteria), so asking the model for it only raises the odds of a rejected
    # answer and a second request — twice the money.
    #
    # The percentage comes out of the DISPLAYED values: if the screen shows
    # blocks adding to 68 out of 75, the overall must be 91. Computed any other
    # way, a manager adding up the numbers on the screen would get a different
    # answer and stop trusting the score.
    base = _round_half_up(100 * sum(block_scores.values()) / displayed_max)
    expected_overall = 0 if zeroed else max(0, min(100, base + penalty_total))

    confidence = _validate_confidence(data.get("confidence"))
    sentiment = _validate_choice(
        data.get("client_sentiment"), VALID_SENTIMENTS, "`client_sentiment`"
    )
    quality = _validate_choice(
        data.get("transcript_quality"), VALID_QUALITY, "`transcript_quality`"
    )
    outcome = _validate_outcome(data.get("outcome_signal"))

    coaching = str(data.get("coaching_note") or "").strip()
    if not coaching:
        raise ScoreInvalid(
            "the AI wrote no `coaching_note` — a score with no advice for the "
            "employee is useless"
        )

    language = str(data.get("language_detected") or "").strip().lower() or "mixed"
    if language not in ("uz", "ru", "mixed", "other"):
        language = "other"

    scenario = str(data.get("call_scenario") or "").strip().lower()
    if scenario not in VALID_SCENARIOS:
        # WARNING: the answer is NOT rejected for this field. It does not affect
        # the score — it is context only. Throwing away a whole score over an
        # unfamiliar label would be expensive and pointless.
        scenario = "other"

    return ScoreDraft(
        overall=expected_overall,
        blocks=blocks_clean,
        block_scores=block_scores,
        red_flags=red_flags,
        penalty_total=penalty_total,
        outcome_signal=outcome,
        sentiment=sentiment,
        coaching_note=coaching,
        confidence_pct=_round_half_up(confidence * 100),
        language_detected=language,
        transcript_quality=quality,
        applicable_points=applicable_points,
        earned_points=earned_points,
        na_criteria=na_criteria,
        scenario=scenario,
        zeroed=zeroed,
        na_over_budget=na_over_budget,
        warnings=warnings,
    )


def _apply_na_budget(
    blocks: dict[str, list[dict[str, Any]]],
    *,
    duration_sec: int | None,
    enforce: bool,
    warnings: list[str],
) -> bool:
    """Apply the ``na`` budget. ``True`` means it had been exceeded.

    Two different jobs:

      * ``enforce=True`` (an ordinary attempt) — REJECT the answer; the model is
        asked again and usually corrects itself (measured: on the second attempt
        the scores fell into the 58-92 range, i.e. the model actually assessed
        the criteria);
      * ``enforce=False`` (the LAST attempt) — rejecting has no meaning left,
        because the call would end up not scored at all and the money paid three
        times would be wasted. Here the budget is applied BY HAND: the cheapest
        ``na`` marks are kept and the rest are counted as "not done" (0 points,
        ``fail``).

    WARNING: WHY THE CHEAPEST ARE KEPT. A low-scoring criterion (upsell 6, value
    argument 5) is more likely to be genuinely beside the point; a high-scoring
    one (requirement gathering, 8) should almost always have happened in a long
    conversation. The decision is visible to a person: the score goes into the
    review queue.
    """
    if duration_sec is None:
        return False

    na_items = [
        c for criteria in blocks.values() for c in criteria if not c["applicable"]
    ]
    if not na_items:
        return False

    dropped_points = sum(c["max"] for c in na_items)
    budget = na_budget(duration_sec)
    if dropped_points <= budget:
        return False

    minutes = duration_sec // 60
    listed = ", ".join(c["id"] for c in na_items)
    message = (
        f"the conversation lasted {minutes} minutes, so there was time for the "
        f"stages. {dropped_points} points were dropped as 'does not apply' "
        f"({listed}); a conversation of this length allows {budget}. If the "
        "situation allowed it and the employee did not use it, that is `fail`, "
        "not `na`."
    )
    if enforce:
        raise ScoreInvalid(message + " The score was not saved.")

    # Applying the budget by hand: cheapest first, keep what fits
    remaining = budget
    restored: list[str] = []
    for item in sorted(na_items, key=lambda c: c["max"]):
        if item["max"] <= remaining:
            remaining -= item["max"]
            continue
        item["applicable"] = True
        item["verdict"] = "fail"
        item["score"] = 0
        # WARNING: the evidence TEXT is set too. Otherwise the card would show
        # a verdict of "not done" next to evidence reading "does not apply to
        # this conversation" — a manager reads that as a broken system.
        item["evidence"] = (
            "[System: long conversation, restored to the count because it "
            "exceeded the 'does not apply' budget] " + (item.get("evidence") or "")
        ).strip()
        item["improvement"] = (
            item.get("improvement")
            or "The conversation was long — this stage should not have been skipped"
        )
        restored.append(item["id"])

    warnings.append(
        message + f" Restored to the count beyond the budget: {', '.join(restored)}."
    )
    return True


def _validate_criteria(
    raw: Any, *, spec: dict[str, Any], label: str
) -> tuple[list[dict[str, Any]], int]:
    """Check the criteria and COMPUTE the block score.

    Returns ``(cleaned list, points earned)``.

    Which criteria applied is in ``clean[i]["applicable"]`` — it is recomputed
    from that list AFTER the budget has been applied, so it is not returned
    separately here.

    The input comes in two shapes:

      * an object — ``{"A1": {"score": 5, ...}, ...}`` (what the schema demands:
        every criterion with its own ceiling and its own verdict list);
      * a list — ``[{"id": "A1", "score": 5, ...}, ...]`` (the older shape).

    WARNING: BOTH ARE ACCEPTED. A provider with no schema support may return a
    list, and throwing the score away then would be beside the point — the
    information is complete either way.

    ``na`` only on a criterion the rubric marks ``optional: true``. Otherwise
    the model could drop any criterion it liked and a low score would never
    appear: "did not greet the customer" would become "does not apply".
    """
    if isinstance(raw, dict):
        items: list[Any] = [
            {"id": cid, **(payload if isinstance(payload, dict) else {})}
            for cid, payload in raw.items()
        ]
    elif isinstance(raw, list):
        items = raw
    else:
        items = []

    if not items:
        raise ScoreInvalid(
            f"block '{label}' was given no criteria — every point must be "
            "justified with evidence"
        )

    known = {c["id"]: int(c.get("points", 0)) for c in spec.get("criteria", [])}
    optional = {c["id"]: bool(c.get("optional")) for c in spec.get("criteria", [])}
    seen: set[str] = set()
    clean: list[dict[str, Any]] = []
    total = 0

    for item in items:
        if not isinstance(item, dict):
            raise ScoreInvalid(f"block '{label}': a criterion is not an object")
        cid = str(item.get("id") or "").strip()
        if cid not in known:
            raise ScoreInvalid(
                f"block '{label}': criterion '{cid}' is not in the rubric. "
                f"Available: {', '.join(sorted(known))}"
            )
        if cid in seen:
            raise ScoreInvalid(
                f"block '{label}': criterion '{cid}' was returned twice"
            )
        seen.add(cid)

        verdict = str(item.get("verdict") or "").strip().lower()
        if verdict not in VALID_VERDICTS:
            verdict = "partial"

        score = _as_int(item.get("score"), where=f"'{label}' / {cid}")
        if not 0 <= score <= known[cid]:
            raise ScoreInvalid(
                f"'{label}' / {cid}: {score} points, the allowed range is 0..{known[cid]}"
            )

        if verdict == NOT_APPLICABLE:
            if not optional.get(cid):
                raise ScoreInvalid(
                    f"'{label}' / {cid}: this criterion is assessed in ANY "
                    "conversation and cannot be marked 'does not apply'. If the "
                    "situation called for it and the employee did not do it, use "
                    "`fail`. The score was not saved."
                )
            # WARNING: on `na` the score is IGNORED, the answer is NOT rejected.
            # Such a criterion does not enter the arithmetic at all, so whatever
            # the model wrote there is immaterial — throwing away the whole
            # score for it would be expensive and pointless.
            score = 0
        else:
            total += score

        clean.append(
            {
                "id": cid,
                "score": score,
                "max": known[cid],
                "verdict": verdict,
                "applicable": verdict != NOT_APPLICABLE,
                "evidence": str(item.get("evidence") or "").strip(),
                "improvement": str(item.get("improvement") or "").strip() or None,
            }
        )

    absent = sorted(set(known) - seen)
    if absent:
        raise ScoreInvalid(
            f"block '{label}': criteria {', '.join(absent)} were not assessed. "
            "Every criterion must be in the answer — including the ones marked "
            "'does not apply' (`verdict: \"na\"`)."
        )
    return clean, total


def _validate_red_flags(
    raw: Any, *, rubric_red_flags: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int, bool]:
    """Returns ``(incidents, total penalty, was the score zeroed)``.

    EVERY incident is kept, so no evidence (timestamp, quote) is lost. The
    penalty is counted once per TYPE: shouting twice is not fined twice.
    """
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ScoreInvalid("`red_flags` must be an array")

    known = {f["type"]: f for f in rubric_red_flags}
    clean: list[dict[str, Any]] = []
    penalty = 0
    zeroed = False
    seen: set[str] = set()

    for item in raw:
        if not isinstance(item, dict):
            raise ScoreInvalid("an element of `red_flags` is not an object")
        flag_type = str(item.get("type") or "").strip()
        spec = known.get(flag_type)
        if spec is None:
            raise ScoreInvalid(
                f"the AI returned an invented red flag: '{flag_type}'. The rubric "
                f"has only these: {', '.join(sorted(known))}. The score was not saved."
            )
        # WARNING: the penalty is NOT taken from the model — it comes from the
        # rubric. Otherwise the model would invent its own penalty and break
        # the score.
        #
        # On repeats: a second breach of the same type is KEPT (the manager
        # needs the time and the quote of both shouts), but the PENALTY is
        # counted ONCE per type. `counted=False` marks an incident that did not
        # affect the score, and `penalty=0` keeps the sum of the array's
        # penalties equal to `penalty_total`.
        counted = flag_type not in seen
        flag_penalty = int(spec.get("penalty", 0)) if counted else 0
        if counted:
            seen.add(flag_type)
            penalty += flag_penalty
            zeroed = zeroed or bool(spec.get("zeroes_score"))

        clean.append(
            {
                "type": flag_type,
                "label": spec.get("label", flag_type),
                "severity": str(item.get("severity") or "high").strip(),
                "timestamp": str(item.get("timestamp") or "").strip() or None,
                "quote": str(item.get("quote") or "").strip(),
                "penalty": flag_penalty,
                "counted": counted,
            }
        )

    return clean, penalty, zeroed


def _validate_confidence(value: Any) -> float:
    """The model's 0..1 confidence. Kept as a float only inside this module."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ScoreInvalid(f"`confidence` is not a number: '{value}'") from exc
    if not 0.0 <= number <= 1.0:
        raise ScoreInvalid(f"`confidence` must be between 0 and 1, got: {number}")
    return round(number, 3)


def _validate_choice(value: Any, allowed: tuple[str, ...], label: str) -> str:
    text = str(value or "").strip().lower()
    if text not in allowed:
        raise ScoreInvalid(
            f"{label} is wrong: '{value}'. Allowed: {', '.join(allowed)}"
        )
    return text


def _validate_outcome(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ScoreInvalid("`outcome_signal` must be an object")
    outcome_type = _validate_choice(
        raw.get("type"), VALID_OUTCOMES, "`outcome_signal.type`"
    )
    products = raw.get("products_mentioned") or []
    if not isinstance(products, list):
        products = []

    quantity = raw.get("quantity_mentioned")
    if isinstance(quantity, bool) or not isinstance(quantity, int | float):
        quantity = None
    else:
        quantity = int(quantity)

    return {
        "type": outcome_type,
        "products_mentioned": [str(p) for p in products][:10],
        "quantity_mentioned": quantity,
        # The model's own confidence in this signal, 0..1. It lands in a JSONB
        # column as the model gave it: §10 forbids a float COLUMN, and this is
        # a field inside a document rather than a column.
        "confidence": _validate_confidence(raw.get("confidence", 0.5)),
        "evidence": str(raw.get("evidence") or "").strip() or None,
    }
