from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, TypeVar
from uuid import uuid4

from arvuno_core.automation.errors import (
    AutomationNotFoundError,
    AutomationStateError,
    AutomationValidationError,
)
from arvuno_core.automation.evaluator import evaluate_conditions, matched_conditions
from arvuno_core.automation.models import (
    AUTOMATION_EVENT_TYPES,
    AutomationActionType,
    AutomationCreate,
    AutomationPage,
    AutomationRiskLevel,
    AutomationRunPage,
    AutomationRunStatus,
    AutomationToolAction,
    AutomationUpdate,
    StoredAutomation,
    StoredAutomationRun,
)
from arvuno_core.events.models import (
    ArvunoEvent,
    ArvunoEventSource,
    ArvunoEventType,
    AutomationTriggeredPayload,
)
from arvuno_core.persistence.automations import (
    AutomationRecordCreate,
    AutomationRunRecordCreate,
    NotificationRecordCreate,
)
from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.tasks.models import TaskCreate, TaskPlanStep, TaskStatus

logger = logging.getLogger(__name__)


class AutomationUnitOfWorkProtocol(Protocol):
    automations: Any
    automation_runs: Any
    notifications: Any

    def __enter__(self) -> AutomationUnitOfWorkProtocol: ...

    def commit(self) -> None: ...


UnitOfWorkFactory = Callable[[], AutomationUnitOfWorkProtocol]


class AutomationTaskServiceProtocol(Protocol):
    async def create_and_run(
        self,
        request: TaskCreate,
        *,
        correlation_id: str | None = None,
    ) -> Any: ...


class AutomationEventPublisherProtocol(Protocol):
    async def publish(self, event: ArvunoEvent) -> None: ...


@dataclass(frozen=True)
class AutomationExecutionResult:
    automation_id: str
    status: AutomationRunStatus
    task_id: str | None = None
    notification_id: str | None = None


class AutomationService:
    """Evaluates explicit Arvuno context rules without bypassing the tool boundary."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        task_service: AutomationTaskServiceProtocol,
        event_publisher: AutomationEventPublisherProtocol,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        automation_id_factory: Callable[[], str] = lambda: str(uuid4()),
        run_id_factory: Callable[[], str] = lambda: str(uuid4()),
        event_id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._task_service = task_service
        self._event_publisher = event_publisher
        self._clock = clock
        self._automation_id_factory = automation_id_factory
        self._run_id_factory = run_id_factory
        self._event_id_factory = event_id_factory
        self._locks: dict[str, asyncio.Lock] = {}

    async def create(self, request: AutomationCreate) -> StoredAutomation:
        automation_id = self._automation_id_factory()
        now = self._now()

        def persist() -> StoredAutomation:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.automations is None:
                    raise AutomationStateError("The automation repository is unavailable.")
                stored = unit_of_work.automations.create(
                    AutomationRecordCreate(
                        id=automation_id,
                        name=request.name,
                        description=request.description,
                        enabled=request.enabled,
                        trigger=request.trigger.model_dump(mode="json"),
                        condition=[
                            condition.model_dump(mode="json") for condition in request.conditions
                        ],
                        action=request.action.model_dump(mode="json"),
                        cooldown_seconds=request.cooldown_seconds,
                        risk_level=_action_risk_level(request.action),
                        created_at=now,
                        updated_at=now,
                    )
                )
                unit_of_work.commit()
                return stored

        return await self._repository_call(persist)

    async def get(self, automation_id: str) -> StoredAutomation:
        def query() -> StoredAutomation | None:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.automations is None:
                    raise AutomationStateError("The automation repository is unavailable.")
                return unit_of_work.automations.get(automation_id)

        automation = await self._repository_call(query)
        if automation is None:
            raise AutomationNotFoundError("The automation does not exist.")
        return automation

    async def list(
        self,
        *,
        enabled: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> AutomationPage:
        def query() -> AutomationPage:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.automations is None:
                    raise AutomationStateError("The automation repository is unavailable.")
                return unit_of_work.automations.list(
                    enabled=enabled,
                    page=page,
                    page_size=page_size,
                )

        items, total = await self._repository_call(query)
        return AutomationPage(items=items, total=total)

    async def update(
        self,
        automation_id: str,
        request: AutomationUpdate,
    ) -> StoredAutomation:
        now = self._now()

        def persist() -> StoredAutomation | None:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.automations is None:
                    raise AutomationStateError("The automation repository is unavailable.")
                updated = unit_of_work.automations.update(
                    automation_id,
                    request,
                    now=now,
                )
                if updated is None:
                    return None
                unit_of_work.commit()
                return updated

        automation = await self._repository_call(persist)
        if automation is None:
            raise AutomationNotFoundError("The automation does not exist.")
        return automation

    async def set_enabled(self, automation_id: str, enabled: bool) -> StoredAutomation:
        return await self.update(
            automation_id,
            AutomationUpdate(enabled=enabled),
        )

    async def list_runs(
        self,
        automation_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> AutomationRunPage:
        await self.get(automation_id)

        def query() -> AutomationRunPage:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.automation_runs is None:
                    raise AutomationStateError("The automation run repository is unavailable.")
                return unit_of_work.automation_runs.list(
                    automation_id,
                    page=page,
                    page_size=page_size,
                )

        items, total = await self._repository_call(query)
        return AutomationRunPage(items=items, total=total)

    async def handle_event(self, event: ArvunoEvent) -> None:
        if event.event_type.value not in AUTOMATION_EVENT_TYPES:
            return

        def query() -> list[StoredAutomation]:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.automations is None:
                    raise AutomationStateError("The automation repository is unavailable.")
                return unit_of_work.automations.list_enabled_by_event_type(event.event_type.value)

        automations = await self._repository_call(query)
        for automation in automations:
            if automation.trigger.subject_id is not None and (
                event.subject_id != automation.trigger.subject_id
            ):
                continue
            async with self._automation_lock(automation.id):
                await self._process_event(automation, event)

    async def _process_event(
        self,
        automation: StoredAutomation,
        event: ArvunoEvent,
    ) -> None:
        now = self._now()
        source = _condition_source(event)
        matches = matched_conditions(automation.conditions, source)
        if not evaluate_conditions(automation.conditions, source):
            await self._record_terminal_run(
                automation.id,
                event,
                AutomationRunStatus.CONDITION_NOT_MET,
                matched_context=_matched_context(event, matches),
            )
            return

        def latest() -> StoredAutomationRun | None:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.automation_runs is None:
                    raise AutomationStateError("The automation run repository is unavailable.")
                return unit_of_work.automation_runs.latest_run(
                    automation.id,
                    statuses={
                        AutomationRunStatus.COMPLETED,
                        AutomationRunStatus.FAILED,
                        AutomationRunStatus.RISK_REJECTED,
                    },
                )

        previous = await self._repository_call(latest)
        if (
            previous is not None
            and automation.cooldown_seconds > 0
            and now - previous.started_at < timedelta(seconds=automation.cooldown_seconds)
        ):
            await self._record_terminal_run(
                automation.id,
                event,
                AutomationRunStatus.COOLDOWN_SKIPPED,
                matched_context=_matched_context(event, matches),
            )
            return

        if automation.action.type is AutomationActionType.TOOL and (
            automation.action.risk_level
            not in {AutomationRiskLevel.READ_ONLY, AutomationRiskLevel.LOW_RISK}
        ):
            await self._record_terminal_run(
                automation.id,
                event,
                AutomationRunStatus.RISK_REJECTED,
                matched_context=_matched_context(event, matches),
                error={
                    "code": "AUTOMATION_RISK_REJECTED",
                    "message": "Only read-only and low-risk tools may run automatically.",
                    "details": {"risk_level": automation.action.risk_level.value},
                },
            )
            return

        await self._publish_triggered_event(automation, event, matches)
        run_id = self._run_id_factory()
        await self._create_running_run(
            run_id,
            automation.id,
            event,
            _matched_context(event, matches),
        )
        try:
            if automation.action.type is AutomationActionType.NOTIFICATION:
                notification_id = str(uuid4())
                now = self._now()

                def persist_notification() -> None:
                    with self._unit_of_work_factory() as unit_of_work:
                        if (
                            unit_of_work.notifications is None
                            or unit_of_work.automation_runs is None
                        ):
                            raise AutomationStateError(
                                "The notification repository is unavailable."
                            )
                        unit_of_work.notifications.create(
                            NotificationRecordCreate(
                                id=notification_id,
                                channel="web_console",
                                title=automation.action.title,
                                content=automation.action.message,
                                level=automation.action.level,
                                related_event_id=event.id,
                                related_task_id=None,
                                created_at=now,
                                sent_at=now,
                            )
                        )
                        context = dict(_matched_context(event, matches))
                        context["notification_id"] = notification_id
                        unit_of_work.automation_runs.update(
                            run_id,
                            status=AutomationRunStatus.COMPLETED,
                            matched_context=context,
                            task_id=None,
                            error=None,
                            completed_at=self._now(),
                        )
                        unit_of_work.commit()

                await self._repository_call(persist_notification)
                return

            action = automation.action
            if not isinstance(action, AutomationToolAction):
                raise AutomationStateError("Unknown automation action type.")
            task_result = await self._task_service.create_and_run(
                TaskCreate(
                    task_type="automation.action",
                    title=action.title,
                    description=f"Automation {automation.id} triggered by event {event.id}.",
                    origin="automation",
                    steps=[
                        TaskPlanStep(
                            name=action.title,
                            description="Execute the configured automation tool action.",
                            tool_name=action.tool_name,
                            input=action.input,
                        )
                    ],
                    timeout_seconds=60.0,
                ),
                correlation_id=event.correlation_id or event.id,
            )
            task = task_result.task
            if task.status is TaskStatus.COMPLETED:
                status = AutomationRunStatus.COMPLETED
                error = None
            else:
                status = AutomationRunStatus.FAILED
                error = task.error or {
                    "code": "AUTOMATION_TASK_NOT_COMPLETED",
                    "message": f"The automation task ended as {task.status.value}.",
                    "details": {"task_status": task.status.value},
                }
            await self._finish_run(
                run_id,
                status,
                task_id=task.id,
                error=error,
            )
        except BaseException as exc:
            await self._finish_run(
                run_id,
                AutomationRunStatus.FAILED,
                error={
                    "code": "AUTOMATION_EXECUTION_FAILED",
                    "message": "The automation action could not be completed.",
                    "details": {"reason": type(exc).__name__},
                },
            )
            logger.exception(
                "automation_execution_failed",
                extra={
                    "automation_id": automation.id,
                    "event_id": event.id,
                    "correlation_id": event.correlation_id,
                },
            )
            if isinstance(exc, Exception):
                return
            raise

    def _automation_lock(self, automation_id: str) -> asyncio.Lock:
        lock = self._locks.get(automation_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[automation_id] = lock
        return lock

    async def _publish_triggered_event(
        self,
        automation: StoredAutomation,
        event: ArvunoEvent,
        matches: list[dict[str, Any]],
    ) -> None:
        try:
            await self._event_publisher.publish(
                ArvunoEvent(
                    id=self._event_id_factory(),
                    event_type=ArvunoEventType.AUTOMATION_TRIGGERED,
                    source=ArvunoEventSource.AUTOMATION,
                    subject_type="automation",
                    subject_id=automation.id,
                    payload=AutomationTriggeredPayload(
                        automation_id=automation.id,
                        trigger_event_id=event.id,
                        matched_conditions=matches,
                    ),
                    correlation_id=event.correlation_id,
                    occurred_at=self._now(),
                )
            )
        except Exception:
            logger.exception(
                "automation_triggered_event_publish_failed",
                extra={
                    "automation_id": automation.id,
                    "event_id": event.id,
                    "correlation_id": event.correlation_id,
                },
            )

    async def _record_terminal_run(
        self,
        automation_id: str,
        event: ArvunoEvent,
        status: AutomationRunStatus,
        *,
        matched_context: dict[str, Any],
        error: dict[str, Any] | None = None,
    ) -> None:
        now = self._now()

        def persist() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.automation_runs is None:
                    raise AutomationStateError("The automation run repository is unavailable.")
                unit_of_work.automation_runs.create(
                    AutomationRunRecordCreate(
                        id=self._run_id_factory(),
                        automation_id=automation_id,
                        event_id=event.id,
                        status=status,
                        matched_context=matched_context,
                        task_id=None,
                        error=error,
                        started_at=now,
                        completed_at=now,
                    )
                )
                unit_of_work.commit()

        await self._repository_call(persist)

    async def _create_running_run(
        self,
        run_id: str,
        automation_id: str,
        event: ArvunoEvent,
        matched_context: dict[str, Any],
    ) -> None:
        def persist() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.automation_runs is None:
                    raise AutomationStateError("The automation run repository is unavailable.")
                unit_of_work.automation_runs.create(
                    AutomationRunRecordCreate(
                        id=run_id,
                        automation_id=automation_id,
                        event_id=event.id,
                        status=AutomationRunStatus.RUNNING,
                        matched_context=matched_context,
                        task_id=None,
                        error=None,
                        started_at=self._now(),
                        completed_at=None,
                    )
                )
                unit_of_work.commit()

        await self._repository_call(persist)

    async def _finish_run(
        self,
        run_id: str,
        status: AutomationRunStatus,
        *,
        task_id: str | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        def persist() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.automation_runs is None:
                    raise AutomationStateError("The automation run repository is unavailable.")
                updated = unit_of_work.automation_runs.update(
                    run_id,
                    status=status,
                    matched_context={},
                    task_id=task_id,
                    error=error,
                    completed_at=self._now(),
                )
                if updated is None:
                    raise AutomationNotFoundError("The automation run does not exist.")
                unit_of_work.commit()

        try:
            await self._repository_call(persist)
        except Exception:
            logger.exception(
                "automation_run_finalize_failed",
                extra={"automation_run_id": run_id, "status": status.value},
            )

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


def _condition_source(event: ArvunoEvent) -> dict[str, Any]:
    return {
        "event": {
            "id": event.id,
            "event_type": event.event_type.value,
            "subject_id": event.subject_id,
            "correlation_id": event.correlation_id,
        },
        "payload": event.payload.model_dump(mode="json"),
    }


def _matched_context(
    event: ArvunoEvent,
    matches: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "event_id": event.id,
        "event_type": event.event_type.value,
        "subject_id": event.subject_id,
        "correlation_id": event.correlation_id,
        "matched_conditions": matches,
    }


def _action_risk_level(action: Any) -> str:
    if action.type is AutomationActionType.TOOL:
        return action.risk_level.value
    return AutomationRiskLevel.READ_ONLY.value


__all__ = [
    "AutomationExecutionResult",
    "AutomationService",
]
