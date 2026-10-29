from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar
from uuid import uuid4

from arvuno_core.automation.errors import (
    AutomationStateError,
    AutomationValidationError,
    NotificationNotFoundError,
)
from arvuno_core.automation.models import (
    NotificationLevel,
    NotificationPage,
    StoredNotification,
)
from arvuno_core.events.models import ArvunoEvent, ArvunoEventType, TaskFailedPayload
from arvuno_core.persistence.automations import NotificationRecordCreate
from arvuno_core.persistence.exceptions import RepositoryError

logger = logging.getLogger(__name__)


class NotificationUnitOfWorkProtocol(Protocol):
    notifications: Any

    def __enter__(self) -> NotificationUnitOfWorkProtocol: ...

    def commit(self) -> None: ...


UnitOfWorkFactory = Callable[[], NotificationUnitOfWorkProtocol]


@dataclass(frozen=True)
class NotificationResult:
    notification: StoredNotification
    created: bool


class NotificationService:
    """Stores the small set of in-app notifications required by Arvuno."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        notification_id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._notification_id_factory = notification_id_factory

    async def handle_task_failed(self, event: ArvunoEvent) -> None:
        if event.event_type is not ArvunoEventType.TASK_FAILED:
            return
        if not isinstance(event.payload, TaskFailedPayload):
            return
        await self.create(
            channel="web_console",
            title="任务失败",
            content=f"{event.payload.error_message}（任务 {event.payload.task_id}）",
            level=NotificationLevel.ERROR,
            related_event_id=event.id,
            related_task_id=event.payload.task_id,
        )

    async def create(
        self,
        *,
        channel: str,
        title: str,
        content: str,
        level: NotificationLevel,
        related_event_id: str | None = None,
        related_task_id: str | None = None,
    ) -> StoredNotification:
        notification_id = self._notification_id_factory()
        now = self._now()

        def persist() -> StoredNotification:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.notifications is None:
                    raise AutomationStateError("The notification repository is unavailable.")
                stored = unit_of_work.notifications.create(
                    NotificationRecordCreate(
                        id=notification_id,
                        channel=channel,
                        title=title,
                        content=content,
                        level=level.value,
                        related_event_id=related_event_id,
                        related_task_id=related_task_id,
                        created_at=now,
                        sent_at=now,
                    )
                )
                unit_of_work.commit()
                return stored

        return await self._repository_call(persist)

    async def list(
        self,
        *,
        level: str | None = None,
        unread_only: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> NotificationPage:
        def query() -> NotificationPage:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.notifications is None:
                    raise AutomationStateError("The notification repository is unavailable.")
                return unit_of_work.notifications.list(
                    level=level,
                    unread_only=unread_only,
                    page=page,
                    page_size=page_size,
                )

        items, total = await self._repository_call(query)
        return NotificationPage(items=items, total=total)

    async def mark_read(self, notification_id: str) -> StoredNotification:
        def persist() -> StoredNotification | None:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.notifications is None:
                    raise AutomationStateError("The notification repository is unavailable.")
                stored = unit_of_work.notifications.mark_read(notification_id)
                if stored is None:
                    return None
                unit_of_work.commit()
                return stored

        notification = await self._repository_call(persist)
        if notification is None:
            raise NotificationNotFoundError("The notification does not exist.")
        return notification

    async def _repository_call(self, operation: Callable[[], _T]) -> _T:
        try:
            return await asyncio.to_thread(operation)
        except RepositoryError as exc:
            raise AutomationStateError(str(exc)) from exc
        except ValueError as exc:
            raise AutomationValidationError(str(exc)) from exc

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


_T = TypeVar("_T")


__all__ = ["NotificationResult", "NotificationService"]
