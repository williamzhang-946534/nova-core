import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from arvuno_core.ai.storage import ProviderLogFinish, ProviderLogStart
from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import ProviderLog


class ProviderLogRepository:
    """Persists redacted provider call summaries."""

    def __init__(self, session: Any) -> None:
        self._session = session

    def create(self, record: ProviderLogStart) -> ProviderLog:
        try:
            entity = ProviderLog(
                id=record.id,
                provider=record.provider,
                model=record.model,
                request_kind=record.request_kind,
                input_summary=record.input_summary,
                output_summary={},
                status=record.status,
                created_at=record.created_at,
            )
            self._session.add(entity)
            self._session.flush()
            return entity
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a provider log.") from exc

    def finish(self, log_id: str, record: ProviderLogFinish) -> ProviderLog:
        try:
            entity = self._session.get(ProviderLog, log_id)
            if entity is None:
                raise RepositoryError("The provider log does not exist.")
            entity.status = record.status
            entity.output_summary = record.output_summary
            entity.error = record.error
            entity.latency_ms = record.latency_ms
            entity.prompt_tokens = record.prompt_tokens
            entity.completion_tokens = record.completion_tokens
            return entity
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to update a provider log.") from exc

    def metadata(self, log_id: str) -> dict[str, Any]:
        try:
            entity = self._session.get(ProviderLog, log_id)
            if entity is None:
                raise RepositoryError("The provider log does not exist.")
            self._remove_expired_debug(entity, datetime.now(UTC))
            allowed_summary = {
                key: entity.input_summary.get(key)
                for key in (
                    "schema_version",
                    "request_id",
                    "correlation_id",
                    "message_count",
                    "role_distribution",
                )
            }
            return {
                "request_id": entity.id,
                "provider": entity.provider,
                "model": entity.model,
                "request_type": entity.request_kind,
                **allowed_summary,
                "input_token_count": entity.prompt_tokens,
                "output_token_count": entity.completion_tokens,
                "request_duration": entity.latency_ms,
                "response_status": entity.status,
                "error_code": None if entity.error is None else entity.error.get("code"),
                "created_at": entity.created_at,
            }
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a provider log.") from exc

    def cleanup_expired_debug(self, now: datetime, *, limit: int | None = None) -> int:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        try:
            statement = select(ProviderLog).order_by(ProviderLog.created_at, ProviderLog.id)
            if limit is not None:
                statement = statement.limit(limit)
            count = 0
            entities = self._session.scalars(statement).all()
            for entity in entities:
                if self._remove_expired_debug(entity, now):
                    count += 1
            return count
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to clean expired provider debug logs.") from exc

    def cleanup_expired(
        self,
        *,
        now: datetime,
        retention_days: int,
        limit: int,
    ) -> int:
        if retention_days < 1 or limit < 1:
            raise ValueError("Retention period and limit must be positive")
        try:
            cutoff = now - timedelta(days=retention_days)
            ids = list(
                self._session.scalars(
                    select(ProviderLog.id)
                    .where(ProviderLog.created_at < cutoff)
                    .order_by(ProviderLog.created_at, ProviderLog.id)
                    .limit(limit)
                )
            )
            if not ids:
                return 0
            result = self._session.execute(delete(ProviderLog).where(ProviderLog.id.in_(ids)))
            return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to clean expired provider logs.") from exc

    def _remove_expired_debug(self, entity: ProviderLog, now: datetime) -> bool:
        debug = entity.input_summary.get("debug")
        if not isinstance(debug, dict):
            return False
        expires_at = _parse_datetime(debug.get("expires_at"))
        if expires_at is not None and expires_at > now:
            return False
        summary = dict(entity.input_summary)
        summary.pop("debug", None)
        entity.input_summary = summary
        return True


class SqlProviderLogStore:
    """Adapts provider logging to the SQL transaction boundary."""

    def __init__(self, unit_of_work_factory: Callable[[], Any]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def start(self, record: ProviderLogStart) -> None:
        def persist() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.provider_logs is None:
                    raise RepositoryError("The provider log repository is unavailable.")
                unit_of_work.provider_logs.create(record)
                unit_of_work.commit()

        await asyncio.to_thread(persist)

    async def finish(self, log_id: str, record: ProviderLogFinish) -> None:
        def persist() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.provider_logs is None:
                    raise RepositoryError("The provider log repository is unavailable.")
                unit_of_work.provider_logs.finish(log_id, record)
                unit_of_work.commit()

        await asyncio.to_thread(persist)

    async def cleanup_expired_debug(
        self,
        now: datetime,
        *,
        limit: int | None = None,
    ) -> int:
        def persist() -> int:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.provider_logs is None:
                    raise RepositoryError("The provider log repository is unavailable.")
                count = unit_of_work.provider_logs.cleanup_expired_debug(now, limit=limit)
                unit_of_work.commit()
                return count

        return await asyncio.to_thread(persist)

    async def cleanup_expired(
        self,
        *,
        now: datetime,
        retention_days: int,
        limit: int,
    ) -> int:
        def persist() -> int:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.provider_logs is None:
                    raise RepositoryError("The provider log repository is unavailable.")
                count = unit_of_work.provider_logs.cleanup_expired(
                    now=now,
                    retention_days=retention_days,
                    limit=limit,
                )
                unit_of_work.commit()
                return count

        return await asyncio.to_thread(persist)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


__all__ = ["ProviderLogRepository", "SqlProviderLogStore"]
