import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from arvuno_core.events.errors import EventPersistenceError, EventRecursionLimitExceeded
from arvuno_core.events.models import ArvunoEvent
from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork

logger = logging.getLogger(__name__)

EventHandler = Callable[[ArvunoEvent], Awaitable[None]]
UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]

_publish_depth: ContextVar[int] = ContextVar("arvuno_event_publish_depth", default=0)


@dataclass(frozen=True)
class EventSubscription:
    handler: EventHandler
    event_types: set[str] | None


class EventBus:
    """Persists events first, then dispatches them to in-process subscribers."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        max_publish_depth: int = 3,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._max_publish_depth = max_publish_depth
        self._subscriptions: dict[int, EventSubscription] = {}
        self._next_subscription_id = 1

    async def publish(self, event: ArvunoEvent) -> None:
        depth = _publish_depth.get()
        if depth > self._max_publish_depth:
            raise EventRecursionLimitExceeded(
                f"Event publishing exceeded the depth limit of {self._max_publish_depth}"
            )
        token = _publish_depth.set(depth + 1)
        try:
            try:
                await asyncio.to_thread(self._persist, event)
            except RepositoryError as exc:
                raise EventPersistenceError("The event could not be stored.") from exc
            await self._dispatch(event)
        finally:
            _publish_depth.reset(token)

    def subscribe(
        self,
        handler: EventHandler,
        event_types: set[str] | None = None,
    ) -> int:
        subscription_id = self._next_subscription_id
        self._next_subscription_id += 1
        self._subscriptions[subscription_id] = EventSubscription(
            handler=handler,
            event_types=None if event_types is None else set(event_types),
        )
        return subscription_id

    def unsubscribe(self, subscription_id: int) -> None:
        self._subscriptions.pop(subscription_id, None)

    def _persist(self, event: ArvunoEvent) -> None:
        from arvuno_core.persistence.repositories import EventRecordCreate

        record = EventRecordCreate(
            id=event.id,
            event_type=event.event_type.value,
            source=event.source.value,
            subject_type=event.subject_type,
            subject_id=event.subject_id,
            payload=event.payload.model_dump(mode="json"),
            correlation_id=event.correlation_id,
            occurred_at=event.occurred_at,
            created_at=event.created_at,
        )
        try:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.events is None:
                    raise RuntimeError("The event repository is not available.")
                unit_of_work.events.create_event(record)
                unit_of_work.commit()
        except RepositoryError as exc:
            logger.error(
                "event_persistence_failed",
                extra={
                    "event_id": event.id,
                    "event_type": event.event_type.value,
                    "correlation_id": event.correlation_id,
                },
            )
            raise EventPersistenceError("The event could not be stored.") from exc

    async def _dispatch(self, event: ArvunoEvent) -> None:
        for subscription in list(self._subscriptions.values()):
            if subscription.event_types is not None and (
                event.event_type.value not in subscription.event_types
            ):
                continue
            try:
                await subscription.handler(event)
            except Exception:
                logger.exception(
                    "event_subscriber_failed",
                    extra={
                        "event_id": event.id,
                        "event_type": event.event_type.value,
                        "correlation_id": event.correlation_id,
                    },
                )


def normalize_datetime(value: datetime) -> datetime:
    """Normalize datetimes read from storage to timezone-aware UTC values."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def event_extra(event: ArvunoEvent) -> dict[str, Any]:
    return {
        "event_id": event.id,
        "event_type": event.event_type.value,
        "correlation_id": event.correlation_id,
    }
