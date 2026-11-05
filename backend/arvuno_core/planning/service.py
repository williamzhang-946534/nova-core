from __future__ import annotations

import asyncio
import re
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from arvuno_core.agent_runtime.models import AgentToolDescriptor
from arvuno_core.devices.errors import DeviceUnavailableError
from arvuno_core.devices.models import DeviceActionName, DeviceStateName
from arvuno_core.devices.registry import RegisteredDevice
from arvuno_core.persistence.models import Goal, GoalRevision, Plan, PlanReplanningRecord, PlanStep
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.planning.errors import (
    GoalNotFoundError,
    PlanningEnvironmentNotFoundError,
    PlanningStateError,
    PlanNotFoundError,
    PlanValidationError,
)
from arvuno_core.planning.models import PlanView
from arvuno_core.schemas.planning import (
    GoalCompileRequest,
    PlanCreateRequest,
    ReplanRequest,
)
from arvuno_core.tasks.models import TaskCreate, TaskPlanStep
from arvuno_core.tools.catalog import RegistryToolCatalog

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
RISK_ORDER = {"read_only": 0, "low_risk": 1, "medium_risk": 2, "high_risk": 3}
SYSTEM_MAX_RISK = "low_risk"


class TaskSystemProtocol(Protocol):
    async def create_and_run(
        self,
        request: TaskCreate,
        *,
        correlation_id: str | None = None,
    ) -> Any: ...

    async def get_task_detail(self, task_id: str) -> Any: ...


class DeviceServiceProtocol(Protocol):
    async def list_devices(self, **filters: object) -> list[RegisteredDevice]: ...

    async def get_registered_device(self, device_id: str) -> RegisteredDevice: ...

    async def get_state(self, device_id: str) -> Any: ...


def _now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    return current if current.tzinfo is not None else current.replace(tzinfo=UTC)


class PlanningService:
    """Compiles confirmed goals into validated candidate task plans."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        tool_catalog: RegistryToolCatalog,
        task_system: TaskSystemProtocol,
        device_service: DeviceServiceProtocol,
        *,
        environment_name: str = "home",
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._tool_catalog = tool_catalog
        self._task_system = task_system
        self._device_service = device_service
        self._environment_name = environment_name

    async def compile_goal(self, request: GoalCompileRequest) -> Goal:
        now = _now(request.now)
        parsed = self._parse_objective(request.objective, request.desired_state)
        authorization = self._normal_authorization(request.authorization_scope)
        title = self._title(request.objective, parsed)
        goal = Goal(
            environment_id="pending",
            title=title,
            description=request.description,
            objective=request.objective,
            origin_type=request.origin_type,
            origin_record_id=request.source_record_id,
            status="candidate",
            goal_type=parsed["goal_type"],
            scope=parsed["scope"],
            desired_state=parsed["desired_state"],
            constraints=request.constraints,
            prohibitions=request.prohibitions,
            clarifications=parsed["clarifications"],
            unknowns=parsed["unknowns"],
            success_conditions=parsed["success_conditions"],
            failure_conditions=parsed["failure_conditions"],
            priority=request.priority,
            authorization_scope=authorization,
            time_window=request.time_window,
            reasoning_session_id=request.reasoning_session_id,
            confirmed_by_user=False,
            created_at=now,
            updated_at=now,
        )
        revision = GoalRevision(
            revision=1,
            change_type="create",
            before=None,
            after=self._goal_snapshot(goal),
            reason="Compiled from the original objective.",
            source_type=request.origin_type,
            source_id=request.source_record_id,
            created_at=now,
        )

        def execute() -> str:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.planning is not None
                environment = unit_of_work.planning.environment(
                    request.environment_id,
                    self._environment_name,
                )
                if environment is None:
                    raise PlanningEnvironmentNotFoundError()
                if request.reasoning_session_id is not None and (
                    unit_of_work.planning.reasoning_session(
                        request.reasoning_session_id,
                        environment.id,
                    )
                    is None
                ):
                    raise PlanningStateError("The referenced reasoning session is unavailable.")
                goal.environment_id = environment.id
                revision.after = self._goal_snapshot(goal)
                unit_of_work.planning.add_goal(goal, revision)
                unit_of_work.commit()
                return goal.id

        goal_id = await asyncio.to_thread(execute)
        return await self.get_goal(goal_id)

    async def confirm_goal(
        self,
        goal_id: str,
        *,
        requested_authorization: dict[str, Any] | None,
        reason: str | None,
    ) -> Goal:
        def execute() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.planning is not None
                goal = unit_of_work.planning.get_goal(goal_id)
                if goal is None:
                    raise GoalNotFoundError()
                if goal.status not in {"candidate", "paused"}:
                    raise PlanningStateError("Only a candidate or paused goal can be confirmed.")
                before = self._goal_snapshot(goal)
                requested = self._normal_authorization(requested_authorization or {})
                if requested and not self._authorization_is_subset(
                    requested, goal.authorization_scope
                ):
                    raise PlanningStateError(
                        "Confirmation cannot expand the authorization recorded at goal creation.",
                        details={"requested": requested},
                    )
                goal.status = "active"
                goal.confirmed_by_user = True
                goal.updated_at = datetime.now(UTC)
                repository = unit_of_work.planning
                repository.add_revision(
                    GoalRevision(
                        goal_id=goal.id,
                        revision=repository.next_goal_revision(goal.id),
                        change_type="confirm",
                        before=before,
                        after=self._goal_snapshot(goal),
                        reason=reason or "Confirmed by the user without expanding the scope.",
                        source_type="user",
                        source_id="local_user",
                    )
                )
                unit_of_work.commit()

        await asyncio.to_thread(execute)
        return await self.get_goal(goal_id)

    async def close_goal(self, goal_id: str, status: str, reason: str) -> Goal:
        def execute() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.planning is not None
                goal = unit_of_work.planning.get_goal(goal_id)
                if goal is None:
                    raise GoalNotFoundError()
                if goal.status in {"completed", "failed", "cancelled", "expired"}:
                    raise PlanningStateError("The goal is already closed.")
                before = self._goal_snapshot(goal)
                goal.status = status
                goal.closed_at = datetime.now(UTC)
                goal.updated_at = goal.closed_at
                repository = unit_of_work.planning
                repository.add_revision(
                    GoalRevision(
                        goal_id=goal.id,
                        revision=repository.next_goal_revision(goal.id),
                        change_type="close",
                        before=before,
                        after=self._goal_snapshot(goal),
                        reason=reason,
                        source_type="user",
                        source_id="local_user",
                    )
                )
                unit_of_work.commit()

        await asyncio.to_thread(execute)
        return await self.get_goal(goal_id)

    async def analyze_goal(self, goal_id: str) -> dict[str, Any]:
        goal = await self.get_goal(goal_id)
        if goal.status == "candidate":
            return {"goal": goal, "current_state": None, "blocked_by": ["goal_not_confirmed"]}
        if goal.desired_state.get("device_id") is None and (goal.clarifications or goal.unknowns):
            return {"goal": goal, "current_state": None, "blocked_by": ["goal_target_unresolved"]}
        target = await self._device_target(goal)
        if target is None:
            return {"goal": goal, "current_state": None, "blocked_by": ["goal_target_unresolved"]}
        try:
            device = await self._device_service.get_registered_device(target)
            state = await self._device_service.get_state(target)
            return {
                "goal": goal,
                "device": {"id": device.id, "is_online": device.is_online},
                "current_state": state.actual_state,
                "blocked_by": [] if device.is_online else ["device_offline"],
            }
        except Exception as exc:
            return {"goal": goal, "current_state": None, "blocked_by": [type(exc).__name__]}

    async def create_plan(self, goal_id: str, request: PlanCreateRequest) -> PlanView:
        if request.mode == "analyze":
            raise PlanningStateError("Use the analysis endpoint for analyze-only requests.")
        now = _now(request.now)
        current_goal = await self.get_goal(goal_id)
        if current_goal.status != "active":
            raise PlanningStateError("Plans can only be generated for an active goal.")
        draft = await self._draft_plan(goal_id, current_goal, request.reasoning_session_id, now)
        errors = await self._validate(draft, current_goal)
        if errors:
            draft.status = "rejected"
            draft.validation_errors = errors
            draft.closed_at = now
        elif request.mode == "suggest":
            draft.status = "validated"
            draft.run_mode = "suggest_only"
        elif request.auto_execute and self._automatic_execution_allowed(draft, current_goal):
            draft.status = "approved"
            draft.run_mode = "limited_auto_execute"
        else:
            draft.status = "awaiting_confirmation"
            draft.run_mode = "awaiting_confirmation"

        def persist() -> str:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.planning is not None
                repository = unit_of_work.planning
                goal = repository.get_goal(goal_id)
                if goal is None:
                    raise GoalNotFoundError()
                draft.goal_id = goal.id
                draft.environment_id = goal.environment_id
                draft.version = repository.next_plan_version(goal.id)
                for step in draft.steps:
                    step.plan_id = draft.id
                repository.add_plan(draft)
                unit_of_work.commit()
                return draft.id

        plan_id = await asyncio.to_thread(persist)
        plan = await self.get_plan(plan_id)
        if plan.validation_errors:
            raise PlanValidationError(plan.validation_errors)
        if request.mode == "plan" and request.auto_execute and plan.status == "approved":
            return await self.submit_plan(plan_id, correlation_id=f"plan-{plan_id}")
        return plan

    async def approve_plan(self, plan_id: str, reason: str | None) -> PlanView:
        def execute() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.planning is not None
                plan = unit_of_work.planning.get_plan(plan_id)
                if plan is None:
                    raise PlanNotFoundError()
                if plan.status != "awaiting_confirmation":
                    raise PlanningStateError("Only a plan awaiting confirmation can be approved.")
                plan.status = "approved"
                plan.run_mode = "confirm_then_execute"
                plan.updated_at = datetime.now(UTC)
                unit_of_work.commit()

        await asyncio.to_thread(execute)
        if reason:
            await self._audit_approval(plan_id, reason)
        return await self.get_plan(plan_id)

    async def reject_plan(self, plan_id: str, reason: str) -> PlanView:
        def execute() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.planning is not None
                plan = unit_of_work.planning.get_plan(plan_id)
                if plan is None:
                    raise PlanNotFoundError()
                if plan.status not in {"validated", "awaiting_confirmation"}:
                    raise PlanningStateError("This plan can no longer be rejected.")
                plan.status = "rejected"
                plan.closed_at = datetime.now(UTC)
                plan.updated_at = plan.closed_at
                unit_of_work.commit()

        await asyncio.to_thread(execute)
        return await self.get_plan(plan_id)

    async def submit_plan(self, plan_id: str, *, correlation_id: str | None = None) -> PlanView:
        plan = await self.get_plan(plan_id)
        if plan.status != "approved":
            raise PlanningStateError("Only an approved plan can be submitted to the task system.")
        task_request = TaskCreate(
            task_type="planning.execute",
            title=f"Plan {plan.id} version {plan.version}",
            description=f"Generated for goal {plan.goal_id}.",
            origin="api",
            steps=[
                TaskPlanStep(
                    name=step.name,
                    description=step.purpose,
                    tool_name=step.tool_name,
                    input=step.input,
                    requires_confirmation=step.requires_confirmation,
                )
                for step in self._execution_order(plan)
            ],
            timeout_seconds=60.0,
        )
        result = await self._task_system.create_and_run(
            task_request,
            correlation_id=correlation_id or f"plan-{plan.id}",
        )
        task_id = result.task.id

        def persist() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.planning is not None
                row = unit_of_work.planning.get_plan(plan_id)
                if row is None:
                    raise PlanNotFoundError()
                row.status = "submitted"
                row.submitted_task_id = task_id
                row.updated_at = datetime.now(UTC)
                unit_of_work.commit()

        await asyncio.to_thread(persist)
        return await self.get_plan(plan_id)

    async def replan(self, plan_id: str, request: ReplanRequest) -> PlanView:
        old = await self.get_plan(plan_id)
        if old.status not in {"validated", "awaiting_confirmation", "approved", "submitted"}:
            raise PlanningStateError("A closed plan cannot be replanned.")
        now = _now(request.now)
        current_goal = await self.get_goal(old.goal_id)
        if current_goal.status != "active":
            raise PlanningStateError("The goal must be active for replanning.")
        executed = await self._executed_steps(old)
        draft = await self._draft_plan(old.goal_id, current_goal, old.reasoning_session_id, now)
        errors = await self._validate(draft, current_goal)
        decision = "replan" if not errors else "stop"
        if (
            not errors
            and request.auto_execute
            and self._automatic_execution_allowed(draft, current_goal)
        ):
            draft.status = "approved"
            draft.run_mode = "limited_auto_execute"
        elif not errors:
            draft.status = "awaiting_confirmation"
            draft.run_mode = "awaiting_confirmation"
        else:
            draft.status = "rejected"
            draft.validation_errors = errors
            draft.closed_at = now

        def persist() -> str | None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.planning is not None
                repository = unit_of_work.planning
                old_row = repository.get_plan(old.id)
                if old_row is None:
                    raise PlanNotFoundError()
                draft.goal_id = old_row.goal_id
                draft.environment_id = old_row.environment_id
                draft.version = repository.next_plan_version(old_row.goal_id)
                for step in draft.steps:
                    step.plan_id = draft.id
                repository.add_plan(draft)
                repository.add_replanning_record(
                    PlanReplanningRecord(
                        environment_id=old_row.environment_id,
                        old_plan_id=old_row.id,
                        new_plan_id=draft.id if draft.status != "rejected" else None,
                        task_id=request.task_id,
                        trigger_type=request.trigger_type,
                        trigger_record_type=request.trigger_record_type,
                        trigger_record_id=request.trigger_record_id,
                        change_summary=request.change_summary,
                        risk_delta={
                            "old_max_risk_level": old_row.max_risk_level,
                            "new_max_risk_level": draft.max_risk_level,
                        },
                        already_executed_steps=executed,
                        reversible_steps=[],
                        decision=decision,
                        reason=request.reason,
                    )
                )
                if draft.status not in {"rejected", "cancelled"}:
                    old_row.status = "superseded"
                    old_row.superseded_by_id = draft.id
                    old_row.closed_at = now
                    old_row.updated_at = now
                unit_of_work.commit()
                return None if draft.status == "rejected" else draft.id

        new_plan_id = await asyncio.to_thread(persist)
        if new_plan_id is None:
            raise PlanValidationError(errors)
        plan = await self.get_plan(new_plan_id)
        if request.auto_execute and plan.status == "approved":
            return await self.submit_plan(plan.id, correlation_id=f"plan-{plan.id}")
        return plan

    async def get_goal(self, goal_id: str) -> Goal:
        def execute() -> Goal | None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.planning is not None
                return unit_of_work.planning.get_goal(goal_id)

        goal = await asyncio.to_thread(execute)
        if goal is None:
            raise GoalNotFoundError()
        return goal

    async def list_goals(
        self,
        *,
        environment_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Goal], int]:
        def execute() -> tuple[list[Goal], int]:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.planning is not None
                return unit_of_work.planning.list_goals(
                    environment_id=environment_id,
                    status=status,
                    page=page,
                    page_size=page_size,
                )

        rows, total = await asyncio.to_thread(execute)
        return rows, total

    async def get_plan(self, plan_id: str) -> PlanView:
        def execute() -> Plan | None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.planning is not None
                return unit_of_work.planning.get_plan(plan_id)

        row = await asyncio.to_thread(execute)
        if row is None:
            raise PlanNotFoundError()
        return PlanView.model_validate(row)

    async def list_plans(
        self,
        *,
        goal_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[PlanView], int]:
        def execute() -> tuple[list[Plan], int]:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.planning is not None
                return unit_of_work.planning.list_plans(
                    goal_id=goal_id,
                    environment_id=None,
                    status=status,
                    page=page,
                    page_size=page_size,
                )

        rows, total = await asyncio.to_thread(execute)
        return [PlanView.model_validate(row) for row in rows], total

    async def _audit_approval(self, plan_id: str, reason: str) -> None:
        # Approval is represented by plan status; no model-owned text is needed for execution.
        _ = plan_id, reason

    async def _draft_plan(
        self,
        goal_id: str,
        goal: Goal,
        reasoning_session_id: str | None,
        now: datetime,
    ) -> Plan:
        target = await self._device_target(goal)
        if target is None:
            raise PlanningStateError("The goal does not identify a device target.")
        device = await self._device_service.get_registered_device(target)
        try:
            current_state = await self._device_service.get_state(target)
        except DeviceUnavailableError as exc:
            raise PlanningStateError(
                "The target device is offline.",
                details={"device_id": device.id},
            ) from exc
        if str(getattr(current_state, "actual_state", getattr(current_state, "state", ""))) == (
            "unavailable"
        ):
            raise PlanningStateError(
                "The target device is offline.",
                details={"device_id": device.id},
            )
        desired_state = str(goal.desired_state.get("state", ""))
        action = str(goal.desired_state.get("action", ""))
        state_name = DeviceStateName(desired_state) if desired_state else None
        action_name = DeviceActionName(action) if action else None
        if state_name is None or action_name is None:
            raise PlanningStateError("The goal does not contain a valid device action and state.")
        read_state = {
            "tool_name": "get_device_state",
            "input": {"device_id": device.id},
        }
        control = {
            "tool_name": "control_device",
            "input": {
                "device_id": device.id,
                "action": action_name.value,
                "parameters": {},
                "expected_state": state_name.value,
            },
        }
        pre_state_id = str(uuid4())
        control_id = str(uuid4())
        verify_id = str(uuid4())
        return Plan(
            id=str(uuid4()),
            environment_id="pending",
            goal_id=goal_id,
            reasoning_session_id=reasoning_session_id,
            version=0,
            status="draft",
            planner_type="rule",
            run_mode="awaiting_confirmation",
            strategy={
                "selection_basis": "Deterministic single-device state transition.",
                "alternatives_rejected": ["model_planned_unverified"],
            },
            constraints=goal.constraints,
            max_risk_level="low_risk",
            estimated_duration={"seconds": 3, "basis": "local_device_control"},
            resource_requirements={"device_ids": [device.id], "user_confirmation": True},
            success_criteria=[
                {
                    "type": "device_state",
                    "device_id": device.id,
                    "state": state_name.value,
                }
            ],
            failure_policy={
                "on_step_failure": "stop",
                "on_timeout": "verify_state_and_request_replan",
                "automatic_retry": False,
            },
            created_at=now,
            updated_at=now,
            steps=[
                PlanStep(
                    id=pre_state_id,
                    step_index=0,
                    name="Read current device state",
                    purpose="Establish the precondition before changing the device.",
                    tool_name=read_state["tool_name"],
                    input=read_state["input"],
                    expected_effect={"type": "known_device_state"},
                    postconditions={"device_state_known": True},
                    verification={"type": "tool_output"},
                    risk_level="read_only",
                    depends_on=[],
                ),
                PlanStep(
                    id=control_id,
                    step_index=1,
                    name=f"Control {device.name}",
                    purpose=f"Move the device to {state_name.value}.",
                    tool_name=control["tool_name"],
                    input=control["input"],
                    expected_effect={"device_state": state_name.value},
                    postconditions={"device_state": state_name.value},
                    verification={"type": "device_state", "state": state_name.value},
                    risk_level="low_risk",
                    requires_confirmation=True,
                    idempotency_key=f"plan-goal:{goal_id}:state:{state_name.value}",
                    retry_policy={"automatic": False, "reason": "physical_action"},
                    on_failure="stop",
                    depends_on=[pre_state_id],
                ),
                PlanStep(
                    id=verify_id,
                    step_index=2,
                    name="Verify result",
                    purpose="Read the final state after the device action.",
                    tool_name=read_state["tool_name"],
                    input=read_state["input"],
                    expected_effect={"device_state": state_name.value},
                    postconditions={"goal_satisfied": True},
                    verification={"type": "goal_success_condition"},
                    risk_level="read_only",
                    depends_on=[control_id],
                ),
            ],
        )

    async def _validate(self, plan: Plan, goal: Goal) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        if goal.status != "active" or not goal.confirmed_by_user:
            errors.append({"code": "GOAL_NOT_CONFIRMED", "step_index": None})
        if self._risk(plan.max_risk_level) > self._risk(SYSTEM_MAX_RISK):
            errors.append({"code": "SYSTEM_RISK_EXCEEDED", "step_index": None})
        authorized = self._risk(str(goal.authorization_scope.get("max_risk_level", "read_only")))
        if self._risk(plan.max_risk_level) > authorized:
            errors.append({"code": "GOAL_RISK_EXCEEDED", "step_index": None})
        descriptors: dict[int, AgentToolDescriptor] = {}
        for step in plan.steps:
            try:
                descriptors[step.step_index] = await self._tool_catalog.validate(
                    step.tool_name,
                    step.input,
                )
            except Exception as exc:
                errors.append(
                    {
                        "code": "TOOL_UNAVAILABLE_OR_INVALID",
                        "step_index": step.step_index,
                        "details": str(exc),
                    }
                )
                continue
            descriptor = descriptors[step.step_index]
            tool_risk_level = descriptor.tool.risk_level
            if self._risk(tool_risk_level) > self._risk(plan.max_risk_level):
                errors.append({"code": "STEP_RISK_EXCEEDED", "step_index": step.step_index})
            if tool_risk_level != "read_only" and (
                not step.expected_effect or not step.verification
            ):
                errors.append(
                    {"code": "MISSING_EFFECT_OR_VERIFICATION", "step_index": step.step_index}
                )
            if (step.retry_policy or {}).get("automatic") and not step.idempotency_key:
                errors.append({"code": "UNSAFE_AUTOMATIC_RETRY", "step_index": step.step_index})
        errors.extend(self._dependency_errors(plan))
        errors.extend(self._prohibition_errors(plan, goal))
        return errors

    @staticmethod
    def _dependency_errors(plan: Plan) -> list[dict[str, Any]]:
        ids = {step.id for step in plan.steps}
        edges: dict[str, set[str]] = defaultdict(set)
        indegree: dict[str, int] = {step.id: 0 for step in plan.steps}
        for step in plan.steps:
            for dependency in step.depends_on:
                if dependency not in ids:
                    return [
                        {
                            "code": "UNKNOWN_STEP_DEPENDENCY",
                            "step_index": step.step_index,
                            "details": dependency,
                        }
                    ]
                if dependency not in edges[step.id]:
                    edges[step.id].add(dependency)
                    indegree[step.id] += 1
        queue = deque(item for item, degree in indegree.items() if degree == 0)
        visited = 0
        while queue:
            item = queue.popleft()
            visited += 1
            for target, dependencies in edges.items():
                if item in dependencies:
                    indegree[target] -= 1
                    if indegree[target] == 0:
                        queue.append(target)
        if visited != len(plan.steps):
            return [{"code": "STEP_DEPENDENCY_CYCLE", "step_index": None}]
        return []

    @staticmethod
    def _prohibition_errors(plan: Plan, goal: Goal) -> list[dict[str, Any]]:
        errors = []
        prohibited_actions = {
            str(item.get("action", "")).casefold()
            for item in goal.prohibitions
            if isinstance(item, dict)
        }
        prohibited_devices = {
            str(item.get("device_id", "")).casefold()
            for item in goal.prohibitions
            if isinstance(item, dict)
        }
        for step in plan.steps:
            action = str(step.input.get("action", "")).casefold()
            device = str(step.input.get("device_id", "")).casefold()
            if action and action in prohibited_actions:
                errors.append({"code": "PROHIBITED_ACTION", "step_index": step.step_index})
            if device and device in prohibited_devices:
                errors.append({"code": "PROHIBITED_DEVICE", "step_index": step.step_index})
        return errors

    @staticmethod
    def _execution_order(plan: PlanView | Plan) -> list[Any]:
        steps = list(plan.steps)
        completed: set[str] = set()
        ordered = []
        pending = steps[:]
        while pending:
            ready = [step for step in pending if all(item in completed for item in step.depends_on)]
            if not ready:
                raise PlanningStateError("The plan dependencies cannot be ordered.")
            for step in sorted(ready, key=lambda item: item.step_index):
                ordered.append(step)
                completed.add(step.id)
                pending.remove(step)
        return ordered

    async def _executed_steps(self, plan: PlanView) -> list[dict[str, Any]]:
        if plan.submitted_task_id is None:
            return []
        try:
            detail = await self._task_system.get_task_detail(plan.submitted_task_id)
        except Exception:
            return []
        return [
            {"step_index": step.step_index, "name": step.name, "status": step.status.value}
            for step in detail.steps
            if step.status.value == "completed"
        ]

    @staticmethod
    def _automatic_execution_allowed(plan: Plan, goal: Goal) -> bool:
        if any(step.risk_level != "read_only" for step in plan.steps):
            return False
        authorization = str(goal.authorization_scope.get("automatic_execution", "none"))
        return authorization == "limited"

    async def _device_target(self, goal: Goal) -> str:
        value = goal.desired_state.get("device_id")
        if value:
            return str(value)

        devices = await self._device_service.list_devices()
        device_type = goal.scope.get("device_type")
        hint = str(goal.scope.get("space_hint", "")).casefold()
        typed = [
            device for device in devices if device.device_type == str(device_type or "").lower()
        ]
        candidates = typed or devices
        hint_tokens = {token for token in re.findall(r"\w+", hint) if len(token) > 2}

        def relevance(device: RegisteredDevice) -> int:
            text = " ".join(
                (
                    device.id,
                    device.external_id,
                    device.name,
                    device.area or "",
                    " ".join(device.aliases or []),
                ),
            ).casefold()
            return sum(token in text for token in hint_tokens)

        best_score = max((relevance(device) for device in candidates), default=0)
        if best_score > 0:
            candidates = [device for device in candidates if relevance(device) == best_score]
        if len(candidates) == 1:
            return candidates[0].id
        if not candidates:
            raise PlanningStateError(
                "No available device matches the goal target.",
                details={"device_type": device_type},
            )
        raise PlanningStateError(
            "The goal target is ambiguous; specify a device ID.",
            details={"candidate_device_ids": [device.id for device in candidates]},
        )

    def _parse_objective(
        self,
        objective: str,
        desired_state: dict[str, Any],
    ) -> dict[str, Any]:
        clarifications: list[str] = []
        unknowns: list[str] = []
        text = objective.strip().casefold()
        state = desired_state.get("state")
        action = desired_state.get("action")
        match = re.search(r"\bturn\s+(on|off)\b\s+(?:the\s+)?(.+)$", text)
        if match:
            state = state or ("on" if match.group(1) == "on" else "off")
            phrase = match.group(2)
        else:
            match = re.search(r"把(.+?)(打开|开启|关掉|关闭)", text)
            if match is None:
                match = re.search(r"(.+?)(打开|开启|关掉|关闭)", text)
            if match:
                phrase = match.group(1)
                state = state or ("off" if match.group(2) in {"关掉", "关闭"} else "on")
            else:
                phrase = text
        expanded = self._expand_chinese(phrase)
        device_type, goal_type = self._device_type(expanded)
        if action is None and state in {"on", "off"}:
            action = "turn_on" if state == "on" else "turn_off"
        if state not in {"on", "off"}:
            clarifications.append("Please confirm the desired device state.")
        if device_type is None:
            clarifications.append("Please identify the target device type.")
            unknowns.append("target_device_type")
        if desired_state.get("device_id") is None:
            clarifications.append("Please confirm the exact target device after device resolution.")
        scope = {"objective_text": objective, "device_type": device_type, "space_hint": expanded}
        success = [] if state not in {"on", "off"} else [{"type": "device_state", "state": state}]
        failure = (
            []
            if state not in {"on", "off"}
            else [{"type": "device_state_not_reached", "state": state}]
        )
        return {
            "goal_type": goal_type,
            "scope": scope,
            "desired_state": {
                "device_id": desired_state.get("device_id"),
                "state": state,
                "action": action,
            },
            "clarifications": clarifications,
            "unknowns": unknowns,
            "success_conditions": success,
            "failure_conditions": failure,
        }

    @staticmethod
    def _expand_chinese(value: str) -> str:
        replacements = {
            "客厅": "living room",
            "卧室": "bedroom",
            "厨房": "kitchen",
            "浴室": "bathroom",
            "卫生间": "bathroom",
            "书房": "study",
            "餐厅": "dining room",
            "灯": "light",
            "空调": "climate",
            "开关": "switch",
        }
        result = value
        for source, target in replacements.items():
            result = result.replace(source, f" {target} ")
        return " ".join(result.split())

    @staticmethod
    def _device_type(value: str) -> tuple[str | None, str]:
        if "light" in value:
            return "light", "device_state"
        if "climate" in value:
            return "climate", "comfort"
        if "switch" in value:
            return "switch", "device_state"
        return None, "other"

    @classmethod
    def _normal_authorization(cls, value: dict[str, Any]) -> dict[str, Any]:
        requested_risk = str(value.get("max_risk_level", "read_only"))
        risk = (
            requested_risk
            if cls._risk(requested_risk) <= cls._risk(SYSTEM_MAX_RISK)
            else SYSTEM_MAX_RISK
        )
        automatic = str(value.get("automatic_execution", "none"))
        if risk not in RISK_ORDER or automatic not in {"none", "limited"}:
            raise PlanningStateError("The requested authorization scope is invalid.")
        return {
            "max_risk_level": risk,
            "automatic_execution": automatic,
            "device_scope": value.get("device_scope", "requested_target_only"),
        }

    @staticmethod
    def _authorization_is_subset(requested: dict[str, Any], existing: dict[str, Any]) -> bool:
        return RISK_ORDER[str(requested.get("max_risk_level", "read_only"))] <= RISK_ORDER[
            str(existing.get("max_risk_level", "read_only"))
        ] and str(requested.get("automatic_execution", "none")) <= str(
            existing.get("automatic_execution", "none")
        )

    @staticmethod
    def _risk(value: str) -> int:
        return RISK_ORDER.get(value, 99)

    @staticmethod
    def _title(objective: str, parsed: dict[str, Any]) -> str:
        state = parsed["desired_state"].get("state")
        suffix = f" ({state})" if state in {"on", "off"} else ""
        return f"{objective[:180]}{suffix}"

    @staticmethod
    def _goal_snapshot(goal: Goal) -> dict[str, Any]:
        return {
            "title": goal.title,
            "objective": goal.objective,
            "status": goal.status,
            "scope": goal.scope,
            "desired_state": goal.desired_state,
            "authorization_scope": goal.authorization_scope,
            "priority": goal.priority,
        }


__all__ = ["PlanningService"]
