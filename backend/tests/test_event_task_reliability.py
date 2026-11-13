import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from arvuno_core.automation.models import (
    AutomationCondition,
    AutomationCreate,
    AutomationRunStatus,
    AutomationToolAction,
    AutomationTrigger,
)
from arvuno_core.automation.service import AutomationService
from arvuno_core.devices.registry import DeviceRegistry
from arvuno_core.events.bus import EventBus
from arvuno_core.events.models import (
    ArvunoEvent,
    ArvunoEventSource,
    ArvunoEventType,
    DeviceStateChangedPayload,
)
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.tasks.models import (
    TaskCreate,
    TaskPlanStep,
    TaskRunResult,
    TaskStatus,
    TaskStepStatus,
)
from arvuno_core.tasks.service import TaskService
from arvuno_core.tools.errors import ToolConfirmationRequiredError
from arvuno_core.tools.models import (
    PermissionResult,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolRiskLevel,
)
from tests.test_automation_system import (
    automation_environment,
    automation_settings,
    state_event,
)


def manager_for(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(automation_settings(tmp_path))
    manager.initialize_database()
    return manager


def domain_event() -> ArvunoEvent:
    return ArvunoEvent(
        event_type=ArvunoEventType.DEVICE_STATE_CHANGED,
        source=ArvunoEventSource.MOCK_ADAPTER,
        subject_type="device",
        subject_id="device-1",
        payload=DeviceStateChangedPayload(
            device_id="device-1",
            previous_state="off",
            current_state="on",
        ),
        correlation_id="event-task-reliability",
    )


@dataclass
class ConfirmationExecutor:
    calls: int = 0

    async def execute(
        self,
        tool_name: str,
        raw_input: dict[str, Any],
        *,
        context: ToolExecutionContext,
        confirmation_token: str | None = None,
        **_kwargs: Any,
    ) -> ToolExecutionResult:
        self.calls += 1
        if confirmation_token is None:
            raise ToolConfirmationRequiredError(
                "Confirmation is required.",
                details={"confirmation_token": "process-local-token"},
            )
        return ToolExecutionResult(
            execution_id="execution-confirmed",
            tool_name=tool_name,
            status="succeeded",
            input=raw_input,
            output={"confirmed": True},
            verified=True,
            risk_level=ToolRiskLevel.LOW,
            permission_result=PermissionResult.ALLOWED,
            correlation_id=context.correlation_id,
        )


@dataclass
class WaitingTaskProxy:
    task_service: TaskService
    token: str | None = None

    async def create_and_run(
        self,
        request: TaskCreate,
        *,
        correlation_id: str | None = None,
    ) -> TaskRunResult:
        result = await self.task_service.create_and_run(
            request,
            correlation_id=correlation_id,
        )
        self.token = result.confirmation_token
        return result


def test_slow_subscriber_times_out_without_blocking_other_subscribers(tmp_path: Path) -> None:
    manager = manager_for(tmp_path)
    try:

        async def scenario() -> tuple[bool, list[ArvunoEvent]]:
            release = asyncio.Event()
            started = asyncio.Event()
            received: list[ArvunoEvent] = []

            async def slow_subscriber(_event: ArvunoEvent) -> None:
                started.set()
                await release.wait()

            async def fast_subscriber(event: ArvunoEvent) -> None:
                received.append(event)

            bus = EventBus(
                lambda: SqlAlchemyUnitOfWork(manager.session_factory),
                subscriber_timeout_seconds=0.03,
            )
            bus.subscribe(slow_subscriber)
            bus.subscribe(fast_subscriber)

            await bus.publish(domain_event())
            release.set()
            return started.is_set(), received

        started, received = asyncio.run(scenario())
        assert started
        assert received
    finally:
        manager.dispose()


@pytest.mark.parametrize(
    ("confirmed", "expected_run_status", "expected_task_status"),
    [
        (True, AutomationRunStatus.COMPLETED, TaskStatus.COMPLETED),
        (False, AutomationRunStatus.CANCELLED, TaskStatus.CANCELLED),
    ],
)
def test_waiting_automation_run_follows_confirmation_decision(
    tmp_path: Path,
    confirmed: bool,
    expected_run_status: AutomationRunStatus,
    expected_task_status: TaskStatus,
) -> None:
    manager = manager_for(tmp_path)
    try:

        async def scenario() -> tuple[
            list[AutomationRunStatus],
            list[AutomationRunStatus],
            TaskStatus,
        ]:
            environment = automation_environment(
                manager,
                tool_permissions={"control_device": "require_confirmation"},
            )
            registry = DeviceRegistry(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
            await registry.sync_devices(environment.adapter)
            light = await registry.get_by_external_id("mock", "mock.light.living_room")
            assert light is not None

            proxy = WaitingTaskProxy(environment.task_service)
            automation = AutomationService(
                lambda: SqlAlchemyUnitOfWork(manager.session_factory),
                proxy,
                environment.event_bus,
                clock=environment.clock,
            )
            environment.task_service.lifecycle_observer = automation
            rule = await automation.create(
                AutomationCreate(
                    name="Confirmation-gated automation",
                    trigger=AutomationTrigger(
                        event_type="device_state_changed",
                        subject_id=light.id,
                    ),
                    conditions=[
                        AutomationCondition(
                            field="payload.current_state",
                            operator="eq",
                            value="on",
                        )
                    ],
                    action=AutomationToolAction(
                        tool_name="control_device",
                        input={"device_id": light.id, "action": "turn_on"},
                        title="Turn on light",
                        risk_level="read_only",
                    ),
                )
            )

            event = state_event(light.id)
            persistence_bus = EventBus(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
            await persistence_bus.publish(event)
            await automation.handle_event(event)
            waiting_runs = await automation.list_runs(rule.id)
            task_id = waiting_runs.items[0].task_id
            assert task_id is not None
            assert proxy.token is not None

            await environment.task_service.confirm(
                task_id,
                confirmation_token=proxy.token,
                confirmed=confirmed,
            )
            final_runs = await automation.list_runs(rule.id)
            task = await environment.task_service.get_task_detail(task_id)
            return (
                [run.status for run in waiting_runs.items],
                [run.status for run in final_runs.items],
                task.status,
            )

        waiting_statuses, final_statuses, task_status = asyncio.run(scenario())
        assert waiting_statuses == [AutomationRunStatus.WAITING_CONFIRMATION]
        assert final_statuses == [expected_run_status]
        assert task_status is expected_task_status
    finally:
        manager.dispose()


def test_restart_cancels_unconfirmable_waiting_task(tmp_path: Path) -> None:
    manager = manager_for(tmp_path)
    try:

        async def scenario() -> tuple[TaskStatus, str, str]:
            def factory() -> SqlAlchemyUnitOfWork:
                return SqlAlchemyUnitOfWork(manager.session_factory)

            first = TaskService(factory, ConfirmationExecutor(), EventBus(factory))
            waiting = await first.create_and_run(
                TaskCreate(
                    task_type="device.operation",
                    title="Waiting",
                    origin="api",
                    steps=[
                        TaskPlanStep(
                            name="Control",
                            tool_name="control_device",
                            input={"device_id": "device-1", "action": "turn_on"},
                        )
                    ],
                ),
                correlation_id="restart-waiting",
            )
            assert waiting.confirmation_token is not None

            second = TaskService(factory, ConfirmationExecutor(), EventBus(factory))
            recovery = await second.recover_tasks()
            recovered = await second.get_task_detail(waiting.task.id)
            message = recovered.error["message"] if recovered.error is not None else ""
            return (
                recovered.status,
                message,
                recovery.waiting_cancelled_task_ids[0],
            )

        status, message, recovered_task_id = asyncio.run(scenario())
        assert status is TaskStatus.CANCELLED
        assert "confirmation token was lost" in message
        assert recovered_task_id
    finally:
        manager.dispose()


def test_restart_does_not_repeat_a_running_device_execution(tmp_path: Path) -> None:
    manager = manager_for(tmp_path)
    try:

        async def scenario() -> tuple[TaskStatus, TaskStepStatus, str, list[str], int, str]:
            def factory() -> SqlAlchemyUnitOfWork:
                return SqlAlchemyUnitOfWork(manager.session_factory)

            first = TaskService(factory, ConfirmationExecutor(), EventBus(factory))
            task = await first.create_task(
                TaskCreate(
                    task_type="device.operation",
                    title="Interrupted",
                    origin="api",
                    steps=[
                        TaskPlanStep(
                            name="Control",
                            tool_name="control_device",
                            input={"device_id": "device-1", "action": "turn_on"},
                        )
                    ],
                ),
                correlation_id="restart-unknown",
            )
            task_detail = await first.get_task_detail(task.id)
            with SqlAlchemyUnitOfWork(manager.session_factory) as unit_of_work:
                assert unit_of_work.tasks is not None
                unit_of_work.tasks.update_task_status(
                    task.id,
                    TaskStatus.PLANNING,
                    now=first._now(),
                    plan=task.plan,
                )
                unit_of_work.tasks.update_task_status(
                    task.id,
                    TaskStatus.RUNNING,
                    now=first._now(),
                    plan=task.plan,
                )
                unit_of_work.tasks.update_step_status(
                    task_detail.steps[0].id,
                    TaskStepStatus.RUNNING,
                    now=first._now(),
                )
                unit_of_work.commit()

            executor = ConfirmationExecutor()
            second = TaskService(factory, executor, EventBus(factory))
            recovery = await second.recover_tasks()
            recovered = await second.get_task_detail(task.id)
            error_code = recovered.error["code"] if recovered.error is not None else ""
            return (
                recovered.status,
                recovered.steps[0].status,
                error_code,
                recovery.unknown_task_ids,
                executor.calls,
                task.id,
            )

        status, step_status, error_code, unknown_ids, calls, task_id = asyncio.run(scenario())
        assert status is TaskStatus.NEEDS_VERIFICATION
        assert step_status is TaskStepStatus.TIMED_OUT
        assert error_code == "TASK_EXECUTION_UNKNOWN"
        assert unknown_ids == [task_id]
        assert calls == 0
    finally:
        manager.dispose()
