"""Running scheduled work exactly once (T150, SPEC §10.4).

Two properties, and both of them are the whole point:

**Only one worker runs a job at a time.** Held with a PostgreSQL *advisory*
lock rather than a row: an advisory lock is released automatically when the
session dies, so a worker that is killed mid-job does not leave a lock nobody
can clear. A second worker that cannot take the lock **skips** rather than
waits — a queued duplicate would run the job twice in a row, which is the thing
being prevented, only later.

**Every job is safe to run twice.** The lock stops two workers overlapping; it
does not stop a worker restarting after a crash and running the same job again,
and it does not stop an operator triggering one by hand. Idempotency is each
job's own responsibility and is asserted in each job's test.

A job that raises does so loudly: the traceback is logged, and three
consecutive failures raise an alert. A scheduler that fails silently is worse
than no scheduler, because the absence of alerts then means nothing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock, database
from src.core.logging import get_logger

log = get_logger(__name__)

#: SPEC §10.4: three consecutive failures raise the alert.
FAILURES_BEFORE_ALERT = 3

#: A job still holding its lock after this is assumed wedged, and the next run
#: is skipped rather than piling up behind it. Chosen longer than the slowest
#: job (retention over a year of audio) and shorter than any daily cadence.
MAX_JOB_RUNTIME = timedelta(minutes=30)

#: The signature every job callable has: it is handed a session and owns the
#: transaction inside it, exactly like a service method serving a request.
JobCallable = Callable[[AsyncSession], Awaitable[int]]


def lock_key(name: str) -> int:
    """A stable 63-bit advisory-lock key for a job name.

    Derived from the name so two workers on different releases agree without
    sharing a table, and truncated to fit ``bigint``.
    """
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (2**63)


@dataclass
class JobResult:
    """What one run did, for the log line and for the tests."""

    name: str
    ran: bool
    processed: int = 0
    error: str | None = None
    duration_ms: int = 0


@dataclass
class JobRunner:
    """Runs registered jobs under an advisory lock, and counts failures."""

    consecutive_failures: dict[str, int] = field(default_factory=dict)

    async def run(self, name: str, job: JobCallable) -> JobResult:
        """Run ``job`` if this process can take its lock.

        The lock is taken on a **dedicated connection** held for the duration.
        Sharing the request session would release the lock at the first commit,
        which is exactly halfway through most of these jobs.
        """
        started = clock.now()
        engine = database.get_engine()
        async with engine.connect() as lock_connection:
            acquired = await lock_connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key(name)}
            )
            if not acquired:
                log.info("job_skipped", job=name, reason="another worker holds the lock")
                return JobResult(name=name, ran=False)
            try:
                async with database.get_sessionmaker()() as session:
                    log.info("job_started", job=name)
                    processed = await job(session)
                duration = int((clock.now() - started).total_seconds() * 1000)
                self.consecutive_failures[name] = 0
                log.info(
                    "job_finished", job=name, processed=processed, duration_ms=duration
                )
                return JobResult(
                    name=name, ran=True, processed=processed, duration_ms=duration
                )
            except Exception as exc:  # a job may fail for any reason; it must be loud
                failures = self.consecutive_failures.get(name, 0) + 1
                self.consecutive_failures[name] = failures
                log.exception("job_failed", job=name, consecutive_failures=failures)
                if failures >= FAILURES_BEFORE_ALERT:
                    await self._raise_failure_alert(name, failures, exc)
                return JobResult(
                    name=name,
                    ran=True,
                    error=f"{type(exc).__name__}: {exc}",
                    duration_ms=int((clock.now() - started).total_seconds() * 1000),
                )
            finally:
                # Released explicitly rather than relying on the connection
                # closing, so the lock is gone before the next tick even if the
                # pool holds the connection open.
                await lock_connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key(name)}
                )

    async def _raise_failure_alert(self, name: str, failures: int, exc: Exception) -> None:
        """Three strikes. Raised on its own session, because the job's failed.

        Imported here rather than at module level: ``core`` must not import a
        module (§2), and the composition root cannot inject into a dataclass
        the scheduler builds. This one call is the exception, and it is a write
        to the alerts table by the only process that can know a job failed.
        """
        from src.core.enums import AlertKind, AlertSeverity
        from src.modules.alerts.service import AlertService

        kind = (
            AlertKind.BACKUP_FAILED
            if name == "backup_verify"
            else AlertKind.RETENTION_JOB_FAILED
        )
        try:
            async with database.get_sessionmaker()() as session:
                await AlertService(session).raise_alert(
                    kind=kind,
                    severity=AlertSeverity.CRITICAL,
                    scope=name,
                    detail={
                        "job": name,
                        "consecutive_failures": failures,
                        "error": f"{type(exc).__name__}",
                    },
                )
                await session.commit()
        except Exception:  # the database is the likely cause of the job failing
            log.exception("job_failure_alert_failed", job=name)


__all__ = [
    "FAILURES_BEFORE_ALERT",
    "MAX_JOB_RUNTIME",
    "JobCallable",
    "JobResult",
    "JobRunner",
    "lock_key",
]
