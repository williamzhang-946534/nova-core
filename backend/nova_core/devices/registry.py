import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import Field

from nova_core.devices.interface import DeviceAdapter
from nova_core.devices.models import (
    Device,
    DeviceCapability,
    DeviceEvent,
    DevicePermissions,
    DeviceRiskLevel,
    DeviceState,
    DeviceStateName,
)
from nova_core.persistence.repositories import CapabilityRecord, DeviceProjectionUpdate
from nova_core.persistence.unit_of_work import SqlAlchemyUnitOfWork


class RegisteredDevice(Device):
    id: str = Field(min_length=1)
    adapter_id: str = Field(min_length=1)
    is_enabled: bool = True


class RegisteredDeviceState(DeviceState):
    device_id: str = Field(min_length=1)


@dataclass(frozen=True)
class DeviceSyncResult:
    synced_devices: int
    disabled_devices: int
    state_snapshots: int


class DeviceRegistry:
    """Stores Nova's lightweight projections and maps external IDs to Nova IDs."""

    def __init__(self, unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def sync_devices(self, adapter: DeviceAdapter) -> DeviceSyncResult:
        devices = await adapter.get_devices()
        states = [await adapter.get_state(device.external_id) for device in devices]
        state_by_external_id = {state.external_id: state for state in states}

        def execute() -> DeviceSyncResult:
            with self._unit_of_work_factory() as uow:
                assert uow.devices is not None
                repository = uow.devices
                nova_id_by_external_id: dict[str, str] = {}
                for device in devices:
                    projection = repository.upsert_projection(
                        _projection_update(
                            adapter,
                            device,
                            state_by_external_id.get(device.external_id),
                        )
                    )
                    repository.replace_capabilities(
                        projection.id,
                        [
                            CapabilityRecord(
                                capability=capability.capability,
                                supported_actions=[item.value for item in capability.actions],
                                parameters=capability.parameters,
                                risk_level=capability.risk_level.value,
                                requires_confirmation=capability.requires_confirmation,
                                enabled=True,
                            )
                            for capability in device.capabilities
                        ],
                    )
                    nova_id_by_external_id[device.external_id] = projection.id
                snapshots = 0
                for external_id, nova_id in nova_id_by_external_id.items():
                    state = state_by_external_id.get(external_id)
                    if state is not None:
                        repository.add_state_snapshot(
                            nova_id,
                            state=state.state.value,
                            attributes=state.attributes,
                            raw_state=state.raw_state,
                            source=adapter.adapter_id,
                            observed_at=state.observed_at,
                        )
                        snapshots += 1
                disabled = repository.disable_not_in_external_ids(
                    adapter.adapter_id,
                    [device.external_id for device in devices],
                )
                uow.commit()
                return DeviceSyncResult(
                    synced_devices=len(devices),
                    disabled_devices=disabled,
                    state_snapshots=snapshots,
                )

        return await asyncio.to_thread(execute)

    async def list_devices(
        self,
        *,
        adapter_id: str | None = None,
        device_type: str | None = None,
        area: str | None = None,
        is_online: bool | None = None,
        is_enabled: bool | None = None,
        keyword: str | None = None,
    ) -> list[RegisteredDevice]:
        def execute() -> list[RegisteredDevice]:
            with self._unit_of_work_factory() as uow:
                assert uow.devices is not None
                projections = uow.devices.list_devices(
                    adapter_id=adapter_id,
                    device_type=device_type,
                    area=area,
                    is_online=is_online,
                    is_enabled=is_enabled,
                    keyword=keyword,
                )
                return [_domain_device(projection) for projection in projections]

        return await asyncio.to_thread(execute)

    async def get_by_id(self, device_id: str) -> RegisteredDevice | None:
        return await self._read(lambda devices: _domain_device(devices.get_by_id(device_id)))

    async def get_by_external_id(
        self,
        adapter_id: str,
        external_id: str,
    ) -> RegisteredDevice | None:
        return await self._read(
            lambda devices: _domain_device(devices.get_by_external_id(adapter_id, external_id))
        )

    async def nova_device_id(self, adapter_id: str, external_id: str) -> str | None:
        def execute(devices: Any) -> str | None:
            projection = devices.get_by_external_id(adapter_id, external_id)
            return projection.id if projection is not None else None

        return await self._read(execute)

    async def latest_state(self, device_id: str) -> RegisteredDeviceState | None:
        def execute(devices: Any) -> RegisteredDeviceState | None:
            snapshot = devices.latest_state(device_id)
            if snapshot is None:
                return None
            return RegisteredDeviceState(
                device_id=snapshot.device_id,
                external_id=snapshot.device.external_id,
                state=snapshot.state,
                attributes=snapshot.attributes,
                raw_state=snapshot.raw_state,
                observed_at=snapshot.observed_at,
            )

        return await self._read(execute)

    async def record_observed_state(
        self,
        device_id: str,
        *,
        state: str,
        attributes: dict[str, Any],
        source: str,
        observed_at: datetime,
    ) -> None:
        def execute() -> None:
            with self._unit_of_work_factory() as uow:
                assert uow.devices is not None
                uow.devices.record_observed_state(
                    device_id,
                    state=state,
                    attributes=attributes,
                    raw_state=None,
                    source=source,
                    observed_at=observed_at,
                )
                uow.commit()

        await asyncio.to_thread(execute)

    async def update_profile(
        self,
        device_id: str,
        *,
        aliases: list[str] | None = None,
        allowed_actions: list[str] | None = None,
        max_risk_level: DeviceRiskLevel | None = None,
        requires_confirmation: bool | None = None,
    ) -> RegisteredDevice:
        def execute() -> RegisteredDevice:
            with self._unit_of_work_factory() as uow:
                assert uow.devices is not None
                projection = uow.devices.update_registry_profile(
                    device_id,
                    aliases=aliases,
                    allowed_actions=allowed_actions,
                    max_risk_level=max_risk_level.value if max_risk_level else None,
                    requires_confirmation=requires_confirmation,
                )
                uow.commit()
                return _domain_device(projection)

        return await asyncio.to_thread(execute)

    async def localize_event(self, event: DeviceEvent, external_id: str) -> DeviceEvent:
        device_id = await self.nova_device_id(event.source, external_id)
        if device_id is None:
            raise KeyError(f"No Nova device projection for {event.source}/{external_id}")
        return event.model_copy(update={"subject_id": device_id})

    async def _read(self, reader: Callable[[Any], Any]) -> Any:
        def execute() -> Any:
            with self._unit_of_work_factory() as uow:
                assert uow.devices is not None
                return reader(uow.devices)

        return await asyncio.to_thread(execute)


def _projection_update(
    adapter: DeviceAdapter,
    device: Device,
    state: DeviceState | None,
) -> DeviceProjectionUpdate:
    entries = [capability.model_dump(mode="json") for capability in device.capabilities]
    profile = {
        "aliases": device.aliases,
        "permissions": device.permissions.model_dump(mode="json"),
    }
    return DeviceProjectionUpdate(
        adapter_id=adapter.adapter_id,
        external_id=device.external_id,
        name=device.name,
        device_type=device.device_type.value,
        area=device.area,
        manufacturer=None,
        model=None,
        is_online=(
            device.is_online if state is None else state.state != DeviceStateName.UNAVAILABLE
        ),
        risk_level=device.risk_level.value,
        capabilities={"entries": entries, "profile": profile},
        metadata_summary=device.metadata,
        last_seen_at=state.observed_at if state is not None else None,
    )


def _domain_device(projection: Any) -> RegisteredDevice:
    if projection is None:
        return None  # type: ignore[return-value]
    summary = projection.capabilities or {}
    entries = summary.get("entries", [])
    profile = summary.get("profile", {})
    permissions = profile.get("permissions", {})
    capabilities = [DeviceCapability.model_validate(entry) for entry in entries]
    return RegisteredDevice(
        id=projection.id,
        adapter_id=projection.adapter_id,
        external_id=projection.external_id,
        name=projection.name,
        device_type=projection.device_type,
        area=projection.area,
        capabilities=capabilities,
        risk_level=projection.risk_level,
        is_online=projection.is_online,
        is_enabled=projection.is_enabled,
        metadata=projection.metadata_summary,
        aliases=profile.get("aliases", []),
        permissions=DevicePermissions.model_validate(permissions),
    )
