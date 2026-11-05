import asyncio
import itertools
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from arvuno_core.config import Settings
from arvuno_core.devices.mock import MockDeviceAdapter
from arvuno_core.devices.registry import DeviceRegistry
from arvuno_core.devices.service import DeviceApplicationService
from arvuno_core.errors import ArvunoError
from arvuno_core.events.bus import EventBus
from arvuno_core.observations.pipeline import ObservationPipeline
from arvuno_core.observations.service import ObservationService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.tools import SqlToolExecutionStore
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.planning.errors import PlanningStateError
from arvuno_core.planning.service import PlanningService
from arvuno_core.schemas.planning import (
    GoalCompileRequest,
    PlanCreateRequest,
    ReplanRequest,
)
from arvuno_core.tasks.service import TaskService
from arvuno_core.tools.catalog import RegistryToolCatalog
from arvuno_core.tools.confirmation import ConfirmationService
from arvuno_core.tools.executor import ToolExecutor
from arvuno_core.tools.registry import build_default_tool_registry
from arvuno_core.tools.safety import SafetyPolicy


@dataclass
class FixedClock:
    now: datetime = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@dataclass
class PlanningEnvironment:
    manager: DatabaseManager
    adapter: MockDeviceAdapter
    service: PlanningService
    task_service: TaskService


def phase_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


def planning_environment(
    tmp_path: Path,
    *,
    control_permission: str = "allow_low_risk",
) -> PlanningEnvironment:
    manager = DatabaseManager(phase_settings(tmp_path))
    manager.initialize_database()

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(manager.session_factory)

    adapter = MockDeviceAdapter()
    registry = DeviceRegistry(factory)
    asyncio.run(registry.sync_devices(adapter))
    observation_pipeline = ObservationPipeline(factory, ObservationService(factory))
    device_service = DeviceApplicationService(registry, {"mock": adapter}, observation_pipeline)
    event_bus = EventBus(factory)
    clock = FixedClock()
    task_counter = itertools.count(1)
    step_counter = itertools.count(1)
    execution_counter = itertools.count(1)
    tool_registry = build_default_tool_registry(device_service)
    executor = ToolExecutor(
        registry=tool_registry,
        safety_policy=SafetyPolicy(
            device_service,
            tool_permissions={
                "list_devices": "allow",
                "get_device_state": "allow",
                "control_device": control_permission,
            },
        ),
        confirmation_service=ConfirmationService(ttl_seconds=300, clock=clock),
        execution_store=SqlToolExecutionStore(factory),
        event_publisher=event_bus,
        execution_id_factory=lambda: f"execution-{next(execution_counter)}",
    )
    task_service = TaskService(
        factory,
        executor,
        event_bus,
        clock=clock,
        task_id_factory=lambda: f"task-{next(task_counter)}",
        step_id_factory=lambda: f"step-{next(step_counter)}",
    )
    service = PlanningService(
        factory,
        RegistryToolCatalog(
            tool_registry,
            permissions={
                "list_devices": "allow",
                "get_device_state": "allow",
                "control_device": control_permission,
            },
        ),
        task_service,
        device_service,
    )
    return PlanningEnvironment(manager, adapter, service, task_service)


async def _compile_goal(
    service: PlanningService,
    objective: str,
    **overrides: Any,
) -> Any:
    authorization_scope = overrides.pop(
        "authorization_scope",
        {"max_risk_level": "low_risk"},
    )
    request = GoalCompileRequest(
        objective=objective,
        authorization_scope=authorization_scope,
        **overrides,
    )
    return await service.compile_goal(request)


async def _active_goal(service: PlanningService, objective: str, **overrides: Any) -> Any:
    goal = await _compile_goal(service, objective, **overrides)
    return await service.confirm_goal(goal.id, requested_authorization={}, reason="test")


def test_goal_is_structured_confirmed_and_generates_waiting_plan(tmp_path: Path) -> None:
    environment = planning_environment(tmp_path)

    try:

        async def scenario() -> None:
            goal = await _compile_goal(
                environment.service,
                "把客厅灯打开",
                origin_type="user",
                source_record_id="conversation-1",
            )
            assert goal.status == "candidate"
            assert goal.confirmed_by_user is False
            assert goal.desired_state["state"] == "on"
            assert goal.desired_state["action"] == "turn_on"
            assert goal.scope["device_type"] == "light"
            assert goal.origin_type == "user"
            assert goal.origin_record_id == "conversation-1"
            assert goal.authorization_scope["max_risk_level"] == "low_risk"

            confirmed = await environment.service.confirm_goal(
                goal.id,
                requested_authorization={},
                reason="The user confirmed the goal.",
            )
            assert confirmed.status == "active"
            assert confirmed.confirmed_by_user is True
            assert confirmed.revisions[-1].change_type == "confirm"

            plan = await environment.service.create_plan(
                goal.id,
                PlanCreateRequest(mode="plan"),
            )
            assert plan.version == 1
            assert plan.status == "awaiting_confirmation"
            assert plan.run_mode == "awaiting_confirmation"
            assert [step.tool_name for step in plan.steps] == [
                "get_device_state",
                "control_device",
                "get_device_state",
            ]
            assert plan.steps[1].depends_on == [plan.steps[0].id]
            assert plan.steps[2].depends_on == [plan.steps[1].id]
            assert plan.steps[1].risk_level == "low_risk"
            assert plan.steps[1].requires_confirmation is True

        asyncio.run(scenario())
    finally:
        environment.manager.dispose()


def test_ambiguous_goal_records_clarifications_without_a_device_plan(tmp_path: Path) -> None:
    environment = planning_environment(tmp_path)

    try:

        async def scenario() -> None:
            goal = await _active_goal(environment.service, "请让房间舒服一点")
            assert goal.status == "active"
            assert goal.desired_state.get("device_id") is None
            assert "Please confirm the desired device state." in goal.clarifications
            assert "Please identify the target device type." in goal.clarifications
            assert "target_device_type" in goal.unknowns

            analysis = await environment.service.analyze_goal(goal.id)
            assert analysis["blocked_by"] == ["goal_target_unresolved"]
            plans, total = await environment.service.list_plans(goal_id=goal.id)
            assert (plans, total) == ([], 0)

        asyncio.run(scenario())
    finally:
        environment.manager.dispose()


def test_goal_authorization_is_capped_and_confirmation_cannot_expand_it(
    tmp_path: Path,
) -> None:
    environment = planning_environment(tmp_path)

    try:

        async def scenario() -> None:
            goal = await _compile_goal(
                environment.service,
                "turn on the living room light",
                authorization_scope={
                    "max_risk_level": "high_risk",
                    "automatic_execution": "limited",
                },
            )
            assert goal.authorization_scope["max_risk_level"] == "low_risk"
            assert goal.authorization_scope["automatic_execution"] == "limited"

            with pytest.raises(PlanningStateError, match="cannot expand"):
                await environment.service.confirm_goal(
                    goal.id,
                    requested_authorization={"max_risk_level": "medium_risk"},
                    reason="attempted expansion",
                )

            unchanged = await environment.service.get_goal(goal.id)
            assert unchanged.authorization_scope["max_risk_level"] == "low_risk"

        asyncio.run(scenario())
    finally:
        environment.manager.dispose()


def test_offline_device_is_rejected_before_plan_persistence(tmp_path: Path) -> None:
    environment = planning_environment(tmp_path)

    try:

        async def scenario() -> None:
            goal = await _active_goal(environment.service, "turn on the living room light")
            environment.adapter.set_offline("mock.light.living_room")
            with pytest.raises(PlanningStateError, match="offline"):
                await environment.service.create_plan(goal.id, PlanCreateRequest())
            _, total = await environment.service.list_plans(goal_id=goal.id)
            assert total == 0

        asyncio.run(scenario())
    finally:
        environment.manager.dispose()


def test_disabled_or_unpermitted_tool_produces_rejected_plan(tmp_path: Path) -> None:
    environment = planning_environment(tmp_path, control_permission="allow_read_only")

    try:

        async def scenario() -> None:
            goal = await _active_goal(environment.service, "turn on the living room light")
            with pytest.raises(ArvunoError, match="failed validation"):
                await environment.service.create_plan(goal.id, PlanCreateRequest())

            plan, total = await environment.service.list_plans(goal_id=goal.id)
            assert total == 1
            assert plan[0].status == "rejected"
            codes = {error["code"] for error in plan[0].validation_errors}
            assert "TOOL_UNAVAILABLE_OR_INVALID" in codes

        asyncio.run(scenario())
    finally:
        environment.manager.dispose()


def test_prohibited_action_is_rejected_and_preserved_for_audit(tmp_path: Path) -> None:
    environment = planning_environment(tmp_path)

    try:

        async def scenario() -> None:
            goal = await _active_goal(
                environment.service,
                "turn on the living room light",
                prohibitions=[{"action": "turn_on", "device_id": "*"}],
            )
            with pytest.raises(ArvunoError, match="failed validation"):
                await environment.service.create_plan(goal.id, PlanCreateRequest())
            plan, _ = await environment.service.list_plans(goal_id=goal.id)
            assert plan[0].status == "rejected"
            assert {"code": "PROHIBITED_ACTION", "step_index": 1} in plan[0].validation_errors

        asyncio.run(scenario())
    finally:
        environment.manager.dispose()


def test_approved_plan_submits_to_task_system_and_waits_for_tool_confirmation(
    tmp_path: Path,
) -> None:
    environment = planning_environment(tmp_path)

    try:

        async def scenario() -> str:
            goal = await _active_goal(environment.service, "turn on the living room light")
            plan = await environment.service.create_plan(goal.id, PlanCreateRequest())
            approved = await environment.service.approve_plan(plan.id, reason="user approved")
            assert approved.status == "approved"
            submitted = await environment.service.submit_plan(approved.id)
            assert submitted.status == "submitted"
            assert submitted.submitted_task_id is not None

            detail = await environment.task_service.get_task_detail(submitted.submitted_task_id)
            assert detail.task_type == "planning.execute"
            assert detail.steps[0].status.value == "completed"
            assert detail.steps[1].status.value == "waiting_confirmation"
            assert submitted.submitted_task_id.startswith("task-")
            return submitted.submitted_task_id

        task_id = asyncio.run(scenario())
        assert task_id.startswith("task-")
    finally:
        environment.manager.dispose()


def test_task_failure_replan_preserves_history_and_creates_next_version(
    tmp_path: Path,
) -> None:
    environment = planning_environment(tmp_path)

    try:

        async def scenario() -> None:
            goal = await _active_goal(environment.service, "turn on the living room light")
            plan = await environment.service.create_plan(goal.id, PlanCreateRequest())
            await environment.service.approve_plan(plan.id, reason="user approved")
            environment.adapter.set_action_failure("mock.light.living_room")
            failed = await environment.service.submit_plan(plan.id)
            assert failed.status == "submitted"

            replacement = await environment.service.replan(
                plan.id,
                ReplanRequest(
                    trigger_type="tool_failed",
                    task_id=failed.submitted_task_id,
                    trigger_record_type="task",
                    trigger_record_id=failed.submitted_task_id,
                    change_summary={"failed_step": "control_device"},
                    reason="The adapter rejected the action.",
                ),
            )
            assert replacement.version == 2
            assert replacement.status == "awaiting_confirmation"

            old_plan = await environment.service.get_plan(plan.id)
            assert old_plan.status == "superseded"
            assert old_plan.superseded_by_id == replacement.id
            assert old_plan.replanning_records[-1].decision == "replan"
            assert old_plan.replanning_records[-1].already_executed_steps[0]["step_index"] == 0

        asyncio.run(scenario())
    finally:
        environment.manager.dispose()


def test_replan_after_unsatisfactory_result_does_not_expand_authorization(
    tmp_path: Path,
) -> None:
    environment = planning_environment(tmp_path)

    try:

        async def scenario() -> None:
            goal = await _active_goal(environment.service, "turn off the living room light")
            plan = await environment.service.create_plan(goal.id, PlanCreateRequest())
            replacement = await environment.service.replan(
                plan.id,
                ReplanRequest(
                    trigger_type="verification_failed",
                    change_summary={"observed_state": "on"},
                    reason="The result did not satisfy the goal.",
                ),
            )
            assert replacement.status == "awaiting_confirmation"
            assert replacement.max_risk_level == "low_risk"
            assert replacement.goal_id == goal.id

        asyncio.run(scenario())
    finally:
        environment.manager.dispose()


def test_planner_uses_service_boundaries_and_does_not_operate_devices_directly() -> None:
    service_source = (
        Path(__file__).parents[1] / "arvuno_core" / "planning" / "service.py"
    ).read_text(encoding="utf-8")
    assert "ToolExecutor" not in service_source
    assert "DeviceAdapter" not in service_source
    assert "SqlAlchemyUnitOfWork" in service_source
    assert ".execute(" not in service_source
