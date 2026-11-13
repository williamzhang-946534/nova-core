import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import RobotTaskRequestRecord
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.robots.models import RobotCapabilityName

HEADERS = {"Authorization": "Bearer test-api-token"}


def isolated_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        robot_profile="legacy_mock_mobile",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


def locked_environment(tmp_path: Path):
    app_settings = isolated_settings(tmp_path)
    manager = DatabaseManager(app_settings)
    manager.initialize_database()
    app = create_app(
        app_settings,
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
        initialize_tool_runtime=True,
    )
    return manager, app


def assert_locked(response) -> None:
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "ROBOT_EXECUTION_LOCKED"
    assert error["message"] == (
        "Robot execution is locked until the unified safety chain is available."
    )
    assert error["details"] == {
        "required_boundary": "task_system+tool_registry+safety_policy+tool_executor",
        "temporary_lock": True,
    }


def prepare_mobile_request(app, client: TestClient) -> str:
    adapter = app.state.mock_robot_adapter
    adapter.set_emergency_stop(active=False)
    for capability in (RobotCapabilityName.NAVIGATE_TO, RobotCapabilityName.OBSERVE):
        adapter.set_capability(
            capability,
            runtime_enabled=True,
            verification_status="bench_verified",
        )
    asyncio.run(app.state.robot_service.sync_robot(adapter, adapter.external_id))
    robots = asyncio.run(app.state.robot_service.list_robots())
    asyncio.run(app.state.robot_service.enable_robot(robots[0].id, enabled=True))
    for capability in (RobotCapabilityName.NAVIGATE_TO, RobotCapabilityName.OBSERVE):
        asyncio.run(
            app.state.robot_service.set_capability_governance(
                robots[0].id,
                capability,
                enabled=True,
                approved=True,
                consent_granted=True,
                approved_by="test-admin",
            )
        )

    spatial = app.state.spatial_service
    root = asyncio.run(spatial.ensure_root())
    room = asyncio.run(
        spatial.create_space(
            parent_id=root.id,
            name="WP0 Locked Mobile Observation",
            space_type="room",
        )
    )
    from arvuno_core.schemas.perception import ActivePerceptionEvaluateRequest

    request = asyncio.run(
        app.state.robot_mobile_perception_service.evaluate(
            ActivePerceptionEvaluateRequest(
                question="What is in this room now?",
                space_id=room.id,
                attribute="scene_label",
                start_time="2027-01-01T00:00:00Z",
                end_time="2027-01-01T00:05:00Z",
                now="2027-01-01T00:05:00Z",
            ),
            robot_id=robots[0].id,
        )
    )
    asyncio.run(
        app.state.robot_mobile_perception_service.authorize(
            request.id,
            confirmed_navigation=True,
            confirmed_camera_capture=True,
        )
    )
    return request.id


def test_robot_api_write_paths_are_locked_and_reads_remain_available(
    tmp_path: Path,
) -> None:
    manager, app = locked_environment(tmp_path)
    try:
        with TestClient(app) as client:
            listed = client.get("/api/robots", headers=HEADERS)
            assert listed.status_code == 200
            robot = listed.json()[0]["data"]
            robot_id = robot["id"]

            assert_locked(client.post(f"/api/robots/{robot_id}/enable", headers=HEADERS))
            assert_locked(
                client.post(
                    f"/api/robots/{robot_id}/task-requests",
                    headers=HEADERS,
                    json={
                        "capability": "navigate_to",
                        "parameters": {"target_location": {"x": 1, "y": 2}},
                        "requested_by": "wp0-user",
                        "idempotency_key": "wp0-confirmed-bypass",
                        "confirmed": True,
                    },
                )
            )
            assert_locked(
                client.post(
                    "/api/robots/task-requests/missing/confirm",
                    headers=HEADERS,
                    json={"confirmed": True, "confirmed_by": "wp0-user"},
                )
            )
            assert_locked(
                client.post(
                    "/api/robots/task-requests/missing/cancel",
                    headers=HEADERS,
                    json={"cancelled_by": "wp0-user"},
                )
            )

            # Registry administration remains an internal test setup path; the public
            # API write is locked, but read projections should still be observable.
            asyncio.run(app.state.robot_service.enable_robot(robot_id, enabled=True))
            assert client.get(f"/api/robots/{robot_id}", headers=HEADERS).status_code == 200
            capabilities = client.get(f"/api/robots/{robot_id}/capabilities", headers=HEADERS)
            assert capabilities.status_code == 200
            assert len(capabilities.json()["data"]) > 0
            assert client.get(f"/api/robots/{robot_id}/state", headers=HEADERS).status_code == 200
            assert client.get(f"/api/robots/{robot_id}/events", headers=HEADERS).status_code == 200
            history = client.get(f"/api/robots/{robot_id}/task-requests", headers=HEADERS)
            assert history.status_code == 200
            assert history.json() == []

            with manager.session_factory() as session:
                count = session.scalar(select(func.count()).select_from(RobotTaskRequestRecord))
            assert count == 0
    finally:
        manager.dispose()


def test_authorized_mobile_observation_cannot_execute_robot_motion(tmp_path: Path) -> None:
    manager, app = locked_environment(tmp_path)
    try:
        with TestClient(app) as client:
            request_id = prepare_mobile_request(app, client)
            assert_locked(
                client.post(
                    f"/api/robot-perception/requests/{request_id}/execute",
                    headers=HEADERS,
                )
            )
            assert (
                client.get(
                    f"/api/robot-perception/requests/{request_id}", headers=HEADERS
                ).status_code
                == 200
            )
            with manager.session_factory() as session:
                assert session.scalar(select(func.count()).select_from(RobotTaskRequestRecord)) == 0
    finally:
        manager.dispose()


def test_generic_perception_execute_cannot_bypass_robot_lock(tmp_path: Path) -> None:
    manager, app = locked_environment(tmp_path)
    try:
        with TestClient(app) as client:
            request_id = prepare_mobile_request(app, client)
            response = client.post(
                f"/api/active-perception/requests/{request_id}/execute",
                headers=HEADERS,
            )

            assert response.status_code == 200
            assert response.json()["data"]["status"] == "unavailable"
            assert response.json()["data"]["unavailable_reason"] == (
                "No read-only observer is configured for this deployment."
            )
            with manager.session_factory() as session:
                assert session.scalar(select(func.count()).select_from(RobotTaskRequestRecord)) == 0
    finally:
        manager.dispose()
