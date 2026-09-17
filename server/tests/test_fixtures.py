"""The shared fixtures themselves (T154, CONVENTIONS.md §13).

Twenty modules will build their test data through these. A factory that is
subtly wrong is twenty subtly wrong test suites, so the factories are tested
here once, where the failure is legible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from src.core import clock
from src.core.enums import (
    AiRole,
    AnalysisFailure,
    AnalysisStage,
    CallDisposition,
    InstallationStatus,
)
from src.core.permissions import Perm
from src.core.settings_keys import ALL_SETTING_KEYS

pytestmark = pytest.mark.asyncio


async def test_the_suite_refuses_a_database_that_is_not_the_test_one() -> None:
    """The BonviZvonki incident, made structurally impossible (§13)."""
    from conftest import _assert_test_database

    with pytest.raises(RuntimeError, match="must end in '_test'"):
        _assert_test_database("postgresql+asyncpg://u:p@host:5432/bonvicall")


async def test_db_rolls_back_between_tests(db, agent_factory) -> None:
    """Two tests, one name: the second would fail if the first had persisted."""
    await agent_factory(full_name="Rollback Probe")
    count = await db.scalar(
        sa.text("SELECT count(*) FROM agents WHERE full_name = 'Rollback Probe'")
    )
    assert count == 1


async def test_db_rolls_back_between_tests_again(db, agent_factory) -> None:
    count = await db.scalar(
        sa.text("SELECT count(*) FROM agents WHERE full_name = 'Rollback Probe'")
    )
    assert count == 0


async def test_role_clients_carry_the_right_permissions(
    admin, manager, sales, service_token
) -> None:
    assert admin.principal.has(Perm.AUDIT_READ)
    assert not manager.principal.has(Perm.AUDIT_READ)
    assert sales.principal.has(Perm.CALLS_READ_OWN)
    assert not sales.principal.has(Perm.CALLS_READ)
    assert service_token.principal.has(Perm.EXPORT_READ)


async def test_a_sales_principal_is_linked_to_an_agent(sales) -> None:
    """Own-scope narrowing filters on this; without it the fixture proves nothing."""
    assert sales.principal.agent_id is not None


async def test_registered_number_factory_assigns_when_asked(
    db, agent_factory, registered_number_factory
) -> None:
    agent = await agent_factory()
    number = await registered_number_factory(agent=agent)
    assert number.phone_key == number.e164[-9:]
    holder = await db.scalar(
        sa.select(sa.func.count())
        .select_from(sa.table("number_assignments"))
        .where(sa.column("number_id") == number.id)
    )
    assert holder == 1


async def test_installation_factory_creates_the_whole_chain(
    installation_factory,
) -> None:
    installation = await installation_factory()
    assert installation.status is InstallationStatus.ACTIVE
    assert installation.number_id and installation.agent_id and installation.device_id


async def test_call_factory_satisfies_the_check_constraints(call_factory) -> None:
    answered = await call_factory()
    assert answered.disposition is CallDisposition.ANSWERED
    assert answered.answered_at is not None and answered.duration_sec > 0

    unanswered = await call_factory(disposition=CallDisposition.NO_ANSWER)
    assert unanswered.answered_at is None and unanswered.duration_sec == 0


async def test_audio_factory_writes_real_bytes(audio_factory, audio_root) -> None:
    """Range requests and checksums need a file, not a row that claims one."""
    audio = await audio_factory(payload=b"OggS" + b"\x01" * 1024)
    path = audio_root / audio.storage_key
    assert path.is_file()
    assert path.stat().st_size == audio.bytes == 1028


async def test_transcript_factory_keeps_its_counts_honest(transcript_factory) -> None:
    """A fixture whose ``char_count`` disagrees with its text is a fixture every
    later assertion about size has to distrust."""
    transcript = await transcript_factory(text="[00:00] SPEAKER_0: Hello there.")
    assert transcript.char_count == len("[00:00] SPEAKER_0: Hello there.")
    assert transcript.word_count == 4


async def test_score_factory_blocks_sum_to_the_overall_score(score_factory) -> None:
    """Two views of one number. The panel draws both, so they cannot differ."""
    score = await score_factory()
    assert score.overall_score == sum(score.blocks.values())
    assert all(isinstance(value, int) for value in score.blocks.values())
    assert score.rubric_version == "v1"


async def test_score_factory_satisfies_the_range_checks(db, score_factory) -> None:
    """0-100 is a database fact; a 167 % bar reached a manager once."""
    await score_factory(overall_score=100, confidence_pct=0)
    with pytest.raises(IntegrityError) as caught:
        await score_factory(overall_score=101)
    assert "overall_score_range" in str(caught.value)
    await db.rollback()


async def test_analysis_state_factory_satisfies_the_check_constraints(
    analysis_state_factory,
) -> None:
    """A stopped call always carries a reason; a running one never does."""
    queued = await analysis_state_factory()
    assert queued.stage is AnalysisStage.QUEUED and queued.failure_code is None

    skipped = await analysis_state_factory(stage=AnalysisStage.SKIPPED)
    assert skipped.failure_code is not None

    failed = await analysis_state_factory(stage=AnalysisStage.FAILED)
    assert failed.failure_code is not None
    assert failed.asr_calls == 0 and failed.llm_calls == 0


async def test_a_running_stage_cannot_carry_a_failure_code(
    db, analysis_state_factory
) -> None:
    """The other half of the constraint, asserted against the database."""
    with pytest.raises(IntegrityError) as caught:
        await analysis_state_factory(
            stage=AnalysisStage.TRANSCRIBING, failure_code=AnalysisFailure.TIMEOUT
        )
    assert "stopped_has_reason" in str(caught.value)
    await db.rollback()


async def test_provider_cooldown_factory_is_keyed_by_the_role(
    db, provider_cooldown_factory
) -> None:
    """At most two rows, ever: the role is the identity."""
    cooldown = await provider_cooldown_factory()
    assert cooldown.role is AiRole.ASR
    assert cooldown.until_at > cooldown.started_at
    with pytest.raises(IntegrityError):
        await provider_cooldown_factory(role=AiRole.ASR)
    await db.rollback()


async def test_frozen_clock_pins_now(frozen_clock) -> None:
    moment = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    frozen_clock(moment)
    assert clock.now() == moment
    frozen_clock(moment + timedelta(hours=5))
    assert clock.now() == moment + timedelta(hours=5)


async def test_truncate_all_leaves_the_seeded_settings(db, truncate_all) -> None:
    """Truncation must not delete the migration's seed, or every later test lies."""
    await truncate_all()
    remaining = await db.scalar(sa.text("SELECT count(*) FROM app_settings"))
    # Every key `SettingKey` declares is seeded by a migration, and
    # `test_schema.py::test_every_settings_key_is_seeded_with_its_documented_default`
    # checks the values one by one. Counting against that declaration
    # rather than against a literal keeps this test from needing an edit
    # every time a module adds a setting — which, with three ports landing
    # at once, it needed three times in one afternoon.
    assert remaining == len(ALL_SETTING_KEYS)
