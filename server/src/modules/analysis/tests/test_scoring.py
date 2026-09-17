"""The scoring core: arithmetic, applicability, parsing and known defects.

Pure unit tests — no database, no app, no vendor key (SPEC-ANALYTICS §9.1).
Ported from BonviZvonki's ``scoring/tests/{test_score_arithmetic,
test_applicability, test_response_parsing, test_validator, test_known_defects}``,
which between them are the most valuable test file in the three ported modules:
every case here is behaviour that was measured on real calls, and several are
bugs that reached a score once.

WHY THIS MATTERS: the model can answer "blocks 84, overall 96". If that false
number reaches the database the employee is scored wrongly and nobody notices.
So the validator does not TRUST the model's numbers, it RECOMPUTES them — and
these tests compute the expected value by hand, in the test, so a regression in
the arithmetic cannot hide behind the code that produced it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.modules.analysis.entities import (
    BLOCK_MAX,
    RED_FLAG_PENALTY,
    RedFlagType,
    ScoreBlock,
)
from src.modules.analysis.prompt import build_schema
from src.modules.analysis.rubric_default import DEFAULT_RUBRIC, RUBRIC_VERSION
from src.modules.analysis.score_writer import _blocks_payload
from src.modules.analysis.scorer import CallContext, CallScorer
from src.modules.analysis.tests.stubs import build_payload
from src.modules.analysis.validator import (
    MIN_APPLICABLE_POINTS,
    VALID_OUTCOMES,
    VALID_QUALITY,
    VALID_SENTIMENTS,
    ScoreInvalid,
    _validate_red_flags,
    loads,
    na_budget,
    validate,
)

BLOCKS = DEFAULT_RUBRIC["blocks"]
FLAGS = DEFAULT_RUBRIC["red_flags"]

#: The rubric's own penalties — so a test can add them up by hand.
PENALTY = {f["type"]: int(f["penalty"]) for f in FLAGS}

#: Points that CANNOT be marked ``na`` in the standard rubric.
#: Greeting (5) + conduct (25) + answering the question (10) + a concrete next
#: step (5 + 6) = 51.
MANDATORY_POINTS = sum(
    int(c["points"]) for b in BLOCKS for c in b["criteria"] if not c.get("optional")
)


def _criteria_points() -> dict[str, int]:
    """``{"A1": 5, "A2": 8, ...}`` — every criterion's maximum."""
    return {c["id"]: int(c["points"]) for b in BLOCKS for c in b["criteria"]}


def _answer(
    *,
    scores: dict[str, int] | None = None,
    na: tuple[str, ...] = (),
    red_flags: tuple[str, ...] = (),
    model_penalty: int | None = None,
    block_score_override: dict[str, int] | None = None,
    overall_override: int | None = None,
) -> str:
    """Build a rubric-shaped answer with EXACT per-criterion scores.

    ``stubs.build_payload`` puts random scores in; here every number has to be
    visible in the test, because the expected result is computed by hand.
    Omitted criteria take full marks.
    """
    maxima = _criteria_points()
    blocks: dict[str, Any] = {}
    blocks_total = 0

    for block in BLOCKS:
        items: list[dict[str, Any]] = []
        block_total = 0
        for criterion in block["criteria"]:
            cid = criterion["id"]
            if cid in na:
                items.append(
                    {
                        "id": cid,
                        "score": 0,
                        "verdict": "na",
                        "evidence": (
                            "Mijoz aniq buyurtma berdi — bu bosqich talab qilinmadi"
                        ),
                    }
                )
                continue
            score = (scores or {}).get(cid, maxima[cid])
            block_total += score
            items.append(
                {
                    "id": cid,
                    "score": score,
                    "verdict": "pass",
                    "evidence": f"[00:10] — dalil ({cid})",
                }
            )
        written = (block_score_override or {}).get(block["key"], block_total)
        blocks[block["key"]] = {"score": written, "criteria": items}
        blocks_total += written

    penalty = 0
    zeroed = False
    flag_items: list[dict[str, Any]] = []
    for flag_type in red_flags:
        penalty += PENALTY[flag_type]
        zeroed = zeroed or flag_type == "profanity"
        item: dict[str, Any] = {
            "type": flag_type,
            "severity": "high",
            "timestamp": "07:42",
            "quote": "iqtibos",
        }
        if model_penalty is not None:
            # The model invented its own penalty — the validator must ignore it
            item["penalty"] = model_penalty
        flag_items.append(item)

    overall = 0 if zeroed else max(0, min(100, blocks_total + penalty))

    return json.dumps(
        {
            "language_detected": "uz",
            "transcript_quality": "high",
            "blocks": blocks,
            "red_flags": flag_items,
            "outcome_signal": {
                "type": "follow_up",
                "products_mentioned": ["X-200"],
                "quantity_mentioned": 50,
                "confidence": 0.7,
                "evidence": "[00:58] — «ertaga aytaman»",
            },
            "client_sentiment": "neutral",
            "coaching_note": "E'tiroz bilan ishlashni kuchaytiring.",
            "confidence": 0.9,
            "call_scenario": "repeat_order" if na else "new_client",
            "overall_score": overall if overall_override is None else overall_override,
        },
        ensure_ascii=False,
    )


def _check(raw: str):
    return validate(raw, rubric_blocks=BLOCKS, rubric_red_flags=FLAGS)


def _dump(**kwargs) -> str:
    return json.dumps(build_payload(BLOCKS, FLAGS, **kwargs), ensure_ascii=False)


# ==========================================================================
#  0. The rubric itself
# ==========================================================================


def test_the_rubric_blocks_total_exactly_one_hundred() -> None:
    """The one invariant the rubric has, and phase 1 has no screen enforcing it.

    BonviZvonki checked this in ``RubricService._validate`` when an admin saved
    a rubric. That service is phase 2 (§1.4), so while the rubric is a constant
    the check lives here — otherwise a one-line edit could make every score in
    the product incomparable with every score before it, silently.
    """
    assert sum(int(b["max"]) for b in BLOCKS) == 100


def test_every_block_max_equals_the_sum_of_its_criteria() -> None:
    """A block whose criteria do not add up to its maximum cannot be scored 100."""
    for block in BLOCKS:
        criteria_total = sum(int(c["points"]) for c in block["criteria"])
        assert criteria_total == int(block["max"]), block["key"]


def test_block_max_is_derived_from_the_rubric() -> None:
    """Written in two places these diverged 25 vs 15 and drew a 167 % bar."""
    rubric_max = {block["key"]: int(block["max"]) for block in BLOCKS}
    code_max = {block.value: value for block, value in BLOCK_MAX.items()}

    assert code_max == rubric_max
    assert sum(BLOCK_MAX.values()) == 100


def test_block_keys_and_the_rubric_agree() -> None:
    assert {b["key"] for b in BLOCKS} == {b.value for b in ScoreBlock}


def test_red_flag_types_and_penalties_agree_with_the_rubric() -> None:
    """The validator reads the rubric; ``RED_FLAG_PENALTY`` must not drift."""
    assert {f["type"] for f in FLAGS} == {f.value for f in RedFlagType}
    assert {f.value: v for f, v in RED_FLAG_PENALTY.items()} == PENALTY


def test_the_rubric_version_is_pinned() -> None:
    """Every score carries it, so a rubric edit must bump it (§2.5)."""
    assert RUBRIC_VERSION == "v1"


def test_mandatory_criteria_stay_above_the_applicable_floor() -> None:
    """All optional criteria dropped still leaves 51, above the floor of 40.

    Normal work never reaches ``MIN_APPLICABLE_POINTS``. Reaching it means the
    rubric has been all but switched off, which is a malfunction, not an answer.
    """
    assert MANDATORY_POINTS == 51
    assert MANDATORY_POINTS > MIN_APPLICABLE_POINTS


# ==========================================================================
#  1. Criterion -> block -> overall
# ==========================================================================


def test_criterion_scores_add_up_to_the_block_and_the_overall() -> None:
    """Every number counted by hand: A=15, B=17, C=16, D=13 -> 61."""
    points = {
        "A1": 5, "A2": 4, "A3": 3, "A4": 3,   # script        = 15
        "B1": 8, "B2": 5, "B3": 2, "B4": 2,   # communication = 17
        "C1": 6, "C2": 5, "C3": 5,            # resolution    = 16
        "D1": 4, "D2": 3, "D3": 3, "D4": 3,   # sales_skill   = 13
    }

    draft = _check(_answer(scores=points))

    assert draft.block_scores == {
        "script": 15,
        "communication": 17,
        "resolution": 16,
        "sales_skill": 13,
    }
    assert draft.blocks_total == 61
    assert draft.overall == 61


def test_the_block_score_is_computed_from_its_criteria() -> None:
    """The model wrote "20" for a block whose criteria add to 15 — 15 wins.

    An answer like this USED TO BE REJECTED. Once ``na`` existed the model began
    inflating the block total to "fill up" the maximum after a dropped
    criterion, and answers were being destroyed. The total is a computed value;
    the model's claim is recorded as a warning and does not touch the score.
    """
    points = dict.fromkeys(_criteria_points(), 0) | {
        "A1": 5, "A2": 4, "A3": 3, "A4": 3
    }

    draft = _check(_answer(scores=points, block_score_override={"script": 20}))

    assert draft.blocks["script"]["raw_score"] == 15
    assert draft.overall == 15
    assert draft.warnings


def test_the_overall_score_written_by_the_model_is_ignored() -> None:
    """The model wrote 96, the blocks add to 61 — the answer is 61.

    ``overall_score`` is no longer asked for at all: the calculation contains a
    division (a percentage within the applied criteria), and demanding it from
    the model meant a rejected answer and a second request — twice the money.
    """
    points = {
        "A1": 5, "A2": 4, "A3": 3, "A4": 3,
        "B1": 8, "B2": 5, "B3": 2, "B4": 2,
        "C1": 6, "C2": 5, "C3": 5,
        "D1": 4, "D2": 3, "D3": 3, "D4": 3,
    }

    draft = _check(_answer(scores=points, overall_override=96))

    assert draft.overall == 61


def test_all_zero_criteria_still_produce_a_full_chain() -> None:
    """Zeros are counted — they must not be confused with "no criteria given"."""
    draft = _check(_answer(scores=dict.fromkeys(_criteria_points(), 0)))

    assert draft.blocks_total == 0
    assert draft.overall == 0
    assert draft.zeroed is False  # a zero score is not a red-flag zeroing


def test_a_valid_answer_from_the_stub_passes() -> None:
    draft = validate(_dump(seed=1), rubric_blocks=BLOCKS, rubric_red_flags=FLAGS)

    assert draft.overall == draft.blocks_total
    assert set(draft.block_scores) == {b["key"] for b in BLOCKS}


# ==========================================================================
#  2. The bounds: 0 and 100
# ==========================================================================


def test_a_perfect_call_scores_exactly_one_hundred() -> None:
    draft = _check(_answer())

    assert draft.blocks_total == 100
    assert draft.overall == 100


def test_combined_penalties_never_drive_the_score_negative() -> None:
    """-25 -20 -15 -15 -10 = -85 against blocks of 61 -> 61-85 = -24 -> 0."""
    points = {
        "A1": 5, "A2": 4, "A3": 3, "A4": 3,
        "B1": 8, "B2": 5, "B3": 2, "B4": 2,
        "C1": 6, "C2": 5, "C3": 5,
        "D1": 4, "D2": 3, "D3": 3, "D4": 3,
    }
    flags = (
        "off_policy_deal",
        "shouting",
        "unrealistic_promise",
        "badmouthing",
        "ignored_complaint",
    )

    draft = _check(_answer(scores=points, red_flags=flags))

    assert draft.penalty_total == -85
    assert draft.blocks_total == 61
    assert draft.overall == 0  # not -24
    assert draft.overall >= 0


def test_a_penalty_on_a_perfect_score_is_subtracted() -> None:
    """100 - 20 = 80. The ceiling applies, but it does not swallow the penalty."""
    draft = _check(_answer(red_flags=("shouting",)))

    assert draft.blocks_total == 100
    assert draft.penalty_total == -20
    assert draft.overall == 80


def test_profanity_zeroes_the_whole_score() -> None:
    """``zeroes_score`` is not a subtraction — it is a direct zero."""
    draft = _check(_answer(red_flags=("profanity",)))

    assert draft.zeroed is True
    assert draft.overall == 0
    assert draft.red_flags[0]["penalty"] == -100


def test_half_a_point_rounds_up_in_the_employees_favour() -> None:
    """25 x 5/10 = 12.5 -> 13, never Python's banker's 12.

    The rubric resolves doubt in the employee's favour and the arithmetic has
    to point the same way, or "why 12, I make it 12.5" has no answer.
    """
    draft = _check(_answer(na=("A2", "A3"), scores={"A1": 5, "A4": 0}))

    assert draft.blocks["script"]["applicable_max"] == 10
    assert draft.blocks["script"]["raw_score"] == 5
    assert draft.block_scores["script"] == 13


# ==========================================================================
#  3. The penalty comes from the RUBRIC
# ==========================================================================


def test_a_penalty_invented_by_the_model_is_ignored() -> None:
    """The model wrote -1; the rubric's -20 applies.

    Otherwise the model could invent a convenient penalty and lift the score.
    """
    draft = _check(_answer(red_flags=("shouting",), model_penalty=-1))

    assert draft.red_flags[0]["penalty"] == PENALTY["shouting"] == -20
    assert draft.penalty_total == -20
    assert draft.overall == 80  # 100 - 20, NOT the model's 100 - 1 = 99


def test_an_excessive_penalty_from_the_model_loses_to_the_rubric() -> None:
    """The other direction: the model wrote -999, the answer is still -10."""
    draft = _check(
        _answer(red_flags=("ignored_complaint",), model_penalty=-999)
    )

    assert draft.penalty_total == -10
    assert draft.overall == 90


def test_several_penalties_sum_the_rubrics_values() -> None:
    draft = _check(
        _answer(red_flags=("off_policy_deal", "ignored_complaint"), model_penalty=0)
    )

    assert [f["penalty"] for f in draft.red_flags] == [-25, -10]
    assert draft.penalty_total == (
        PENALTY["off_policy_deal"] + PENALTY["ignored_complaint"]
    )
    assert draft.overall == 65


def test_the_flag_label_comes_from_the_rubric_too() -> None:
    """The manager sees the rubric's label, not the model's wording."""
    draft = _check(_answer(red_flags=("badmouthing",)))

    expected = next(f for f in FLAGS if f["type"] == "badmouthing")["label"]
    assert draft.red_flags[0]["label"] == expected


# ==========================================================================
#  4. `na` — a short repeat order is scored fairly
# ==========================================================================


def test_a_short_reorder_call_is_not_punished() -> None:
    """THE HEADLINE GUARANTEE — the whole point of the change.

    A returning customer said "send me 50", the employee took it politely and
    named the date. Requirement gathering, product presentation, objection
    handling, upsell and the value argument were none of them called for.

    This call USED TO SCORE 51 out of 100 (34 points written off as "not done").
    Now it is 100, because everything that applied was done.
    """
    dropped = ("A2", "A3", "C2", "C3", "D1", "D2", "D4")

    draft = _check(_answer(na=dropped))

    assert draft.overall == 100
    assert draft.na_criteria == list(dropped)
    assert draft.applicable_points == MANDATORY_POINTS == 51


def test_an_inapplicable_criterion_does_not_score_zero_either() -> None:
    """``na`` means "not counted", NOT "zero".

    The difference shows in the block figure: drop A2 (8) and A3 (7) from
    "Script" and 10 points remain. An employee who earned all 10 shows 25/25,
    not 10/25.
    """
    draft = _check(_answer(na=("A2", "A3")))

    assert draft.blocks["script"]["applicable_max"] == 10
    assert draft.blocks["script"]["raw_score"] == 10
    assert draft.block_scores["script"] == 25


def test_a_mandatory_criterion_cannot_be_dropped() -> None:
    """The greeting is assessed in every conversation.

    Otherwise the model could take any criterion out of the count and a low
    score would never appear at all.
    """
    with pytest.raises(ScoreInvalid) as exc:
        _check(_answer(na=("A1",)))

    assert "A1" in exc.value.message
    assert "any conversation" in exc.value.message.lower()


def test_a_score_written_on_an_na_criterion_is_ignored_not_rejected() -> None:
    """``na`` plus a score is a self-contradictory answer — but it is KEPT.

    Such a criterion does not enter the arithmetic, so whatever the model wrote
    there is immaterial. Throwing the whole score away over it would mean a
    second request and a second payment for nothing.
    """
    payload = json.loads(_answer(na=("A2",)))
    for item in payload["blocks"]["script"]["criteria"]:
        if item["id"] == "A2":
            item["score"] = 8

    draft = _check(json.dumps(payload, ensure_ascii=False))

    a2 = next(c for c in draft.blocks["script"]["criteria"] if c["id"] == "A2")
    assert a2["score"] == 0
    assert a2["applicable"] is False
    assert draft.blocks["script"]["applicable_max"] == 17  # 25 - 8


def test_a_block_total_inflated_by_na_points_changes_nothing() -> None:
    clean = _check(_answer(na=("A2",)))
    payload = json.loads(_answer(na=("A2",)))
    payload["blocks"]["script"]["score"] += 8

    draft = _check(json.dumps(payload, ensure_ascii=False))

    assert draft.overall == clean.overall
    assert draft.warnings


def test_a_wholly_inapplicable_block_is_not_shown() -> None:
    """``applicable_max = 0`` keeps a block out of the cut entirely.

    Drawing it as 0 would make the employee look at fault; drawing it at its
    maximum would award points for work nobody checked. (In the standard rubric
    D3 is mandatory, so this cannot happen — the mechanism still has to work.)
    """
    blocks = [
        {
            "key": "script",
            "label": "Skript",
            "max": 50,
            "criteria": [
                {"id": "A1", "label": "Salom", "points": 50, "optional": False}
            ],
        },
        {
            "key": "sales_skill",
            "label": "Savdo",
            "max": 50,
            "criteria": [
                {"id": "D1", "label": "Upsell", "points": 50, "optional": True}
            ],
        },
    ]
    payload = {
        "language_detected": "uz",
        "transcript_quality": "high",
        "blocks": {
            "script": {
                "score": 40,
                "criteria": [
                    {
                        "id": "A1",
                        "score": 40,
                        "verdict": "partial",
                        "evidence": "[00:01] salom",
                    }
                ],
            },
            "sales_skill": {
                "score": 0,
                "criteria": [
                    {
                        "id": "D1",
                        "score": 0,
                        "verdict": "na",
                        "evidence": "Mijoz o'zi buyurtma berdi",
                    }
                ],
            },
        },
        "red_flags": [],
        "outcome_signal": {"type": "order_agreed", "confidence": 0.9},
        "client_sentiment": "positive",
        "coaching_note": "Yaxshi.",
        "confidence": 0.9,
        "call_scenario": "repeat_order",
    }

    draft = validate(
        json.dumps(payload, ensure_ascii=False),
        rubric_blocks=blocks,
        rubric_red_flags=FLAGS,
    )

    assert "sales_skill" not in draft.block_scores, "it must stay out of the cut"
    assert draft.applicable_max == 50, "only the applied block's maximum"
    assert draft.overall == 80, "40/50 -> 80"


def test_a_penalty_lands_on_top_of_the_normalised_score() -> None:
    """Shouting is -20 — a short call feels the full penalty too."""
    payload = json.loads(_answer(na=("A2", "A3", "C2", "C3", "D1", "D2", "D4")))
    payload["red_flags"] = [
        {
            "type": "shouting",
            "severity": "high",
            "timestamp": "01:12",
            "quote": "NEGA HALIGACHA YUBORMADINGIZ",
        }
    ]

    draft = _check(json.dumps(payload, ensure_ascii=False))

    assert draft.penalty_total == -20
    assert draft.overall == 80


def test_a_rubric_without_optional_flags_rejects_na_entirely() -> None:
    """A guard: skip the upgrade and the system scores the OLD, strict way.

    "Lenient" mode cannot switch itself on by accident.
    """
    old = [
        {
            **b,
            "criteria": [
                {k: v for k, v in c.items() if k != "optional"} for c in b["criteria"]
            ],
        }
        for b in BLOCKS
    ]

    with pytest.raises(ScoreInvalid):
        validate(_answer(na=("A2",)), rubric_blocks=old, rubric_red_flags=FLAGS)


def test_criteria_are_accepted_as_an_object_as_well_as_a_list() -> None:
    """The schema demands the object shape: ``{"A1": {...}, ...}``.

    The shape was changed deliberately. As a list there was one shared ceiling,
    and the model redistributed a dropped criterion's points to the rest (15 on
    A4 instead of 5). As an object each key carries its own schema and that
    answer is structurally impossible. The list shape is still accepted, because
    a provider without schema support may send one.
    """
    as_list = json.loads(_answer(na=("A2", "A3")))
    as_object = json.loads(_answer(na=("A2", "A3")))
    for block in as_object["blocks"].values():
        block["criteria"] = {item.pop("id"): item for item in block["criteria"]}
        # The schema has no block score at all — it is computed
        block.pop("score")

    a = _check(json.dumps(as_list, ensure_ascii=False))
    b = _check(json.dumps(as_object, ensure_ascii=False))

    assert a.overall == b.overall
    assert a.na_criteria == b.na_criteria
    assert a.block_scores == b.block_scores


def test_the_schema_gives_every_criterion_its_own_ceiling() -> None:
    """The schema is the first barrier, the validator the last."""
    schema = build_schema(BLOCKS, FLAGS)
    script = schema["properties"]["blocks"]["properties"]["script"]
    criteria = script["properties"]["criteria"]["properties"]

    assert criteria["A1"]["properties"]["score"]["maximum"] == 5
    assert criteria["A2"]["properties"]["score"]["maximum"] == 8
    # `na` only on an optional criterion — the schema itself blocks the rest
    assert "na" not in criteria["A1"]["properties"]["verdict"]["enum"]
    assert "na" in criteria["A2"]["properties"]["verdict"]["enum"]
    # Every criterion is required: the model cannot leave one out
    assert set(script["properties"]["criteria"]["required"]) == set(criteria)


# ==========================================================================
#  5. The `na` budget — no wholesale dropping in a long conversation
# ==========================================================================


def test_a_short_call_is_not_constrained_by_the_budget() -> None:
    """35 seconds of "send me 50" — there was no TIME for the stages."""
    draft = validate(
        _answer(na=("A2", "A3", "C2", "C3", "D1", "D2", "D4")),
        rubric_blocks=BLOCKS,
        rubric_red_flags=FLAGS,
        duration_sec=35,
    )

    assert draft.overall == 100


def test_wholesale_na_in_a_long_call_is_rejected() -> None:
    """THE MIRROR OF THE FIRST PROBLEM.

    Measured: left without a ceiling the model marked seven criteria "does not
    apply" even in a ten-minute conversation and gave 8 of 12 calls a flat 100.
    Before, everything scored unjustifiably low; now it scored unjustifiably
    high — either one makes the tool useless.
    """
    with pytest.raises(ScoreInvalid) as exc:
        validate(
            _answer(na=("A2", "A3", "C2", "C3", "D1", "D2", "D4")),
            rubric_blocks=BLOCKS,
            rubric_red_flags=FLAGS,
            duration_sec=600,
        )

    assert "minutes" in exc.value.message
    assert "`fail`" in exc.value.message


def test_a_little_na_in_a_long_call_is_still_accepted() -> None:
    """The budget does not ban ``na`` — the reasonable ones survive.

    Upsell (6) and the value argument (5) can be beside the point in a long
    call too: a customer ringing with a complaint, for instance.
    """
    draft = validate(
        _answer(na=("D2", "D4")),
        rubric_blocks=BLOCKS,
        rubric_red_flags=FLAGS,
        duration_sec=600,
    )

    assert draft.na_criteria == ["D2", "D4"]
    assert draft.applicable_points == 100 - 11


def test_the_budget_falls_as_the_call_gets_longer() -> None:
    assert na_budget(30) > na_budget(150) > na_budget(600)


def test_the_last_attempt_applies_the_budget_by_hand() -> None:
    """The score is NOT LOST, but excessive ``na`` does not get through either.

    Going over budget rejects the answer and the model is asked again — correct,
    and it usually helps (measured: on the second attempt the scores fell into
    the 58-92 range). Once the attempts are exhausted, rejecting would leave the
    call unscored and waste the money paid three times. So the budget is applied
    by hand: the cheapest ``na`` marks are kept, the rest count as not done, and
    the score goes into the review queue.
    """
    draft = validate(
        _answer(na=("A2", "A3", "C2", "C3", "D1", "D2", "D4")),
        rubric_blocks=BLOCKS,
        rubric_red_flags=FLAGS,
        duration_sec=600,
        enforce_na_budget=False,
    )

    assert draft.na_over_budget is True
    assert draft.warnings
    # Budget 20: A3 (7) + D2 (6) + D4 (5) = 18 fits; the rest were restored
    assert set(draft.na_criteria) == {"A3", "D2", "D4"}
    assert draft.applicable_points == 100 - 18
    # No longer 100 — the restored criteria scored zero
    assert draft.overall < 100


def test_inside_the_budget_no_flag_is_raised() -> None:
    draft = validate(
        _answer(na=("D2", "D4")),
        rubric_blocks=BLOCKS,
        rubric_red_flags=FLAGS,
        duration_sec=600,
        enforce_na_budget=False,
    )

    assert draft.na_over_budget is False


def test_marking_everything_inapplicable_is_refused() -> None:
    """The floor that closes the "``na`` everything" road.

    The rubric's optional criteria alone cannot reach it, so this is built from
    a rubric where they can — the guard has to hold for phase 2's editable
    rubrics as well.
    """
    blocks = [
        {
            "key": "script",
            "label": "Skript",
            "max": 100,
            "criteria": [
                {"id": "A1", "label": "Salom", "points": 70, "optional": True},
                {"id": "A2", "label": "Ehtiyoj", "points": 30, "optional": False},
            ],
        }
    ]
    payload = {
        "language_detected": "uz",
        "transcript_quality": "high",
        "blocks": {
            "script": {
                "criteria": [
                    {
                        "id": "A1",
                        "score": 0,
                        "verdict": "na",
                        "evidence": "talab qilinmadi",
                    },
                    {
                        "id": "A2",
                        "score": 30,
                        "verdict": "pass",
                        "evidence": "[00:03] dalil",
                    },
                ]
            }
        },
        "red_flags": [],
        "outcome_signal": {"type": "order_agreed", "confidence": 0.9},
        "client_sentiment": "positive",
        "coaching_note": "Yaxshi.",
        "confidence": 0.9,
        "call_scenario": "repeat_order",
    }

    with pytest.raises(ScoreInvalid) as exc:
        validate(
            json.dumps(payload, ensure_ascii=False),
            rubric_blocks=blocks,
            rubric_red_flags=FLAGS,
        )

    assert str(MIN_APPLICABLE_POINTS) in exc.value.message


# ==========================================================================
#  6. Reading the answer: fences, prose, and the enumerated values
# ==========================================================================


def test_a_json_fence_is_unwrapped() -> None:
    body = json.dumps({"overall_score": 61}, ensure_ascii=False)

    assert loads(f"```json\n{body}\n```") == {"overall_score": 61}


def test_a_fence_without_a_language_is_unwrapped_too() -> None:
    """Some models omit the word ``json`` — it has to behave the same."""
    assert loads('```\n{"a": 1}\n```') == {"a": 1}


def test_whitespace_around_the_fence_does_not_matter() -> None:
    assert loads('  \n ```json  \n {"a": 1} \n``` \n ') == {"a": 1}


def test_a_full_fenced_answer_passes_validation() -> None:
    """Not only ``loads``: the whole chain has to survive the wrapper."""
    body = _dump(seed=42)

    draft = _check(f"```json\n{body}\n```")

    assert draft.overall == draft.blocks_total


def test_a_sentence_before_the_json_is_forgiven() -> None:
    """"Here is the result:" — last resort: first ``{`` to last ``}``."""
    body = json.dumps({"overall_score": 61}, ensure_ascii=False)

    assert loads(f"Mana natija:\n{body}\nUmid qilamanki foydali bo'ldi.") == {
        "overall_score": 61
    }


def test_an_empty_answer_is_rejected_with_a_reason() -> None:
    with pytest.raises(ScoreInvalid) as exc:
        loads("   \n  ")

    assert "empty answer" in exc.value.message


def test_a_json_array_is_rejected() -> None:
    """Valid JSON, but not an object — where would the blocks come from?"""
    with pytest.raises(ScoreInvalid) as exc:
        loads("[1, 2, 3]")

    assert "object" in exc.value.message


def test_unclosed_json_is_rejected() -> None:
    with pytest.raises(ScoreInvalid):
        loads('```json\n{"blocks": {\n```')


def test_prose_instead_of_json_is_rejected() -> None:
    with pytest.raises(ScoreInvalid) as exc:
        validate(
            "mana sizga baho: yaxshi", rubric_blocks=BLOCKS, rubric_red_flags=FLAGS
        )

    assert "JSON" in exc.value.message


def _payload(**overrides) -> dict:
    data = build_payload(BLOCKS, FLAGS, seed=42)
    data.update(overrides)
    return data


def _check_payload(data: dict):
    return _check(json.dumps(data, ensure_ascii=False))


def test_an_unknown_sentiment_is_rejected() -> None:
    with pytest.raises(ScoreInvalid) as exc:
        _check_payload(_payload(client_sentiment="очень позитивный"))

    assert "client_sentiment" in exc.value.message
    # The message names what was allowed, so an admin knows what was expected
    assert "positive" in exc.value.message


@pytest.mark.parametrize("value", VALID_SENTIMENTS)
def test_every_listed_sentiment_is_accepted(value: str) -> None:
    assert _check_payload(_payload(client_sentiment=value)).sentiment == value


def test_sentiment_tolerates_case_and_whitespace() -> None:
    """"  NEGATIVE " — the meaning is right, the shape is immaterial."""
    assert _check_payload(_payload(client_sentiment="  NEGATIVE ")).sentiment == (
        "negative"
    )


def test_an_unknown_outcome_is_rejected() -> None:
    with pytest.raises(ScoreInvalid) as exc:
        _check_payload(_payload(outcome_signal={"type": "sotildi", "confidence": 0.5}))

    assert "outcome_signal.type" in exc.value.message


@pytest.mark.parametrize("value", VALID_OUTCOMES)
def test_every_listed_outcome_is_accepted(value: str) -> None:
    draft = _check_payload(_payload(outcome_signal={"type": value, "confidence": 0.5}))

    assert draft.outcome_signal["type"] == value


def test_an_outcome_that_is_not_an_object_is_rejected() -> None:
    with pytest.raises(ScoreInvalid) as exc:
        _check_payload(_payload(outcome_signal="follow_up"))

    assert "outcome_signal" in exc.value.message


def test_an_unknown_transcript_quality_is_rejected() -> None:
    with pytest.raises(ScoreInvalid) as exc:
        _check_payload(_payload(transcript_quality="o'rtacha"))

    assert "transcript_quality" in exc.value.message


@pytest.mark.parametrize("value", VALID_QUALITY)
def test_every_listed_quality_is_accepted(value: str) -> None:
    assert _check_payload(_payload(transcript_quality=value)).transcript_quality == value


def test_a_missing_sentiment_is_rejected_rather_than_assumed() -> None:
    """Absent means absent — "neutral" is not guessed on the model's behalf."""
    data = _payload()
    data.pop("client_sentiment")

    with pytest.raises(ScoreInvalid):
        _check_payload(data)


def test_an_unknown_language_becomes_other_rather_than_a_rejection() -> None:
    """Language does not affect correctness — only statistics.

    Losing a whole paid-for score over a label would be senseless.
    """
    assert _check_payload(_payload(language_detected="tj")).language_detected == "other"
    assert _check_payload(_payload(language_detected="")).language_detected == "mixed"


def test_confidence_is_stored_as_an_integer_percent() -> None:
    """The column is a SMALLINT and the threshold is compared in three languages."""
    draft = _check_payload(_payload(confidence=0.915))

    assert draft.confidence_pct == 92
    assert isinstance(draft.confidence_pct, int)


def test_confidence_out_of_range_is_rejected() -> None:
    with pytest.raises(ScoreInvalid):
        _check_payload(_payload(confidence=4.2))


def test_a_missing_coaching_note_is_rejected() -> None:
    """A score with no advice for the employee is useless to a coach."""
    with pytest.raises(ScoreInvalid) as exc:
        _check_payload(_payload(coaching_note="   "))

    assert "coaching_note" in exc.value.message


# ==========================================================================
#  7. Invented keys are refused
# ==========================================================================


def test_an_invented_red_flag_is_rejected() -> None:
    with pytest.raises(ScoreInvalid) as exc:
        validate(
            _dump(seed=4, invented_flag="rude_tone"),
            rubric_blocks=BLOCKS,
            rubric_red_flags=FLAGS,
        )

    assert "rude_tone" in exc.value.message


def test_an_unknown_block_is_rejected() -> None:
    payload = build_payload(BLOCKS, FLAGS, seed=5)
    payload["blocks"]["teamwork"] = {"score": 5, "criteria": []}

    with pytest.raises(ScoreInvalid):
        _check_payload(payload)


def test_a_missing_block_is_rejected() -> None:
    payload = build_payload(BLOCKS, FLAGS, seed=5)
    payload["blocks"].pop("resolution")

    with pytest.raises(ScoreInvalid) as exc:
        _check_payload(payload)

    assert "resolution" in exc.value.message


def test_an_unknown_criterion_is_rejected() -> None:
    payload = build_payload(BLOCKS, FLAGS, seed=6)
    payload["blocks"]["script"]["criteria"][0]["id"] = "A9"

    with pytest.raises(ScoreInvalid) as exc:
        _check_payload(payload)

    assert "A9" in exc.value.message


def test_a_missing_criterion_is_rejected() -> None:
    """``na`` is an answer; leaving the criterion out is not."""
    payload = build_payload(BLOCKS, FLAGS, seed=6)
    payload["blocks"]["script"]["criteria"].pop()

    with pytest.raises(ScoreInvalid) as exc:
        _check_payload(payload)

    assert "A4" in exc.value.message


def test_a_criterion_returned_twice_is_rejected() -> None:
    payload = build_payload(BLOCKS, FLAGS, seed=6)
    payload["blocks"]["script"]["criteria"].append(
        dict(payload["blocks"]["script"]["criteria"][0])
    )

    with pytest.raises(ScoreInvalid) as exc:
        _check_payload(payload)

    assert "twice" in exc.value.message


def test_a_score_above_the_criterions_maximum_is_rejected() -> None:
    """THIS CEILING SURVIVED.

    The block total is no longer checked, but each CRITERION's ceiling is: that
    is exactly where the model tries to redistribute a dropped criterion's
    points (15 on A4 instead of 5). The schema blocks it; the validator is the
    last barrier.
    """
    payload = build_payload(BLOCKS, FLAGS, seed=8)
    payload["blocks"]["script"]["criteria"][3]["score"] = 15

    with pytest.raises(ScoreInvalid) as exc:
        _check_payload(payload)

    assert "allowed range" in exc.value.message


def test_a_block_score_the_model_inflated_does_not_raise_the_result() -> None:
    payload = build_payload(BLOCKS, FLAGS, seed=7)
    clean = _check_payload(payload)
    payload["blocks"]["script"]["score"] = 99

    draft = _check_payload(payload)

    assert draft.overall == clean.overall


# ==========================================================================
#  8. Known defects — each one reached a real score once
# ==========================================================================


def test_two_breaches_of_the_same_type_are_both_kept() -> None:
    """Shouted twice in one call — the manager must see both.

    The second incident used to be dropped silently, which took the evidence
    with it.
    """
    raw = [
        {
            "type": "shouting",
            "severity": "high",
            "timestamp": "02:15",
            "quote": "Nega tushunmayapsiz?!",
        },
        {
            "type": "shouting",
            "severity": "high",
            "timestamp": "07:42",
            "quote": "Menga baqirmang dedim!",
        },
    ]

    clean, penalty, zeroed = _validate_red_flags(raw, rubric_red_flags=FLAGS)

    assert len(clean) == 2
    assert [f["timestamp"] for f in clean] == ["02:15", "07:42"]
    assert [f["quote"] for f in clean] == [
        "Nega tushunmayapsiz?!",
        "Menga baqirmang dedim!",
    ]
    # The penalty is counted once — double-fining is deliberately not done
    assert penalty == -20
    assert zeroed is False
    assert [f["counted"] for f in clean] == [True, False]
    # The array's own penalties must add up to `penalty_total`, or the call page
    # and the score would tell a manager two different stories
    assert sum(f["penalty"] for f in clean) == penalty


def test_different_breach_types_each_carry_their_own_penalty() -> None:
    raw = [
        {"type": "shouting", "timestamp": "02:15", "quote": "a"},
        {"type": "badmouthing", "timestamp": "05:01", "quote": "b"},
    ]

    clean, penalty, _ = _validate_red_flags(raw, rubric_red_flags=FLAGS)

    assert [f["type"] for f in clean] == ["shouting", "badmouthing"]
    assert penalty == -35


def _draft():
    return _check(_dump(seed=11))


def test_the_written_blocks_survive_the_analytics_float_cast() -> None:
    """Every written value has to be a FLAT number.

    ``block_breakdown`` runs exactly this loop BEFORE filtering, so any stray
    key in ``blocks`` (an old ``_meta``, for instance) would arrive here and
    500 the cut.
    """
    payload = _blocks_payload(_draft())

    totals: dict[str, list[float]] = {}
    for key, value in payload.items():
        totals.setdefault(key, []).append(float(value))

    assert totals["script"][0] == float(_draft().block_scores["script"])


def test_the_written_blocks_cover_every_rubric_key() -> None:
    payload = _blocks_payload(_draft())

    assert {b["key"] for b in BLOCKS} <= set(payload)
    assert all(isinstance(v, int) for v in payload.values())
    assert "_meta" not in payload


# ==========================================================================
#  9. The scorer's retry loop
# ==========================================================================


class _ScriptedLLM:
    """Returns the prepared answers in order, then repeats the last one."""

    model = "stub-llm"
    provider_key = "stub"

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.prompts: list[str] = []

    async def complete(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 4096,
    ) -> str:
        self.calls += 1
        self.prompts.append(user)
        return self._responses[min(self.calls - 1, len(self._responses) - 1)]

    async def ping(self) -> str:
        return "ok"


def _scorer(llm: _ScriptedLLM, *, invalid_retries: int = 1) -> CallScorer:
    return CallScorer(
        llm,
        rubric_blocks=BLOCKS,
        rubric_red_flags=FLAGS,
        invalid_retries=invalid_retries,
    )


def _context(**overrides) -> CallContext:
    base = {
        "transcript": "[00:02] Sotuvchi: Assalomu alaykum.",
        "duration_sec": 45,
        "direction": "outbound",
        "started_at": "2026-09-17 10:00",
    }
    return CallContext(**(base | overrides))


@pytest.mark.asyncio
async def test_a_valid_first_answer_costs_one_call() -> None:
    llm = _ScriptedLLM(_dump(seed=3))

    outcome = await _scorer(llm).score(_context())

    assert llm.calls == 1
    assert outcome.llm_calls == 1
    assert outcome.attempts == 1
    assert outcome.draft.overall == outcome.draft.blocks_total


@pytest.mark.asyncio
async def test_an_invalid_answer_is_retried_with_the_reason_attached() -> None:
    """The model is told what was wrong; otherwise it repeats the same mistake."""
    llm = _ScriptedLLM("not json at all", _dump(seed=3))

    outcome = await _scorer(llm).score(_context())

    assert llm.calls == 2
    assert outcome.llm_calls == 2
    assert outcome.attempts == 2
    assert "RAD ETILDI" in llm.prompts[1]


@pytest.mark.asyncio
async def test_the_retries_are_bounded_and_the_last_error_is_raised() -> None:
    """Three paid requests is the ceiling — the money is not spent forever."""
    llm = _ScriptedLLM("not json at all")

    with pytest.raises(ScoreInvalid):
        await _scorer(llm, invalid_retries=2).score(_context())

    assert llm.calls == 3


@pytest.mark.asyncio
async def test_the_last_attempt_keeps_the_score_and_flags_it_instead() -> None:
    """The paid-for answer is not thrown away — it goes to a person.

    Over-budget ``na`` rejects an ordinary attempt. On the LAST attempt
    rejecting would leave the call unscored and waste everything paid so far,
    so the score is accepted with ``na_over_budget`` set.
    """
    over_budget = _answer(na=("A2", "A3", "C2", "C3", "D1", "D2", "D4"))
    llm = _ScriptedLLM(over_budget)

    outcome = await _scorer(llm, invalid_retries=1).score(
        _context(duration_sec=600)
    )

    assert llm.calls == 2, "the first, enforcing attempt was rejected"
    assert outcome.draft.na_over_budget is True
    assert outcome.draft.overall < 100


@pytest.mark.asyncio
async def test_the_prompt_carries_the_budget_the_validator_will_enforce() -> None:
    """One source for the limit, or the model is checked against another number."""
    llm = _ScriptedLLM(_dump(seed=3))

    await _scorer(llm).score(_context(duration_sec=600))

    assert f"`na` CHEGARASI: {na_budget(600)} ball" in llm.prompts[0]


def test_the_system_prompt_does_not_depend_on_the_call() -> None:
    """Byte-stable, or prompt caching never hits and the rubric is paid for
    on every single call."""
    first = _scorer(_ScriptedLLM("")).system_prompt
    second = _scorer(_ScriptedLLM("")).system_prompt

    assert first == second
    assert "2026" not in first, "no date, no call id, nothing per-call"
