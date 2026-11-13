import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import RetentionRun


class RetentionRunRepository:
    """Persists bounded operational audit records for retention jobs."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record_started(self, *, job_name: str, started_at: datetime) -> str:
        run_id = str(uuid4())
        try:
            self._session.add(
                RetentionRun(
                    id=run_id,
                    job_name=job_name,
                    status="running",
                    started_at=started_at,
                    affected_count=0,
                    details={},
                )
            )
            self._session.flush()
            return run_id
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to record the retention run.") from exc

    def record_success(
        self,
        run_id: str,
        *,
        finished_at: datetime,
        affected_count: int,
        next_run_at: datetime,
        details: dict[str, Any],
    ) -> None:
        try:
            run = self._session.get(RetentionRun, run_id)
            if run is None:
                raise RepositoryError("The retention run does not exist.")
            run.status = "succeeded"
            run.finished_at = finished_at
            run.affected_count = affected_count
            run.next_run_at = next_run_at
            run.details = details
            self._session.flush()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to finish the retention run.") from exc

    def record_failure(
        self,
        run_id: str,
        *,
        finished_at: datetime,
        next_run_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        try:
            run = self._session.get(RetentionRun, run_id)
            if run is None:
                raise RepositoryError("The retention run does not exist.")
            run.status = "failed"
            run.finished_at = finished_at
            run.next_run_at = next_run_at
            run.error_code = error_code[:100]
            run.error_message = error_message[:500]
            self._session.flush()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to finish the retention run.") from exc

    def latest_by_job(self) -> dict[str, dict[str, Any]]:
        try:
            rows = self._session.scalars(
                select(RetentionRun).order_by(RetentionRun.started_at.desc(), RetentionRun.id)
            )
            latest: dict[str, dict[str, Any]] = {}
            for row in rows:
                if row.job_name in latest:
                    continue
                latest[row.job_name] = _view(row)
            return latest
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read retention runs.") from exc

    def list_failures(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        try:
            rows = self._session.scalars(
                select(RetentionRun)
                .where(RetentionRun.status == "failed")
                .order_by(RetentionRun.started_at.desc(), RetentionRun.id)
                .limit(limit)
            )
            return [_view(row) for row in rows]
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read retention failures.") from exc


class SqlRetentionRunStore:
    """Adapts retention run persistence to unit-of-work transactions."""

    def __init__(self, unit_of_work_factory: Callable[[], Any]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def record_started(self, *, job_name: str, started_at: datetime) -> str:
        with self._unit_of_work_factory() as unit_of_work:
            if unit_of_work.retention_runs is None:
                raise RepositoryError("The retention run repository is unavailable.")
            run_id = unit_of_work.retention_runs.record_started(
                job_name=job_name,
                started_at=started_at,
            )
            unit_of_work.commit()
            return run_id

    def record_success(self, run_id: str, **values: Any) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            if unit_of_work.retention_runs is None:
                raise RepositoryError("The retention run repository is unavailable.")
            unit_of_work.retention_runs.record_success(run_id, **values)
            unit_of_work.commit()

    def record_failure(self, run_id: str, **values: Any) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            if unit_of_work.retention_runs is None:
                raise RepositoryError("The retention run repository is unavailable.")
            unit_of_work.retention_runs.record_failure(run_id, **values)
            unit_of_work.commit()

    def latest_by_job(self) -> dict[str, dict[str, Any]]:
        with self._unit_of_work_factory() as unit_of_work:
            if unit_of_work.retention_runs is None:
                raise RepositoryError("The retention run repository is unavailable.")
            return unit_of_work.retention_runs.latest_by_job()

    def list_failures(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._unit_of_work_factory() as unit_of_work:
            if unit_of_work.retention_runs is None:
                raise RepositoryError("The retention run repository is unavailable.")
            return unit_of_work.retention_runs.list_failures(limit=limit)

    async def latest(self) -> dict[str, dict[str, Any]]:
        return await asyncio.to_thread(self.latest_by_job)

    async def failures(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.list_failures, limit=limit)


def _view(row: RetentionRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "job_name": row.job_name,
        "status": row.status,
        "started_at": _utc(row.started_at),
        "finished_at": _utc(row.finished_at) if row.finished_at is not None else None,
        "affected_count": row.affected_count,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "details": row.details,
        "next_run_at": _utc(row.next_run_at) if row.next_run_at is not None else None,
    }


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
