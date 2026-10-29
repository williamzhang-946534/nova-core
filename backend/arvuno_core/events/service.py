import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from arvuno_core.devices.models import DeviceEvent
from arvuno_core.devices.registry import DeviceRegistry
from arvuno_core.events.bus import EventBus, normalize_datetime
from arvuno_core.events.conversion import device_event_to_arvuno_event
from arvuno_core.events.errors import EventPersistenceError
from arvuno_core.events.models import ArvunoEvent
from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.repositories import EventRecordCreate
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]


@dataclass(frozen=True)
class EventPage:
    items: list[ArvunoEvent]
    total: int


class DeviceEventService:
    """Localizes adapter events, records observed state, and publishes Arvuno events."""

    def __init__(self, registry: DeviceRegistry, event_bus: EventBus) -> None:
        self._registry = registry
        self._event_bus = event_bus

    async def publish(self, event: DeviceEvent) -> ArvunoEvent:
        registered = await self._registry.get_by_id(event.subject_id)
        if registered is None and event.external_id is not None:
            registered = await self._registry.get_by_external_id(
                event.source,
                event.external_id,
            )
        if registered is None:
            raise KeyError(f"No device projection found for adapter event {event.subject_id}")

        arvuno_event = device_event_to_arvuno_event(
            event,
            device_id=registered.id,
            device_type=registered.device_type,
        )
        await self._event_bus.publish(arvuno_event)
        await self._record_observed_state(event, registered.id)
        return arvuno_event

    async def _record_observed_state(self, event: DeviceEvent, device_id: str) -> None:
        payload = event.payload
        current_state = str(payload.get("current_state", "unavailable"))
        attributes = payload.get("attributes")
        await self._registry.record_observed_state(
            device_id,
            state=current_state,
            attributes=attributes if isinstance(attributes, dict) else {},
            source=event.source,
            observed_at=event.occurred_at,
        )


class EventQueryService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def list(
        self,
        *,
        event_type: str | None = None,
        source: str | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        correlation_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        order: str = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> EventPage:
        def execute() -> EventPage:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.events is None:
                    raise RuntimeError("The event repository is not available.")
                items, total = unit_of_work.events.query(
                    event_type=event_type,
                    source=source,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    correlation_id=correlation_id,
                    start_time=start_time,
                    end_time=end_time,
                    order=order,
                    page=page,
                    page_size=page_size,
                )
                return EventPage(items=[_domain_event(item) for item in items], total=total)

        return await asyncio.to_thread(execute)

    async def get(self, event_id: str) -> ArvunoEvent | None:
        def execute() -> ArvunoEvent | None:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.events is None:
                    raise RuntimeError("The event repository is not available.")
                record = unit_of_work.events.get(event_id)
                return _domain_event(record) if record is not None else None

        return await asyncio.to_thread(execute)


class EventRetentionService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def cleanup(
        self,
        *,
        now: datetime,
        retention_days: int,
        diagnostic_retention_days: int,
        long_term_event_types: list[str],
    ) -> int:
        def execute() -> int:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.events is None:
                    raise RuntimeError("The event repository is not available.")
                deleted = unit_of_work.events.cleanup_expired(
                    now=now,
                    retention_days=retention_days,
                    diagnostic_retention_days=diagnostic_retention_days,
                    long_term_event_types=long_term_event_types,
                )
                unit_of_work.commit()
                return deleted

        return await asyncio.to_thread(execute)


def _domain_event(record: object) -> ArvunoEvent:
    values = {
        "id": record.id,  # type: ignore[attr-defined]
        "event_type": record.event_type,  # type: ignore[attr-defined]
        "source": record.source,  # type: ignore[attr-defined]
        "subject_type": record.subject_type,  # type: ignore[attr-defined]
        "subject_id": record.subject_id,  # type: ignore[attr-defined]
        "payload": record.payload,  # type: ignore[attr-defined]
        "correlation_id": record.correlation_id,  # type: ignore[attr-defined]
        "occurred_at": normalize_datetime(record.occurred_at),  # type: ignore[attr-defined]
        "created_at": normalize_datetime(record.created_at),  # type: ignore[attr-defined]
    }
    return ArvunoEvent.model_validate(values)


__all__ = [
    "DeviceEventService",
    "EventPage",
    "EventPersistenceError",
    "EventQueryService",
    "EventRecordCreate",
    "EventRetentionService",
    "RepositoryError",
]
