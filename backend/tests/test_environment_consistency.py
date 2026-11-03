import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.devices.models import DeviceStateName
from arvuno_core.devices.polling_runtime import DevicePollingRuntime
from arvuno_core.environment.reconciliation import EnvironmentReconciler
from arvuno_core.events.service import DeviceEventService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork

HEADERS = {"Authorization": "Bearer test-api-token"}
LIGHT_EXTERNAL_ID = "mock.light.living_room"


def consistency_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
        device_poll_interval_seconds=3600,
    )


def consistency_app(manager: DatabaseManager, settings: Settings):
    return create_app(
        settings,
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
        initialize_event_runtime=True,
        initialize_tool_runtime=True,
    )


def mock_polling_runtime(app) -> DevicePollingRuntime:
    registry = app.state.device_registry
    adapter = app.state.mock_device_adapter
    return DevicePollingRuntime(
        EnvironmentReconciler(
            registry,
            DeviceEventService(registry, app.state.event_bus),
            app.state.observation_pipeline,
        ),
        {adapter.adapter_id: adapter},
        {adapter.adapter_id: [device.external_id for device in asyncio.run(adapter.get_devices())]},
        interval_seconds=3600,
    )


def create_control_task(client: TestClient, device_id: str, *, correlation_id: str) -> dict:
    response = client.post(
        "/api/tasks",
        headers={**HEADERS, "X-Correlation-ID": correlation_id},
        json={
            "task_type": "device_control",
            "title": "Environment consistency acceptance",
            "steps": [
                {
                    "name": "turn_on_light",
                    "tool_name": "control_device",
                    "input": {
                        "device_id": device_id,
                        "action": "turn_on",
                        "expected_state": "on",
                    },
                }
            ],
        },
    )
    return response.json()["data"]


def event_types(client: TestClient, correlation_id: str) -> set[str]:
    events = client.get(
        "/api/events",
        headers=HEADERS,
        params={"correlation_id": correlation_id},
    ).json()["data"]
    return {event["event_type"] for event in events}


def device_snapshot_count(client: TestClient) -> int:
    return client.get("/api/environment/snapshots", headers=HEADERS).json()["total"]


def test_startup_projects_registry_devices_into_environment(tmp_path: Path) -> None:
    settings = consistency_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    try:
        with TestClient(consistency_app(manager, settings)) as client:
            devices = client.get("/api/devices", headers=HEADERS).json()["data"]
            environment = client.get("/api/environment", headers=HEADERS).json()["data"]
            system = client.get("/api/system/status", headers=HEADERS).json()["data"]

        device_ids = {device["id"] for device in devices}
        assert len(device_ids) == 6
        assert set(environment["environment"]["devices"]) == device_ids
        assert environment["online_device_count"] == 6
        assert environment["unavailable_device_ids"] == []
        assert system["device_count"] == 6
        assert system["online_device_count"] == environment["online_device_count"]
    finally:
        manager.dispose()


def test_verified_control_updates_environment_without_device_state_event(tmp_path: Path) -> None:
    settings = consistency_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    try:
        with TestClient(consistency_app(manager, settings)) as client:
            device_id = next(
                device["id"]
                for device in client.get("/api/devices", headers=HEADERS).json()["data"]
                if device["external_id"] == LIGHT_EXTERNAL_ID
            )
            snapshots_before = device_snapshot_count(client)

            task = create_control_task(client, device_id, correlation_id="env-control-1")

            assert task["status"] == "completed"
            detail = client.get(f"/api/tasks/{task['id']}", headers=HEADERS).json()["data"]
            assert detail["executions"][0]["validation"]["verified"] is True

            environment = client.get("/api/environment", headers=HEADERS).json()["data"]
            assert environment["environment"]["devices"][device_id]["state"] == "on"
            assert device_snapshot_count(client) == snapshots_before + 1

            types = event_types(client, "env-control-1")
            assert {"task_started", "task_completed", "tool_executed"} <= types
            assert "device_state_changed" not in types
    finally:
        manager.dispose()


def test_offline_device_control_does_not_project_target_state(tmp_path: Path) -> None:
    settings = consistency_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    try:
        with TestClient(consistency_app(manager, settings)) as client:
            device_id = next(
                device["id"]
                for device in client.get("/api/devices", headers=HEADERS).json()["data"]
                if device["external_id"] == LIGHT_EXTERNAL_ID
            )
            adapter = client.app.state.mock_device_adapter
            adapter.set_offline(LIGHT_EXTERNAL_ID)

            task = create_control_task(client, device_id, correlation_id="env-offline-1")

            assert task["status"] == "failed"
            environment = client.get("/api/environment", headers=HEADERS).json()["data"]
            assert environment["environment"]["devices"][device_id]["state"] == "off"
            assert "device_state_changed" not in event_types(client, "env-offline-1")
    finally:
        manager.dispose()


@pytest.mark.parametrize("fault", ["timeout", "action_failure"])
def test_execution_failure_does_not_project_target_state(tmp_path: Path, fault: str) -> None:
    settings = consistency_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    try:
        with TestClient(consistency_app(manager, settings)) as client:
            device_id = next(
                device["id"]
                for device in client.get("/api/devices", headers=HEADERS).json()["data"]
                if device["external_id"] == LIGHT_EXTERNAL_ID
            )
            adapter = client.app.state.mock_device_adapter
            getattr(adapter, f"set_{fault}")(LIGHT_EXTERNAL_ID)
            snapshots_before = device_snapshot_count(client)

            task = create_control_task(client, device_id, correlation_id=f"env-fault-{fault}")

            assert task["status"] == "failed"
            environment = client.get("/api/environment", headers=HEADERS).json()["data"]
            assert environment["environment"]["devices"][device_id]["state"] == "off"
            assert device_snapshot_count(client) == snapshots_before
    finally:
        manager.dispose()


def test_state_verification_failure_is_not_reported_or_projected(tmp_path: Path) -> None:
    settings = consistency_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    try:
        with TestClient(consistency_app(manager, settings)) as client:
            device_id = next(
                device["id"]
                for device in client.get("/api/devices", headers=HEADERS).json()["data"]
                if device["external_id"] == LIGHT_EXTERNAL_ID
            )
            adapter = client.app.state.mock_device_adapter
            adapter.set_verification_failure(LIGHT_EXTERNAL_ID)
            snapshots_before = device_snapshot_count(client)

            task = create_control_task(client, device_id, correlation_id="env-verify-1")

            assert task["status"] == "failed"
            detail = client.get(f"/api/tasks/{task['id']}", headers=HEADERS).json()["data"]
            assert detail["executions"][0]["status"] == "failed"
            environment = client.get("/api/environment", headers=HEADERS).json()["data"]
            assert environment["environment"]["devices"][device_id]["state"] == "off"
            assert device_snapshot_count(client) == snapshots_before
    finally:
        manager.dispose()


def test_external_state_change_still_publishes_and_updates_environment(tmp_path: Path) -> None:
    settings = consistency_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    try:
        app = consistency_app(manager, settings)
        with TestClient(app) as client:
            device_id = next(
                device["id"]
                for device in client.get("/api/devices", headers=HEADERS).json()["data"]
                if device["external_id"] == LIGHT_EXTERNAL_ID
            )
            runtime = mock_polling_runtime(app)
            adapter = app.state.mock_device_adapter

            asyncio.run(adapter.set_state(LIGHT_EXTERNAL_ID, DeviceStateName.ON))
            asyncio.run(runtime.poll_once())

            events = client.get(
                "/api/events",
                headers=HEADERS,
                params={"event_type": "device_state_changed", "subject_id": device_id},
            ).json()
            assert events["total"] == 1
            environment = client.get("/api/environment", headers=HEADERS).json()["data"]
            assert environment["environment"]["devices"][device_id]["state"] == "on"
    finally:
        manager.dispose()


def test_nova_control_does_not_trigger_device_state_automation(tmp_path: Path) -> None:
    settings = consistency_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    try:
        app = consistency_app(manager, settings)
        with TestClient(app) as client:
            device_id = next(
                device["id"]
                for device in client.get("/api/devices", headers=HEADERS).json()["data"]
                if device["external_id"] == LIGHT_EXTERNAL_ID
            )
            rule = client.post(
                "/api/automations",
                headers=HEADERS,
                json={
                    "name": "Self-trigger guard",
                    "enabled": True,
                    "trigger": {
                        "event_type": "device_state_changed",
                        "subject_id": device_id,
                    },
                    "conditions": [
                        {
                            "field": "payload.current_state",
                            "operator": "eq",
                            "value": "on",
                        }
                    ],
                    "action": {
                        "type": "notification",
                        "title": "Light turned on",
                        "message": "The light turned on.",
                    },
                    "cooldown_seconds": 0,
                },
            ).json()["data"]

            task = create_control_task(client, device_id, correlation_id="env-automation-1")
            assert task["status"] == "completed"

            asyncio.run(mock_polling_runtime(app).poll_once())

            events = client.get(
                "/api/events",
                headers=HEADERS,
                params={"event_type": "device_state_changed"},
            ).json()
            runs = client.get(f"/api/automations/{rule['id']}/runs", headers=HEADERS).json()["data"]
            notifications = client.get("/api/notifications", headers=HEADERS).json()["data"]

            assert events["total"] == 0
            assert runs == []
            assert notifications == []
    finally:
        manager.dispose()


def test_restart_does_not_duplicate_environment_snapshots(tmp_path: Path) -> None:
    settings = consistency_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    try:
        with TestClient(consistency_app(manager, settings)) as client:
            first_devices = len(
                client.get("/api/environment", headers=HEADERS).json()["data"]["environment"][
                    "devices"
                ]
            )
            first_snapshots = device_snapshot_count(client)
            first_events = client.get("/api/events", headers=HEADERS).json()["total"]

        with TestClient(consistency_app(manager, settings)) as client:
            second_devices = len(
                client.get("/api/environment", headers=HEADERS).json()["data"]["environment"][
                    "devices"
                ]
            )
            second_snapshots = device_snapshot_count(client)
            second_events = client.get("/api/events", headers=HEADERS).json()["total"]

        assert first_devices == second_devices == 6
        assert first_snapshots == second_snapshots == 1
        assert first_events == second_events == 0
    finally:
        manager.dispose()
