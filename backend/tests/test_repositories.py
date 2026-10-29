from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from arvuno_core.config import Settings
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import Device, DeviceState, Event, SystemSetting
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork


def phase_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


def device(name: str = "Living Room Light", external_id: str = "light.living") -> Device:
    return Device(
        adapter_id="mock",
        external_id=external_id,
        name=name,
        normalized_name=name.lower(),
        device_type="light",
        is_online=True,
        is_enabled=True,
        risk_level="low",
        capabilities={"brightness": True},
        metadata_summary={"source": "test"},
    )


def event(event_type: str, occurred_at: datetime, subject_id: str) -> Event:
    return Event(
        event_type=event_type,
        source="test",
        subject_type="device",
        subject_id=subject_id,
        payload={"value": subject_id},
        correlation_id="correlation-1",
        occurred_at=occurred_at,
    )


@pytest.fixture
def manager(tmp_path: Path) -> DatabaseManager:
    test_manager = DatabaseManager(phase_settings(tmp_path))
    test_manager.initialize_database()
    yield test_manager
    test_manager.dispose()


def test_repositories_save_and_query_domain_data(manager: DatabaseManager) -> None:
    now = datetime.now(UTC)
    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        stored_device = uow.devices.add(device())
        stored_device.states.append(
            DeviceState(
                state="on",
                attributes={"brightness": 80},
                source="test",
                observed_at=now,
            )
        )
        uow.events.add(event("device_state_changed", now, "light.living"))
        uow.events.add(event("sensor_updated", now + timedelta(seconds=1), "sensor.temp"))
        uow.system_settings.upsert_non_sensitive(
            key="home_assistant.configured",
            value={"configured": True},
            value_type="object",
        )
        uow.commit()

    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        projection = uow.devices.get_by_external_id("mock", "light.living")
        assert projection is not None
        assert projection.states[0].state == "on"
        assert uow.devices.list(page=1, page_size=1) == [projection]

        events, total = uow.events.query(
            event_type="device_state_changed",
            correlation_id="correlation-1",
        )
        assert [item.subject_id for item in events] == ["light.living"]
        assert total == 1
        events, total = uow.events.query(order="asc")
        assert total == 2
        assert [item.event_type for item in events] == [
            "device_state_changed",
            "sensor_updated",
        ]

        setting = uow.system_settings.get_by_key("home_assistant.configured")
        assert setting is not None
        assert setting.value == {"configured": True}
        assert setting.is_secret is False


def test_unit_of_work_rolls_back_on_error(manager: DatabaseManager) -> None:
    with (
        pytest.raises(RuntimeError, match="expected failure"),
        SqlAlchemyUnitOfWork(manager.session_factory) as uow,
    ):
        uow.devices.add(device(name="Rolled Back Device", external_id="light.rollback"))
        raise RuntimeError("expected failure")

    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        assert uow.devices.get_by_external_id("mock", "light.rollback") is None


def test_unique_device_projection_is_enforced(manager: DatabaseManager) -> None:
    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        uow.devices.add(device())
        uow.commit()

    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        uow.devices.add(device())
        with pytest.raises(RepositoryError, match="Failed to commit"):
            uow.commit()


def test_secret_system_settings_cannot_be_written_through_repository(
    manager: DatabaseManager,
) -> None:
    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        uow.system_settings.add(
            SystemSetting(
                key="provider.credential",
                value={"reference": "ARVUNO_API_TOKEN"},
                value_type="reference",
                is_secret=True,
            )
        )
        uow.commit()

    with (
        SqlAlchemyUnitOfWork(manager.session_factory) as uow,
        pytest.raises(RepositoryError, match="Secret system settings"),
    ):
        uow.system_settings.upsert_non_sensitive(
            key="provider.credential",
            value={"reference": "OTHER_TOKEN"},
            value_type="reference",
        )


def test_pagination_is_validated(manager: DatabaseManager) -> None:
    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        with pytest.raises(ValueError, match="Page must be positive"):
            uow.devices.list(page=0)
        with pytest.raises(ValueError, match="page_size"):
            uow.events.list(page_size=101)
