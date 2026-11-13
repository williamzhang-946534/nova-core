"""ARS-06.4 final acceptance probes for the embodied-intelligence boundary.

These tests exercise the documented acceptance list end to end through the
public API and the robot application service. They intentionally use the Mock
Robot Adapter; real hardware acceptance remains a separate, unexecuted gate.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import Observation, ObservationSource
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.robots.mock import MockRobotAdapter
from arvuno_core.robots.models import RobotCapabilityName

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


def app_environment(tmp_path: Path):
    manager = DatabaseManager(settings(tmp_path))
    manager.initialize_database()
    app = create_app(
        settings(tmp_path),
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
        initialize_tool_runtime=True,
    )
    return manager, app


def prepare_robot(app, *, emergency_stop: bool = False, manual_takeover: bool = False):
    adapter: MockRobotAdapter = app.state.mock_robot_adapter
    adapter.set_emergency_stop(active=emergency_stop)
    adapter.set_manual_takeover(active=manual_takeover)
    for capability in (RobotCapabilityName.NAVIGATE_TO, RobotCapabilityName.OBSERVE):
        adapter.set_capability(
            capability,
            runtime_enabled=True,
            verification_status="bench_verified",
        )
    asyncio.run(app.state.robot_service.sync_robot(adapter, adapter.external_id))
    robot = asyncio.run(app.state.robot_service.list_robots())[0]
    asyncio.run(app.state.robot_service.enable_robot(robot.id, enabled=True))
    for capability in (RobotCapabilityName.NAVIGATE_TO, RobotCapabilityName.OBSERVE):
        asyncio.run(
            app.state.robot_service.set_capability_governance(
                robot.id,
                capability,
                enabled=True,
                approved=True,
                consent_granted=True,
                approved_by="test-admin",
            )
        )
    return adapter, robot


def create_room(app, name: str) -> str:
    spatial = app.state.spatial_service
    root = asyncio.run(spatial.ensure_root())
    return asyncio.run(
        spatial.create_space(
            parent_id=root.id,
            name=f"ARS-06 {name}",
            space_type="room",
        )
    ).id


def navigation_payload(*, idempotency_key: str, confirmed: bool = False) -> dict:
    return {
        "capability": "navigate_to",
        "parameters": {
            "target_location": {
                "reference_frame": "room",
                "x": 1.2,
                "y": 2.3,
                "yaw": 90,
                "position_confidence": 0.8,
            }
        },
        "requested_by": "acceptance-user",
        "idempotency_key": idempotency_key,
        "confirmed": confirmed,
        "correlation_id": "ars06-acceptance",
    }


def assert_execution_locked(response) -> None:
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROBOT_EXECUTION_LOCKED"


def test_acceptance_capability_registration_and_state_sync(tmp_path: Path) -> None:
    manager, app = app_environment(tmp_path)
    try:
        with TestClient(app) as client:
            listed = client.get("/api/robots", headers=HEADERS)
            assert listed.status_code == 200
            robot = listed.json()[0]["data"]
            assert robot["adapter_id"] == "mock_robot"
            assert robot["is_enabled"] is False
            assert robot["emergency_stop"] is True

            enabled = client.post(
                f"/api/robots/{robot['id']}/enable",
                headers=HEADERS,
            )
            assert_execution_locked(enabled)

            default_capabilities = client.get(
                f"/api/robots/{robot['id']}/capabilities",
                headers=HEADERS,
            )
            assert default_capabilities.status_code == 200
            assert all(
                item["verification_status"] == "concept" and item["runtime_enabled"] is False
                for item in default_capabilities.json()["data"]
            )

            adapter = app.state.mock_robot_adapter
            adapter.set_emergency_stop(active=False)
            for capability in (
                RobotCapabilityName.NAVIGATE_TO,
                RobotCapabilityName.OBSERVE,
            ):
                adapter.set_capability(
                    capability,
                    runtime_enabled=True,
                    verification_status="bench_verified",
                )
            asyncio.run(app.state.robot_service.sync_robot(adapter, adapter.external_id))
            for capability in (
                RobotCapabilityName.NAVIGATE_TO,
                RobotCapabilityName.OBSERVE,
            ):
                asyncio.run(
                    app.state.robot_service.set_capability_governance(
                        robot["id"],
                        capability,
                        enabled=True,
                        approved=True,
                        consent_granted=True,
                        approved_by="test-admin",
                    )
                )

            capabilities = client.get(
                f"/api/robots/{robot['id']}/capabilities",
                headers=HEADERS,
            ).json()["data"]
            by_name = {item["capability"]: item for item in capabilities}
            assert by_name["navigate_to"]["runtime_enabled"] is True
            assert by_name["navigate_to"]["verification_status"] == "bench_verified"
            assert by_name["observe"]["runtime_enabled"] is True
            assert by_name["observe"]["evidence"]["mock_only"] is True

            state = client.get(
                f"/api/robots/{robot['id']}/state",
                headers=HEADERS,
            )
            assert state.status_code == 200
            data = state.json()["data"]
            assert data["connection_state"] == "connected"
            assert data["is_online"] is True
            assert data["emergency_stop"] is False
            assert data["location"]["localization_state"] == "known"
            assert data["location"]["position_confidence"] == 0.9
            assert data["last_seen_at"] is not None
    finally:
        manager.dispose()


def test_acceptance_navigation_is_locked_before_confirmation(
    tmp_path: Path,
) -> None:
    manager, app = app_environment(tmp_path)
    try:
        with TestClient(app) as client:
            _, robot = prepare_robot(app)
            created = client.post(
                f"/api/robots/{robot.id}/task-requests",
                headers=HEADERS,
                json=navigation_payload(idempotency_key="ars06-nav-0001"),
            )
            assert_execution_locked(created)

            state = client.get(
                f"/api/robots/{robot.id}/state",
                headers=HEADERS,
            ).json()["data"]
            assert state["location"]["x"] == 0
            assert state["location"]["y"] == 0

            events = client.get(
                f"/api/robots/{robot.id}/events",
                headers=HEADERS,
            )
            assert events.status_code == 200
            assert events.json() == []
    finally:
        manager.dispose()


def test_acceptance_idempotency_conflict_is_a_structured_error(tmp_path: Path) -> None:
    manager, app = app_environment(tmp_path)
    try:
        with TestClient(app) as client:
            _, robot = prepare_robot(app)
            first = client.post(
                f"/api/robots/{robot.id}/task-requests",
                headers=HEADERS,
                json=navigation_payload(idempotency_key="ars06-conflict-01"),
            )
            assert_execution_locked(first)
            conflicting = navigation_payload(idempotency_key="ars06-conflict-01")
            conflicting["parameters"]["target_location"]["x"] = 9.9
            conflict = client.post(
                f"/api/robots/{robot.id}/task-requests",
                headers=HEADERS,
                json=conflicting,
            )
            assert_execution_locked(conflict)
    finally:
        manager.dispose()


def test_acceptance_mobile_observation_uses_robot_source_and_dual_consent(
    tmp_path: Path,
) -> None:
    manager, app = app_environment(tmp_path)
    try:
        with TestClient(app) as client:
            _, robot = prepare_robot(app)
            room_id = create_room(app, "mobile observation")
            now = datetime.now(UTC)

            evaluated = client.post(
                "/api/robot-perception/requests/evaluate",
                headers=HEADERS,
                json={
                    "robot_id": robot.id,
                    "request": {
                        "question": "What is in this room now?",
                        "space_id": room_id,
                        "attribute": "scene_label",
                        "start_time": (now - timedelta(minutes=5)).isoformat(),
                        "end_time": now.isoformat(),
                        "now": now.isoformat(),
                    },
                },
            )
            assert evaluated.status_code == 201
            request = evaluated.json()["data"]
            assert request["status"] == "awaiting_consent"
            plan = request["proposed_input"]["mobile_plan"]
            assert plan["steps"] == ["navigate_to", "observe"]
            assert plan["target_space_id"] == room_id
            assert request["execution_trace"]["mock_only"] is True

            incomplete = client.post(
                f"/api/robot-perception/requests/{request['id']}/authorize",
                headers=HEADERS,
                json={
                    "confirmed_navigation": True,
                    "confirmed_camera_capture": False,
                },
            )
            assert incomplete.status_code == 409
            assert incomplete.json()["error"]["code"] == "ROBOT_MOBILE_CONFIRMATION_REQUIRED"

            authorized = client.post(
                f"/api/robot-perception/requests/{request['id']}/authorize",
                headers=HEADERS,
                json={
                    "confirmed_navigation": True,
                    "confirmed_camera_capture": True,
                },
            )
            assert authorized.status_code == 200
            assert authorized.json()["data"]["authorization_scope"]["target_space_id"] == room_id

            executed = client.post(
                f"/api/robot-perception/requests/{request['id']}/execute",
                headers=HEADERS,
            )
            assert_execution_locked(executed)
            fetched = client.get(
                f"/api/robot-perception/requests/{request['id']}",
                headers=HEADERS,
            ).json()["data"]
            assert fetched["status"] == "proposed"
            assert fetched["execution_trace"]["mock_only"] is True

            with manager.session_factory() as session:
                assert (
                    session.scalars(
                        select(Observation).where(Observation.correlation_id == request["id"])
                    ).all()
                    == []
                )
                source = session.scalars(
                    select(ObservationSource).where(ObservationSource.source_type == "robot_mobile")
                ).one()
                assert source.config["mock_only"] is True
                assert source.privacy_scope["sensitive"] is True
    finally:
        manager.dispose()


@pytest.mark.parametrize("blocker", ["emergency_stop", "manual_takeover"])
def test_acceptance_safety_stop_and_manual_takeover_block_navigation(
    tmp_path: Path,
    blocker: str,
) -> None:
    manager, app = app_environment(tmp_path)
    try:
        with TestClient(app) as client:
            _, robot = prepare_robot(
                app,
                emergency_stop=blocker == "emergency_stop",
                manual_takeover=blocker == "manual_takeover",
            )
            response = client.post(
                f"/api/robots/{robot.id}/task-requests",
                headers=HEADERS,
                json=navigation_payload(
                    idempotency_key=f"ars06-{blocker}-01",
                    confirmed=True,
                ),
            )
            assert_execution_locked(response)

            state = client.get(
                f"/api/robots/{robot.id}/state",
                headers=HEADERS,
            ).json()["data"]
            assert state["location"]["x"] == 0
            if blocker == "emergency_stop":
                assert state["emergency_stop"] is True
                assert state["motion_safety_state"] == "stopped"
            else:
                assert state["manual_takeover"] is True
                assert state["motion_safety_state"] == "manual_takeover"
    finally:
        manager.dispose()


def test_acceptance_offline_recovery_restores_state_and_new_tasks(tmp_path: Path) -> None:
    manager, app = app_environment(tmp_path)
    try:
        with TestClient(app) as client:
            adapter, robot = prepare_robot(app)
            adapter.set_offline(offline=True)

            offline_task = client.post(
                f"/api/robots/{robot.id}/task-requests",
                headers=HEADERS,
                json=navigation_payload(
                    idempotency_key="ars06-offline-01",
                    confirmed=True,
                ),
            )
            assert_execution_locked(offline_task)

            offline_state = client.get(
                f"/api/robots/{robot.id}/state",
                headers=HEADERS,
            )
            assert offline_state.status_code == 200
            assert offline_state.json()["data"]["connection_state"] == "disconnected"
            assert offline_state.json()["data"]["is_online"] is False

            adapter.set_offline(offline=False)
            recovered = client.get(
                f"/api/robots/{robot.id}/state",
                headers=HEADERS,
            ).json()["data"]
            assert recovered["connection_state"] == "connected"
            assert recovered["is_online"] is True
            assert recovered["last_seen_at"] is not None

            events = client.get(
                f"/api/robots/{robot.id}/events",
                headers=HEADERS,
            ).json()
            assert any(
                event["event_type"] == "connection_changed"
                and event["payload"]["is_online"] is True
                for event in events
            )

            recovered_task = client.post(
                f"/api/robots/{robot.id}/task-requests",
                headers=HEADERS,
                json=navigation_payload(
                    idempotency_key="ars06-recovered-01",
                    confirmed=True,
                ),
            )
            assert_execution_locked(recovered_task)
    finally:
        manager.dispose()


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/api/system/status",
        "/api/devices",
        "/api/spaces",
        "/api/environment",
        "/api/events",
        "/api/tasks",
        "/api/memories",
        "/api/observation-sources",
        "/api/robots",
    ],
)
def test_acceptance_core_surface_remains_available_while_robot_offline(
    tmp_path: Path,
    path: str,
) -> None:
    manager, app = app_environment(tmp_path)
    try:
        app.state.mock_robot_adapter.set_offline(offline=True)
        with TestClient(app) as client:
            response = client.get(path, headers=HEADERS)
            assert response.status_code == 200, f"{path}: {response.text}"
    finally:
        manager.dispose()


def test_acceptance_mobile_perception_reports_offline_robot_without_500(
    tmp_path: Path,
) -> None:
    manager, app = app_environment(tmp_path)
    try:
        with TestClient(app) as client:
            _, robot = prepare_robot(app)
            room_id = create_room(app, "offline mobile")
            app.state.mock_robot_adapter.set_offline(offline=True)
            now = datetime.now(UTC)
            response = client.post(
                "/api/robot-perception/requests/evaluate",
                headers=HEADERS,
                json={
                    "robot_id": robot.id,
                    "request": {
                        "question": "What is in this room now?",
                        "space_id": room_id,
                        "attribute": "scene_label",
                        "start_time": (now - timedelta(minutes=5)).isoformat(),
                        "end_time": now.isoformat(),
                        "now": now.isoformat(),
                    },
                },
            )
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "ROBOT_MOBILE_UNAVAILABLE"
    finally:
        manager.dispose()
