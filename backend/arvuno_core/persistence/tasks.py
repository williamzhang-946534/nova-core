from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import Task, TaskStep, ToolExecution
from arvuno_core.tasks.models import (
    StoredTask,
    StoredTaskDetail,
    StoredTaskStep,
    StoredToolExecution,
    TaskCreateRecord,
    TaskPage,
    TaskStatus,
    TaskStepStatus,
    validate_task_step_transition,
    validate_task_transition,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class TaskRepository:
    """Reads and writes task aggregates through the persistence boundary."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, record: TaskCreateRecord) -> StoredTask:
        try:
            entity = Task(
                id=record.id,
                task_type=record.task_type,
                title=record.title,
                description=record.description,
                status=TaskStatus.PENDING.value,
                origin=record.origin,
                plan=record.plan,
                correlation_id=record.correlation_id,
                created_at=record.created_at,
            )
            for step in record.steps:
                entity.steps.append(
                    TaskStep(
                        id=step.id,
                        step_index=step.step_index,
                        name=step.name,
                        description=step.description,
                        tool_name=step.tool_name,
                        status=TaskStepStatus.PENDING.value,
                        input=step.input,
                    )
                )
            self._session.add(entity)
            self._session.flush()
            return _task(entity)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a task.") from exc

    def get(self, task_id: str) -> StoredTask | None:
        try:
            entity = self._session.get(Task, task_id)
            return None if entity is None else _task(entity)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a task.") from exc

    def get_detail(self, task_id: str) -> StoredTaskDetail | None:
        try:
            entity = self._session.get(Task, task_id)
            if entity is None:
                return None
            executions = list(
                self._session.scalars(
                    select(ToolExecution)
                    .where(ToolExecution.task_id == task_id)
                    .order_by(ToolExecution.started_at.asc(), ToolExecution.id.asc())
                )
            )
            return StoredTaskDetail(
                **_task(entity).model_dump(),
                steps=[
                    _step(step)
                    for step in sorted(entity.steps, key=lambda item: (item.step_index, item.id))
                ],
                executions=[_execution(execution) for execution in executions],
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read task details.") from exc

    def list(
        self,
        *,
        status: TaskStatus | None = None,
        task_type: str | None = None,
        conversation_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> TaskPage:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("Page must be positive and page_size must be between 1 and 100")
        try:
            filters = []
            if status is not None:
                filters.append(Task.status == status.value)
            if task_type is not None:
                filters.append(Task.task_type == task_type)
            if conversation_id is not None:
                filters.append(Task.conversation_id == conversation_id)
            if start_time is not None:
                filters.append(Task.created_at >= start_time)
            if end_time is not None:
                filters.append(Task.created_at <= end_time)

            statement = select(Task).where(*filters)
            count_statement = select(func.count()).select_from(Task).where(*filters)
            total = self._session.scalar(count_statement) or 0
            statement = (
                statement.order_by(Task.created_at.desc(), Task.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            items = [_task(item) for item in self._session.scalars(statement)]
            return TaskPage(items=items, total=total)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list tasks.") from exc

    def count_active(self) -> int:
        try:
            active_statuses = [
                TaskStatus.PENDING.value,
                TaskStatus.PLANNING.value,
                TaskStatus.WAITING_CONFIRMATION.value,
                TaskStatus.RUNNING.value,
            ]
            value = self._session.scalar(
                select(func.count()).select_from(Task).where(Task.status.in_(active_statuses))
            )
            return int(value or 0)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to count active tasks.") from exc

    def update_task_status(
        self,
        task_id: str,
        target: TaskStatus,
        *,
        now: datetime,
        plan: dict[str, Any],
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> StoredTask:
        try:
            entity = self._session.get(Task, task_id)
            if entity is None:
                raise RepositoryError("The task does not exist.")
            current = TaskStatus(entity.status)
            validate_task_transition(current, target)
            entity.status = target.value
            entity.plan = plan
            entity.result = result
            entity.error = error
            if (
                target in {TaskStatus.RUNNING, TaskStatus.WAITING_CONFIRMATION}
                and entity.started_at is None
            ):
                entity.started_at = now
            if target in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
                entity.completed_at = now
            return _task(entity)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to update the task status.") from exc

    def get_steps(self, task_id: str) -> list[StoredTaskStep]:
        try:
            statement = (
                select(TaskStep)
                .where(TaskStep.task_id == task_id)
                .order_by(TaskStep.step_index.asc(), TaskStep.id.asc())
            )
            return [_step(item) for item in self._session.scalars(statement)]
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read task steps.") from exc

    def update_step_status(
        self,
        step_id: str,
        target: TaskStepStatus,
        *,
        now: datetime,
        output: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> StoredTaskStep:
        try:
            entity = self._session.get(TaskStep, step_id)
            if entity is None:
                raise RepositoryError("The task step does not exist.")
            validate_task_step_transition(TaskStepStatus(entity.status), target)
            entity.status = target.value
            entity.output = output
            entity.error = error
            if target is TaskStepStatus.RUNNING and entity.started_at is None:
                entity.started_at = now
            if target in {
                TaskStepStatus.COMPLETED,
                TaskStepStatus.FAILED,
                TaskStepStatus.TIMED_OUT,
                TaskStepStatus.CANCELLED,
            }:
                entity.completed_at = now
            return _step(entity)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to update the task step status.") from exc

    def cancel_steps(
        self,
        task_id: str,
        *,
        now: datetime,
        statuses: set[TaskStepStatus],
    ) -> int:
        try:
            statement = select(TaskStep).where(
                TaskStep.task_id == task_id,
                TaskStep.status.in_([item.value for item in statuses]),
            )
            cancelled = 0
            for entity in self._session.scalars(statement):
                entity.status = TaskStepStatus.CANCELLED.value
                entity.completed_at = now
                cancelled += 1
            return cancelled
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to cancel task steps.") from exc


def _task(entity: Task) -> StoredTask:
    return StoredTask(
        id=entity.id,
        task_type=entity.task_type,
        title=entity.title,
        description=entity.description,
        status=TaskStatus(entity.status),
        origin=entity.origin,
        conversation_id=entity.conversation_id,
        plan=entity.plan,
        result=entity.result,
        error=entity.error,
        correlation_id=entity.correlation_id,
        created_at=_utc(entity.created_at),
        started_at=_utc(entity.started_at) if entity.started_at is not None else None,
        completed_at=_utc(entity.completed_at) if entity.completed_at is not None else None,
    )


def _step(entity: TaskStep) -> StoredTaskStep:
    return StoredTaskStep(
        id=entity.id,
        task_id=entity.task_id,
        step_index=entity.step_index,
        name=entity.name,
        description=entity.description,
        tool_name=entity.tool_name,
        status=TaskStepStatus(entity.status),
        input=entity.input,
        output=entity.output,
        error=entity.error,
        started_at=_utc(entity.started_at) if entity.started_at is not None else None,
        completed_at=_utc(entity.completed_at) if entity.completed_at is not None else None,
    )


def _execution(entity: ToolExecution) -> StoredToolExecution:
    return StoredToolExecution(
        id=entity.id,
        tool_name=entity.tool.name,
        task_id=entity.task_id,
        task_step_id=entity.task_step_id,
        status=entity.status,
        input=entity.input,
        output=entity.output,
        validation=entity.validation,
        risk_level=entity.risk_level,
        permission_result=entity.permission_result,
        error=entity.error,
        correlation_id=entity.correlation_id,
        started_at=_utc(entity.started_at),
        completed_at=_utc(entity.completed_at) if entity.completed_at is not None else None,
        duration_ms=entity.duration_ms,
    )
