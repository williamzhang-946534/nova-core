import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.devices.models import DeviceStateName
from arvuno_core.events.service import DeviceEventService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork


def console_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


@pytest.fixture
def manager(tmp_path: Path) -> DatabaseManager:
    test_manager = DatabaseManager(console_settings(tmp_path))
    test_manager.initialize_database()
    yield test_manager
    test_manager.dispose()


def console_app(
    manager: DatabaseManager,
    tmp_path: Path,
    *,
    initialize_runtime: bool = True,
):
    return create_app(
        console_settings(tmp_path),
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
        initialize_event_runtime=initialize_runtime,
        initialize_tool_runtime=initialize_runtime,
    )


def test_web_console_apis_require_a_bearer_token(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    app = console_app(manager, tmp_path, initialize_runtime=False)
    client = TestClient(app)

    paths = [
        "/api/system/status",
        "/api/devices",
        "/api/environment",
        "/api/environment/snapshots",
        "/api/settings",
    ]
    for path in paths:
        without_token = client.get(path)
        wrong_token = client.get(path, headers={"Authorization": "Bearer wrong-token"})
        assert without_token.status_code == 401, path
        assert without_token.json()["error"]["code"] == "UNAUTHORIZED"
        assert wrong_token.status_code == 401, path


def test_system_status_reports_backend_devices_and_adapters(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    app = console_app(manager, tmp_path)

    with TestClient(app) as client:
        response = client.get(
            "/api/system/status",
            headers={"Authorization": "Bearer test-api-token"},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["version"]
    assert data["environment"] == "test"
    assert data["database"] == "ok"
    assert data["device_count"] == 6
    assert data["online_device_count"] == 6
    assert data["active_task_count"] == 0
    assert {item["adapter_id"]: item["status"] for item in data["adapters"]} == {
        "mock": "healthy",
        "home_assistant": "disconnected",
    }
    assert data["recent_error_events"] == []


def test_device_apis_filter_paginate_and_read_mock_device_state(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    app = console_app(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}

    with TestClient(app) as client:
        living_room = client.get(
            "/api/devices",
            headers=headers,
            params={"area": "Living Room"},
        )
        lights = client.get(
            "/api/devices",
            headers=headers,
            params={"device_type": "light", "keyword": "light"},
        )
        page = client.get(
            "/api/devices",
            headers=headers,
            params={"page": 1, "page_size": 2},
        )
        device_id = lights.json()["data"][0]["id"]
        detail = client.get(f"/api/devices/{device_id}", headers=headers)
        state = client.get(f"/api/devices/{device_id}/state", headers=headers)
        missing = client.get(f"/api/devices/{uuid4()}", headers=headers)

    assert living_room.status_code == 200
    assert living_room.json()["total"] == 3
    assert lights.status_code == 200
    assert lights.json()["total"] == 1
    assert page.status_code == 200
    assert len(page.json()["data"]) == 2
    assert page.json()["page_size"] == 2
    assert detail.status_code == 200
    assert detail.json()["data"]["device"]["id"] == device_id
    assert detail.json()["data"]["latest_state"]["state"] == "off"
    assert detail.json()["data"]["recent_events"] == []
    assert state.status_code == 200
    assert state.json()["data"]["state"] == "off"
    assert state.json()["data"]["attributes"] == {"brightness_pct": 0}
    assert state.json()["data"]["verified"] is True
    assert missing.status_code == 404


def test_environment_apis_return_context_events_and_snapshots(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    app = console_app(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}

    with TestClient(app) as client:

        async def publish_event() -> None:
            registry = app.state.device_registry
            registered = await registry.get_by_external_id("mock", "mock.light.living_room")
            assert registered is not None
            adapter = app.state.mock_device_adapter
            service = DeviceEventService(registry, app.state.event_bus)
            event = await adapter.trigger_state_change(
                "mock.light.living_room",
                DeviceStateName.ON,
            )
            await service.publish(event)
            return registered.id

        device_id = asyncio.run(publish_event())
        environment = client.get("/api/environment", headers=headers)
        snapshots = client.get(
            "/api/environment/snapshots",
            headers=headers,
            params={"page": 1, "page_size": 10},
        )

    assert environment.status_code == 200
    summary = environment.json()["data"]
    assert summary["environment"]["environment_id"] is not None
    assert summary["environment"]["devices"][device_id]["name"] == "Virtual Living Room Light"
    assert summary["environment"]["devices"][device_id]["area"] == "Living Room"
    assert summary["online_device_count"] == 1
    assert summary["unavailable_device_ids"] == []
    assert summary["active_task_count"] == 0
    assert len(summary["recent_events"]) == 1
    assert summary["recent_events"][0]["subject_id"] == device_id

    assert snapshots.status_code == 200
    assert snapshots.json()["total"] == 1
    assert snapshots.json()["data"][0]["context"]["devices"][device_id]["state"] == "on"


def test_settings_api_returns_non_sensitive_runtime_settings_and_persists_preferences(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    app = console_app(manager, tmp_path, initialize_runtime=False)
    headers = {"Authorization": "Bearer test-api-token"}

    with TestClient(app) as client:
        initial = client.get("/api/settings", headers=headers)
        updated = client.patch(
            "/api/settings",
            headers=headers,
            json={"web_console": {"event_poll_interval_seconds": 30}},
        )
        invalid = client.patch(
            "/api/settings",
            headers=headers,
            json={"web_console": {"event_poll_interval_seconds": 1}},
        )

    assert initial.status_code == 200
    runtime = initial.json()["data"]["runtime"]
    assert runtime["ai_provider"] == "mock"
    assert runtime["home_assistant_configured"] is False
    assert runtime["home_assistant_write_enabled"] is False
    assert initial.json()["data"]["web_console"] == {"event_poll_interval_seconds": 10}
    assert "test-api-token" not in initial.text
    assert "api_key" not in initial.text.lower()

    assert updated.status_code == 200
    assert updated.json()["data"]["web_console"] == {"event_poll_interval_seconds": 30}
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"

    with SqlAlchemyUnitOfWork(manager.session_factory) as unit_of_work:
        assert unit_of_work.system_settings is not None
        setting = unit_of_work.system_settings.get_by_key("web_console")
        assert setting is not None
        assert setting.is_secret is False
        assert setting.value == {"event_poll_interval_seconds": 30}


def test_openapi_contains_web_console_paths(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    app = console_app(manager, tmp_path, initialize_runtime=False)
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/system/status" in response.json()["paths"]
    assert "/api/devices" in response.json()["paths"]
    assert "/api/devices/{device_id}" in response.json()["paths"]
    assert "/api/devices/{device_id}/state" in response.json()["paths"]
    assert "/api/environment" in response.json()["paths"]
    assert "/api/environment/snapshots" in response.json()["paths"]
    assert "/api/settings" in response.json()["paths"]
