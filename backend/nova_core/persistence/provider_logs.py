import asyncio
from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from nova_core.ai.storage import ProviderLogFinish, ProviderLogStart
from nova_core.persistence.exceptions import RepositoryError
from nova_core.persistence.models import ProviderLog


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


__all__ = ["ProviderLogRepository", "SqlProviderLogStore"]
