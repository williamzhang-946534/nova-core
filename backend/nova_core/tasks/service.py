from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from nova_core.events.models import (
    NovaEvent,
    NovaEventSource,
    NovaEventType,
    TaskCompletedPayload,
    TaskFailedPayload,
    TaskStartedPayload,
    UserConfirmedPayload,
)
from nova_core.tasks.errors import TaskNotFoundError, TaskStateError, TaskValidationError
from nova_core.tasks.models import (
    StoredTask,
    StoredTaskDetail,
    StoredTaskStep,
    TaskCreate,
    TaskCreateRecord,
    TaskPage,
    TaskRunResult,
    TaskStatus,
    TaskStepCreateRecord,
    TaskStepStatus,
)
from nova_core.tools.errors import ToolConfirmationRequiredError, ToolError
from nova_core.tools.models import ToolExecutionContext, ToolExecutionResult

logger = logging.getLogger(__name__)


class TaskUnitOfWorkProtocol(Protocol):
    tasks: Any

    def __enter__(self) -> TaskUnitOfWorkProtocol: ...

    def commit(self) -> None: ...


UnitOfWorkFactory = Callable[[], TaskUnitOfWorkProtocol]


class TaskToolExecutorProtocol(Protocol):
    async def execute(
        self,
        tool_name: str,
        raw_input: dict[str, Any],
        *,
        context: ToolExecutionContext,
        confirmation_token: str | None = None,
        task_id: str | None = None,
        task_step_id: str | None = None,
    ) -> ToolExecutionResult: ...


class TaskEventPublisherProtocol(Protocol):
    async def publish(self, event: NovaEvent) -> None: ...


class TaskService:
    """Executes explicit task plans through the audited tool boundary."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        tool_executor: TaskToolExecutorProtocol,
        event_publisher: TaskEventPublisherProtocol,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        task_id_factory: Callable[[], str] = lambda: str(uuid4()),
        step_id_factory: Callable[[], str] = lambda: str(uuid4()),
        event_id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._tool_executor = tool_executor
        self._event_publisher = event_publisher
        self._clock = clock
        self._task_id_factory = task_id_factory
        self._step_id_factory = step_id_factory
        self._event_id_factory = event_id_factory

    async def create_task(
        self,
        request: TaskCreate,
        *,
        correlation_id: str | None = None,
    ) -> StoredTask:
        task_id = self._task_id_factory()
        record = TaskCreateRecord(
            id=task_id,
            task_type=request.task_type,
            title=request.title,
            description=request.description,
            origin=request.origin,
            correlation_id=correlation_id or task_id,
            created_at=self._now(),
            plan=_task_plan(request),
            steps=[
                TaskStepCreateRecord(
                    id=self._step_id_factory(),
                    step_index=index,
                    name=step.name,
                    description=step.description,
                    tool_name=step.tool_name,
                    input=step.input,
                )
                for index, step in enumerate(request.steps)
            ],
        )

        def persist() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                repository = _tasks(unit_of_work)
                repository.create(record)
                unit_of_work.commit()

        await asyncio.to_thread(persist)
        task = await self.get_task(task_id)
        if task is None:
            raise TaskStateError("The task could not be created.")
        return task

    async def create_and_run(
        self,
        request: TaskCreate,
        *,
        correlation_id: str | None = None,
    ) -> TaskRunResult:
        task = await self.create_task(request, correlation_id=correlation_id)
        return await self.run_task(task.id)

    async def run_task(self, task_id: str) -> TaskRunResult:
        task = await self.get_task(task_id)
        if task is None:
            raise TaskNotFoundError
        if task.status is not TaskStatus.PENDING:
            return TaskRunResult(await self.get_task_detail(task_id))

        def start() -> StoredTask:
            with self._unit_of_work_factory() as unit_of_work:
                repository = _tasks(unit_of_work)
                planning = repository.update_task_status(
                    task_id,
                    TaskStatus.PLANNING,
                    now=self._now(),
                    plan=task.plan,
                )
                running = repository.update_task_status(
                    task_id,
                    TaskStatus.RUNNING,
                    now=self._now(),
                    plan=planning.plan,
                )
                unit_of_work.commit()
                return running

        try:
            running = await asyncio.to_thread(start)
        except ValueError as exc:
            raise TaskStateError(str(exc)) from exc
        await self._publish_task_started(running)
        return await self._execute_steps(
            task_id,
            running.plan.get("timeout_seconds", 60.0),
        )

    async def resume_task(self, task_id: str) -> TaskRunResult:
        task = await self.get_task(task_id)
        if task is None:
            raise TaskNotFoundError
        if task.status is TaskStatus.PENDING:
            return await self.run_task(task_id)
        if task.status is not TaskStatus.RUNNING:
            return TaskRunResult(await self.get_task_detail(task_id))
        remaining = self._remaining_seconds(task)
        if remaining <= 0:
            await self.cancel(task_id, reason="The task timed out while it was recoverable.")
            return TaskRunResult(await self.get_task_detail(task_id))
        return await self._execute_steps(task_id, remaining)

    async def confirm(
        self,
        task_id: str,
        *,
        confirmation_token: str,
        confirmed: bool,
    ) -> TaskRunResult:
        task = await self.get_task(task_id)
        if task is None:
            raise TaskNotFoundError
        token_hash = _token_hash(confirmation_token)
        used_hashes = _used_confirmation_hashes(task.plan)
        if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            if token_hash in used_hashes:
                return TaskRunResult(await self.get_task_detail(task_id))
            raise TaskStateError("The task is no longer waiting for confirmation.")
        if task.status is not TaskStatus.WAITING_CONFIRMATION:
            raise TaskStateError("The task is not waiting for confirmation.")
        if not confirmed:
            await self.cancel(task_id, reason="The user declined the task confirmation.")
            await self._publish_user_confirmed(task_id, token_hash, confirmed=False)
            return TaskRunResult(await self.get_task_detail(task_id))

        active = _active_confirmation(task.plan)
        if active is None or not secrets.compare_digest(
            str(active.get("token_hash", "")), token_hash
        ):
            raise TaskStateError("The confirmation token does not match this task step.")
        step_id = active.get("task_step_id")
        steps = await self._steps(task_id)
        step = next((item for item in steps if item.id == step_id), None)
        if step is None or step.status is not TaskStepStatus.WAITING_CONFIRMATION:
            raise TaskStateError("The confirmed task step is no longer waiting.")

        remaining = self._remaining_seconds(task)
        if remaining <= 0:
            await self.cancel(task_id, reason="The task confirmation timed out.")
            return TaskRunResult(await self.get_task_detail(task_id))

        plan = _copy_plan(task.plan)
        plan.setdefault("confirmations_used", []).append(
            {
                "task_step_id": step.id,
                "token_hash": token_hash,
                "confirmed_at": self._now().isoformat(),
            }
        )
        plan.pop("confirmation", None)

        def resume() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                repository = _tasks(unit_of_work)
                repository.update_task_status(
                    task_id,
                    TaskStatus.RUNNING,
                    now=self._now(),
                    plan=plan,
                )
                repository.update_step_status(step.id, TaskStepStatus.RUNNING, now=self._now())
                unit_of_work.commit()

        try:
            await asyncio.to_thread(resume)
        except ValueError as exc:
            raise TaskStateError(str(exc)) from exc

        await self._publish_user_confirmed(task_id, token_hash)
        try:
            async with asyncio.timeout(remaining):
                result = await self._tool_executor.execute(
                    step.tool_name or "",
                    step.input or {},
                    context=ToolExecutionContext(
                        correlation_id=task.correlation_id or task_id,
                        task_id=task_id,
                        task_step_id=step.id,
                    ),
                    confirmation_token=confirmation_token,
                    task_id=task_id,
                    task_step_id=step.id,
                )
        except ToolConfirmationRequiredError as exc:
            return await self._wait_for_confirmation(task_id, step.id, exc)
        except ToolError as exc:
            await self._fail_task(task_id, step.id, _tool_error(exc))
            return TaskRunResult(await self.get_task_detail(task_id))
        except TimeoutError:
            await self._fail_task(
                task_id,
                step.id,
                {
                    "code": "TASK_TIMEOUT",
                    "message": "The task timed out.",
                    "details": {"timeout_seconds": task.plan.get("timeout_seconds")},
                },
                timed_out=True,
            )
            return TaskRunResult(await self.get_task_detail(task_id))
        except Exception:
            logger.exception(
                "confirmed_task_step_execution_failed",
                extra={
                    "task_id": task_id,
                    "task_step_id": step.id,
                    "correlation_id": task.correlation_id,
                },
            )
            await self._fail_task(
                task_id,
                step.id,
                {
                    "code": "TASK_EXECUTION_FAILED",
                    "message": "The confirmed task step could not be executed.",
                    "details": {},
                },
            )
            return TaskRunResult(await self.get_task_detail(task_id))

        detail = await self._complete_step(task_id, step.id, result)
        if detail.status is not TaskStatus.RUNNING:
            return TaskRunResult(detail)
        current = await self.get_task(task_id)
        if current is None:
            raise TaskStateError("The task disappeared during confirmation.")
        updated_remaining = self._remaining_seconds(current)
        if updated_remaining <= 0:
            await self.cancel(task_id, reason="The task timed out after confirmation.")
            return TaskRunResult(await self.get_task_detail(task_id))
        return await self._execute_steps(task_id, updated_remaining)

    async def cancel(self, task_id: str, *, reason: str) -> StoredTaskDetail:
        task = await self.get_task(task_id)
        if task is None:
            raise TaskNotFoundError
        if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            raise TaskStateError("A completed task cannot be cancelled.")
        now = self._now()
        error = {
            "code": "TASK_CANCELLED",
            "message": reason,
            "details": {"cancelled_at": now.isoformat()},
        }
        plan = _copy_plan(task.plan)
        plan["cancellation"] = {"reason": reason, "cancelled_at": now.isoformat()}

        def persist_cancel() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                repository = _tasks(unit_of_work)
                repository.update_task_status(
                    task_id,
                    TaskStatus.CANCELLED,
                    now=now,
                    plan=plan,
                    error=error,
                )
                repository.cancel_steps(
                    task_id,
                    now=now,
                    statuses={
                        TaskStepStatus.PENDING,
                        TaskStepStatus.RUNNING,
                        TaskStepStatus.WAITING_CONFIRMATION,
                    },
                )
                unit_of_work.commit()

        try:
            await asyncio.to_thread(persist_cancel)
        except ValueError as exc:
            raise TaskStateError(str(exc)) from exc
        detail = await self.get_task_detail(task_id)
        if detail is None:
            raise TaskStateError("The task could not be cancelled.")
        return detail

    async def list(
        self,
        *,
        status: str | None = None,
        task_type: str | None = None,
        conversation_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> TaskPage:
        task_status = None
        if status is not None:
            try:
                task_status = TaskStatus(status)
            except ValueError as exc:
                raise TaskValidationError("Unknown task status.") from exc

        def query() -> TaskPage:
            with self._unit_of_work_factory() as unit_of_work:
                return _tasks(unit_of_work).list(
                    status=task_status,
                    task_type=task_type,
                    conversation_id=conversation_id,
                    start_time=start_time,
                    end_time=end_time,
                    page=page,
                    page_size=page_size,
                )

        return await asyncio.to_thread(query)

    async def get_task(self, task_id: str) -> StoredTask | None:
        def query() -> StoredTask | None:
            with self._unit_of_work_factory() as unit_of_work:
                return _tasks(unit_of_work).get(task_id)

        return await asyncio.to_thread(query)

    async def get_task_detail(self, task_id: str) -> StoredTaskDetail:
        def query() -> StoredTaskDetail | None:
            with self._unit_of_work_factory() as unit_of_work:
                return _tasks(unit_of_work).get_detail(task_id)

        detail = await asyncio.to_thread(query)
        if detail is None:
            raise TaskNotFoundError
        return detail

    async def _execute_steps(self, task_id: str, timeout_seconds: float) -> TaskRunResult:
        try:
            async with asyncio.timeout(timeout_seconds):
                detail = await self.get_task_detail(task_id)
                for step in detail.steps:
                    current = await self.get_task(task_id)
                    if current is None or current.status is not TaskStatus.RUNNING:
                        return TaskRunResult(await self.get_task_detail(task_id))
                    if step.status is TaskStepStatus.COMPLETED:
                        continue
                    if step.status not in {TaskStepStatus.PENDING, TaskStepStatus.RUNNING}:
                        return TaskRunResult(await self.get_task_detail(task_id))
                    try:
                        if step.status is TaskStepStatus.PENDING:
                            await self._start_step(task_id, step.id)
                        result = await self._tool_executor.execute(
                            step.tool_name or "",
                            step.input or {},
                            context=ToolExecutionContext(
                                correlation_id=detail.correlation_id or task_id,
                                task_id=task_id,
                                task_step_id=step.id,
                            ),
                            task_id=task_id,
                            task_step_id=step.id,
                        )
                    except ToolConfirmationRequiredError as exc:
                        return await self._wait_for_confirmation(task_id, step.id, exc)
                    except ToolError as exc:
                        await self._fail_task(task_id, step.id, _tool_error(exc))
                        return TaskRunResult(await self.get_task_detail(task_id))
                    except Exception:
                        logger.exception(
                            "task_step_execution_failed",
                            extra={
                                "task_id": task_id,
                                "task_step_id": step.id,
                                "correlation_id": detail.correlation_id,
                            },
                        )
                        await self._fail_task(
                            task_id,
                            step.id,
                            {
                                "code": "TASK_EXECUTION_FAILED",
                                "message": "The task step could not be executed.",
                                "details": {},
                            },
                        )
                        return TaskRunResult(await self.get_task_detail(task_id))
                    updated_detail = await self._complete_step(task_id, step.id, result)
                    if updated_detail.status is not TaskStatus.RUNNING:
                        return TaskRunResult(updated_detail)
                return TaskRunResult(await self.get_task_detail(task_id))
        except TimeoutError:
            steps = await self._steps(task_id)
            current_step = next(
                (item for item in steps if item.status is TaskStepStatus.RUNNING),
                None,
            )
            if current_step is None:
                return TaskRunResult(await self.get_task_detail(task_id))
            task = await self.get_task(task_id)
            await self._fail_task(
                task_id,
                current_step.id,
                {
                    "code": "TASK_TIMEOUT",
                    "message": "The task timed out.",
                    "details": {
                        "timeout_seconds": task.plan.get("timeout_seconds")
                        if task is not None
                        else timeout_seconds
                    },
                },
                timed_out=True,
            )
            return TaskRunResult(await self.get_task_detail(task_id))

    async def _start_step(self, task_id: str, step_id: str) -> None:
        def persist() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                _tasks(unit_of_work).update_step_status(
                    step_id,
                    TaskStepStatus.RUNNING,
                    now=self._now(),
                )
                unit_of_work.commit()

        await asyncio.to_thread(persist)

    async def _complete_step(
        self,
        task_id: str,
        step_id: str,
        result: ToolExecutionResult,
    ) -> StoredTaskDetail:
        now = self._now()

        def persist() -> StoredTaskDetail | None:
            with self._unit_of_work_factory() as unit_of_work:
                repository = _tasks(unit_of_work)
                detail = repository.get_detail(task_id)
                if detail is None:
                    raise TaskNotFoundError
                current_step = next((item for item in detail.steps if item.id == step_id), None)
                if (
                    detail.status is not TaskStatus.RUNNING
                    or current_step is None
                    or current_step.status is not TaskStepStatus.RUNNING
                ):
                    unit_of_work.commit()
                    return detail
                repository.update_step_status(
                    step_id,
                    TaskStepStatus.COMPLETED,
                    now=now,
                    output=result.output,
                    error=None,
                )
                detail = repository.get_detail(task_id)
                if (
                    detail is not None
                    and detail.status is TaskStatus.RUNNING
                    and all(step.status is TaskStepStatus.COMPLETED for step in detail.steps)
                ):
                    result_payload = {
                        "status": TaskStatus.COMPLETED.value,
                        "completed_steps": len(detail.steps),
                        "execution_ids": [execution.id for execution in detail.executions],
                    }
                    repository.update_task_status(
                        task_id,
                        TaskStatus.COMPLETED,
                        now=now,
                        plan=detail.plan,
                        result=result_payload,
                        error=None,
                    )
                unit_of_work.commit()
                return repository.get_detail(task_id)

        try:
            detail = await asyncio.to_thread(persist)
        except ValueError as exc:
            raise TaskStateError(str(exc)) from exc
        if detail is None:
            raise TaskNotFoundError
        if detail.status is TaskStatus.COMPLETED:
            await self._publish_task_completed(detail)
        return detail

    async def _wait_for_confirmation(
        self,
        task_id: str,
        step_id: str,
        error: ToolConfirmationRequiredError,
    ) -> TaskRunResult:
        token = error.details.get("confirmation_token")
        if not isinstance(token, str):
            raise TaskStateError("The tool executor did not provide a confirmation token.")
        task = await self.get_task(task_id)
        if task is None:
            raise TaskNotFoundError
        now = self._now()
        plan = _copy_plan(task.plan)
        plan["confirmation"] = {
            "task_step_id": step_id,
            "token_hash": _token_hash(token),
            "execution_id": error.details.get("execution_id"),
            "risk_level": error.details.get("risk_level"),
            "issued_at": now.isoformat(),
        }

        def persist() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                repository = _tasks(unit_of_work)
                repository.update_task_status(
                    task_id,
                    TaskStatus.WAITING_CONFIRMATION,
                    now=now,
                    plan=plan,
                )
                repository.update_step_status(
                    step_id,
                    TaskStepStatus.WAITING_CONFIRMATION,
                    now=now,
                )
                unit_of_work.commit()

        try:
            await asyncio.to_thread(persist)
        except ValueError as exc:
            raise TaskStateError(str(exc)) from exc
        detail = await self.get_task_detail(task_id)
        return TaskRunResult(detail, confirmation_token=token)

    async def _fail_task(
        self,
        task_id: str,
        step_id: str,
        error: dict[str, Any],
        *,
        timed_out: bool = False,
    ) -> None:
        now = self._now()

        def persist() -> StoredTask | None:
            with self._unit_of_work_factory() as unit_of_work:
                repository = _tasks(unit_of_work)
                repository.update_step_status(
                    step_id,
                    TaskStepStatus.TIMED_OUT if timed_out else TaskStepStatus.FAILED,
                    now=now,
                    error=error,
                )
                task = repository.update_task_status(
                    task_id,
                    TaskStatus.FAILED,
                    now=now,
                    plan=_current_plan(repository, task_id),
                    error=error,
                )
                repository.cancel_steps(
                    task_id,
                    now=now,
                    statuses={TaskStepStatus.PENDING, TaskStepStatus.WAITING_CONFIRMATION},
                )
                unit_of_work.commit()
                return task

        try:
            task = await asyncio.to_thread(persist)
        except ValueError:
            task = await self.get_task(task_id)
        if task is not None:
            await self._publish_task_failed(task, step_id, error)

    async def _steps(self, task_id: str) -> list[StoredTaskStep]:
        def query() -> list[StoredTaskStep]:
            with self._unit_of_work_factory() as unit_of_work:
                return _tasks(unit_of_work).get_steps(task_id)

        return await asyncio.to_thread(query)

    async def _publish_task_started(self, task: StoredTask) -> None:
        await self._publish(
            NovaEvent(
                id=self._event_id_factory(),
                event_type=NovaEventType.TASK_STARTED,
                source=NovaEventSource.TASK,
                subject_type="task",
                subject_id=task.id,
                payload=TaskStartedPayload(
                    task_id=task.id,
                    task_type=task.task_type,
                    origin=task.origin,
                ),
                correlation_id=task.correlation_id,
                occurred_at=self._now(),
            )
        )

    async def _publish_task_completed(self, task: StoredTaskDetail) -> None:
        await self._publish(
            NovaEvent(
                id=self._event_id_factory(),
                event_type=NovaEventType.TASK_COMPLETED,
                source=NovaEventSource.TASK,
                subject_type="task",
                subject_id=task.id,
                payload=TaskCompletedPayload(
                    task_id=task.id,
                    result_summary=f"Completed {len(task.steps)} task steps.",
                    completed_at=task.completed_at or self._now(),
                ),
                correlation_id=task.correlation_id,
                occurred_at=self._now(),
            )
        )

    async def _publish_task_failed(
        self,
        task: StoredTask,
        step_id: str,
        error: dict[str, Any],
    ) -> None:
        await self._publish(
            NovaEvent(
                id=self._event_id_factory(),
                event_type=NovaEventType.TASK_FAILED,
                source=NovaEventSource.TASK,
                subject_type="task",
                subject_id=task.id,
                payload=TaskFailedPayload(
                    task_id=task.id,
                    error_code=str(error.get("code", "TASK_EXECUTION_FAILED")),
                    error_message=str(error.get("message", "The task failed."))[:2000],
                    failed_step_id=step_id,
                ),
                correlation_id=task.correlation_id,
                occurred_at=self._now(),
            )
        )

    async def _publish_user_confirmed(
        self,
        task_id: str,
        token_hash: str,
        *,
        confirmed: bool = True,
    ) -> None:
        task = await self.get_task(task_id)
        if task is None:
            return
        await self._publish(
            NovaEvent(
                id=self._event_id_factory(),
                event_type=NovaEventType.USER_CONFIRMED,
                source=NovaEventSource.TASK,
                subject_type="task",
                subject_id=task.id,
                payload=UserConfirmedPayload(
                    task_id=task.id,
                    confirmed=confirmed,
                    confirmation_token_hash=token_hash,
                ),
                correlation_id=task.correlation_id,
                occurred_at=self._now(),
            )
        )

    async def _publish(self, event: NovaEvent) -> None:
        try:
            await self._event_publisher.publish(event)
        except Exception:
            logger.exception(
                "task_event_publish_failed",
                extra={
                    "event_type": event.event_type.value,
                    "task_id": event.subject_id,
                    "correlation_id": event.correlation_id,
                },
            )

    def _remaining_seconds(self, task: StoredTask) -> float:
        timeout_seconds = task.plan.get("timeout_seconds", 60.0)
        if not isinstance(timeout_seconds, int | float) or isinstance(timeout_seconds, bool):
            return 0.0
        started_at = task.started_at or task.created_at
        deadline = started_at + timedelta(seconds=float(timeout_seconds))
        return (deadline - self._now()).total_seconds()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def _tasks(unit_of_work: TaskUnitOfWorkProtocol) -> Any:
    if unit_of_work.tasks is None:
        raise TaskStateError("The task repository is unavailable.")
    return unit_of_work.tasks


def _current_plan(repository: Any, task_id: str) -> dict[str, Any]:
    task = repository.get(task_id)
    return _copy_plan(task.plan if task is not None else {})


def _task_plan(request: TaskCreate) -> dict[str, Any]:
    return {
        "version": 1,
        "timeout_seconds": request.timeout_seconds,
        "steps": [step.model_dump(mode="json") for step in request.steps],
        "confirmations_used": [],
    }


def _copy_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return dict(plan)


def _active_confirmation(plan: dict[str, Any]) -> dict[str, Any] | None:
    value = plan.get("confirmation")
    return value if isinstance(value, dict) else None


def _used_confirmation_hashes(plan: dict[str, Any]) -> set[str]:
    values = plan.get("confirmations_used", [])
    if not isinstance(values, list):
        return set()
    return {
        item["token_hash"]
        for item in values
        if isinstance(item, dict) and isinstance(item.get("token_hash"), str)
    }


def _tool_error(error: ToolError) -> dict[str, Any]:
    return {
        "code": error.code,
        "message": error.message,
        "details": error.details,
    }


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


__all__ = [
    "TaskEventPublisherProtocol",
    "TaskService",
    "TaskToolExecutorProtocol",
]
