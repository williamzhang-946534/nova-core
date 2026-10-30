import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from arvuno_core.devices.registry import DeviceRegistry
from arvuno_core.events.models import (
    ArvunoEvent,
    ArvunoEventType,
    DeviceStateChangedPayload,
    DeviceUnavailablePayload,
    SensorUpdatedPayload,
    utc_now,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]


class DeviceContextState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    name: str
    device_type: str
    area: str | None = None
    state: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class SensorContextState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    sensor_type: str
    value: float | int | bool | str
    unit: str | None = None
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class EnvironmentStateSink(Protocol):
    """Narrow write port used after a verified device action."""

    async def apply_verified_state(
        self,
        device_id: str,
        *,
        state: str,
        attributes: dict[str, Any],
        observed_at: datetime,
    ) -> None: ...


class EnvironmentContextState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str | None = None
    environment_name: str = "home"
    devices: dict[str, DeviceContextState] = Field(default_factory=dict)
    sensors: dict[str, SensorContextState] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("updated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @property
    def unavailable_device_ids(self) -> list[str]:
        return [
            device_id for device_id, state in self.devices.items() if state.state == "unavailable"
        ]

    @property
    def anomaly_count(self) -> int:
        return len(self.unavailable_device_ids)


class EnvironmentContextService:
    """Keeps a concise current-state summary and persists observation snapshots."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        registry: DeviceRegistry | None = None,
        environment_name: str = "home",
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._registry = registry
        self._environment_name = environment_name
        self._state = EnvironmentContextState(environment_name=environment_name)
        self._lock = asyncio.Lock()

    @property
    def state(self) -> EnvironmentContextState:
        return self._state.model_copy(deep=True)

    async def initialize(self) -> None:
        def execute() -> tuple[str, dict[str, Any], datetime | None]:
            with self._unit_of_work_factory() as unit_of_work:
                if unit_of_work.environments is None:
                    raise RuntimeError("The environment repository is not available.")
                environment = unit_of_work.environments.ensure_default(self._environment_name)
                snapshot = unit_of_work.environments.latest_snapshot(environment.id)
                unit_of_work.commit()
                if snapshot is None:
                    return environment.id, {}, None
                return environment.id, snapshot.context, snapshot.created_at

        environment_id, context, created_at = await asyncio.to_thread(execute)
        async with self._lock:
            self._state = EnvironmentContextState.model_validate(
                {
                    **context,
                    "environment_id": environment_id,
                    "environment_name": self._environment_name,
                    "updated_at": created_at or utc_now(),
                }
            )

    async def synchronize_with_registry(self) -> None:
        """Project the authoritative device registry into the environment view."""
        if self._registry is None:
            return
        projected: dict[str, DeviceContextState] = {}
        for device in await self._registry.list_devices(is_enabled=True):
            latest = await self._registry.latest_state(device.id)
            if latest is None:
                continue
            projected[device.id] = DeviceContextState(
                device_id=device.id,
                name=device.name,
                device_type=device.device_type.value,
                area=device.area,
                state=latest.state.value,
                attributes=latest.attributes or {},
                updated_at=latest.observed_at,
            )

        async with self._lock:
            merged: dict[str, DeviceContextState] = {}
            changed = set(projected) != set(self._state.devices)
            for device_id, candidate in projected.items():
                current = self._state.devices.get(device_id)
                if current is None or not _same_device_state(current, candidate):
                    merged[device_id] = candidate
                    changed = True
                else:
                    merged[device_id] = current
            sensors = {
                device_id: sensor
                for device_id, sensor in self._state.sensors.items()
                if device_id in merged
            }
            if sensors != self._state.sensors:
                changed = True
            if not changed:
                return
            self._state.devices = merged
            self._state.sensors = sensors
            self._state.updated_at = utc_now()
            state = self.state

        await asyncio.to_thread(self._save_snapshot, state)

    async def apply_verified_state(
        self,
        device_id: str,
        *,
        state: str,
        attributes: dict[str, Any],
        observed_at: datetime,
    ) -> None:
        """Reflect a state that a device adapter confirmed after an Arvuno action."""
        if self._registry is None:
            return
        device = await self._registry.get_by_id(device_id)
        if device is None or not device.is_enabled:
            return
        observed = utc_timestamp(observed_at)

        async with self._lock:
            current = self._state.devices.get(device_id)
            if current is not None and current.state == state and current.attributes == attributes:
                return
            self._state.devices[device_id] = DeviceContextState(
                device_id=device_id,
                name=device.name,
                device_type=device.device_type.value,
                area=device.area,
                state=state,
                attributes=dict(attributes),
                updated_at=observed,
            )
            self._state.updated_at = observed
            snapshot = self.state

        await asyncio.to_thread(self._save_snapshot, snapshot)

    async def handle_event(self, event: ArvunoEvent) -> None:
        if event.event_type not in {
            ArvunoEventType.DEVICE_STATE_CHANGED,
            ArvunoEventType.SENSOR_UPDATED,
            ArvunoEventType.DEVICE_UNAVAILABLE,
        }:
            return
        registered = None
        if self._registry is not None and event.subject_id is not None:
            registered = await self._registry.get_by_id(event.subject_id)

        async with self._lock:
            if isinstance(event.payload, DeviceStateChangedPayload):
                self._apply_device_change(event, event.payload, registered)
            elif isinstance(event.payload, SensorUpdatedPayload):
                self._apply_sensor_change(event, event.payload, registered)
            elif isinstance(event.payload, DeviceUnavailablePayload):
                self._apply_unavailable(event, event.payload, registered)
            state = self.state

        await asyncio.to_thread(self._save_snapshot, state)

    def _apply_device_change(
        self,
        event: ArvunoEvent,
        payload: DeviceStateChangedPayload,
        registered: Any,
    ) -> None:
        existing = self._state.devices.get(payload.device_id)
        self._state.devices[payload.device_id] = DeviceContextState(
            device_id=payload.device_id,
            name=getattr(registered, "name", existing.name if existing else payload.device_id),
            device_type=_device_type(registered, existing),
            area=getattr(registered, "area", existing.area if existing else None),
            state=payload.current_state,
            attributes=payload.attributes,
            updated_at=event.occurred_at,
        )
        self._state.updated_at = event.occurred_at

    def _apply_sensor_change(
        self,
        event: ArvunoEvent,
        payload: SensorUpdatedPayload,
        registered: Any,
    ) -> None:
        existing = self._state.devices.get(payload.device_id)
        self._state.sensors[payload.device_id] = SensorContextState(
            device_id=payload.device_id,
            sensor_type=payload.sensor_type,
            value=payload.value,
            unit=payload.unit,
            updated_at=event.occurred_at,
        )
        self._state.devices[payload.device_id] = DeviceContextState(
            device_id=payload.device_id,
            name=getattr(registered, "name", existing.name if existing else payload.device_id),
            device_type=_device_type(registered, existing, f"sensor_{payload.sensor_type}"),
            area=getattr(registered, "area", existing.area if existing else None),
            state=str(payload.value),
            attributes=existing.attributes if existing is not None else {},
            updated_at=event.occurred_at,
        )
        self._state.updated_at = event.occurred_at

    def _apply_unavailable(
        self,
        event: ArvunoEvent,
        payload: DeviceUnavailablePayload,
        registered: Any,
    ) -> None:
        existing = self._state.devices.get(payload.device_id)
        self._state.devices[payload.device_id] = DeviceContextState(
            device_id=payload.device_id,
            name=getattr(registered, "name", existing.name if existing else payload.device_id),
            device_type=_device_type(registered, existing),
            area=getattr(registered, "area", existing.area if existing else None),
            state="unavailable",
            attributes={},
            updated_at=event.occurred_at,
        )
        self._state.updated_at = event.occurred_at

    def _save_snapshot(self, state: EnvironmentContextState) -> None:
        if state.environment_id is None:
            return
        with self._unit_of_work_factory() as unit_of_work:
            if unit_of_work.environments is None:
                raise RuntimeError("The environment repository is not available.")
            unit_of_work.environments.add_snapshot(
                state.environment_id,
                context=state.model_dump(mode="json"),
                active_task_ids=[],
                anomaly_count=state.anomaly_count,
            )
            unit_of_work.commit()


def area_summary(state: EnvironmentContextState) -> dict[str, dict[str, int | list[str]]]:
    areas: dict[str, list[DeviceContextState]] = {}
    for device in state.devices.values():
        area_name = device.area or "Unassigned"
        areas.setdefault(area_name, []).append(device)
    return {
        area_name: {
            "device_count": len(devices),
            "online_device_count": sum(device.state != "unavailable" for device in devices),
            "unavailable_device_ids": [
                device.device_id for device in devices if device.state == "unavailable"
            ],
        }
        for area_name, devices in areas.items()
    }


def _same_device_state(
    current: DeviceContextState,
    candidate: DeviceContextState,
) -> bool:
    return (
        current.name == candidate.name
        and current.device_type == candidate.device_type
        and current.area == candidate.area
        and current.state == candidate.state
        and current.attributes == candidate.attributes
    )


def _device_type(
    registered: Any, existing: DeviceContextState | None, default: str = "unknown"
) -> str:
    if registered is not None:
        return registered.device_type.value
    if existing is not None:
        return existing.device_type
    return default


def utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
