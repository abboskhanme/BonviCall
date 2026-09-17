"""The four scheduled entry points (SPEC-ANALYTICS §5).

``worker.py`` decides when these run; this file decides what they do. The whole
coupling is one line of shared code per job: a module exports
``async def (AsyncSession) -> int`` and the ``SCHEDULE`` entry names it. Task 8
adds those four entries and the alert mapping.

**No Celery and no broker.** BonviZvonki defined these as Celery tasks with a
sync-to-async bridge; BonviCall's worker is already an asyncio process running
APScheduler, and ``core/jobs.py::JobRunner`` takes a PostgreSQL advisory lock
per job name. So:

* between workers — ``pg_try_advisory_lock``: a second process **skips**;
* between a job and itself — ``max_instances=1``, ``coalesce=True``;
* between rows — ``FOR UPDATE SKIP LOCKED`` in ``pipeline.claim``.

Because the first of those holds, exactly one ``analysis_run`` executes
anywhere at a time, which is what lets the rate limiter be in-process and exact
rather than shared and approximate.

**Every one of these is safe to run twice.** The lock stops two workers
overlapping; it does not stop a restart, and it does not stop an operator
typing ``make job n=analysis_dispatch``. With ``analysis.enabled`` false all
four return 0 and touch nothing.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.analysis import pipeline


async def analysis_dispatch(session: AsyncSession) -> int:
    """Queue what has become eligible, every five minutes.

    Two pure-SQL statements, no provider contact: the calls matching §2.6 with
    no state row, and the ``skipped`` rows whose reason has stopped being true.
    Returns 0 and queues nothing when the flag is off or a monthly cap is
    reached.
    """
    return await pipeline.dispatch(session)


async def analysis_run(session: AsyncSession) -> int:
    """Claim a slice of the queue and analyse it. **The only job that spends.**

    Returns the number of calls processed, which is what the job log records —
    so "the pipeline is running and finding nothing" and "the pipeline is not
    running" are different lines rather than the same zero.
    """
    return await pipeline.run_queue(session)


async def analysis_retry_transient(session: AsyncSession) -> int:
    """Re-queue failures that repair themselves, nightly at 01:45.

    BonviZvonki's hardest-won lesson: its nightly run re-read a 48-hour window,
    so 885 calls that failed on a daily quota stayed ``failed`` for ever — the
    quota reset the next morning and nothing ever looked at them again.

    01:45 is between ``model_capture_stats`` (01:00) and ``audio_retention``
    (02:00) on purpose: a slow retry must not delay the job that deletes data.
    """
    return await pipeline.requeue_transient(session)


async def analysis_stale_reset(session: AsyncSession) -> int:
    """Close rows stuck in a running stage, hourly.

    The pipeline commits at every stage boundary deliberately, so a killed
    worker leaves a visible half-finished row rather than an invisible
    rollback. This closes them as ``interrupted``, which is transient — so the
    nightly retry puts them back in the queue.

    Runs whatever the flag says: a row left ``transcribing`` by a worker that
    died just before somebody turned the feature off would otherwise sit there
    for ever, and closing it spends nothing.
    """
    return await pipeline.reset_stale_running(session)


__all__ = [
    "analysis_dispatch",
    "analysis_retry_transient",
    "analysis_run",
    "analysis_stale_reset",
]
