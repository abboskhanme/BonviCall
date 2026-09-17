"""The rubric table: validation, versioning, and the fallback (§2.5).

The claims this file is responsible for:

* **the blocks total exactly 100, or the rubric is refused and not saved** —
  the one rule BonviZvonki's ``RubricService`` had, and the reason it had it: a
  score is a percentage of a maximum, so a maximum nobody checked makes two
  scores incomparable while they claim to be comparable;
* **publishing leaves the previous version exactly as it was**, so
  ``call_scores.rubric_version`` keeps meaning what it says;
* **a scored call still resolves its own version** after a newer one exists;
* **an empty table still scores**, with the rubric pinned in
  ``rubric_default.py`` and under the same ``"v1"``;
* the pipeline really reads the published rubric — not the constant — and
  stamps that version on the score.

The rubric fixtures here carry ENGLISH labels. Uzbek in a ``.py`` file is legal
in six files and this is not one of them (CONVENTIONS.md §14); a label is data,
and none of these assertions is about the language it is written in.
"""

from __future__ import annotations

import importlib.util
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from src.core.enums import AnalysisStage, CallType
from src.core.errors import ValidationError
from src.modules.analysis.config import AnalysisConfig
from src.modules.analysis.models import CallScoreModel, RubricModel
from src.modules.analysis.pipeline import AnalysisPipeline, PipelineDeps
from src.modules.analysis.prompt import MAX_EXTRA_RULES
from src.modules.analysis.rubric_default import DEFAULT_RUBRIC, RUBRIC_VERSION
from src.modules.analysis.rubric_service import (
    RubricService,
    clean_extra_rules,
    prompt_preview,
    validate_rubric,
)
from src.modules.analysis.tests.stubs import StubASR, StubLLM

pytestmark = pytest.mark.asyncio


# --- Harness ---------------------------------------------------------------


def criterion(cid: str, points: int, *, optional: bool = False) -> dict[str, Any]:
    return {
        "id": cid,
        "label": f"Criterion {cid}",
        "points": points,
        "description": None,
        "optional": optional,
    }


def block(
    key: str, maximum: int, *, criteria: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """One block whose criteria add up to its maximum, unless a test says otherwise."""
    return {
        "key": key,
        "label": f"Block {key}",
        "max": maximum,
        "criteria": criteria if criteria is not None else [criterion(f"{key}1", maximum)],
    }


def blocks_totalling(*maxima: int) -> list[dict[str, Any]]:
    return [block(f"b{index}", maximum) for index, maximum in enumerate(maxima, start=1)]


def red_flag(key: str, penalty: int = -10, **overrides: Any) -> dict[str, Any]:
    return {
        "type": key,
        "label": f"Flag {key}",
        "penalty": penalty,
        "zeroes_score": False,
        "description": None,
        **overrides,
    }


VALID_BLOCKS = blocks_totalling(40, 35, 25)
VALID_FLAGS = [red_flag("shouting", -20), red_flag("unrealistic_promise", -15)]


async def publish(service: RubricService, **overrides: Any) -> RubricModel:
    payload: dict[str, Any] = {
        "name": "Published by a test",
        "blocks": VALID_BLOCKS,
        "red_flags": VALID_FLAGS,
    }
    payload.update(overrides)
    return await service.publish(**payload)


def reason_of(error: ValidationError) -> str:
    return str((error.detail or {}).get("reason"))


async def rubric_count(db) -> int:
    return await db.scalar(sa.select(sa.func.count()).select_from(RubricModel))


# --- The fallback: an empty table still scores -----------------------------


async def test_an_empty_table_falls_back_to_the_rubric_pinned_in_code(db) -> None:
    """A database nobody seeded scores exactly as it did before the table existed.

    Not a degraded mode and not an error: until somebody publishes, the constant
    IS the rubric, and it is the same one migration 012 seeds — same criteria,
    same label, same numbers.
    """
    active = await RubricService(db).active()

    assert active.stored is False
    assert active.label == RUBRIC_VERSION == "v1"
    assert active.blocks == DEFAULT_RUBRIC["blocks"]
    assert active.red_flags == DEFAULT_RUBRIC["red_flags"]
    assert active.extra_rules is None


async def test_reading_the_active_rubric_writes_nothing(db) -> None:
    """BonviZvonki's ``get_active()`` inserted the default row on first read.

    That made a GET a write — its router called ``session.commit()`` after a
    read — and it meant the first person to open the page decided what the
    rubric was. Here reading is a read.
    """
    await RubricService(db).active()
    await RubricService(db).active()

    assert await rubric_count(db) == 0


# --- Validation: the rule that survives ------------------------------------


async def test_blocks_that_do_not_total_one_hundred_are_refused_and_not_saved(
    db,
) -> None:
    """**The rule.** 95 points means every score is out of 95 while the screen,
    the export and last month's numbers all say 100."""
    service = RubricService(db)

    with pytest.raises(ValidationError) as caught:
        await publish(service, blocks=blocks_totalling(40, 35, 20))

    assert reason_of(caught.value) == "rubric_total_not_100"
    assert caught.value.detail == {
        "reason": "rubric_total_not_100",
        "total": 95,
        "expected": 100,
    }
    # Refused, not saved: the table is still empty and scoring still uses the
    # rubric it used a second ago.
    assert await rubric_count(db) == 0
    assert (await service.active()).stored is False


async def test_a_block_whose_criteria_miss_its_maximum_is_refused(db) -> None:
    """The same rule one level down, and it fails the same way.

    A block maximum its criteria cannot reach loses points nobody can earn; one
    they overshoot lets a block read 120 %.
    """
    lopsided = [
        block("script", 50, criteria=[criterion("A1", 20), criterion("A2", 20)]),
        block("closing", 50),
    ]

    with pytest.raises(ValidationError) as caught:
        await publish(RubricService(db), blocks=lopsided)

    assert caught.value.detail == {
        "reason": "rubric_block_mismatch",
        "block": "Block script",
        "criteria_sum": 40,
        "block_max": 50,
    }


async def test_a_block_with_no_criteria_is_refused(db) -> None:
    with pytest.raises(ValidationError) as caught:
        await publish(
            RubricService(db),
            blocks=[block("script", 100, criteria=[])],
        )
    assert reason_of(caught.value) == "rubric_block_empty"


async def test_a_rubric_with_no_blocks_at_all_is_refused(db) -> None:
    with pytest.raises(ValidationError) as caught:
        await publish(RubricService(db), blocks=[])
    assert reason_of(caught.value) == "rubric_no_blocks"


@pytest.mark.parametrize(
    "key", ["", "  ", "Shouting", "shaxsiy raqam", "крик", "a", "x" * 33, "9lives"]
)
async def test_a_red_flag_key_the_model_cannot_echo_back_is_refused(db, key) -> None:
    """One bad key stops ALL scoring, which is why it is refused at the door.

    The key goes into the prompt ("only these keys"), into the answer validator
    and into the panel's labels. A key with a space, a capital or a Cyrillic
    letter is one the model cannot reproduce verbatim, so every answer fails
    validation — and the page an admin would use to fix it is this one.
    """
    with pytest.raises(ValidationError) as caught:
        await publish(RubricService(db), red_flags=[red_flag(key)])
    assert reason_of(caught.value) == "rubric_flag_key_invalid"


async def test_two_red_flags_cannot_share_a_key(db) -> None:
    with pytest.raises(ValidationError) as caught:
        await publish(
            RubricService(db),
            red_flags=[red_flag("shouting", -20), red_flag("shouting", -5)],
        )
    assert reason_of(caught.value) == "rubric_flag_key_duplicate"


async def test_a_red_flag_cannot_award_points(db) -> None:
    """A positive penalty would ADD points for swearing at a customer."""
    with pytest.raises(ValidationError) as caught:
        await publish(RubricService(db), red_flags=[red_flag("shouting", 20)])
    assert reason_of(caught.value) == "rubric_flag_penalty_positive"


async def test_the_migration_seeds_the_rubric_as_json_arrays() -> None:
    """Migration 012's seed row, checked without a database.

    IT HAS TO BE CHECKED SOMEWHERE. The suite truncates every table before it
    starts (``conftest._clear_leftovers``), so no test ever sees the seeded row,
    and the first version of this seed passed ``json.dumps(...)`` into a JSONB
    column — which stores the whole rubric as a JSON *string*. Every migration
    ran green, and the symptom would have been a rubric page with no blocks on
    it and ``jsonb_array_length(blocks)`` failing with "cannot get array length
    of a scalar".
    """
    spec = importlib.util.spec_from_file_location(
        "migration_012",
        Path(__file__).resolve().parents[4] / "migrations" / "versions" / "012_create_rubrics.py",
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    (row,) = migration.SEED_ROWS
    assert isinstance(row["blocks"], list)
    assert isinstance(row["red_flags"], list)
    assert row["blocks"] == DEFAULT_RUBRIC["blocks"]
    assert sum(int(block["max"]) for block in row["blocks"]) == 100
    # The seed is version 1 and active, which is what makes every phase-1
    # score's "v1" point at the row that really did produce it.
    assert (row["version"], row["is_active"]) == (1, True)
    assert row["created_by"] is None


async def test_the_default_rubric_passes_its_own_validator() -> None:
    """The seed and the editor are held to one rule.

    If this ever failed, migration 012 would be seeding a rubric the panel would
    refuse to save — and nobody would find out until an admin pressed the button.
    """
    validate_rubric(DEFAULT_RUBRIC["blocks"], DEFAULT_RUBRIC["red_flags"])


async def test_extra_rules_longer_than_the_cap_are_refused() -> None:
    """That text is sent on EVERY call, so its length is money."""
    with pytest.raises(ValidationError) as caught:
        clean_extra_rules("x" * (MAX_EXTRA_RULES + 1))
    assert (caught.value.detail or {})["reason"] == "rubric_extra_rules_too_long"
    assert (caught.value.detail or {})["limit"] == MAX_EXTRA_RULES


async def test_blank_extra_rules_become_null() -> None:
    """Empty and NULL are one thing — "no instructions".

    An empty string would leave the prompt with a heading and nothing under it,
    and a model handed an empty section invents what was supposed to be in it.
    """
    assert clean_extra_rules("   \n ") is None
    assert clean_extra_rules(None) is None
    assert clean_extra_rules("  be brief  ") == "be brief"


# --- Versioning ------------------------------------------------------------


async def test_publishing_writes_the_next_version_and_makes_it_active(db) -> None:
    service = RubricService(db)

    first = await publish(service, name="First")
    second = await publish(service, name="Second")

    assert (first.version, second.version) == (1, 2)
    active = await service.active()
    assert (active.version, active.label, active.stored) == (2, "v2", True)


async def test_publishing_leaves_the_previous_version_exactly_as_it_was(db) -> None:
    """**The reason the table is versioned at all.**

    Every score already written names a version. If that version could change
    underneath it, the string on the score would claim a comparison it can no
    longer support.
    """
    service = RubricService(db)
    original = await publish(
        service, name="First", blocks=VALID_BLOCKS, extra_rules="be brief"
    )
    original_blocks = [dict(item) for item in original.blocks]

    await publish(service, name="Second", blocks=blocks_totalling(60, 40))

    kept = await service.get_version(1)
    assert kept.blocks == original_blocks
    assert kept.extra_rules == "be brief"
    assert kept.name == "First"
    assert kept.is_active is False
    # And it is still listed: nothing is ever deleted from the history.
    assert [row.version for row in await service.versions()] == [2, 1]


async def test_only_one_rubric_is_ever_active(db) -> None:
    """Held by a partial unique index, not by the service being careful.

    Two ``is_active = true`` rows made ``scalar_one_or_none()`` raise
    ``MultipleResultsFound`` in BonviZvonki — a 500 that stopped all scoring.
    """
    service = RubricService(db)
    for name in ("First", "Second", "Third"):
        await publish(service, name=name)

    active = await db.scalar(
        sa.select(sa.func.count())
        .select_from(RubricModel)
        .where(RubricModel.is_active.is_(True))
    )
    assert active == 1


async def test_activating_an_earlier_version_is_the_undo_for_a_bad_edit(db) -> None:
    """It keeps its own number: scores before and after the round trip carry the
    same label and really were produced by the same criteria."""
    service = RubricService(db)
    await publish(service, name="First", blocks=VALID_BLOCKS)
    await publish(service, name="Second", blocks=blocks_totalling(60, 40))

    restored = await service.activate(1)

    assert (restored.version, restored.is_active) == (1, True)
    active = await service.active()
    assert (active.version, active.label) == (1, "v1")
    assert (await service.get_version(2)).is_active is False


async def test_activating_the_version_that_is_already_active_changes_nothing(
    db,
) -> None:
    service = RubricService(db)
    await publish(service, name="First")

    again = await service.activate(1)

    assert again.is_active is True
    assert len(await service.versions()) == 1


async def test_a_scored_call_still_resolves_the_version_that_produced_it(
    db, score_factory
) -> None:
    """The whole point of the string on ``call_scores``.

    A score written under v1 keeps saying v1 after v2 is published, and v1 can
    still be read back criterion by criterion — which is what answering "why 78,
    and against what?" six months later needs.
    """
    service = RubricService(db)
    await publish(service, name="First", blocks=VALID_BLOCKS)
    score = await score_factory(rubric_version="v1")

    await publish(service, name="Second", blocks=blocks_totalling(60, 40))

    await db.refresh(score)
    assert score.rubric_version == "v1"
    produced_by = await service.get_version(1)
    assert produced_by.blocks == VALID_BLOCKS
    assert (await service.active()).version == 2


# --- The prompt preview ----------------------------------------------------


async def test_the_prompt_preview_is_built_from_the_active_rubric(db) -> None:
    """Assembled by the server from the same function the scorer uses.

    Rebuilt in the panel it would drift, and the screen would then show one
    prompt while the model received another — a bug with no symptom.
    """
    service = RubricService(db)
    await publish(service, name="First", extra_rules="ask about delivery dates")

    preview = prompt_preview(await service.active())

    assert (preview.rubric_version, preview.rubric_label) == (1, "v1")
    assert preview.extra_rules_limit == MAX_EXTRA_RULES
    assert preview.char_count == len(preview.full_text)
    assert preview.approx_tokens > 0
    # Exactly one section is editable, and it is the one holding the admin's
    # text. The rest — the language rules, the scoring order, the response
    # format — cannot be touched: break them and every answer fails validation.
    editable = [section for section in preview.sections if section.editable]
    assert [section.key for section in editable] == ["extra_rules"]
    assert "ask about delivery dates" in editable[0].text
    assert "ask about delivery dates" in preview.full_text
    for key in ("b1", "b2", "b3"):
        assert key in preview.full_text


# --- The pipeline reads the table, not the constant ------------------------


def _config() -> AnalysisConfig:
    """The seeded defaults with the waiting removed (``test_pipeline``'s shape)."""
    return AnalysisConfig(
        enabled=True,
        min_duration_sec=30,
        transcribe_internal=False,
        lookback_hours=168,
        max_calls_per_run=200,
        concurrency=1,
        asr_rpm=0,
        llm_rpm=0,
        max_retries=4,
        backoff_base_sec=0,
        backoff_max_sec=0,
        max_wait_sec=60,
        quota_cooldown_sec=1800,
        invalid_retries=2,
        call_timeout_sec=900,
        retry_transient_days=7,
        monthly_cost_cap_micro_usd=50_000_000,
        monthly_max_calls=3000,
        price_asr_micro_usd_per_minute=0,
        price_llm_micro_usd_per_1k_input_tokens=0,
        price_llm_micro_usd_per_1k_output_tokens=0,
        asr_language="uz",
    )


async def _ready(client):
    return client


async def score_one_call(db, call, *, blocks, red_flags) -> tuple[CallScoreModel, StubLLM]:
    """Run the real pipeline over one call with both providers stubbed.

    The stub answers against the blocks it is given; the validator checks the
    answer against the ACTIVE rubric. So an answer built from the published
    blocks only validates if the pipeline really read the table — which is the
    assertion these two tests are making.
    """
    llm = StubLLM(rubric_blocks=blocks, rubric_red_flags=red_flags)
    deps = PipelineDeps(
        asr_factory=lambda _session: _ready(StubASR()),
        llm_factory=lambda _session: _ready(llm),
        session_factory=lambda: nullcontext(db),
    )
    outcome = await AnalysisPipeline(_config(), deps).process_in_session(db, call.id)
    assert outcome.stage is AnalysisStage.COMPLETED, outcome.failure
    score = (
        await db.execute(sa.select(CallScoreModel).where(CallScoreModel.call_id == call.id))
    ).scalar_one()
    return score, llm


async def analysable_call(call_factory, audio_factory):
    call = await call_factory(
        has_audio=True,
        audio_missing_reason=None,
        call_type=CallType.EXTERNAL,
        duration_sec=180,
    )
    await audio_factory(call=call)
    return call


async def test_scoring_uses_the_published_rubric_and_stamps_its_version(
    db, call_factory, audio_factory
) -> None:
    """Published at 11:00, used by the next call — not at the next restart."""
    await publish(
        RubricService(db),
        name="First",
        blocks=VALID_BLOCKS,
        red_flags=VALID_FLAGS,
        extra_rules="ask about delivery dates",
    )
    await publish(
        RubricService(db), name="Second", blocks=blocks_totalling(60, 40),
        red_flags=VALID_FLAGS,
    )
    call = await analysable_call(call_factory, audio_factory)

    score, llm = await score_one_call(
        db, call, blocks=blocks_totalling(60, 40), red_flags=VALID_FLAGS
    )

    assert score.rubric_version == "v2"
    assert set(score.blocks) <= {"b1", "b2"}
    # v2 carries no admin instructions, so v1's must not be in the prompt: the
    # text is part of the rubric and is versioned with it.
    assert "ask about delivery dates" not in llm.systems[0]


async def test_scoring_with_an_empty_table_still_produces_a_v1_score(
    db, call_factory, audio_factory
) -> None:
    """The fallback, proved where it matters: through the pipeline, end to end.

    This is the state every BonviCall database is in today, and the state a
    database restored without the seed would be in tomorrow.
    """
    call = await analysable_call(call_factory, audio_factory)

    score, _ = await score_one_call(
        db,
        call,
        blocks=DEFAULT_RUBRIC["blocks"],
        red_flags=DEFAULT_RUBRIC["red_flags"],
    )

    assert await rubric_count(db) == 0
    assert score.rubric_version == "v1"
    assert set(score.blocks) <= {
        str(item["key"]) for item in DEFAULT_RUBRIC["blocks"]
    }


async def test_the_admins_extra_rules_reach_the_prompt(
    db, call_factory, audio_factory
) -> None:
    """``extra_rules`` is part of the rubric, which is why it is stored on it.

    In ``app_settings`` it would not be versioned: a score could not say which
    instructions produced it, and rolling a bad edit back would not bring the
    text back with it.
    """
    await publish(
        RubricService(db),
        name="First",
        blocks=VALID_BLOCKS,
        red_flags=VALID_FLAGS,
        extra_rules="ask about delivery dates",
    )
    call = await analysable_call(call_factory, audio_factory)

    _, llm = await score_one_call(db, call, blocks=VALID_BLOCKS, red_flags=VALID_FLAGS)

    assert "ask about delivery dates" in llm.systems[0]
