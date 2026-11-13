import asyncio
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.robots.errors import (
    RobotCapabilityDisabledError,
    RobotExecutionLockedError,
    RobotInvalidParameterError,
    RobotTaskIdempotencyConflictError,
)
from arvuno_core.robots.mock import MockRobotAdapter
from arvuno_core.robots.models import (
    CapabilityVerification,
    RegisteredRobotTaskRequest,
    RobotCapabilityName,
    RobotTaskRequestCreate,
    RobotTaskStatus,
    utc_now,
)
from arvuno_core.robots.registry import RobotRegistry
from arvuno_core.robots.service import RobotApplicationService

HEADERS = {"Authorization": "Bearer test-api-token"}


def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        robot_profile="legacy_mock_mobile",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


def environment(tmp_path: Path):
    manager = DatabaseManager(settings(tmp_path))
    manager.initialize_database()
    adapter = MockRobotAdapter(profile="legacy_mock_mobile")
    registry = RobotRegistry(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
    service = RobotApplicationService(
        registry,
        {adapter.adapter_id: adapter},
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
    )
    asyncio.run(service.sync_robot(adapter, adapter.external_id))
    robot = asyncio.run(service.list_robots())[0]
    return manager, adapter, service, robot


def enable_navigation(
    adapter: MockRobotAdapter,
    *,
    verification: CapabilityVerification = "bench_verified",
) -> None:
    adapter.set_capability(
        RobotCapabilityName.NAVIGATE_TO,
        runtime_enabled=True,
        verification_status=verification,
    )


def approve_navigation(service, robot) -> None:
    asyncio.run(
        service.set_capability_governance(
            robot.id,
            RobotCapabilityName.NAVIGATE_TO,
            enabled=True,
            approved=True,
            approved_by="test-admin",
        )
    )


def execute_navigation(
    service: RobotApplicationService,
    robot_id: str,
    request: RobotTaskRequestCreate,
) -> RegisteredRobotTaskRequest:
    return asyncio.run(
        service.execute_preauthorized_task_request(
            robot_id,
            request,
            task_id=str(uuid.uuid4()),
            task_step_id=str(uuid.uuid4()),
            tool_execution_id=str(uuid.uuid4()),
        )
    )


class SlowMockRobotAdapter(MockRobotAdapter):
    """Adapter that ignores the request timeout to prove the service enforces it."""

    def __init__(self) -> None:
        super().__init__(profile="legacy_mock_mobile")

    async def execute_task(self, request: RegisteredRobotTaskRequest):
        await asyncio.sleep(0.6)
        return await super().execute_task(request)


def navigation_request(*, idempotency_key: str, confirmed: bool = False) -> RobotTaskRequestCreate:
    return RobotTaskRequestCreate(
        capability=RobotCapabilityName.NAVIGATE_TO,
        parameters={
            "target_location": {
                "reference_frame": "room",
                "x": 1.2,
                "y": 2.3,
                "yaw": 90,
                "position_confidence": 0.8,
            }
        },
        requested_by="user-1",
        idempotency_key=idempotency_key,
        confirmed=confirmed,
        correlation_id="robot-correlation-1",
    )


def test_default_mock_capabilities_are_concept_and_disabled(tmp_path: Path) -> None:
    manager, adapter, service, robot = environment(tmp_path)
    try:
        capabilities = asyncio.run(service.capabilities(robot.id))
        assert capabilities
        assert all(capability.verification_status == "concept" for capability in capabilities)
        assert all(not capability.runtime_enabled for capability in capabilities)
        assert all(
            capability.requires_confirmation
            for capability in capabilities
            if capability.capability
            not in {RobotCapabilityName.REPORT_STATUS, RobotCapabilityName.REQUEST_SAFE_STOP}
        )
        assert robot.emergency_stop is True
        with pytest.raises(RobotCapabilityDisabledError):
            asyncio.run(
                service.create_task_request(
                    robot.id,
                    RobotTaskRequestCreate(
                        capability=RobotCapabilityName.REPORT_STATUS,
                        parameters={},
                        requested_by="user-1",
                        confirmed=True,
                    ),
                )
            )
    finally:
        manager.dispose()


def test_low_level_control_parameters_are_rejected(tmp_path: Path) -> None:
    manager, adapter, service, robot = environment(tmp_path)
    try:
        request = navigation_request(idempotency_key="low-level-0001", confirmed=True)
        request.parameters["target_location"]["motor"] = 3
        hardware = asyncio.run(adapter.get_robot(adapter.external_id))
        adapter_request = RegisteredRobotTaskRequest(
            id="low-level-request-0001",
            robot_id=hardware.id,
            capability=request.capability,
            status=RobotTaskStatus.CREATED,
            parameters=request.parameters,
            requested_by=request.requested_by,
            origin_type=request.origin_type,
            confirmed_by_user=request.confirmed,
            timeout_seconds=request.timeout_seconds,
            correlation_id=request.correlation_id,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        with pytest.raises(RobotInvalidParameterError):
            asyncio.run(adapter.execute_task(adapter_request))
    finally:
        manager.dispose()


def test_navigation_requires_confirmation_and_success_is_persisted(tmp_path: Path) -> None:
    manager, adapter, service, robot = environment(tmp_path)
    try:
        enable_navigation(adapter)
        asyncio.run(service.enable_robot(robot.id, enabled=True))
        adapter.set_emergency_stop(active=False)
        asyncio.run(service.sync_robot(adapter, adapter.external_id))
        approve_navigation(service, robot)
        created = asyncio.run(
            service.create_task_request(
                robot.id,
                navigation_request(idempotency_key="navigate-0001"),
            )
        )
        assert created.status is RobotTaskStatus.AWAITING_CONFIRMATION
        assert created.confirmed_by_user is False

        duplicate = asyncio.run(
            service.create_task_request(
                robot.id,
                navigation_request(idempotency_key="navigate-0001"),
            )
        )
        assert duplicate.id == created.id

        with pytest.raises(RobotExecutionLockedError):
            asyncio.run(
                service.confirm_task_request(
                    robot.id,
                    created.id,
                    confirmed=True,
                    confirmed_by="user-1",
                )
            )
        completed = execute_navigation(
            service,
            robot.id,
            navigation_request(idempotency_key="navigate-0001"),
        )
        assert completed.error is None
        assert completed.status is RobotTaskStatus.SUCCEEDED
        assert completed.result["moved_to"]["x"] == 1.2
        assert completed.result["moved_to"]["position_confidence"] == 0.9

        state = asyncio.run(service.state(robot.id))
        assert state.location.x == 1.2
        assert state.last_seen_at is not None
        events = asyncio.run(service.events(robot.id, task_request_id=completed.id))
        assert {"task_running", "task_succeeded"} <= {event.event_type for event in events}
    finally:
        manager.dispose()


@pytest.mark.parametrize(
    ("configure", "expected_status", "expected_error"),
    [
        (
            lambda adapter: adapter.set_navigation_failure(enabled=True),
            RobotTaskStatus.FAILED,
            "ROBOT_NAVIGATION_FAILED",
        ),
        (
            lambda adapter: adapter.set_localization_lost(lost=True),
            RobotTaskStatus.FAILED,
            "ROBOT_LOCALIZATION_LOST",
        ),
        (
            lambda adapter: adapter.set_emergency_stop(active=True),
            RobotTaskStatus.SAFE_STOPPED,
            "ROBOT_SAFETY_STATE",
        ),
        (
            lambda adapter: adapter.set_manual_takeover(active=True),
            RobotTaskStatus.SAFE_STOPPED,
            "ROBOT_SAFETY_STATE",
        ),
        (
            lambda adapter: adapter.set_battery_percent(10),
            RobotTaskStatus.UNAVAILABLE,
            "ROBOT_UNAVAILABLE",
        ),
        (
            lambda adapter: adapter.set_offline(offline=True),
            RobotTaskStatus.UNAVAILABLE,
            "ROBOT_CONNECTION_FAILED",
        ),
        (
            lambda adapter: adapter.set_timeout(timeout=True),
            RobotTaskStatus.TIMEOUT,
            "ROBOT_TASK_TIMEOUT",
        ),
    ],
)
def test_navigation_failure_modes_are_normalized(
    tmp_path: Path,
    configure,
    expected_status: RobotTaskStatus,
    expected_error: str,
) -> None:
    manager, adapter, service, robot = environment(tmp_path)
    try:
        enable_navigation(adapter)
        asyncio.run(service.enable_robot(robot.id, enabled=True))
        adapter.set_emergency_stop(active=False)
        configure(adapter)
        asyncio.run(service.sync_robot(adapter, adapter.external_id))
        approve_navigation(service, robot)
        result = execute_navigation(
            service,
            robot.id,
            navigation_request(idempotency_key=f"failure-{expected_error.lower()}"),
        )
        assert result.status is expected_status
        assert result.error is not None
        assert result.error["code"] == expected_error
        assert result.completed_at is not None
        events = asyncio.run(service.events(robot.id, task_request_id=result.id))
        assert events
        assert any(event.payload.get("error", {}).get("code") == expected_error for event in events)
    finally:
        manager.dispose()


def test_task_timeout_is_enforced_even_when_adapter_does_not_return(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(settings(tmp_path))
    manager.initialize_database()
    adapter = SlowMockRobotAdapter()
    registry = RobotRegistry(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
    service = RobotApplicationService(
        registry,
        {adapter.adapter_id: adapter},
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
    )
    try:
        asyncio.run(service.sync_robot(adapter, adapter.external_id))
        robot = asyncio.run(service.list_robots())[0]
        enable_navigation(adapter)
        asyncio.run(service.enable_robot(robot.id, enabled=True))
        adapter.set_emergency_stop(active=False)
        asyncio.run(service.sync_robot(adapter, adapter.external_id))
        approve_navigation(service, robot)

        request = navigation_request(
            idempotency_key="slow-timeout-01",
            confirmed=True,
        ).model_copy(update={"timeout_seconds": 0.05})
        started = time.monotonic()
        result = execute_navigation(service, robot.id, request)
        elapsed = time.monotonic() - started

        assert result.status is RobotTaskStatus.TIMEOUT
        assert result.error is not None
        assert result.error["code"] == "ROBOT_TASK_TIMEOUT"
        assert elapsed < 0.5
        events = asyncio.run(service.events(robot.id, task_request_id=result.id))
        assert "task_failed" in {event.event_type for event in events}
    finally:
        manager.dispose()


def test_idempotency_key_reuse_with_different_parameters_is_rejected(
    tmp_path: Path,
) -> None:
    manager, adapter, service, robot = environment(tmp_path)
    try:
        enable_navigation(adapter)
        asyncio.run(service.enable_robot(robot.id, enabled=True))
        asyncio.run(service.sync_robot(adapter, adapter.external_id))
        approve_navigation(service, robot)
        first = asyncio.run(
            service.create_task_request(
                robot.id,
                navigation_request(idempotency_key="conflict-key-01"),
            )
        )
        with pytest.raises(RobotTaskIdempotencyConflictError):
            asyncio.run(
                service.create_task_request(
                    robot.id,
                    navigation_request(idempotency_key="conflict-key-01").model_copy(
                        update={
                            "parameters": {
                                "target_location": {
                                    "reference_frame": "room",
                                    "x": 9.9,
                                    "y": 9.9,
                                    "yaw": 180,
                                }
                            }
                        }
                    ),
                )
            )
        assert first.status is RobotTaskStatus.AWAITING_CONFIRMATION
    finally:
        manager.dispose()


def test_unverified_capability_stays_disabled(tmp_path: Path) -> None:
    manager, adapter, service, robot = environment(tmp_path)
    try:
        adapter.set_capability(
            RobotCapabilityName.NAVIGATE_TO,
            runtime_enabled=True,
            verification_status="concept",
        )
        asyncio.run(service.enable_robot(robot.id, enabled=True))
        asyncio.run(service.sync_robot(adapter, adapter.external_id))
        asyncio.run(
            service.set_capability_governance(
                robot.id,
                RobotCapabilityName.NAVIGATE_TO,
                enabled=True,
                approved=True,
                consent_granted=True,
                approved_by="test-admin",
            )
        )
        with pytest.raises(RobotCapabilityDisabledError):
            asyncio.run(
                service.create_task_request(
                    robot.id,
                    navigation_request(idempotency_key="unverified-01", confirmed=True),
                )
            )
    finally:
        manager.dispose()


def test_task_cancellation_and_rejection_are_explicit(tmp_path: Path) -> None:
    manager, adapter, service, robot = environment(tmp_path)
    try:
        enable_navigation(adapter)
        asyncio.run(service.enable_robot(robot.id, enabled=True))
        asyncio.run(service.sync_robot(adapter, adapter.external_id))
        approve_navigation(service, robot)
        created = asyncio.run(
            service.create_task_request(
                robot.id,
                navigation_request(idempotency_key="cancel-00001"),
            )
        )
        cancelled = asyncio.run(
            service.cancel_task_request(
                robot.id,
                created.id,
                cancelled_by="user-1",
            )
        )
        assert cancelled.status is RobotTaskStatus.CANCELLED

        rejected_request = asyncio.run(
            service.create_task_request(robot.id, navigation_request(idempotency_key="reject-0001"))
        )
        with pytest.raises(RobotExecutionLockedError):
            asyncio.run(
                service.confirm_task_request(
                    robot.id,
                    rejected_request.id,
                    confirmed=False,
                    confirmed_by="user-1",
                )
            )
    finally:
        manager.dispose()


def test_robot_api_exposes_mock_but_stays_safe_by_default(tmp_path: Path) -> None:
    app_settings = settings(tmp_path)
    manager = DatabaseManager(app_settings)
    manager.initialize_database()
    app = create_app(
        app_settings,
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
        initialize_tool_runtime=True,
    )
    try:
        with TestClient(app) as client:
            robots = client.get("/api/robots", headers=HEADERS)
            assert robots.status_code == 200
            payload = robots.json()[0]["data"]
            assert payload["adapter_id"] == "desktop_firmware_simulator"
            assert payload["is_enabled"] is False
            assert payload["emergency_stop"] is True

            enabled = client.post(f"/api/robots/{payload['id']}/enable", headers=HEADERS)
            assert enabled.status_code == 403
            assert enabled.json()["error"]["code"] == "ROBOT_EXECUTION_LOCKED"
            robot_id = payload["id"]

            capabilities = client.get(f"/api/robots/{robot_id}/capabilities", headers=HEADERS)
            assert capabilities.status_code == 200
            assert all(item["runtime_enabled"] is False for item in capabilities.json()["data"])

            denied = client.post(
                f"/api/robots/{robot_id}/task-requests",
                headers=HEADERS,
                json={
                    "capability": "report_status",
                    "parameters": {},
                    "requested_by": "user-1",
                    "confirmed": True,
                    "idempotency_key": "api-denied-01",
                },
            )
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "ROBOT_EXECUTION_LOCKED"

            adapter = app.state.mock_robot_adapter
            adapter.set_capability(
                RobotCapabilityName.REPORT_STATUS,
                runtime_enabled=True,
                verification_status="bench_verified",
            )
            asyncio.run(app.state.robot_service.sync_robot(adapter, adapter.external_id))
            created = client.post(
                f"/api/robots/{robot_id}/task-requests",
                headers=HEADERS,
                json={
                    "capability": "report_status",
                    "parameters": {},
                    "requested_by": "user-1",
                    "idempotency_key": "api-safety-001",
                },
            )
            assert created.status_code == 403
            assert created.json()["error"]["code"] == "ROBOT_EXECUTION_LOCKED"

            events = client.get(
                f"/api/robots/{robot_id}/events",
                headers=HEADERS,
            )
            assert events.status_code == 200
            assert events.json() == []
    finally:
        manager.dispose()


def test_robot_offline_does_not_break_core_device_surface(tmp_path: Path) -> None:
    app_settings = settings(tmp_path)
    manager = DatabaseManager(app_settings)
    manager.initialize_database()
    app = create_app(
        app_settings,
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
        initialize_tool_runtime=True,
    )
    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            adapter = app.state.mock_robot_adapter
            adapter.set_offline(offline=True)
            robots = client.get("/api/robots", headers=HEADERS)
            assert robots.status_code == 200
            robot = robots.json()[0]["data"]
            enabled = client.post(f"/api/robots/{robot['id']}/enable", headers=HEADERS)
            assert enabled.status_code == 403
            assert enabled.json()["error"]["code"] == "ROBOT_EXECUTION_LOCKED"
            state = client.get(f"/api/robots/{robot['id']}/state", headers=HEADERS)
            assert state.status_code == 200
            assert state.json()["data"]["connection_state"] == "disconnected"
            devices = client.get("/api/devices", headers=HEADERS)
            assert devices.status_code == 200
    finally:
        manager.dispose()
