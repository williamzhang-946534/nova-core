from pathlib import Path

from nova_core.config import Settings
from nova_core.devices.mock import MockDeviceAdapter
from nova_core.devices.models import (
    Device,
    DeviceRiskLevel,
)
from nova_core.devices.registry import DeviceRegistry
from nova_core.persistence.database import DatabaseManager
from nova_core.persistence.unit_of_work import SqlAlchemyUnitOfWork


class SelectiveMockAdapter(MockDeviceAdapter):
    def __init__(self, external_id: str) -> None:
        super().__init__()
        self._selected_external_id = external_id

    async def get_devices(self) -> list[Device]:
        devices = await super().get_devices()
        return [device for device in devices if device.external_id == self._selected_external_id]


def phase_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


def test_registry_syncs_stable_projections_capabilities_states_and_disables_missing() -> None:
    import asyncio
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        manager = DatabaseManager(phase_settings(Path(directory)))
        try:
            manager.initialize_database()
            registry = DeviceRegistry(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
            first = asyncio.run(registry.sync_devices(MockDeviceAdapter()))
            devices = asyncio.run(registry.list_devices(adapter_id="mock"))
            first_id = devices[0].id
            state = asyncio.run(registry.latest_state(first_id))

            second = asyncio.run(registry.sync_devices(MockDeviceAdapter()))
            stable_device = asyncio.run(registry.get_by_external_id("mock", devices[0].external_id))
            selective = asyncio.run(
                registry.sync_devices(SelectiveMockAdapter(devices[0].external_id))
            )
            remaining = asyncio.run(registry.list_devices(adapter_id="mock", is_enabled=True))

            assert first.synced_devices == 6
            assert first.state_snapshots == 6
            assert second.synced_devices == 6
            assert stable_device is not None
            assert stable_device.id == first_id
            assert state is not None
            assert state.device_id == first_id
            assert devices[0].risk_level == DeviceRiskLevel.LOW
            assert selective.disabled_devices == 5
            assert len(remaining) == 1
            assert remaining[0].id == first_id
        finally:
            manager.dispose()


def test_registry_updates_alias_and_permission_projection() -> None:
    import asyncio
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        manager = DatabaseManager(phase_settings(Path(directory)))
        try:
            manager.initialize_database()
            registry = DeviceRegistry(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
            asyncio.run(registry.sync_devices(MockDeviceAdapter()))
            device = asyncio.run(registry.list_devices(adapter_id="mock"))[0]

            updated = asyncio.run(
                registry.update_profile(
                    device.id,
                    aliases=["room light"],
                    allowed_actions=["turn_on"],
                    max_risk_level=DeviceRiskLevel.LOW,
                    requires_confirmation=False,
                )
            )

            assert updated.aliases == ["room light"]
            assert [action.value for action in updated.permissions.allowed_actions] == ["turn_on"]
            assert updated.permissions.max_risk_level == DeviceRiskLevel.LOW

            asyncio.run(registry.sync_devices(MockDeviceAdapter()))
            resynchronized = asyncio.run(registry.get_by_id(device.id))

            assert resynchronized is not None
            assert resynchronized.aliases == ["room light"]
            assert [action.value for action in resynchronized.permissions.allowed_actions] == [
                "turn_on"
            ]
        finally:
            manager.dispose()
