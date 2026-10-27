import asyncio
import itertools
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nova_core.config import Settings
from nova_core.devices.mock import MockDeviceAdapter
from nova_core.devices.models import DeviceStateName
from nova_core.devices.registry import DeviceRegistry
from nova_core.environment.context import EnvironmentContextService, area_summary
from nova_core.environment.reconciliation import EnvironmentReconciler
from nova_core.events.bus import EventBus
from nova_core.events.service import DeviceEventService
from nova_core.persistence.database import DatabaseManager
from nova_core.persistence.unit_of_work import SqlAlchemyUnitOfWork


def phase_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


@pytest.fixture
def manager(tmp_path: Path) -> DatabaseManager:
    test_manager = DatabaseManager(phase_settings(tmp_path))
    test_manager.initialize_database()
    yield test_manager
    test_manager.dispose()


def mock_adapter() -> tuple[MockDeviceAdapter, Iterator[datetime]]:
    start = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
    counter = itertools.count()
    times = (start + timedelta(seconds=next(counter)) for _ in iter(int, 1))
    return MockDeviceAdapter(clock=lambda: next(times)), times


def test_device_events_update_environment_context_and_persist_snapshots(
    manager: DatabaseManager,
) -> None:
    async def scenario() -> None:
        adapter, _ = mock_adapter()

        def factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(manager.session_factory)

        registry = DeviceRegistry(factory)
        await registry.sync_devices(adapter)

        event_bus = EventBus(factory)
        context = EnvironmentContextService(factory, registry=registry, environment_name="home")
        await context.initialize()
        event_bus.subscribe(context.handle_event)
        publisher = DeviceEventService(registry, event_bus)

        switch = await registry.get_by_external_id("mock", "mock.switch.airer")
        temperature = await registry.get_by_external_id("mock", "mock.sensor.temperature")
        assert switch is not None
        assert temperature is not None

        await publisher.publish(
            await adapter.trigger_state_change("mock.switch.airer", DeviceStateName.ON)
        )
        await publisher.publish(
            await adapter.set_state(
                "mock.sensor.temperature",
                DeviceStateName.UNKNOWN,
                attributes={"temperature": 26.5, "unit_of_measurement": "C"},
            )
        )
        await publisher.publish(
            await adapter.trigger_state_change(
                "mock.switch.airer",
                DeviceStateName.UNAVAILABLE,
            )
        )

        state = context.state
        assert state.environment_id is not None
        assert state.devices[switch.id].state == "unavailable"
        assert state.sensors[temperature.id].value == 26.5
        assert state.updated_at.tzinfo is not None
        assert state.anomaly_count == 1
        summaries = area_summary(state)
        assert summaries["Balcony"]["unavailable_device_ids"] == [switch.id]
        assert summaries["Living Room"]["online_device_count"] == 1

        environment_id = state.environment_id
        restored = EnvironmentContextService(factory, environment_name="home")
        await restored.initialize()
        restored_state = restored.state
        assert restored_state.model_dump(exclude={"updated_at"}) == state.model_dump(
            exclude={"updated_at"}
        )
        assert restored_state.updated_at.tzinfo is not None

        return environment_id

    environment_id = asyncio.run(scenario())

    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        assert uow.environments is not None
        assert uow.events is not None
        environment = uow.environments.get(environment_id)
        _, event_total = uow.events.query()
        assert environment is not None
        assert len(environment.snapshots) == 3
        assert event_total == 3


def test_reconciliation_establishes_baseline_and_publishes_only_differences(
    manager: DatabaseManager,
) -> None:
    async def scenario() -> None:
        adapter, _ = mock_adapter()

        def factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(manager.session_factory)

        registry = DeviceRegistry(factory)
        await registry.sync_devices(adapter)
        event_bus = EventBus(factory)
        publisher = DeviceEventService(registry, event_bus)
        reconciler = EnvironmentReconciler(registry, publisher)
        allowlist = ["mock.switch.airer", "mock.sensor.temperature"]

        baseline = await reconciler.reconcile(adapter, allowlist)
        assert (baseline.checked, baseline.reconciled, baseline.events_published) == (2, 0, 0)

        await adapter.set_state(
            "mock.sensor.temperature",
            DeviceStateName.UNKNOWN,
            attributes={"temperature": 27.5, "unit_of_measurement": "C"},
        )
        sensor_change = await reconciler.reconcile(adapter, allowlist)
        assert (
            sensor_change.checked,
            sensor_change.reconciled,
            sensor_change.events_published,
        ) == (
            2,
            1,
            1,
        )

        adapter.set_offline("mock.switch.airer")
        unavailable_change = await reconciler.reconcile(adapter, allowlist)
        assert (
            unavailable_change.checked,
            unavailable_change.reconciled,
            unavailable_change.events_published,
        ) == (2, 1, 1)
        assert unavailable_change.failures == 1

    asyncio.run(scenario())

    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        assert uow.events is not None
        sensor_events, sensor_total = uow.events.query(event_type="sensor_updated")
        unavailable_events, unavailable_total = uow.events.query(event_type="device_unavailable")
        assert sensor_total == 1
        assert unavailable_total == 1
        assert sensor_events[0].source == "mock_adapter"
        assert sensor_events[0].payload == {
            "device_id": sensor_events[0].subject_id,
            "sensor_type": "temperature",
            "value": 27.5,
            "unit": "C",
            "previous_value": 24.5,
        }
        assert unavailable_events[0].source == "mock_adapter"
