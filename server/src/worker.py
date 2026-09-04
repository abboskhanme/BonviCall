"""The scheduler process (T150, SPEC §10.4).

Runs in its own container, alongside the API. Everything the alerting subsystem
promises depends on this process existing: without it silence detection never
fires, retention never deletes, the per-model regression alert never compares
against its M0 baseline, and storage accounting never accumulates. Alerting
would be a capability rather than a behaviour.

**Jobs are registered here and implemented in their modules** (§11.2): a module
exports a callable, this file decides when it runs. That is the whole of the
coupling, and it is why adding a job touches one line of shared code.

**Two workers cannot overlap.** Every run takes a PostgreSQL advisory lock and
skips if it cannot (``core/jobs.py``). **And every job is safe to run twice
anyway**, because the lock does not protect against a worker restarting
mid-run — which is the case that actually happens.
"""

from __future__ import annotations

import asyncio
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.core import database

# The registry, imported before any model is touched (CONVENTIONS.md §10).
from src.core import models as _model_registry  # noqa: F401
from src.core.clock import TASHKENT
from src.core.config import get_settings
from src.core.enums import AlertKind, AlertSeverity
from src.core.jobs import JobCallable, JobRunner
from src.core.logging import configure_logging, get_logger
from src.modules.alerts.service import AlertService
from src.modules.audio.jobs import (
    audio_retention,
    pending_audio_sweeper,
    storage_usage,
    upload_session_sweeper,
)
from src.modules.calls.jobs import reclassify_calls
from src.modules.catalog.jobs import model_capture_stats
from src.modules.commands.jobs import command_timeout
from src.modules.devices.jobs import (
    call_log_delta_close,
    offline_sweep,
    silence_detection,
)
from src.modules.enrolment.jobs import callback_event_retention, receiver_health
from src.modules.installations.jobs import funnel_refresh

log = get_logger(__name__)

#: Every scheduled job: ``name -> (callable, trigger)``. The cadences are
#: SPEC §10.4's, and each one is a decision:
#:
#: * ``command_timeout`` every 10 s — UC-16 promises a person watching the
#:   panel sees the outcome quickly, including the outcome "it did not work".
#: * ``silence_detection`` every 5 min, **including at night**. The rule
#:   counts *working* hours, so a sleeping fleet returns zero elapsed time;
#:   skipping nights in the schedule instead would delay a real alert until
#:   well after Monday morning, and a holiday added to the settings would need
#:   a redeploy to take effect.
#: * the nightly jobs are staggered rather than all at 02:00, so a slow
#:   retention pass does not delay the storage figure that measures it.
SCHEDULE: dict[str, tuple[JobCallable, object]] = {
    "command_timeout": (command_timeout, IntervalTrigger(seconds=10)),
    "offline_sweep": (offline_sweep, IntervalTrigger(minutes=1)),
    "silence_detection": (silence_detection, IntervalTrigger(minutes=5)),
    "funnel_refresh": (funnel_refresh, IntervalTrigger(minutes=5)),
    "receiver_health": (receiver_health, IntervalTrigger(minutes=1)),
    "upload_session_sweeper": (upload_session_sweeper, IntervalTrigger(minutes=15)),
    "pending_audio_sweeper": (pending_audio_sweeper, IntervalTrigger(hours=1)),
    "call_log_delta_close": (call_log_delta_close, IntervalTrigger(hours=1)),
    "model_capture_stats": (
        model_capture_stats,
        CronTrigger(hour=1, minute=0, timezone=TASHKENT),
    ),
    "audio_retention": (
        audio_retention,
        CronTrigger(hour=2, minute=0, timezone=TASHKENT),
    ),
    "callback_event_retention": (
        callback_event_retention,
        CronTrigger(hour=2, minute=15, timezone=TASHKENT),
    ),
    "storage_usage": (
        storage_usage,
        CronTrigger(hour=2, minute=30, timezone=TASHKENT),
    ),
}

#: Jobs that exist but are not scheduled: they run when an admin edits
#: something, not on a clock. Listed here so "what jobs are there" has one
#: answer (``reclassify_calls`` and ``reattribute_calls``, SPEC §10.4).
ON_DEMAND = ("reclassify_calls",)

#: Everything runnable by name, scheduled or not. ``reattribute_calls`` is not
#: here: it takes the number whose assignments changed, so it is triggered by
#: the edit that caused it rather than by a clock or a command line.
ALL_JOBS: dict[str, JobCallable] = {
    name: job for name, (job, _) in SCHEDULE.items()
} | {"reclassify_calls": reclassify_calls}


async def alert_on_repeated_failure(name: str, failures: int, exc: Exception) -> None:
    """Three strikes and an admin is told (SPEC §10.4).

    Lives here and not in ``core/jobs.py`` because ``core`` must not import a
    module (§2), and because "three failures means raise an alert" is a policy
    rather than a property of running a function under a lock.

    Its own session: the job's has already failed, and quite possibly its
    database connection with it.
    """
    kind = (
        AlertKind.BACKUP_FAILED if name == "backup_verify" else AlertKind.RETENTION_JOB_FAILED
    )
    async with database.get_sessionmaker()() as session:
        await AlertService(session).raise_alert(
            kind=kind,
            severity=AlertSeverity.CRITICAL,
            scope=name,
            detail={
                "job": name,
                "consecutive_failures": failures,
                "error": type(exc).__name__,
            },
        )
        await session.commit()


def build_scheduler(runner: JobRunner | None = None) -> AsyncIOScheduler:
    """Wire every job onto the scheduler. Separated so a test can inspect it."""
    runner = runner or JobRunner(on_repeated_failure=alert_on_repeated_failure)
    scheduler = AsyncIOScheduler(timezone=TASHKENT)
    for name, (job, trigger) in SCHEDULE.items():
        scheduler.add_job(
            runner.run,
            trigger=trigger,
            args=[name, job],
            id=name,
            # One run at a time per job in this process, and a late tick is
            # dropped rather than queued: a queue of overdue sweeps all firing
            # at once is how a scheduler turns a hiccup into an outage.
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
    return scheduler


async def run_forever() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.environment)
    settings.assert_production_ready()

    scheduler = build_scheduler()
    scheduler.start()
    log.info("worker_started", jobs=sorted(SCHEDULE), on_demand=list(ON_DEMAND))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for received in (signal.SIGINT, signal.SIGTERM):
        # A clean stop matters more here than in the API: this process may be
        # halfway through deleting audio, and the advisory lock is released
        # when its connection closes either way.
        loop.add_signal_handler(received, stop.set)
    await stop.wait()

    log.info("worker_stopping")
    scheduler.shutdown(wait=True)


async def run_once(name: str) -> int:
    """Run one job by hand, now. ``make job n=silence_detection``.

    The recovery path, and the reason every job is idempotent: an operator
    re-running retention after a failure must not delete twice, and one
    re-running the capture window must not raise the alert twice.
    """
    settings = get_settings()
    configure_logging(settings.log_level, settings.environment)
    job = ALL_JOBS.get(name)
    if job is None:
        print(f"unknown job {name!r}. Known: {', '.join(sorted(ALL_JOBS))}")
        return 1
    result = await JobRunner(on_repeated_failure=alert_on_repeated_failure).run(
        name, job
    )
    if result.error:
        print(f"{name} failed: {result.error}")
        return 1
    print(f"{name}: {'skipped (locked)' if not result.ran else result.processed}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--once":
        raise SystemExit(asyncio.run(run_once(sys.argv[2])))
    asyncio.run(run_forever())
