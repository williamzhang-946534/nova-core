from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arvuno_core.automation.models import (
    AutomationAction,
    AutomationRunStatus,
    AutomationTrigger,
    AutomationUpdate,
    StoredAutomation,
    StoredAutomationRun,
    StoredNotification,
)
from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import Automation, AutomationRun, Notification


def _trigger_from_json(value: dict[str, Any]) -> AutomationTrigger:
    return AutomationTrigger.model_validate(value)


def _conditions_from_json(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    from arvuno_core.automation.models import AutomationCondition

    return [AutomationCondition.model_validate(item) for item in value]


def _action_from_json(value: dict[str, Any]) -> AutomationAction:
    from arvuno_core.automation.models import (
        AutomationNotificationAction,
        AutomationToolAction,
    )

    action_type = value.get("type")
    if action_type == "notification":
        return AutomationNotificationAction.model_validate(value)
    if action_type == "tool":
        return AutomationToolAction.model_validate(value)
    raise RepositoryError("Unknown automation action type.")


def _to_stored(entity: Automation) -> StoredAutomation:
    return StoredAutomation(
        id=entity.id,
        name=entity.name,
        description=entity.description,
        enabled=entity.enabled,
        trigger=_trigger_from_json(entity.trigger),
        conditions=_conditions_from_json(entity.condition),
        action=_action_from_json(entity.action),
        cooldown_seconds=entity.cooldown_seconds,
        risk_level=entity.risk_level,
        created_at=_utc(entity.created_at),
        updated_at=_utc(entity.updated_at),
    )


def _to_stored_run(entity: AutomationRun) -> StoredAutomationRun:
    return StoredAutomationRun(
        id=entity.id,
        automation_id=entity.automation_id,
        event_id=entity.event_id,
        status=AutomationRunStatus(entity.status),
        matched_context=entity.matched_context,
        task_id=entity.task_id,
        notification_id=_optional_str((entity.matched_context or {}).get("notification_id")),
        error=_json_object(entity.error),
        started_at=_utc(entity.started_at),
        completed_at=_utc(entity.completed_at) if entity.completed_at is not None else None,
    )


def _to_stored_notification(entity: Notification) -> StoredNotification:
    from arvuno_core.automation.models import NotificationLevel, NotificationStatus

    return StoredNotification(
        id=entity.id,
        channel=entity.channel,
        title=entity.title,
        content=entity.content,
        level=NotificationLevel(entity.level),
        status=NotificationStatus(entity.status),
        related_event_id=entity.related_event_id,
        related_task_id=entity.related_task_id,
        created_at=_utc(entity.created_at),
        sent_at=_utc(entity.sent_at) if entity.sent_at is not None else None,
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _json_object(value: dict[str, Any] | None) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _action_risk_level(action: AutomationAction) -> str:
    from arvuno_core.automation.models import AutomationActionType

    if action.type is AutomationActionType.TOOL:
        return action.risk_level.value
    return "read_only"


@dataclass(frozen=True)
class AutomationRecordCreate:
    id: str
    name: str
    description: str | None
    enabled: bool
    trigger: dict[str, Any]
    condition: list[dict[str, Any]] | None
    action: dict[str, Any]
    cooldown_seconds: int
    risk_level: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AutomationRunRecordCreate:
    id: str
    automation_id: str
    event_id: str | None
    status: AutomationRunStatus
    matched_context: dict[str, Any]
    task_id: str | None
    error: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None


class AutomationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, record: AutomationRecordCreate) -> StoredAutomation:
        try:
            entity = Automation(
                id=record.id,
                name=record.name,
                description=record.description,
                enabled=record.enabled,
                trigger=record.trigger,
                condition=record.condition,
                action=record.action,
                cooldown_seconds=record.cooldown_seconds,
                risk_level=record.risk_level,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            self._session.add(entity)
            self._session.flush()
            return _to_stored(entity)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save the automation.") from exc

    def get(self, automation_id: str) -> StoredAutomation | None:
        try:
            entity = self._session.get(Automation, automation_id)
            return None if entity is None else _to_stored(entity)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read the automation.") from exc

    def list_enabled_by_event_type(self, event_type: str) -> list[StoredAutomation]:
        try:
            statement = (
                select(Automation)
                .where(Automation.enabled.is_(True))
                .order_by(Automation.created_at, Automation.id)
            )
            entities = list(self._session.scalars(statement))
            stored = [_to_stored(entity) for entity in entities]
            return [item for item in stored if item.trigger.event_type == event_type]
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list automations.") from exc

    def list(
        self,
        *,
        enabled: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[StoredAutomation], int]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("Page must be positive and page_size must be between 1 and 100")
        try:
            filters = []
            if enabled is not None:
                filters.append(Automation.enabled.is_(enabled))
            statement = select(Automation).where(*filters)
            count_statement = select(func.count()).select_from(Automation).where(*filters)
            total = self._session.scalar(count_statement) or 0
            entities = list(
                self._session.scalars(
                    statement.order_by(Automation.created_at, Automation.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            return [_to_stored(entity) for entity in entities], int(total)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list automations.") from exc

    def update(
        self,
        automation_id: str,
        update: AutomationUpdate,
        *,
        now: datetime,
    ) -> StoredAutomation | None:
        try:
            entity = self._session.get(Automation, automation_id)
            if entity is None:
                return None
            if update.name is not None:
                entity.name = update.name
            if update.description is not None:
                entity.description = update.description
            if update.enabled is not None:
                entity.enabled = update.enabled
            if update.trigger is not None:
                entity.trigger = update.trigger.model_dump(mode="json")
            if update.conditions is not None:
                entity.condition = [
                    condition.model_dump(mode="json") for condition in update.conditions
                ]
            if update.action is not None:
                entity.action = update.action.model_dump(mode="json")
                entity.risk_level = _action_risk_level(update.action)
            if update.cooldown_seconds is not None:
                entity.cooldown_seconds = update.cooldown_seconds
            entity.updated_at = now
            return _to_stored(entity)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to update the automation.") from exc


class AutomationRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, record: AutomationRunRecordCreate) -> StoredAutomationRun:
        try:
            entity = AutomationRun(
                id=record.id,
                automation_id=record.automation_id,
                event_id=record.event_id,
                status=record.status.value,
                matched_context=record.matched_context,
                task_id=record.task_id,
                error=record.error,
                started_at=record.started_at,
                completed_at=record.completed_at,
            )
            self._session.add(entity)
            self._session.flush()
            return _to_stored_run(entity)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save the automation run.") from exc

    def update(
        self,
        run_id: str,
        *,
        status: AutomationRunStatus,
        matched_context: dict[str, Any],
        task_id: str | None,
        error: dict[str, Any] | None,
        completed_at: datetime,
    ) -> StoredAutomationRun | None:
        try:
            entity = self._session.get(AutomationRun, run_id)
            if entity is None:
                return None
            entity.status = status.value
            if matched_context:
                entity.matched_context = matched_context
            entity.task_id = task_id
            entity.error = error
            entity.completed_at = completed_at
            return _to_stored_run(entity)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to update the automation run.") from exc

    def latest_run(
        self,
        automation_id: str,
        *,
        statuses: set[AutomationRunStatus] | None = None,
    ) -> StoredAutomationRun | None:
        try:
            statement = select(AutomationRun).where(AutomationRun.automation_id == automation_id)
            if statuses is not None:
                statement = statement.where(
                    AutomationRun.status.in_([status.value for status in statuses])
                )
            statement = statement.order_by(
                AutomationRun.started_at.desc(),
                AutomationRun.id.desc(),
            ).limit(1)
            entity = self._session.scalars(statement).first()
            return _to_stored_run(entity) if entity is not None else None
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read the latest automation run.") from exc

    def list(
        self,
        automation_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[StoredAutomationRun], int]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("Page must be positive and page_size must be between 1 and 100")
        try:
            statement = select(AutomationRun).where(AutomationRun.automation_id == automation_id)
            count_statement = (
                select(func.count())
                .select_from(AutomationRun)
                .where(AutomationRun.automation_id == automation_id)
            )
            total = self._session.scalar(count_statement) or 0
            entities = list(
                self._session.scalars(
                    statement.order_by(AutomationRun.started_at.desc(), AutomationRun.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            return [_to_stored_run(entity) for entity in entities], int(total)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list automation runs.") from exc


@dataclass(frozen=True)
class NotificationRecordCreate:
    id: str
    channel: str
    title: str
    content: str
    level: str
    related_event_id: str | None
    related_task_id: str | None
    created_at: datetime
    sent_at: datetime


class NotificationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, record: NotificationRecordCreate) -> StoredNotification:
        try:
            entity = Notification(
                id=record.id,
                channel=record.channel,
                title=record.title,
                content=record.content,
                level=record.level,
                status="sent",
                related_event_id=record.related_event_id,
                related_task_id=record.related_task_id,
                created_at=record.created_at,
                sent_at=record.sent_at,
            )
            self._session.add(entity)
            self._session.flush()
            return _to_stored_notification(entity)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save the notification.") from exc

    def get(self, notification_id: str) -> StoredNotification | None:
        try:
            entity = self._session.get(Notification, notification_id)
            return None if entity is None else _to_stored_notification(entity)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read the notification.") from exc

    def mark_read(self, notification_id: str) -> StoredNotification | None:
        try:
            entity = self._session.get(Notification, notification_id)
            if entity is None:
                return None
            entity.status = "read"
            return _to_stored_notification(entity)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to update the notification.") from exc

    def list(
        self,
        *,
        level: str | None = None,
        unread_only: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[StoredNotification], int]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("Page must be positive and page_size must be between 1 and 100")
        try:
            filters = []
            if level is not None:
                filters.append(Notification.level == level)
            if unread_only:
                filters.append(Notification.status != "read")
            statement = select(Notification).where(*filters)
            count_statement = select(func.count()).select_from(Notification).where(*filters)
            total = self._session.scalar(count_statement) or 0
            entities = list(
                self._session.scalars(
                    statement.order_by(Notification.created_at.desc(), Notification.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            return [_to_stored_notification(entity) for entity in entities], int(total)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list notifications.") from exc
