import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.robots.errors import (
    RobotCapabilityDisabledError,
    RobotInvalidParameterError,
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
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


def environment(tmp_path: Path):
    manager = DatabaseManager(settings(tmp_path))
    manager.initialize_database()
    adapter = MockRobotAdapter()
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
        assert all(capability.requires_confirmation for capability in capabilities)
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

        completed = asyncio.run(
            service.confirm_task_request(
                robot.id,
                created.id,
                confirmed=True,
                confirmed_by="user-1",
            )
        )
        assert completed.status is RobotTaskStatus.SUCCEEDED
        assert completed.result["moved_to"]["x"] == 1.2
        assert completed.result["moved_to"]["position_confidence"] == 0.9

        state = asyncio.run(service.state(robot.id))
        assert state.location.x == 1.2
        assert state.last_seen_at is not None
        events = asyncio.run(service.events(robot.id, task_request_id=created.id))
        assert [event.event_type for event in events] == ["task_succeeded"]
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
        created = asyncio.run(
            service.create_task_request(
                robot.id,
                navigation_request(idempotency_key=f"failure-{expected_error.lower()}"),
            )
        )
        result = asyncio.run(
            service.confirm_task_request(
                robot.id,
                created.id,
                confirmed=True,
                confirmed_by="user-1",
            )
        )
        assert result.status is expected_status
        assert result.error is not None
        assert result.error["code"] == expected_error
        assert result.completed_at is not None
        events = asyncio.run(service.events(robot.id, task_request_id=created.id))
        assert events
        assert events[0].payload["error"]["code"] == expected_error
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
        rejected = asyncio.run(
            service.confirm_task_request(
                robot.id,
                rejected_request.id,
                confirmed=False,
                confirmed_by="user-1",
            )
        )
        assert rejected.status is RobotTaskStatus.REJECTED
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
            assert payload["adapter_id"] == "mock_robot"
            assert payload["is_enabled"] is False
            assert payload["emergency_stop"] is True

            enabled = client.post(f"/api/robots/{payload['id']}/enable", headers=HEADERS)
            assert enabled.status_code == 200
            robot_id = enabled.json()["data"]["id"]

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
            assert denied.json()["error"]["code"] == "ROBOT_CAPABILITY_DISABLED"

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
            assert created.status_code == 201
            task = created.json()["data"]
            assert task["status"] == "awaiting_confirmation"

            completed = client.post(
                f"/api/robots/task-requests/{task['id']}/confirm",
                headers=HEADERS,
                json={"confirmed": True, "confirmed_by": "user-1"},
            )
            assert completed.status_code == 200
            assert completed.json()["data"]["status"] == "safe_stopped"
            assert completed.json()["data"]["error"]["code"] == "ROBOT_SAFETY_STATE"

            events = client.get(
                f"/api/robots/{robot_id}/events",
                headers=HEADERS,
                params={"task_request_id": task["id"]},
            )
            assert events.status_code == 200
            assert events.json()[0]["event_type"] == "task_safe_stopped"
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
            assert enabled.status_code == 200
            state = client.get(f"/api/robots/{robot['id']}/state", headers=HEADERS)
            assert state.status_code == 200
            assert state.json()["data"]["connection_state"] == "disconnected"
            devices = client.get("/api/devices", headers=HEADERS)
            assert devices.status_code == 200
    finally:
        manager.dispose()
