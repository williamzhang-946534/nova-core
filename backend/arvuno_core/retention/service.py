import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

from arvuno_core.config import Settings
from arvuno_core.events.service import EventRetentionService
from arvuno_core.multimodal.service import MultimodalService
from arvuno_core.observations.pipeline import ObservationPipeline
from arvuno_core.persistence.provider_logs import SqlProviderLogStore
from arvuno_core.persistence.retention import SqlRetentionRunStore
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.proactive.service import ProactiveService
from arvuno_core.retention.models import RetentionPolicy
from arvuno_core.retention.scheduler import RetentionScheduler


class RetentionJob(Protocol):
    name: str

    async def run(self, *, now: datetime) -> int: ...

    def policy(self) -> RetentionPolicy: ...


class EventRetentionJob:
    name = "event"

    def __init__(
        self,
        service: EventRetentionService,
        settings: Settings,
    ) -> None:
        self._service = service
        self._settings = settings

    async def run(self, *, now: datetime) -> int:
        return await self._service.cleanup(
            now=now,
            retention_days=self._settings.event_retention_days,
            diagnostic_retention_days=self._settings.diagnostic_event_retention_days,
            long_term_event_types=self._settings.long_term_event_types,
            limit=self._settings.event_retention_batch_size,
        )

    def policy(self) -> RetentionPolicy:
        return RetentionPolicy(
            name=self.name,
            label="Domain events",
            enabled=self._settings.event_retention_cleanup_enabled,
            interval_seconds=self._settings.event_retention_interval_seconds,
            batch_size=self._settings.event_retention_batch_size,
            rules={
                "default_retention_days": self._settings.event_retention_days,
                "diagnostic_retention_days": self._settings.diagnostic_event_retention_days,
                "long_term_event_types": self._settings.long_term_event_types,
            },
        )


class ObservationRetentionJob:
    name = "observation"

    def __init__(
        self,
        pipeline: ObservationPipeline,
        settings: Settings,
    ) -> None:
        self._pipeline = pipeline
        self._settings = settings

    async def run(self, *, now: datetime) -> int:
        return await self._pipeline.cleanup_expired(
            now=now,
            limit=self._settings.observation_retention_batch_size,
            batch_retention_days=self._settings.observation_ingestion_batch_retention_days,
        )

    def policy(self) -> RetentionPolicy:
        return RetentionPolicy(
            name=self.name,
            label="Observations",
            enabled=self._settings.observation_retention_cleanup_enabled,
            interval_seconds=self._settings.observation_retention_interval_seconds,
            batch_size=self._settings.observation_retention_batch_size,
            rules={
                "record_policy": "per-observation retention_until",
                "ingestion_batch_retention_days": (
                    self._settings.observation_ingestion_batch_retention_days
                ),
            },
        )


class MultimodalRetentionJob:
    name = "multimodal_media"

    def __init__(
        self,
        service: MultimodalService,
        settings: Settings,
    ) -> None:
        self._service = service
        self._settings = settings

    async def run(self, *, now: datetime) -> int:
        return await self._service.purge_expired(
            now,
            limit=self._settings.multimodal_media_retention_batch_size,
        )

    def policy(self) -> RetentionPolicy:
        return RetentionPolicy(
            name=self.name,
            label="Multimodal media",
            enabled=self._settings.multimodal_media_retention_cleanup_enabled,
            interval_seconds=self._settings.multimodal_media_retention_interval_seconds,
            batch_size=self._settings.multimodal_media_retention_batch_size,
            rules={"record_policy": "per-asset retention_until and purge_status"},
        )


class ProactiveRetentionJob:
    name = "proactive"

    def __init__(
        self,
        service: ProactiveService,
        settings: Settings,
    ) -> None:
        self._service = service
        self._settings = settings

    async def run(self, *, now: datetime) -> int:
        return await self._service.cleanup_expired(
            now=now,
            limit=self._settings.proactive_retention_batch_size,
        )

    def policy(self) -> RetentionPolicy:
        return RetentionPolicy(
            name=self.name,
            label="Proactive suggestions",
            enabled=self._settings.proactive_retention_cleanup_enabled,
            interval_seconds=self._settings.proactive_retention_interval_seconds,
            batch_size=self._settings.proactive_retention_batch_size,
            rules={"action": "mark expired at suggestion expires_at"},
        )


class EnvironmentSnapshotRetentionJob:
    name = "environment_snapshot"

    def __init__(
        self,
        unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork],
        settings: Settings,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._settings = settings

    async def run(self, *, now: datetime) -> int:
        def execute() -> int:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.environments is None:
                    raise RuntimeError("The environment repository is unavailable.")
                deleted = unit_of_work.environments.cleanup_expired_snapshots(
                    now=now,
                    retention_days=self._settings.environment_snapshot_retention_days,
                    limit=self._settings.environment_snapshot_retention_batch_size,
                )
                unit_of_work.commit()
                return deleted

        return await asyncio.to_thread(execute)

    def policy(self) -> RetentionPolicy:
        return RetentionPolicy(
            name=self.name,
            label="Environment snapshots",
            enabled=self._settings.environment_snapshot_retention_cleanup_enabled,
            interval_seconds=self._settings.environment_snapshot_retention_interval_seconds,
            batch_size=self._settings.environment_snapshot_retention_batch_size,
            rules={"retention_days": self._settings.environment_snapshot_retention_days},
        )


class ProviderLogRetentionJob:
    name = "provider_log"

    def __init__(
        self,
        store: SqlProviderLogStore,
        settings: Settings,
    ) -> None:
        self._store = store
        self._settings = settings

    async def run(self, *, now: datetime) -> int:
        debug_cleaned = await self._store.cleanup_expired_debug(
            now,
            limit=self._settings.provider_log_retention_batch_size,
        )
        deleted = await self._store.cleanup_expired(
            now=now,
            retention_days=self._settings.provider_log_retention_days,
            limit=self._settings.provider_log_retention_batch_size,
        )
        return debug_cleaned + deleted

    def policy(self) -> RetentionPolicy:
        return RetentionPolicy(
            name=self.name,
            label="Provider logs",
            enabled=self._settings.provider_log_retention_cleanup_enabled,
            interval_seconds=self._settings.provider_log_retention_interval_seconds,
            batch_size=self._settings.provider_log_retention_batch_size,
            rules={
                "metadata_retention_days": self._settings.provider_log_retention_days,
                "debug_capture": "redacted and removed at its short expiry",
            },
        )


def build_retention_scheduler(
    *,
    settings: Settings,
    unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork],
    observation_pipeline: ObservationPipeline,
    multimodal_service: MultimodalService,
    proactive_service: ProactiveService,
    provider_log_store: SqlProviderLogStore,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> RetentionScheduler:
    jobs: list[RetentionJob] = [
        EventRetentionJob(EventRetentionService(unit_of_work_factory), settings),
        ObservationRetentionJob(observation_pipeline, settings),
        MultimodalRetentionJob(multimodal_service, settings),
        ProactiveRetentionJob(proactive_service, settings),
        EnvironmentSnapshotRetentionJob(unit_of_work_factory, settings),
        ProviderLogRetentionJob(provider_log_store, settings),
    ]
    return RetentionScheduler(
        jobs=jobs,
        run_store=SqlRetentionRunStore(unit_of_work_factory),
        tick_seconds=settings.retention_scheduler_tick_seconds,
        manual_cooldown_seconds=settings.retention_manual_cooldown_seconds,
        clock=clock,
        sleep=sleep,
    )
