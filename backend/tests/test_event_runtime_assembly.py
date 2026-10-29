import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.events.models import (
    ArvunoEvent,
    ArvunoEventSource,
    ArvunoEventType,
    DeviceStateChangedPayload,
    utc_now,
)
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork


def runtime_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


@pytest.fixture
def manager(tmp_path: Path) -> DatabaseManager:
    test_manager = DatabaseManager(runtime_settings(tmp_path))
    test_manager.initialize_database()
    yield test_manager
    test_manager.dispose()


def test_create_app_wires_event_bus_to_environment_context(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    app = create_app(
        runtime_settings(tmp_path),
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
        initialize_event_runtime=True,
    )

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert app.state.event_bus is not None
        assert app.state.environment_context is not None
        occurred_at = utc_now()
        event = ArvunoEvent(
            event_type=ArvunoEventType.DEVICE_STATE_CHANGED,
            source=ArvunoEventSource.MOCK_ADAPTER,
            subject_type="device",
            subject_id="device-1",
            payload=DeviceStateChangedPayload(
                device_id="device-1",
                previous_state="off",
                current_state="on",
                attributes={"brightness": 80},
            ),
            correlation_id="correlation-1",
            occurred_at=occurred_at,
        )

        asyncio.run(app.state.event_bus.publish(event))

        state = app.state.environment_context.state
        assert state.environment_id is not None
        assert state.devices["device-1"].state == "on"
        assert state.updated_at == occurred_at


def test_health_does_not_open_a_database_unit_of_work() -> None:
    def forbidden_factory() -> SqlAlchemyUnitOfWork:
        raise AssertionError("The health endpoint must not open a database unit of work.")

    app = create_app(unit_of_work_factory=forbidden_factory)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
