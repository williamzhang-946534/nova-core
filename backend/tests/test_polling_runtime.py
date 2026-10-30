import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.devices.models import DeviceStateName
from arvuno_core.devices.polling_runtime import DevicePollingRuntime
from arvuno_core.environment.reconciliation import EnvironmentReconciler
from arvuno_core.events.service import DeviceEventService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork

LIGHT_EXTERNAL_ID = "mock.light.living_room"


def polling_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
        device_poll_interval_seconds=3600,
    )


def _app(manager: DatabaseManager, settings: Settings, *, start_device_polling: bool):
    return create_app(
        settings,
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
        initialize_event_runtime=True,
        initialize_tool_runtime=True,
        start_device_polling=start_device_polling,
    )


def test_device_polling_runtime_is_started_with_the_application(tmp_path: Path) -> None:
    settings = polling_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()

    try:
        app = _app(manager, settings, start_device_polling=True)
        with TestClient(app):
            assert getattr(app.state, "device_polling_runtime", None) is not None
    finally:
        manager.dispose()


def test_device_polling_runtime_is_opt_in(tmp_path: Path) -> None:
    settings = polling_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()

    try:
        app = _app(manager, settings, start_device_polling=False)
        with TestClient(app):
            assert getattr(app.state, "device_polling_runtime", None) is None
    finally:
        manager.dispose()


def test_polling_publishes_device_events_and_updates_environment(tmp_path: Path) -> None:
    settings = polling_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()

    try:
        app = _app(manager, settings, start_device_polling=False)
        headers = {"Authorization": "Bearer test-api-token"}
        with TestClient(app) as client:
            adapter = app.state.mock_device_adapter
            registry = app.state.device_registry
            runtime = DevicePollingRuntime(
                EnvironmentReconciler(
                    registry,
                    DeviceEventService(registry, app.state.event_bus),
                ),
                {adapter.adapter_id: adapter},
                {
                    adapter.adapter_id: [
                        device.external_id for device in asyncio.run(adapter.get_devices())
                    ]
                },
                interval_seconds=3600,
            )

            devices = client.get("/api/devices", headers=headers).json()["data"]
            light = next(device for device in devices if device["external_id"] == LIGHT_EXTERNAL_ID)

            asyncio.run(runtime.poll_once())
            assert (
                client.get(
                    "/api/events",
                    headers=headers,
                    params={"event_type": "device_state_changed"},
                ).json()["total"]
                == 0
            )

            asyncio.run(adapter.set_state(LIGHT_EXTERNAL_ID, DeviceStateName.ON))
            asyncio.run(runtime.poll_once())

            events = client.get(
                "/api/events",
                headers=headers,
                params={"event_type": "device_state_changed"},
            ).json()
            assert events["total"] == 1
            assert events["data"][0]["subject_id"] == light["id"]
            assert events["data"][0]["payload"]["current_state"] == "on"

            state = client.get(f"/api/devices/{light['id']}/state", headers=headers).json()["data"]
            assert state["state"] == "on"

            environment = client.get("/api/environment", headers=headers).json()["data"]
            assert environment["environment"]["devices"][light["id"]]["state"] == "on"
            assert environment["online_device_count"] == 6
    finally:
        manager.dispose()
