import asyncio
import itertools
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nova_core.app import create_app
from nova_core.config import Settings
from nova_core.devices.mock import MockDeviceAdapter
from nova_core.devices.registry import DeviceRegistry
from nova_core.devices.service import DeviceApplicationService
from nova_core.events.bus import EventBus
from nova_core.persistence.database import DatabaseManager
from nova_core.persistence.tools import SqlToolExecutionStore
from nova_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from nova_core.tasks.errors import TaskStateError
from nova_core.tasks.models import (
    TaskCreate,
    TaskCreateRecord,
    TaskPlanStep,
    TaskStatus,
    TaskStepCreateRecord,
    TaskStepStatus,
    validate_task_step_transition,
    validate_task_transition,
)
from nova_core.tasks.service import TaskService
from nova_core.tools.confirmation import ConfirmationService
from nova_core.tools.errors import ToolConfirmationRequiredError
from nova_core.tools.executor import ToolExecutor
from nova_core.tools.models import PermissionResult, ToolExecutionResult, ToolRiskLevel
from nova_core.tools.registry import build_default_tool_registry
from nova_core.tools.safety import SafetyPolicy


def phase_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


@dataclass
class FixedClock:
    now: datetime = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.now is None:
            self.now = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@dataclass
class TaskEnvironment:
    manager: DatabaseManager
    adapter: MockDeviceAdapter
    registry: DeviceRegistry
    executor: ToolExecutor
    event_bus: EventBus
    service: TaskService
    clock: FixedClock


def task_environment(
    manager: DatabaseManager,
    *,
    permissions: dict[str, str] | None = None,
    clock: FixedClock | None = None,
) -> TaskEnvironment:
    mutable_clock = clock or FixedClock()

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(manager.session_factory)

    adapter = MockDeviceAdapter()
    registry = DeviceRegistry(factory)
    event_bus = EventBus(factory)
    device_service = DeviceApplicationService(registry, {"mock": adapter})
    task_counter = itertools.count(1)
    step_counter = itertools.count(1)
    execution_counter = itertools.count(1)
    executor = ToolExecutor(
        registry=build_default_tool_registry(device_service),
        safety_policy=SafetyPolicy(
            device_service,
            tool_permissions=permissions
            or {
                "list_devices": "allow",
                "get_device_state": "allow",
                "control_device": "allow_low_risk",
            },
        ),
        confirmation_service=ConfirmationService(
            ttl_seconds=300,
            clock=mutable_clock,
        ),
        execution_store=SqlToolExecutionStore(factory),
        event_publisher=event_bus,
        execution_id_factory=lambda: f"execution-{next(execution_counter)}",
    )
    service = TaskService(
        factory,
        executor,
        event_bus,
        clock=mutable_clock,
        task_id_factory=lambda: f"task-{next(task_counter)}",
        step_id_factory=lambda: f"step-{next(step_counter)}",
    )
    return TaskEnvironment(
        manager,
        adapter,
        registry,
        executor,
        event_bus,
        service,
        mutable_clock,
    )


def query_task(manager: DatabaseManager, task_id: str) -> Any:
    with SqlAlchemyUnitOfWork(manager.session_factory) as unit_of_work:
        assert unit_of_work.tasks is not None
        return unit_of_work.tasks.get_detail(task_id)


def query_events(manager: DatabaseManager, correlation_id: str) -> list[str]:
    with SqlAlchemyUnitOfWork(manager.session_factory) as unit_of_work:
        assert unit_of_work.events is not None
        events, _ = unit_of_work.events.query(correlation_id=correlation_id, order="asc")
        return [event.event_type for event in events]


def create_request(
    steps: list[TaskPlanStep],
    *,
    timeout_seconds: float = 60,
) -> TaskCreate:
    return TaskCreate(
        task_type="device.operation",
        title="Explicit task plan",
        steps=steps,
        timeout_seconds=timeout_seconds,
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.PENDING, TaskStatus.PLANNING),
        (TaskStatus.PENDING, TaskStatus.CANCELLED),
        (TaskStatus.PLANNING, TaskStatus.RUNNING),
        (TaskStatus.PLANNING, TaskStatus.FAILED),
        (TaskStatus.WAITING_CONFIRMATION, TaskStatus.RUNNING),
        (TaskStatus.WAITING_CONFIRMATION, TaskStatus.CANCELLED),
        (TaskStatus.RUNNING, TaskStatus.COMPLETED),
        (TaskStatus.RUNNING, TaskStatus.FAILED),
        (TaskStatus.RUNNING, TaskStatus.CANCELLED),
    ],
)
def test_task_state_machine_accepts_documented_paths(
    current: TaskStatus,
    target: TaskStatus,
) -> None:
    validate_task_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.PENDING, TaskStatus.RUNNING),
        (TaskStatus.RUNNING, TaskStatus.PLANNING),
        (TaskStatus.COMPLETED, TaskStatus.RUNNING),
        (TaskStatus.FAILED, TaskStatus.CANCELLED),
        (TaskStatus.CANCELLED, TaskStatus.PLANNING),
    ],
)
def test_task_state_machine_rejects_invalid_paths(
    current: TaskStatus,
    target: TaskStatus,
) -> None:
    with pytest.raises(ValueError, match="Invalid task transition"):
        validate_task_transition(current, target)


def test_task_step_state_machine_rejects_invalid_paths() -> None:
    validate_task_step_transition(TaskStepStatus.RUNNING, TaskStepStatus.TIMED_OUT)
    with pytest.raises(ValueError, match="Invalid task step transition"):
        validate_task_step_transition(TaskStepStatus.PENDING, TaskStepStatus.COMPLETED)


def test_task_repository_saves_details_and_queries_history(tmp_path: Path) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))
    try:
        manager.initialize_database()
        now = datetime.now(UTC)
        with SqlAlchemyUnitOfWork(manager.session_factory) as unit_of_work:
            assert unit_of_work.tasks is not None
            unit_of_work.tasks.create(
                TaskCreateRecord(
                    id="task-history-1",
                    task_type="device.query",
                    title="History task",
                    description=None,
                    origin="api",
                    plan={"version": 1, "steps": []},
                    correlation_id="correlation-history",
                    created_at=now - timedelta(minutes=1),
                    steps=[
                        TaskStepCreateRecord(
                            id="step-history-1",
                            step_index=0,
                            name="List",
                            description=None,
                            tool_name="list_devices",
                            input={},
                        )
                    ],
                )
            )
            unit_of_work.commit()

        with SqlAlchemyUnitOfWork(manager.session_factory) as unit_of_work:
            assert unit_of_work.tasks is not None
            detail = unit_of_work.tasks.get_detail("task-history-1")
            assert detail is not None
            assert detail.status is TaskStatus.PENDING
            assert detail.steps[0].task_id == "task-history-1"

            page = unit_of_work.tasks.list(
                status=TaskStatus.PENDING,
                task_type="device.query",
                start_time=now - timedelta(hours=1),
                end_time=now,
                page=1,
                page_size=10,
            )
            assert page.total == 1
            assert page.items[0].id == "task-history-1"

            with pytest.raises(ValueError, match="Invalid task transition"):
                unit_of_work.tasks.update_task_status(
                    "task-history-1",
                    TaskStatus.COMPLETED,
                    now=now,
                    plan=detail.plan,
                )

        assert query_task(manager, "task-history-1").status is TaskStatus.PENDING
    finally:
        manager.dispose()


def test_task_service_executes_single_step_through_tool_executor(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))
    try:
        manager.initialize_database()

        async def scenario() -> tuple[Any, str]:
            environment = task_environment(manager)
            await environment.registry.sync_devices(environment.adapter)
            result = await environment.service.create_and_run(
                create_request([TaskPlanStep(name="List", tool_name="list_devices", input={})]),
                correlation_id="correlation-single",
            )
            return result.task, "correlation-single"

        task, correlation_id = asyncio.run(scenario())
        assert task.status is TaskStatus.COMPLETED
        assert task.result == {
            "status": "completed",
            "completed_steps": 1,
            "execution_ids": ["execution-1"],
        }
        assert task.steps[0].status is TaskStepStatus.COMPLETED
        assert task.steps[0].output is not None
        assert len(task.executions) == 1
        assert task.executions[0].task_id == task.id
        assert task.executions[0].task_step_id == task.steps[0].id
        assert task.executions[0].correlation_id == correlation_id
        assert task.executions[0].validation == {"schema_valid": True, "verified": True}
        assert set(query_events(manager, correlation_id)) == {
            "task_started",
            "tool_executed",
            "task_completed",
        }
    finally:
        manager.dispose()


def test_task_service_executes_a_successful_multi_step_plan(tmp_path: Path) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))
    try:
        manager.initialize_database()

        async def scenario() -> Any:
            environment = task_environment(manager)
            await environment.registry.sync_devices(environment.adapter)
            devices = await environment.registry.list_devices()
            device_id = next(device.id for device in devices if device.device_type.value == "light")
            result = await environment.service.create_and_run(
                create_request(
                    [
                        TaskPlanStep(name="List", tool_name="list_devices", input={}),
                        TaskPlanStep(
                            name="Read light",
                            tool_name="get_device_state",
                            input={"device_id": device_id},
                        ),
                    ]
                ),
                correlation_id="correlation-multi-step",
            )
            return result.task

        task = asyncio.run(scenario())
        assert task.status is TaskStatus.COMPLETED
        assert [step.status for step in task.steps] == [
            TaskStepStatus.COMPLETED,
            TaskStepStatus.COMPLETED,
        ]
        assert task.result is not None
        assert task.result["completed_steps"] == 2
        assert len(task.executions) == 2
    finally:
        manager.dispose()


def test_task_service_executes_ordered_steps_and_cancels_after_failure(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))
    try:
        manager.initialize_database()

        async def scenario() -> Any:
            environment = task_environment(manager)
            await environment.registry.sync_devices(environment.adapter)
            devices = await environment.registry.list_devices()
            device_id = next(device.id for device in devices if device.device_type.value == "light")
            result = await environment.service.create_and_run(
                create_request(
                    [
                        TaskPlanStep(name="List", tool_name="list_devices", input={}),
                        TaskPlanStep(
                            name="Read missing",
                            tool_name="get_device_state",
                            input={"device_id": "missing-device-id-1234567890"},
                        ),
                        TaskPlanStep(name="Never runs", tool_name="list_devices", input={}),
                    ]
                ),
                correlation_id="correlation-failure",
            )
            assert device_id
            return result.task

        task = asyncio.run(scenario())
        assert task.status is TaskStatus.FAILED
        assert [step.status for step in task.steps] == [
            TaskStepStatus.COMPLETED,
            TaskStepStatus.FAILED,
            TaskStepStatus.CANCELLED,
        ]
        assert task.error is not None
        assert task.error["code"] == "PERMISSION_DENIED"
        assert len(task.executions) == 2
        assert "task_failed" in query_events(manager, task.correlation_id or "")
    finally:
        manager.dispose()


def test_task_confirmation_token_is_required_validated_and_idempotent(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))
    try:
        manager.initialize_database()

        async def scenario() -> tuple[Any, str]:
            environment = task_environment(
                manager,
                permissions={
                    "list_devices": "allow",
                    "get_device_state": "allow",
                    "control_device": "require_confirmation",
                },
            )
            await environment.registry.sync_devices(environment.adapter)
            devices = await environment.registry.list_devices()
            device_id = next(
                device.id for device in devices if device.external_id == "mock.light.living_room"
            )
            waiting = await environment.service.create_and_run(
                create_request(
                    [
                        TaskPlanStep(
                            name="Turn on",
                            tool_name="control_device",
                            input={"device_id": device_id, "action": "turn_on"},
                        )
                    ]
                ),
                correlation_id="correlation-confirmation",
            )
            assert waiting.task.status is TaskStatus.WAITING_CONFIRMATION
            assert waiting.confirmation_token is not None

            with pytest.raises(TaskStateError, match="does not match"):
                await environment.service.confirm(
                    waiting.task.id,
                    confirmation_token="wrong-token",
                    confirmed=True,
                )
            still_waiting = await environment.service.get_task_detail(waiting.task.id)
            assert still_waiting.status is TaskStatus.WAITING_CONFIRMATION

            confirmed = await environment.service.confirm(
                waiting.task.id,
                confirmation_token=waiting.confirmation_token,
                confirmed=True,
            )
            await environment.service.confirm(
                waiting.task.id,
                confirmation_token=waiting.confirmation_token,
                confirmed=True,
            )
            return (
                confirmed.task,
                waiting.confirmation_token or "",
                waiting.task.steps[0].started_at,
            )

        task, token, started_at = asyncio.run(scenario())
        assert query_task(manager, task.id).status is TaskStatus.COMPLETED
        assert token not in str(query_task(manager, task.id).plan)
        assert "confirmation" not in query_task(manager, task.id).plan
        assert task.steps[0].started_at == started_at
        assert query_task(manager, task.id).steps[0].started_at == started_at
        assert query_events(manager, task.correlation_id or "").count("user_confirmed") == 1
        assert len(query_task(manager, task.id).executions) == 2
    finally:
        manager.dispose()


def test_expired_confirmation_fails_and_waiting_task_timeout_cancels(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))
    try:
        manager.initialize_database()

        async def scenario() -> Any:
            clock = FixedClock()
            environment = task_environment(
                manager,
                permissions={"control_device": "require_confirmation"},
                clock=clock,
            )
            await environment.registry.sync_devices(environment.adapter)
            devices = await environment.registry.list_devices()
            device_id = next(
                device.id for device in devices if device.external_id == "mock.light.living_room"
            )

            expired = await environment.service.create_and_run(
                create_request(
                    [
                        TaskPlanStep(
                            name="Turn on",
                            tool_name="control_device",
                            input={"device_id": device_id, "action": "turn_on"},
                        )
                    ],
                    timeout_seconds=600,
                ),
                correlation_id="correlation-expired",
            )
            assert expired.confirmation_token is not None
            clock.now += timedelta(seconds=301)
            failed = await environment.service.confirm(
                expired.task.id,
                confirmation_token=expired.confirmation_token,
                confirmed=True,
            )

            waiting_timeout = await environment.service.create_and_run(
                create_request(
                    [
                        TaskPlanStep(
                            name="Turn on again",
                            tool_name="control_device",
                            input={"device_id": device_id, "action": "turn_on"},
                        )
                    ],
                    timeout_seconds=30,
                ),
                correlation_id="correlation-wait-timeout",
            )
            assert waiting_timeout.confirmation_token is not None
            clock.now += timedelta(seconds=31)
            cancelled = await environment.service.confirm(
                waiting_timeout.task.id,
                confirmation_token=waiting_timeout.confirmation_token,
                confirmed=True,
            )
            return failed.task, cancelled.task

        failed, cancelled = asyncio.run(scenario())
        assert failed.status is TaskStatus.FAILED
        assert failed.steps[0].status is TaskStepStatus.FAILED
        assert failed.error is not None
        assert failed.error["code"] == "PERMISSION_DENIED"
        assert cancelled.status is TaskStatus.CANCELLED
        assert cancelled.steps[0].status is TaskStepStatus.CANCELLED
        assert cancelled.error is not None
        assert cancelled.error["code"] == "TASK_CANCELLED"
    finally:
        manager.dispose()


def test_task_service_cancels_pending_steps_and_rejects_duplicate_cancel(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))
    try:
        manager.initialize_database()

        async def scenario() -> Any:
            environment = task_environment(manager)
            task = await environment.service.create_task(
                create_request([TaskPlanStep(name="List", tool_name="list_devices", input={})]),
                correlation_id="correlation-cancel",
            )
            cancelled = await environment.service.cancel(task.id, reason="User cancelled.")
            return cancelled

        task = asyncio.run(scenario())
        assert task.status is TaskStatus.CANCELLED
        assert task.steps[0].status is TaskStepStatus.CANCELLED
        service_environment = task_environment(manager)
        with pytest.raises(TaskStateError, match="cannot be cancelled"):
            asyncio.run(service_environment.service.cancel(task.id, reason="Again"))
        with pytest.raises(TaskStateError, match="no longer waiting"):
            asyncio.run(
                service_environment.service.confirm(
                    task.id,
                    confirmation_token="unused",
                    confirmed=False,
                )
            )
    finally:
        manager.dispose()


@dataclass
class DelayedToolExecutor:
    delay_seconds: float
    calls: list[dict[str, Any]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.calls = []

    async def execute(
        self,
        tool_name: str,
        raw_input: dict[str, Any],
        *,
        context: Any,
        confirmation_token: str | None = None,
        task_id: str | None = None,
        task_step_id: str | None = None,
    ) -> Any:
        self.calls.append(
            {
                "tool_name": tool_name,
                "context": context,
                "task_id": task_id,
                "task_step_id": task_step_id,
            }
        )
        await asyncio.sleep(self.delay_seconds)
        raise RuntimeError("unexpected executor failure after delay")


def test_task_timeout_marks_step_timed_out_and_task_failed(tmp_path: Path) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))
    try:
        manager.initialize_database()

        async def scenario() -> Any:
            def factory() -> SqlAlchemyUnitOfWork:
                return SqlAlchemyUnitOfWork(manager.session_factory)

            executor = DelayedToolExecutor(2)
            service = TaskService(factory, executor, EventBus(factory))
            return await service.create_and_run(
                create_request(
                    [TaskPlanStep(name="Slow", tool_name="list_devices", input={})],
                    timeout_seconds=1,
                ),
                correlation_id="correlation-timeout",
            )

        result = asyncio.run(scenario())
        assert result.task.status is TaskStatus.FAILED
        assert result.task.steps[0].status is TaskStepStatus.TIMED_OUT
        assert result.task.error is not None
        assert result.task.error["code"] == "TASK_TIMEOUT"
    finally:
        manager.dispose()


@dataclass
class BrokenToolExecutor:
    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("tool boundary crashed")


@dataclass
class ConfirmThenBrokenToolExecutor:
    async def execute(
        self,
        *_args: Any,
        confirmation_token: str | None = None,
        **_kwargs: Any,
    ) -> Any:
        if confirmation_token is None:
            raise ToolConfirmationRequiredError(
                "Confirmation is required.",
                details={"confirmation_token": "task-confirmation-token"},
            )
        raise RuntimeError("tool boundary crashed after confirmation")


def test_unexpected_tool_executor_error_recovers_task_to_failed(tmp_path: Path) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))
    try:
        manager.initialize_database()

        async def scenario() -> Any:
            def factory() -> SqlAlchemyUnitOfWork:
                return SqlAlchemyUnitOfWork(manager.session_factory)

            service = TaskService(factory, BrokenToolExecutor(), EventBus(factory))
            return await service.create_and_run(
                create_request([TaskPlanStep(name="Broken", tool_name="broken", input={})]),
                correlation_id="correlation-broken",
            )

        result = asyncio.run(scenario())
        assert result.task.status is TaskStatus.FAILED
        assert result.task.steps[0].status is TaskStepStatus.FAILED
        assert result.task.error is not None
        assert result.task.error["code"] == "TASK_EXECUTION_FAILED"
        assert "task_failed" in query_events(manager, "correlation-broken")
    finally:
        manager.dispose()


def test_unexpected_confirmed_step_error_recovers_task_to_failed(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))
    try:
        manager.initialize_database()

        async def scenario() -> Any:
            def factory() -> SqlAlchemyUnitOfWork:
                return SqlAlchemyUnitOfWork(manager.session_factory)

            service = TaskService(factory, ConfirmThenBrokenToolExecutor(), EventBus(factory))
            waiting = await service.create_and_run(
                create_request([TaskPlanStep(name="Broken", tool_name="broken", input={})]),
                correlation_id="correlation-confirmed-broken",
            )
            assert waiting.confirmation_token is not None
            return await service.confirm(
                waiting.task.id,
                confirmation_token=waiting.confirmation_token,
                confirmed=True,
            )

        result = asyncio.run(scenario())
        assert result.task.status is TaskStatus.FAILED
        assert result.task.steps[0].status is TaskStepStatus.FAILED
        assert result.task.error is not None
        assert result.task.error["code"] == "TASK_EXECUTION_FAILED"
        assert "user_confirmed" in query_events(manager, "correlation-confirmed-broken")
    finally:
        manager.dispose()


@dataclass
class ControlledToolExecutor:
    release: asyncio.Event

    async def execute(
        self,
        tool_name: str,
        raw_input: dict[str, Any],
        *,
        context: Any,
        **_kwargs: Any,
    ) -> Any:
        await self.release.wait()
        return ToolExecutionResult(
            execution_id="execution-controlled",
            tool_name=tool_name,
            status="succeeded",
            input=raw_input,
            output={},
            verified=True,
            risk_level=ToolRiskLevel.READ_ONLY,
            permission_result=PermissionResult.ALLOWED,
            correlation_id=context.correlation_id,
        )


def test_cancel_during_tool_execution_is_not_overwritten(tmp_path: Path) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))
    try:
        manager.initialize_database()

        async def scenario() -> Any:
            def factory() -> SqlAlchemyUnitOfWork:
                return SqlAlchemyUnitOfWork(manager.session_factory)

            executor = ControlledToolExecutor(asyncio.Event())
            service = TaskService(
                factory,
                executor,
                EventBus(factory),
                task_id_factory=lambda: "task-cancel-race",
                step_id_factory=lambda: "step-cancel-race",
            )
            task = await service.create_task(
                create_request([TaskPlanStep(name="Slow", tool_name="list_devices", input={})]),
                correlation_id="correlation-cancel-race",
            )
            running = asyncio.create_task(service.run_task(task.id))
            await asyncio.sleep(0)
            while True:
                current = await service.get_task_detail(task.id)
                if current.steps[0].status is TaskStepStatus.RUNNING:
                    break
                await asyncio.sleep(0)
            cancelled = await service.cancel(task.id, reason="User cancelled during execution.")
            executor.release.set()
            return cancelled, await running

        cancelled, completed_path = asyncio.run(scenario())
        assert cancelled.status is TaskStatus.CANCELLED
        assert cancelled.steps[0].status is TaskStepStatus.CANCELLED
        assert completed_path.task.status is TaskStatus.CANCELLED
        assert completed_path.task.steps[0].status is TaskStepStatus.CANCELLED
        assert query_task(manager, cancelled.id).status is TaskStatus.CANCELLED
    finally:
        manager.dispose()


def test_tasks_api_requires_auth_and_exposes_task_lifecycle(tmp_path: Path) -> None:
    settings = phase_settings(tmp_path)
    manager = DatabaseManager(settings)
    try:
        manager.initialize_database()
        app = create_app(
            settings,
            unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
            initialize_tool_runtime=True,
        )
        headers = {"Authorization": "Bearer test-api-token"}
        body = {
            "task_type": "device.query",
            "title": "List devices",
            "steps": [{"name": "List", "tool_name": "list_devices", "input": {}}],
        }
        with TestClient(app) as client:
            unauthorized = client.post("/api/tasks", json=body)
            response = client.post(
                "/api/tasks",
                headers={**headers, "X-Correlation-ID": "correlation-api"},
                json=body,
            )
            task_id = response.json()["data"]["id"]
            history = client.get(
                "/api/tasks",
                headers=headers,
                params={"status": "completed", "task_type": "device.query"},
            )
            detail = client.get(f"/api/tasks/{task_id}", headers=headers)
            missing = client.get("/api/tasks/missing-task", headers=headers)
            cancel = client.post(f"/api/tasks/{task_id}/cancel", headers=headers)
            invalid_status = client.get(
                "/api/tasks",
                headers=headers,
                params={"status": "unknown"},
            )
            openapi = client.get("/openapi.json")

        confirmation_settings = phase_settings(tmp_path)
        confirmation_settings.tool_permissions = {
            "list_devices": "allow",
            "get_device_state": "allow",
            "control_device": "require_confirmation",
        }
        confirmation_app = create_app(
            confirmation_settings,
            unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
            initialize_tool_runtime=True,
        )
        with TestClient(confirmation_app) as client:
            devices = asyncio.run(confirmation_app.state.device_service.list_devices())
            device_id = next(
                device.id for device in devices if device.external_id == "mock.light.living_room"
            )
            waiting = client.post(
                "/api/tasks",
                headers={**headers, "X-Correlation-ID": "correlation-api-confirmation"},
                json={
                    "task_type": "device.operation",
                    "title": "Turn on a light",
                    "steps": [
                        {
                            "name": "Turn on",
                            "tool_name": "control_device",
                            "input": {"device_id": device_id, "action": "turn_on"},
                        }
                    ],
                },
            )
            confirmation_token = waiting.json()["data"]["confirmation_token"]
            confirmed = client.post(
                f"/api/tasks/{waiting.json()['data']['id']}/confirm",
                headers=headers,
                json={"confirmed": True, "confirmation_token": confirmation_token},
            )

        assert unauthorized.status_code == 401
        assert response.status_code == 200
        assert response.headers["X-Correlation-ID"] == "correlation-api"
        assert response.json()["data"]["status"] == "completed"
        assert history.status_code == 200
        assert history.json()["total"] == 1
        assert detail.status_code == 200
        assert detail.json()["data"]["executions"][0]["correlation_id"] == "correlation-api"
        assert waiting.status_code == 200
        assert waiting.json()["data"]["status"] == "waiting_confirmation"
        assert confirmed.status_code == 200
        assert confirmed.json()["data"]["status"] == "completed"
        assert len(confirmed.json()["data"]["steps"]) == 1
        assert len(confirmed.json()["data"]["executions"]) == 2
        assert missing.status_code == 404
        assert cancel.status_code == 409
        assert invalid_status.status_code == 400
        assert openapi.status_code == 200
        for path in (
            "/api/tasks",
            "/api/tasks/{task_id}",
            "/api/tasks/{task_id}/confirm",
            "/api/tasks/{task_id}/cancel",
        ):
            assert path in openapi.json()["paths"]
    finally:
        manager.dispose()
