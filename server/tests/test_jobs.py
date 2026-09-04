"""The scheduler and its jobs (T150, T151, SPEC §10.4).

Two properties are asserted for every job, because both are load-bearing:

* **only one worker runs it at a time** — the advisory lock;
* **it is safe to run twice** — which the lock does *not* give you, because a
  worker that crashes mid-run and restarts is the case that actually happens.

Retention gets the most attention: it deletes irreversibly, so "run it twice"
is not a tidiness question.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import sqlalchemy as sa

from src.core.enums import (
    AlertKind,
    AudioMissingReason,
    CommandStatus,
    UploadStatus,
)
from src.core.jobs import FAILURES_BEFORE_ALERT, JobRunner, lock_key
from src.modules.alerts.models import AlertModel
from src.modules.audio.models import AudioUploadSessionModel, CallAudioModel
from src.worker import ALL_JOBS, ON_DEMAND, SCHEDULE, build_scheduler

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _runner_uses_the_test_session(db, engine, monkeypatch):
    """Point ``JobRunner``'s own session at the **test transaction**.

    Two separate problems, one fixture:

    * the application engine is pooled and therefore bound to whichever event
      loop first used it, so with a loop per test the second test gets a
      connection from a closed loop;
    * a session on its own connection **commits for real**, and those rows
      then leak into every later test. That is not hypothetical — it broke
      eleven unrelated tests before this bound the maker to ``db``'s
      connection.

    The lock connection still comes from the engine, which is right: an
    advisory lock taken inside the test transaction would be released by the
    rollback rather than by the job finishing.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.core import database

    connection = await db.connection()
    monkeypatch.setattr(database, "get_engine", lambda: engine)
    monkeypatch.setattr(
        database,
        "get_sessionmaker",
        lambda: async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ),
    )


# --- The registry -----------------------------------------------------------


async def test_every_job_spec_names_is_registered() -> None:
    """SPEC §10.4's table. A job nobody scheduled is a promise nobody keeps."""
    expected = {
        "offline_sweep",
        "command_timeout",
        "silence_detection",
        "upload_session_sweeper",
        "pending_audio_sweeper",
        "funnel_refresh",
        "call_log_delta_close",
        "callback_event_retention",
        "model_capture_stats",
        "audio_retention",
        "storage_usage",
    }
    assert expected <= set(SCHEDULE)
    # The two the SPEC marks "on demand" are runnable but not on a clock.
    assert "reclassify_calls" in ALL_JOBS
    assert "reclassify_calls" in ON_DEMAND


async def test_the_scheduler_builds_with_one_instance_per_job() -> None:
    """A queue of overdue sweeps all firing at once turns a hiccup into an
    outage, so a late tick is dropped rather than stacked."""
    scheduler = build_scheduler()
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == set(SCHEDULE)
    for job in jobs.values():
        assert job.max_instances == 1
        assert job.coalesce is True


async def test_lock_keys_are_stable_and_distinct() -> None:
    """Two workers on different releases must agree without sharing a table."""
    assert lock_key("audio_retention") == lock_key("audio_retention")
    keys = {name: lock_key(name) for name in SCHEDULE}
    assert len(set(keys.values())) == len(keys)
    assert all(0 <= key < 2**63 for key in keys.values())


# --- The advisory lock ------------------------------------------------------


async def test_a_second_worker_skips_rather_than_waits(db) -> None:
    """T150's done criterion: a job runs exactly once with two workers up.

    Skipping and not queueing: a queued duplicate would run the job twice in a
    row, which is the thing being prevented, only later.
    """
    calls: list[int] = []

    async def counting_job(session) -> int:
        calls.append(1)
        # Long enough that the second runner is genuinely concurrent.
        await asyncio.sleep(0.3)
        return 1

    runner = JobRunner()
    first, second = await asyncio.gather(
        runner.run("test_lock_job", counting_job),
        runner.run("test_lock_job", counting_job),
    )
    assert len(calls) == 1
    assert {first.ran, second.ran} == {True, False}


async def test_the_lock_is_released_when_the_job_finishes(db, engine) -> None:
    """Otherwise the next tick skips forever and the job silently stops."""

    async def trivial(session) -> int:
        return 0

    runner = JobRunner()
    await runner.run("test_release_job", trivial)
    async with engine.connect() as connection:
        free = await connection.scalar(
            sa.text("SELECT pg_try_advisory_lock(:key)"),
            {"key": lock_key("test_release_job")},
        )
        await connection.execute(
            sa.text("SELECT pg_advisory_unlock(:key)"),
            {"key": lock_key("test_release_job")},
        )
    assert free is True


async def test_the_lock_is_released_when_the_job_raises(db, engine) -> None:
    """A failing job that kept its lock would stop itself forever."""

    async def failing(session) -> int:
        raise RuntimeError("boom")

    runner = JobRunner()
    result = await runner.run("test_failing_job", failing)
    assert result.error is not None and "boom" in result.error

    async with engine.connect() as connection:
        free = await connection.scalar(
            sa.text("SELECT pg_try_advisory_lock(:key)"),
            {"key": lock_key("test_failing_job")},
        )
        await connection.execute(
            sa.text("SELECT pg_advisory_unlock(:key)"),
            {"key": lock_key("test_failing_job")},
        )
    assert free is True


async def test_three_consecutive_failures_raise_an_alert(db) -> None:
    """A scheduler that fails silently is worse than none: the absence of
    alerts then means nothing."""

    async def failing(session) -> int:
        raise RuntimeError("still broken")

    from src.worker import alert_on_repeated_failure

    runner = JobRunner(on_repeated_failure=alert_on_repeated_failure)
    for _ in range(FAILURES_BEFORE_ALERT):
        await runner.run("test_alerting_job", failing)
    assert runner.consecutive_failures["test_alerting_job"] == FAILURES_BEFORE_ALERT

    raised = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AlertModel)
        .where(AlertModel.kind == AlertKind.RETENTION_JOB_FAILED)
    )
    assert raised == 1


async def test_a_success_resets_the_failure_count(db) -> None:
    """Otherwise one bad night arms the alert for the rest of the year."""

    async def failing(session) -> int:
        raise RuntimeError("transient")

    async def working(session) -> int:
        return 0

    runner = JobRunner()
    await runner.run("test_reset_job", failing)
    await runner.run("test_reset_job", working)
    assert runner.consecutive_failures["test_reset_job"] == 0


# --- Retention: the one that deletes irreversibly ---------------------------


async def test_retention_is_safe_to_run_twice(db, audio_factory, audio_root) -> None:
    """The case that happens: a worker crashes mid-run and restarts."""
    from src.modules.audio.jobs import audio_retention

    audio = await audio_factory(payload=b"OggS" + b"\x00" * 512)
    audio.recorded_at = datetime.now(UTC) - timedelta(days=800)
    await db.flush()

    assert await audio_retention(db) == 1
    assert await audio_retention(db) == 0, "the second run must find nothing"

    await db.refresh(audio)
    assert audio.deleted_at is not None
    assert audio.deleted_reason == "retention"
    assert not (audio_root / audio.storage_key).exists()
    assert await db.scalar(sa.select(sa.func.count()).select_from(CallAudioModel)) == 1


async def test_retention_deletes_the_blob_before_marking_the_row(
    db, audio_factory, audio_root
) -> None:
    """The order is the design.

    A crash between the two leaves a row claiming a file that is gone, which
    the next run repairs because ``delete`` is idempotent. Marking first and
    crashing would leave a file nobody ever deletes and nobody can find — the
    failure that running the job again cannot fix.
    """
    from src.modules.audio.jobs import audio_retention

    audio = await audio_factory(payload=b"OggS")
    audio.recorded_at = datetime.now(UTC) - timedelta(days=800)
    await db.flush()

    # Simulate the crash: the blob is already gone, the row is not marked.
    (audio_root / audio.storage_key).unlink()
    assert await audio_retention(db) == 1, "a missing blob must not stop the sweep"
    await db.refresh(audio)
    assert audio.deleted_at is not None


async def test_retention_leaves_recent_audio_alone(db, audio_factory) -> None:
    from src.modules.audio.jobs import audio_retention

    audio = await audio_factory(payload=b"OggS")
    assert await audio_retention(db) == 0
    await db.refresh(audio)
    assert audio.deleted_at is None


# --- Silence detection: the working-hours guard -----------------------------


async def _quiet_fleet(db, installation_factory, hours_ago: float, moment) -> None:
    from src.modules.devices.models import DeviceHealthModel

    for _ in range(3):
        installation = await installation_factory()
        db.add(
            DeviceHealthModel(
                installation_id=installation.id,
                last_heartbeat_at=moment - timedelta(hours=hours_ago),
                last_call_at=moment - timedelta(hours=hours_ago),
                service_running=True,
            )
        )
    await db.flush()


async def test_the_night_sweep_alerts_on_nothing(
    db, installation_factory, frozen_clock
) -> None:
    """**The trap this job sets.** It runs every five minutes, at 03:00 too.

    A phone that stopped reporting at 20:00 has been quiet for zero *working*
    hours at 03:00. An alerting system that cries wolf outside business hours
    gets muted, and then it is not an alerting system.
    """
    from src.modules.devices.jobs import silence_detection

    # 03:00 Tashkent on a Tuesday is 22:00 UTC on the Monday.
    moment = datetime(2026, 9, 7, 22, 0, tzinfo=UTC)
    frozen_clock(moment)
    await _quiet_fleet(db, installation_factory, hours_ago=7, moment=moment)

    assert await silence_detection(db) == 0
    assert await db.scalar(sa.select(sa.func.count()).select_from(AlertModel)) == 0


async def test_the_same_silence_alerts_during_the_working_day(
    db, installation_factory, frozen_clock
) -> None:
    """The other half: the rule must still fire when it should."""
    from src.modules.devices.jobs import silence_detection

    # 17:00 Tashkent on a Monday, quiet since 09:00 — eight working hours.
    moment = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    frozen_clock(moment)
    await _quiet_fleet(db, installation_factory, hours_ago=8, moment=moment)

    await silence_detection(db)
    kinds = (await db.scalars(sa.select(AlertModel.kind))).all()
    assert AlertKind.FLEET_SILENT in kinds


async def test_running_the_silence_sweep_twice_raises_one_alert(
    db, installation_factory, frozen_clock
) -> None:
    from src.modules.devices.jobs import silence_detection

    moment = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    frozen_clock(moment)
    await _quiet_fleet(db, installation_factory, hours_ago=8, moment=moment)

    await silence_detection(db)
    await silence_detection(db)
    rows = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AlertModel)
        .where(AlertModel.kind == AlertKind.FLEET_SILENT)
    )
    assert rows == 1, "the dedupe key is what makes a 5-minute job survivable"


# --- The sweepers -----------------------------------------------------------


async def test_the_upload_sweeper_expires_and_marks_the_call(
    db, call_factory, installation_factory, audio_root
) -> None:
    from src.modules.audio.jobs import upload_session_sweeper

    installation = await installation_factory()
    call = await call_factory(installation=installation)
    upload = AudioUploadSessionModel(
        installation_id=installation.id,
        client_call_id=call.client_call_id,
        call_id=call.id,
        bytes_total=1000,
        chunk_size=512,
        sha256_expected="a" * 64,
        codec="opus",
        container="ogg",
        capture_route="oem_file_harvest",
        status=UploadStatus.OPEN,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    db.add(upload)
    await db.flush()

    assert await upload_session_sweeper(db) == 1
    assert await upload_session_sweeper(db) == 0
    await db.refresh(upload)
    await db.refresh(call)
    assert upload.status is UploadStatus.EXPIRED
    assert call.audio_missing_reason is AudioMissingReason.UPLOAD_EXPIRED, (
        "a recording that never arrived must appear in the gap report as a loss"
    )


async def test_pending_audio_becomes_visible_after_a_day(
    db, call_factory
) -> None:
    """SPEC §3.9: audio in flight is not a capture failure, but it cannot stay
    invisible forever or the gap report flatters itself."""
    from src.modules.audio.jobs import pending_audio_sweeper

    fresh = await call_factory()
    stale = await call_factory()
    stale.received_at = datetime.now(UTC) - timedelta(hours=30)
    await db.flush()

    assert await pending_audio_sweeper(db) == 1
    assert await pending_audio_sweeper(db) == 0
    await db.refresh(fresh)
    await db.refresh(stale)
    assert fresh.audio_missing_reason is AudioMissingReason.PENDING_UPLOAD
    assert stale.audio_missing_reason is AudioMissingReason.UPLOAD_EXPIRED


async def test_the_delta_closer_leaves_unreconciled_gaps_open(
    db, installation_factory
) -> None:
    """A delta that never agrees is the measurement telling us something was
    lost. Closing it would erase the finding (N3)."""
    from src.modules.devices.jobs import call_log_delta_close
    from src.modules.devices.models import CallLogDeltaModel

    installation = await installation_factory()
    old = datetime.now(UTC) - timedelta(hours=30)
    reconciled = CallLogDeltaModel(
        installation_id=installation.id,
        number_id=installation.number_id,
        period_date=old.date(),
        device_counted=30,
        uploaded_count=30,
        first_reported_at=old,
    )
    other = await installation_factory()
    gap = CallLogDeltaModel(
        installation_id=other.id,
        number_id=other.number_id,
        period_date=old.date(),
        device_counted=31,
        uploaded_count=28,
        first_reported_at=old,
    )
    db.add_all([reconciled, gap])
    await db.flush()

    assert await call_log_delta_close(db) == 1
    await db.refresh(reconciled)
    await db.refresh(gap)
    assert reconciled.closed_at is not None
    assert gap.closed_at is None


async def test_command_timeout_is_idempotent(
    db, manager, installation_factory
) -> None:
    from src.modules.commands.jobs import command_timeout
    from src.modules.commands.models import CommandModel

    installation = await installation_factory()
    issued = (
        await manager.post(
            f"/api/v1/devices/{installation.id}/commands",
            json={"kind": "dial", "number": "+998935554433"},
        )
    ).json()
    import uuid as _uuid

    command = await db.get(CommandModel, _uuid.UUID(issued["id"]))
    command.status = CommandStatus.SENT
    command.sent_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.flush()

    assert await command_timeout(db) == 1
    assert await command_timeout(db) == 0
    await db.refresh(command)
    assert command.status is CommandStatus.FAILED


async def test_storage_usage_is_one_row_per_day(db, audio_factory) -> None:
    from src.modules.audio.jobs import storage_usage
    from src.modules.audio.models import StorageUsageDailyModel

    await audio_factory(payload=b"OggS" + b"\x00" * 1024)
    await storage_usage(db)
    await storage_usage(db)
    rows = await db.scalar(
        sa.select(sa.func.count()).select_from(StorageUsageDailyModel)
    )
    assert rows == 1, "upserted, so a second run recomputes rather than adds"


async def test_callback_events_are_deleted_not_kept(db, service_token) -> None:
    """They are inbound call records of employees' work numbers with no value
    after the enrolment. Keeping them forever, for no purpose, is the thing
    this product promises not to do."""
    from src.modules.enrolment.jobs import callback_event_retention
    from src.modules.enrolment.models import CallbackEventModel, CallbackReceiverModel

    receiver = CallbackReceiverModel(
        name="gw", msisdn="+998712000000", kind="gsm_gateway", token_hash="a" * 64
    )
    db.add(receiver)
    await db.flush()
    db.add(
        CallbackEventModel(
            receiver_id=receiver.id,
            caller_e164="+998901112233",
            cli_presented=True,
            received_at=datetime.now(UTC) - timedelta(days=120),
        )
    )
    await db.flush()

    assert await callback_event_retention(db) == 1
    assert await callback_event_retention(db) == 0
    assert await db.scalar(sa.select(sa.func.count()).select_from(CallbackEventModel)) == 0
