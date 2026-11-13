import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, Protocol

from arvuno_core.retention.models import RetentionPolicy

logger = logging.getLogger(__name__)


class RetentionJob(Protocol):
    name: str

    async def run(self, *, now: datetime) -> int: ...

    def policy(self) -> RetentionPolicy: ...


class RetentionRunStore(Protocol):
    def record_started(self, *, job_name: str, started_at: datetime) -> str: ...

    def record_success(self, run_id: str, **values: Any) -> None: ...

    def record_failure(self, run_id: str, **values: Any) -> None: ...

    async def latest(self) -> dict[str, dict[str, Any]]: ...

    async def failures(self, *, limit: int = 50) -> list[dict[str, Any]]: ...


class RetentionConflictError(Exception):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RetentionScheduler:
    """Single-process sequential scheduler for bounded retention jobs."""

    def __init__(
        self,
        *,
        jobs: list[RetentionJob],
        run_store: RetentionRunStore,
        tick_seconds: int,
        manual_cooldown_seconds: int,
        clock: Callable[[], datetime],
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._jobs = {job.name: job for job in jobs}
        self._run_store = run_store
        self._tick_seconds = tick_seconds
        self._manual_cooldown_seconds = manual_cooldown_seconds
        self._clock = clock
        self._sleep = sleep or asyncio.sleep
        now = self._clock()
        self._next_run_at = {
            name: now + timedelta(seconds=job.policy().interval_seconds)
            for name, job in self._jobs.items()
        }
        self._running_names: set[str] = set()
        self._last_manual_started_at: datetime | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return

    async def run_due(self, *, now: datetime | None = None) -> list[str]:
        current = now or self._clock()
        names = [
            name
            for name, job in self._jobs.items()
            if job.policy().enabled and self._next_run_at.get(name, current) <= current
        ]
        await self._run_jobs(names, current)
        return names

    async def run_manual(self, names: list[str]) -> list[str]:
        current = self._clock()
        unknown = [name for name in names if name not in self._jobs]
        if unknown:
            raise RetentionConflictError(
                code="RETENTION_JOB_NOT_FOUND",
                message="One or more retention jobs do not exist.",
            )
        disabled = [name for name in names if not self._jobs[name].policy().enabled]
        if disabled:
            raise RetentionConflictError(
                code="RETENTION_JOB_DISABLED",
                message="One or more retention jobs are disabled.",
            )
        overlap = sorted(self._running_names.intersection(names))
        if overlap:
            raise RetentionConflictError(
                code="RETENTION_JOB_RUNNING",
                message="One or more retention jobs are already running.",
            )
        last = self._last_manual_started_at
        if last is not None and current - last < timedelta(seconds=self._manual_cooldown_seconds):
            raise RetentionConflictError(
                code="RETENTION_MANUAL_COOLDOWN",
                message="Manual retention execution is cooling down.",
            )
        self._last_manual_started_at = current
        await self._run_jobs(names, current)
        return names

    def policies(self) -> list[dict[str, Any]]:
        return [job.policy().view() for job in self._jobs.values()]

    async def status(self) -> dict[str, Any]:
        latest = await self._run_store.latest()
        return {
            "single_process_only": True,
            "jobs": [
                {
                    **self._jobs[name].policy().view(),
                    "next_run_at": self._next_run_at.get(name),
                    "last_run": latest.get(name),
                }
                for name in self._jobs
            ],
        }

    async def failures(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return await self._run_store.failures(limit=limit)

    @property
    def running_job_names(self) -> set[str]:
        return set(self._running_names)

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run_loop(self) -> None:
        while True:
            await self.run_due()
            now = self._clock()
            next_times = [
                value
                for name, value in self._next_run_at.items()
                if self._jobs[name].policy().enabled
            ]
            if next_times:
                delay = max(0.0, min((value - now).total_seconds() for value in next_times))
            else:
                delay = float(self._tick_seconds)
            await self._sleep(min(delay, float(self._tick_seconds)))

    async def _run_jobs(self, names: list[str], started_at: datetime) -> None:
        overlap = sorted(self._running_names.intersection(names))
        if overlap:
            raise RetentionConflictError(
                code="RETENTION_JOB_RUNNING",
                message="One or more retention jobs are already running.",
            )
        selected = [self._jobs[name] for name in names]
        self._running_names.update(names)
        try:
            for job in selected:
                await self._run_job(job, started_at)
        finally:
            self._running_names.difference_update(names)

    async def _run_job(self, job: RetentionJob, started_at: datetime) -> None:
        run_id: str | None = None
        policy = job.policy()
        try:
            run_id = await asyncio.to_thread(
                self._run_store.record_started,
                job_name=job.name,
                started_at=started_at,
            )
            affected = await job.run(now=started_at)
            finished_at = self._clock()
            next_run_at = finished_at + timedelta(seconds=policy.interval_seconds)
            self._next_run_at[job.name] = next_run_at
            await asyncio.to_thread(
                self._run_store.record_success,
                run_id,
                finished_at=finished_at,
                affected_count=affected,
                next_run_at=next_run_at,
                details={},
            )
        except asyncio.CancelledError:
            failed_at = self._clock()
            next_run_at = failed_at + timedelta(seconds=policy.interval_seconds)
            self._next_run_at[job.name] = next_run_at
            if run_id is not None:
                try:
                    self._run_store.record_failure(
                        run_id,
                        finished_at=failed_at,
                        next_run_at=next_run_at,
                        error_code="CANCELLED",
                        error_message="The retention job was cancelled.",
                    )
                except Exception:
                    logger.exception("retention_failure_record_failed")
            raise
        except Exception as exc:
            logger.exception(
                "retention_job_failed",
                extra={"payload": {"job_name": job.name, "error_code": type(exc).__name__}},
            )
            failed_at = self._clock()
            next_run_at = failed_at + timedelta(seconds=policy.interval_seconds)
            self._next_run_at[job.name] = next_run_at
            if run_id is not None:
                await self._safe_record_failure(
                    run_id,
                    finished_at=failed_at,
                    next_run_at=next_run_at,
                    error_code=type(exc).__name__,
                    error_message="The retention job failed.",
                )

    async def _safe_record_failure(self, run_id: str, **values: Any) -> None:
        try:
            await asyncio.to_thread(self._run_store.record_failure, run_id, **values)
        except Exception:
            logger.exception("retention_failure_record_failed")
