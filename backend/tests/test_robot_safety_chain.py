import asyncio
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.events.service import EventQueryService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import RobotTaskRequestRecord
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.robots.mock import MockRobotAdapter
from arvuno_core.robots.models import (
    RegisteredRobot,
    RegisteredRobotTaskRequest,
    RobotCapability,
    RobotCapabilityName,
    RobotConsent,
    RobotConsentGrant,
    RobotExecutionResult,
    RobotPolicySnapshot,
    utc_now,
)
from arvuno_core.tasks.models import (
    TaskCreate,
    TaskPlanStep,
    TaskStatus,
    TaskStepStatus,
)
from arvuno_core.tasks.service import TaskService
from arvuno_core.tools.confirmation import ConfirmationService
from arvuno_core.tools.errors import ToolPermissionDeniedError
from arvuno_core.tools.executor import ToolExecutor
from arvuno_core.tools.models import (
    PermissionResult,
    RobotActionInput,
    RobotActionOutput,
    ToolExecutionContext,
    ToolPermission,
    ToolRiskLevel,
)
from arvuno_core.tools.registry import ToolDefinition
from arvuno_core.tools.safety import SafetyPolicy

HEADERS = {"Authorization": "Bearer test-api-token"}


@dataclass
class MutableClock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


@dataclass
class RobotEnvironment:
    manager: DatabaseManager
    app: FastAPI
    client: TestClient
    adapter: MockRobotAdapter
    robot_id: str
    space_id: str

    @property
    def settings(self) -> Settings:
        assert isinstance(self.app.state.settings, Settings)
        return self.app.state.settings

    @property
    def task_service(self) -> TaskService:
        return self.app.state.task_service

    @property
    def tool_executor(self) -> ToolExecutor:
        return self.app.state.tool_executor

    @property
    def robot_service(self):  # type: ignore[no-untyped-def]
        return self.app.state.robot_service

    def robot_requests(self) -> list[RegisteredRobotTaskRequest]:
        return asyncio.run(self.robot_service.list_task_requests(self.robot_id))

    def robot_request_count(self) -> int:
        with self.manager.session_factory() as session:
            return len(
                session.query(RobotTaskRequestRecord)
                .filter(RobotTaskRequestRecord.robot_id == self.robot_id)
                .all()
            )


@contextmanager
def robot_environment(
    tmp_path: Path, *, profile: str = "desktop_robot"
) -> Iterator[RobotEnvironment]:
    app_settings = Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        robot_profile=profile,  # type: ignore[arg-type]
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )
    manager = DatabaseManager(app_settings)
    manager.initialize_database()
    app = create_app(
        app_settings,
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
        initialize_tool_runtime=True,
    )
    try:
        with TestClient(app) as client:
            service = app.state.robot_service
            robot = asyncio.run(service.list_robots())[0]
            root = asyncio.run(app.state.spatial_service.ensure_root())
            yield RobotEnvironment(
                manager=manager,
                app=app,
                client=client,
                adapter=app.state.mock_robot_adapter,
                robot_id=robot.id,
                space_id=root.id,
            )
    finally:
        manager.dispose()


def enable_capability(environment: RobotEnvironment, capability: RobotCapabilityName) -> None:
    environment.adapter.set_capability(
        capability,
        runtime_enabled=True,
        verification_status="bench_verified",
    )
    asyncio.run(environment.robot_service.enable_robot(environment.robot_id, enabled=True))
    environment.adapter.set_emergency_stop(active=False)
    asyncio.run(
        environment.robot_service.sync_robot(environment.adapter, environment.adapter.external_id)
    )
    asyncio.run(
        environment.robot_service.set_capability_governance(
            environment.robot_id,
            capability,
            enabled=True,
            approved=True,
            consent_granted=True,
            approved_by="test-admin",
        )
    )


def grant_speaker_consent(
    environment: RobotEnvironment,
    *,
    space_id: str | None = None,
    expires_at: datetime | None = None,
) -> Any:
    return asyncio.run(
        environment.robot_service.grant_consent(
            environment.robot_id,
            RobotConsentGrant(
                capability=RobotCapabilityName.SPEAK,
                data_category="speaker",
                space_id=space_id if space_id is not None else environment.space_id,
                expires_at=expires_at,
                grant_source="test",
                granted_by="test-user",
            ),
        )
    )


def speak_task(environment: RobotEnvironment, *, text: str = "Hello from the safety chain."):
    return TaskCreate(
        task_type="robot_safety_chain",
        title="Run a governed robot action",
        origin="user",
        steps=[
            TaskPlanStep(
                name="Speak through the robot",
                tool_name="robot_speak",
                input={
                    "robot_id": environment.robot_id,
                    "space_id": environment.space_id,
                    "text": text,
                },
                requires_confirmation=True,
            )
        ],
        timeout_seconds=60,
    )


def tool_context(
    task_id: str,
    task_step_id: str,
    *,
    execution_id: str | None = None,
    task_system: bool = True,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        correlation_id=task_id,
        task_id=task_id,
        task_step_id=task_step_id,
        tool_execution_id=execution_id,
        task_system=task_system,
    )


def test_missing_consent_rejects_before_robot_execution(tmp_path: Path) -> None:
    with robot_environment(tmp_path) as environment:
        enable_capability(environment, RobotCapabilityName.SPEAK)
        result = asyncio.run(environment.task_service.create_and_run(speak_task(environment)))

        assert result.task.status is TaskStatus.FAILED
        assert result.task.steps[0].status is TaskStepStatus.FAILED
        assert result.task.error is not None
        assert result.task.error["code"] == "PERMISSION_DENIED"
        assert result.task.error["details"]["safety"]["reason"] == "robot_consent_required"
        assert result.task.error["details"]["safety"]["missing_consents"] == ["speaker"]
        assert len(result.task.executions) == 1
        assert result.task.executions[0].status == "rejected"
        assert environment.robot_request_count() == 0


@pytest.mark.parametrize(
    "consent_mode",
    ["expired", "revoked", "space_mismatch"],
)
def test_inactive_or_scoped_consent_is_not_accepted(
    tmp_path: Path,
    consent_mode: str,
) -> None:
    with robot_environment(tmp_path) as environment:
        enable_capability(environment, RobotCapabilityName.SPEAK)
        if consent_mode == "expired":
            grant = grant_speaker_consent(
                environment,
                expires_at=utc_now() - timedelta(seconds=1),
            )
            assert grant.status == "expired"
        elif consent_mode == "revoked":
            grant = grant_speaker_consent(environment)
            revoked = asyncio.run(
                environment.robot_service.revoke_consent(
                    environment.robot_id,
                    grant.id,
                    revoked_by="test-user",
                )
            )
            assert revoked.status == "revoked"
        else:
            grant_speaker_consent(environment, space_id=str(uuid.uuid4()))

        result = asyncio.run(environment.task_service.create_and_run(speak_task(environment)))

        assert result.task.status is TaskStatus.FAILED
        assert result.task.error is not None
        assert result.task.error["code"] == "PERMISSION_DENIED"
        assert result.task.error["details"]["safety"]["reason"] == "robot_consent_required"
        assert environment.robot_request_count() == 0


def test_confirmation_is_required_and_has_no_client_bypass(tmp_path: Path) -> None:
    with robot_environment(tmp_path) as environment:
        enable_capability(environment, RobotCapabilityName.SPEAK)
        grant_speaker_consent(environment)
        task = asyncio.run(environment.task_service.create_task(speak_task(environment)))
        result = asyncio.run(environment.task_service.run_task(task.id))

        assert result.task.status is TaskStatus.WAITING_CONFIRMATION
        assert isinstance(result.confirmation_token, str)
        assert result.confirmation_token
        assert result.task.steps[0].status is TaskStepStatus.WAITING_CONFIRMATION
        assert len(result.task.executions) == 1
        assert result.task.executions[0].status == "confirmation_required"
        assert environment.robot_request_count() == 0

        # A legacy confirmed=true robot API request never reaches the service.
        response = environment.client.post(
            f"/api/robots/{environment.robot_id}/task-requests",
            headers=HEADERS,
            json={
                "capability": "speak",
                "parameters": {"text": "bypass"},
                "requested_by": "test-user",
                "origin_type": "user",
                "confirmed": True,
                "idempotency_key": "confirmed-bypass-01",
            },
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "ROBOT_EXECUTION_LOCKED"
        assert environment.robot_request_count() == 0


def test_expired_confirmation_token_fails_the_task(tmp_path: Path) -> None:
    with robot_environment(tmp_path) as environment:
        enable_capability(environment, RobotCapabilityName.SPEAK)
        grant_speaker_consent(environment)
        clock = MutableClock(utc_now())
        environment.tool_executor._confirmation_service = ConfirmationService(
            ttl_seconds=60,
            clock=clock,
        )
        task = asyncio.run(environment.task_service.create_task(speak_task(environment)))
        waiting = asyncio.run(environment.task_service.run_task(task.id))
        assert waiting.confirmation_token is not None

        clock.now += timedelta(seconds=61)
        confirmed = asyncio.run(
            environment.task_service.confirm(
                task.id,
                confirmation_token=waiting.confirmation_token,
                confirmed=True,
            )
        )

        assert confirmed.task.status is TaskStatus.FAILED
        assert confirmed.task.error is not None
        assert confirmed.task.error["code"] == "PERMISSION_DENIED"
        assert "invalid, expired" in confirmed.task.error["message"]
        assert environment.robot_request_count() == 0


def test_parameter_change_invalidates_confirmation_token(tmp_path: Path) -> None:
    with robot_environment(tmp_path) as environment:
        enable_capability(environment, RobotCapabilityName.SPEAK)
        grant_speaker_consent(environment)
        task = asyncio.run(environment.task_service.create_task(speak_task(environment)))
        waiting = asyncio.run(environment.task_service.run_task(task.id))
        assert waiting.confirmation_token is not None
        confirmation = waiting.task.plan["confirmation"]
        step = waiting.task.steps[0]

        with pytest.raises(ToolPermissionDeniedError) as rejected:
            asyncio.run(
                environment.tool_executor.execute(
                    "robot_speak",
                    {
                        "robot_id": environment.robot_id,
                        "space_id": environment.space_id,
                        "text": "Changed after confirmation",
                    },
                    context=tool_context(
                        task.id,
                        step.id,
                        execution_id=confirmation["execution_id"],
                    ),
                    confirmation_token=waiting.confirmation_token,
                )
            )

        assert rejected.value.code == "PERMISSION_DENIED"
        assert environment.robot_request_count() == 0


def test_confirmation_token_is_single_use(tmp_path: Path) -> None:
    with robot_environment(tmp_path) as environment:
        enable_capability(environment, RobotCapabilityName.SPEAK)
        grant_speaker_consent(environment)
        task = asyncio.run(environment.task_service.create_task(speak_task(environment)))
        waiting = asyncio.run(environment.task_service.run_task(task.id))
        completed = asyncio.run(
            environment.task_service.confirm(
                task.id,
                confirmation_token=waiting.confirmation_token,
                confirmed=True,
            )
        )
        assert completed.task.status is TaskStatus.COMPLETED

        with pytest.raises(ToolPermissionDeniedError) as replayed:
            asyncio.run(
                environment.tool_executor.execute(
                    "robot_speak",
                    waiting.task.steps[0].input,
                    context=tool_context(task.id, waiting.task.steps[0].id),
                    confirmation_token=waiting.confirmation_token,
                )
            )

        assert replayed.value.code == "PERMISSION_DENIED"
        assert len(environment.robot_requests()) == 1


def test_successful_task_correlates_task_tool_robot_and_events(tmp_path: Path) -> None:
    with robot_environment(tmp_path) as environment:
        enable_capability(environment, RobotCapabilityName.SPEAK)
        grant = grant_speaker_consent(environment)
        task = asyncio.run(environment.task_service.create_task(speak_task(environment)))
        waiting = asyncio.run(environment.task_service.run_task(task.id))
        completed = asyncio.run(
            environment.task_service.confirm(
                task.id,
                confirmation_token=waiting.confirmation_token,
                confirmed=True,
            )
        )

        assert completed.task.status is TaskStatus.COMPLETED
        assert completed.task.correlation_id == task.id
        assert len(completed.task.executions) == 1
        execution = completed.task.executions[0]
        assert execution.task_id == task.id
        assert execution.task_step_id == completed.task.steps[0].id
        assert execution.status == "completed"
        assert execution.output is not None
        request_id = execution.output["request_id"]

        robot_requests = environment.robot_requests()
        assert len(robot_requests) == 1
        robot_request = robot_requests[0]
        assert robot_request.id == request_id
        assert robot_request.task_id == task.id
        assert robot_request.task_step_id == completed.task.steps[0].id
        assert robot_request.tool_execution_id == execution.id
        assert robot_request.correlation_id == task.id
        assert robot_request.status.value == "succeeded"
        assert robot_request.result == {"spoken": "Hello from the safety chain."}

        robot_events = asyncio.run(
            environment.robot_service.events(environment.robot_id, task_request_id=request_id)
        )
        assert {"task_running", "task_succeeded"} <= {event.event_type for event in robot_events}

        events = asyncio.run(
            EventQueryService(
                lambda: SqlAlchemyUnitOfWork(environment.manager.session_factory)
            ).list(event_type="tool_executed", correlation_id=task.id)
        )
        assert events.total == 1
        assert events.items[0].payload.tool_execution_id == execution.id
        assert grant.status == "granted"


def test_adapter_execution_failure_is_audited_as_a_failed_robot_task(
    tmp_path: Path,
) -> None:
    with robot_environment(tmp_path) as environment:
        enable_capability(environment, RobotCapabilityName.SPEAK)
        grant_speaker_consent(environment)
        adapter = environment.adapter

        async def failing_execution(
            request: RegisteredRobotTaskRequest,
        ) -> RobotExecutionResult:
            raise RuntimeError("adapter execution failed")

        adapter.execute_task = failing_execution  # type: ignore[method-assign]
        task = asyncio.run(environment.task_service.create_task(speak_task(environment)))
        waiting = asyncio.run(environment.task_service.run_task(task.id))

        failed = asyncio.run(
            environment.task_service.confirm(
                task.id,
                confirmation_token=waiting.confirmation_token,
                confirmed=True,
            )
        )

        assert failed.task.status is TaskStatus.FAILED
        assert failed.task.executions[0].status == "failed"
        robot_request = environment.robot_requests()[0]
        assert robot_request.status.value == "failed"
        assert robot_request.tool_execution_id == failed.task.executions[0].id
        assert robot_request.error is not None
        assert robot_request.error["code"] == "ROBOT_TASK_FAILED"
        robot_events = asyncio.run(
            environment.robot_service.events(
                environment.robot_id,
                task_request_id=robot_request.id,
            )
        )
        assert {"task_running", "task_failed"} <= {event.event_type for event in robot_events}


def test_successful_adapter_result_is_rejected_when_state_contract_fails(
    tmp_path: Path,
) -> None:
    with robot_environment(tmp_path) as environment:
        enable_capability(environment, RobotCapabilityName.SPEAK)
        grant_speaker_consent(environment)
        adapter = environment.adapter

        async def success_without_verified_result(
            request: RegisteredRobotTaskRequest,
        ) -> RobotExecutionResult:
            state = await adapter.get_state(adapter.external_id)
            return RobotExecutionResult(
                success=True,
                request_id=request.id,
                result={},
                state=state,
            )

        adapter.execute_task = success_without_verified_result  # type: ignore[method-assign]
        task = asyncio.run(environment.task_service.create_task(speak_task(environment)))
        waiting = asyncio.run(environment.task_service.run_task(task.id))
        failed = asyncio.run(
            environment.task_service.confirm(
                task.id,
                confirmation_token=waiting.confirmation_token,
                confirmed=True,
            )
        )

        assert failed.task.status is TaskStatus.FAILED
        assert failed.task.executions[0].status == "failed"
        robot_request = environment.robot_requests()[0]
        assert robot_request.status.value == "failed"
        assert robot_request.error is not None
        assert robot_request.error["code"] == "ROBOT_STATE_VERIFICATION_FAILED"
        assert robot_request.tool_execution_id == failed.task.executions[0].id
        robot_events = asyncio.run(
            environment.robot_service.events(
                environment.robot_id,
                task_request_id=robot_request.id,
            )
        )
        assert {"task_running", "task_failed"} <= {event.event_type for event in robot_events}


def test_direct_robot_tool_invocation_without_task_system_is_rejected(
    tmp_path: Path,
) -> None:
    with robot_environment(tmp_path) as environment:
        enable_capability(environment, RobotCapabilityName.REQUEST_SAFE_STOP)
        with environment.manager.session_factory() as session:
            assert session.query(RobotTaskRequestRecord).count() == 0

        with pytest.raises(ToolPermissionDeniedError) as rejected:
            asyncio.run(
                environment.tool_executor.execute(
                    "robot_safe_stop",
                    {
                        "robot_id": environment.robot_id,
                        "space_id": environment.space_id,
                    },
                    context=tool_context(str(uuid.uuid4()), str(uuid.uuid4()), task_system=False),
                )
            )

        assert rejected.value.message == "Robot actions can execute only through the task system."
        assert environment.robot_request_count() == 0


def test_mobile_profile_cannot_execute_motion_through_the_task_system(
    tmp_path: Path,
) -> None:
    with robot_environment(tmp_path, profile="mobile_robot") as environment:
        request = TaskCreate(
            task_type="robot_motion",
            title="Use the mobile robot",
            origin="user",
            steps=[
                TaskPlanStep(
                    name="Speak",
                    tool_name="robot_speak",
                    input={
                        "robot_id": environment.robot_id,
                        "space_id": environment.space_id,
                        "text": "This motion profile is not approved.",
                    },
                    requires_confirmation=False,
                )
            ],
        )

        result = asyncio.run(environment.task_service.create_and_run(request))

        assert result.task.status is TaskStatus.FAILED
        assert result.task.error is not None
        assert result.task.error["code"] == "RISK_POLICY_REJECTED"
        assert result.task.error["details"]["safety"]["reason"] == (
            "robot_profile_is_not_approved_for_execution"
        )
        assert environment.robot_request_count() == 0


def test_high_risk_robot_capability_is_denied_even_if_projection_claims_execution() -> None:
    now = utc_now()
    robot = RegisteredRobot(
        id=str(uuid.uuid4()),
        adapter_id="mock_robot",
        external_id="mock.desktop.robot",
        name="Desktop Robot",
        profile="desktop_robot",
        is_enabled=True,
        is_online=True,
        emergency_stop=False,
        created_at=now,
        updated_at=now,
    )
    capability = RobotCapability(
        robot_id=robot.id,
        capability=RobotCapabilityName.LOOK_AT,
        discovered=True,
        supported=True,
        enabled=True,
        approved=True,
        executable=True,
        runtime_enabled=True,
        risk_level="high_risk",
        requires_confirmation=True,
        requires_consents=["motion"],
    )
    consent = RobotConsent(
        id=str(uuid.uuid4()),
        robot_id=robot.id,
        capability=RobotCapabilityName.LOOK_AT,
        data_category="motion",
        space_id="space-1",
        status="granted",
        granted_at=now,
        expires_at=now + timedelta(hours=1),
        grant_source="test",
        granted_by="test-user",
    )

    async def async_handler(
        context: ToolExecutionContext, payload: RobotActionInput
    ) -> RobotActionOutput:
        return RobotActionOutput(
            robot_id=payload.robot_id,
            request_id=str(uuid.uuid4()),
            capability=RobotCapabilityName.LOOK_AT.value,
            status="success",
            result={},
            verified=True,
            tool_execution_id=context.tool_execution_id or str(uuid.uuid4()),
        )

    class Reader:
        async def find_robot_for_policy(self, robot_id: str) -> RobotPolicySnapshot | None:
            if robot_id != robot.id:
                return None
            return RobotPolicySnapshot(
                robot=robot,
                capabilities=(capability,),
                consents=(consent,),
            )

    definition = ToolDefinition(
        name="robot_look_at",
        version="1.0.0",
        description="test",
        category="robot_control",
        risk_level=ToolRiskLevel.MEDIUM,
        default_permission=ToolPermission.ALLOW,
        requires_confirmation=True,
        enabled=True,
        input_type=RobotActionInput,
        output_type=RobotActionOutput,
        handler=async_handler,
    )
    policy = SafetyPolicy(
        Reader(),
        robot_reader=Reader(),
        tool_permissions={"robot_look_at": "allow"},
    )

    decision = asyncio.run(
        policy.evaluate(
            definition,
            RobotActionInput(robot_id=robot.id, space_id="space-1", target={"point": 1}),
        )
    )

    assert decision.permission_result is PermissionResult.RISK_EXCEEDED
    assert decision.risk_level is ToolRiskLevel.HIGH
    assert decision.details["reason"] == "high_risk_robot_capabilities_are_disabled"
