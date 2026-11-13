import asyncio
import itertools
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from arvuno_core.config import Settings
from arvuno_core.devices.errors import (
    AdapterTimeoutError,
    AdapterUnavailableError,
    AuthorizationError,
    DeviceError,
    DeviceUnavailableError,
)
from arvuno_core.devices.mock import MockDeviceAdapter
from arvuno_core.devices.models import DeviceState, DeviceStateName
from arvuno_core.devices.registry import DeviceRegistry
from arvuno_core.environment.reconciliation import EnvironmentReconciler
from arvuno_core.events.bus import EventBus
from arvuno_core.events.service import DeviceEventService
from arvuno_core.observations.pipeline import ObservationPipeline
from arvuno_core.observations.service import ObservationService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork


def availability_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


@pytest.fixture
def manager(tmp_path: Path) -> DatabaseManager:
    test_manager = DatabaseManager(availability_settings(tmp_path))
    test_manager.initialize_database()
    yield test_manager
    test_manager.dispose()


class SequenceClock:
    def __init__(self) -> None:
        counter = itertools.count()
        self._times = (
            datetime(2026, 11, 11, 12, 0, tzinfo=UTC) + timedelta(seconds=next(counter))
            for _ in iter(int, 1)
        )

    def __call__(self) -> datetime:
        return next(self._times)


class FailingGetStateAdapter:
    def __init__(self, underlying: MockDeviceAdapter, error: DeviceError | None) -> None:
        self.underlying = underlying
        self.error = error

    @property
    def adapter_id(self) -> str:
        return self.underlying.adapter_id

    @property
    def version(self) -> str:
        return self.underlying.version

    async def get_devices(self):
        return await self.underlying.get_devices()

    async def get_state(self, external_id: str) -> DeviceState:
        if self.error is not None:
            raise self.error
        return await self.underlying.get_state(external_id)


class ScriptedStateAdapter(MockDeviceAdapter):
    def __init__(
        self,
        states: list[DeviceState | DeviceError],
        *,
        external_id: str = "mock.switch.airer",
    ) -> None:
        super().__init__()
        self.scripted_states = deque(states)
        self.scripted_external_id = external_id
        self.last_state: DeviceState | None = None

    async def get_state(self, external_id: str) -> DeviceState:
        if external_id != self.scripted_external_id:
            return await super().get_state(external_id)
        item = self.scripted_states.popleft() if self.scripted_states else self.last_state
        if item is None:
            raise RuntimeError("No scripted state was provided.")
        if isinstance(item, DeviceError):
            raise item
        state = item
        self.last_state = state
        return state.model_copy(update={"external_id": external_id})


def make_reconciler(manager: DatabaseManager, *, clock: SequenceClock | None = None):
    factory = lambda: SqlAlchemyUnitOfWork(manager.session_factory)  # noqa: E731
    registry = DeviceRegistry(factory)
    event_bus = EventBus(factory)
    pipeline = ObservationPipeline(factory, ObservationService(factory))
    reconciler = EnvironmentReconciler(
        registry,
        DeviceEventService(registry, event_bus),
        pipeline,
        clock=clock or SequenceClock(),
    )
    return registry, reconciler


def event_count(manager: DatabaseManager, event_type: str) -> int:
    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        assert uow.events is not None
        _, total = uow.events.query(event_type=event_type)
        return total


def test_consecutive_adapter_errors_publish_one_unavailable_transition(
    manager: DatabaseManager,
) -> None:
    async def scenario() -> None:
        adapter = MockDeviceAdapter()
        registry, reconciler = make_reconciler(manager)
        await registry.sync_devices(adapter)
        device = await registry.get_by_external_id("mock", "mock.switch.airer")
        assert device is not None

        await reconciler.reconcile(adapter, ["mock.switch.airer"])
        adapter.set_timeout("mock.switch.airer")

        results = [await reconciler.reconcile(adapter, ["mock.switch.airer"]) for _ in range(10)]
        assert [result.events_published for result in results] == [1, *([0] * 9)]
        assert all(result.failures == 1 for result in results)
        assert event_count(manager, "device_unavailable") == 1

        availability = await registry.availability(device.id)
        assert availability.availability == "unavailable"
        assert availability.error_code == "adapter_timeout"
        assert availability.failure_scope == "adapter"
        assert availability.last_successful_read_at is not None
        assert availability.last_failure_at is not None
        assert availability.transitioned_at is not None

        latest = await registry.latest_state(device.id)
        assert latest is not None
        assert latest.state == DeviceStateName.OFF

    asyncio.run(scenario())


def test_recovery_and_second_outage_each_publish_one_transition(
    manager: DatabaseManager,
) -> None:
    async def scenario() -> None:
        adapter = MockDeviceAdapter()
        registry, reconciler = make_reconciler(manager)
        await registry.sync_devices(adapter)
        device = await registry.get_by_external_id("mock", "mock.switch.airer")
        assert device is not None
        await reconciler.reconcile(adapter, ["mock.switch.airer"])

        adapter.set_timeout("mock.switch.airer")
        await reconciler.reconcile(adapter, ["mock.switch.airer"])
        adapter.set_timeout("mock.switch.airer", timeout=False)
        await adapter.set_state("mock.switch.airer", DeviceStateName.ON)

        recovery = await reconciler.reconcile(adapter, ["mock.switch.airer"])
        assert recovery.events_published == 1
        assert event_count(manager, "device_state_changed") == 1
        assert event_count(manager, "device_unavailable") == 1
        assert (await registry.availability(device.id)).availability == "online"

        adapter.set_timeout("mock.switch.airer")
        first_again = await reconciler.reconcile(adapter, ["mock.switch.airer"])
        repeated_again = await reconciler.reconcile(adapter, ["mock.switch.airer"])
        assert (first_again.events_published, repeated_again.events_published) == (1, 0)
        assert event_count(manager, "device_unavailable") == 2

    asyncio.run(scenario())


def test_availability_state_survives_reconciler_restart(manager: DatabaseManager) -> None:
    async def scenario() -> None:
        adapter = MockDeviceAdapter()
        registry, reconciler = make_reconciler(manager)
        await registry.sync_devices(adapter)
        await reconciler.reconcile(adapter, ["mock.switch.airer"])
        adapter.set_timeout("mock.switch.airer")
        await reconciler.reconcile(adapter, ["mock.switch.airer"])

        restarted_registry, restarted_reconciler = make_reconciler(manager)
        restarted = await restarted_reconciler.reconcile(adapter, ["mock.switch.airer"])
        device = await restarted_registry.get_by_external_id("mock", "mock.switch.airer")
        assert device is not None
        assert restarted.events_published == 0
        assert event_count(manager, "device_unavailable") == 1
        assert (await restarted_registry.availability(device.id)).availability == "unavailable"

    asyncio.run(scenario())


def test_adapter_wide_failure_marks_each_device_once_without_losing_trusted_states(
    manager: DatabaseManager,
) -> None:
    async def scenario() -> None:
        underlying = MockDeviceAdapter()
        registry, reconciler = make_reconciler(manager)
        await registry.sync_devices(underlying)
        allowlist = ["mock.switch.airer", "mock.sensor.temperature"]
        await reconciler.reconcile(underlying, allowlist)

        adapter = FailingGetStateAdapter(underlying, AdapterUnavailableError("Network failed"))
        first = await reconciler.reconcile(adapter, allowlist)
        second = await reconciler.reconcile(adapter, allowlist)
        assert (first.events_published, second.events_published) == (2, 0)
        assert event_count(manager, "device_unavailable") == 2

        for external_id in allowlist:
            device = await registry.get_by_external_id("mock", external_id)
            assert device is not None
            availability = await registry.availability(device.id)
            assert (availability.error_code, availability.failure_scope) == (
                "adapter_unavailable",
                "adapter",
            )
            latest = await registry.latest_state(device.id)
            assert latest is not None
            assert latest.state != DeviceStateName.UNAVAILABLE

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("error", "error_code", "failure_scope"),
    [
        (AdapterTimeoutError("timeout"), "adapter_timeout", "adapter"),
        (AdapterUnavailableError("network"), "adapter_unavailable", "adapter"),
        (AuthorizationError("unauthorized"), "authorization_failed", "adapter"),
        (DeviceUnavailableError("offline"), "device_unavailable", "device"),
    ],
)
def test_failure_classification_distinguishes_adapter_device_and_auth_errors(
    manager: DatabaseManager,
    error: DeviceError,
    error_code: str,
    failure_scope: str,
) -> None:
    async def scenario() -> None:
        underlying = MockDeviceAdapter()
        registry, reconciler = make_reconciler(manager)
        await registry.sync_devices(underlying)
        await reconciler.reconcile(underlying, ["mock.switch.airer"])

        adapter = FailingGetStateAdapter(underlying, error)
        result = await reconciler.reconcile(adapter, ["mock.switch.airer"])
        assert result.events_published == 1
        device = await registry.get_by_external_id("mock", "mock.switch.airer")
        assert device is not None
        availability = await registry.availability(device.id)
        assert (availability.error_code, availability.failure_scope) == (
            error_code,
            failure_scope,
        )

    asyncio.run(scenario())


def test_entity_unavailable_is_classified_separately_and_deduplicated(
    manager: DatabaseManager,
) -> None:
    async def scenario() -> None:
        clock = SequenceClock()
        adapter = ScriptedStateAdapter(
            [
                DeviceState(
                    external_id="mock.switch.airer",
                    state=DeviceStateName.OFF,
                    observed_at=clock(),
                ),
                DeviceState(
                    external_id="mock.switch.airer",
                    state=DeviceStateName.OFF,
                    observed_at=clock(),
                ),
                DeviceState(
                    external_id="mock.switch.airer",
                    state=DeviceStateName.UNAVAILABLE,
                    observed_at=clock(),
                ),
                DeviceState(
                    external_id="mock.switch.airer",
                    state=DeviceStateName.UNAVAILABLE,
                    observed_at=clock(),
                ),
            ]
        )
        registry, reconciler = make_reconciler(manager)
        await registry.sync_devices(adapter)
        await reconciler.reconcile(adapter, ["mock.switch.airer"])

        first = await reconciler.reconcile(adapter, ["mock.switch.airer"])
        repeated = await reconciler.reconcile(adapter, ["mock.switch.airer"])
        assert (first.events_published, repeated.events_published) == (1, 0)
        assert event_count(manager, "device_unavailable") == 1
        device = await registry.get_by_external_id("mock", "mock.switch.airer")
        assert device is not None
        availability = await registry.availability(device.id)
        assert (availability.error_code, availability.failure_scope) == (
            "device_unavailable",
            "entity",
        )

    asyncio.run(scenario())


def test_late_state_does_not_overwrite_newer_trusted_state(manager: DatabaseManager) -> None:
    async def scenario() -> None:
        newer = datetime(2026, 11, 11, 12, 1, tzinfo=UTC)
        older = newer - timedelta(minutes=1)
        newest = newer + timedelta(minutes=1)
        adapter = ScriptedStateAdapter(
            [
                DeviceState(
                    external_id="mock.switch.airer",
                    state=DeviceStateName.OFF,
                    observed_at=newer,
                ),
                DeviceState(
                    external_id="mock.switch.airer",
                    state=DeviceStateName.OFF,
                    observed_at=newer,
                ),
                DeviceState(
                    external_id="mock.switch.airer",
                    state=DeviceStateName.ON,
                    observed_at=older,
                ),
                DeviceState(
                    external_id="mock.switch.airer",
                    state=DeviceStateName.ON,
                    observed_at=newest,
                ),
            ]
        )
        registry, reconciler = make_reconciler(manager)
        await registry.sync_devices(adapter)
        await reconciler.reconcile(adapter, ["mock.switch.airer"])

        late = await reconciler.reconcile(adapter, ["mock.switch.airer"])
        assert late.events_published == 0
        assert late.failures == 1
        device = await registry.get_by_external_id("mock", "mock.switch.airer")
        assert device is not None
        latest = await registry.latest_state(device.id)
        assert latest is not None
        assert latest.state == DeviceStateName.OFF
        assert latest.observed_at.replace(tzinfo=UTC) == newer

        accepted = await reconciler.reconcile(adapter, ["mock.switch.airer"])
        assert accepted.events_published == 1
        latest = await registry.latest_state(device.id)
        assert latest is not None
        assert latest.state == DeviceStateName.ON
        assert latest.observed_at.replace(tzinfo=UTC) == newest

    asyncio.run(scenario())


def test_late_recovery_does_not_mark_stale_device_online(manager: DatabaseManager) -> None:
    async def scenario() -> None:
        latest = datetime(2026, 11, 11, 12, 2, tzinfo=UTC)
        stale = latest - timedelta(minutes=1)
        recovered = latest + timedelta(minutes=1)
        adapter = ScriptedStateAdapter(
            [
                DeviceState(
                    external_id="mock.switch.airer",
                    state=DeviceStateName.OFF,
                    observed_at=latest - timedelta(minutes=2),
                ),
                DeviceState(
                    external_id="mock.switch.airer",
                    state=DeviceStateName.OFF,
                    observed_at=latest,
                ),
                AdapterTimeoutError("timeout"),
                DeviceState(
                    external_id="mock.switch.airer",
                    state=DeviceStateName.OFF,
                    observed_at=stale,
                ),
                DeviceState(
                    external_id="mock.switch.airer",
                    state=DeviceStateName.ON,
                    observed_at=recovered,
                ),
            ]
        )
        registry, reconciler = make_reconciler(manager)
        await registry.sync_devices(adapter)
        await reconciler.reconcile(adapter, ["mock.switch.airer"])
        await reconciler.reconcile(adapter, ["mock.switch.airer"])

        stale_result = await reconciler.reconcile(adapter, ["mock.switch.airer"])
        device = await registry.get_by_external_id("mock", "mock.switch.airer")
        assert device is not None
        assert stale_result.failures == 1
        assert (await registry.availability(device.id)).availability == "unavailable"
        trusted = await registry.latest_state(device.id)
        assert trusted is not None
        assert trusted.state == DeviceStateName.OFF

        recovered_result = await reconciler.reconcile(adapter, ["mock.switch.airer"])
        assert recovered_result.events_published == 1
        assert (await registry.availability(device.id)).availability == "online"

    asyncio.run(scenario())
