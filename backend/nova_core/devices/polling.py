import json
from typing import Protocol

from nova_core.devices.errors import (
    AdapterTimeoutError,
    AdapterUnavailableError,
    DeviceUnavailableError,
)
from nova_core.devices.interface import DeviceAdapter
from nova_core.devices.models import (
    DeviceEvent,
    DeviceEventType,
    DeviceState,
    DeviceStateName,
    DeviceType,
)


class DeviceIdResolver(Protocol):
    async def __call__(self, adapter_id: str, external_id: str) -> str | None: ...


def _attribute_fingerprint(attributes: dict[str, object]) -> str:
    return json.dumps(attributes, sort_keys=True, separators=(",", ":"), default=str)


class DeviceStatePoller:
    """Polls allowlisted entities and emits the unified device event shape."""

    def __init__(
        self,
        adapter: DeviceAdapter,
        external_ids: list[str],
        id_resolver: DeviceIdResolver,
    ) -> None:
        self._adapter = adapter
        self._external_ids = list(dict.fromkeys(external_ids))
        self._id_resolver = id_resolver
        self._previous: dict[str, tuple[DeviceStateName, str]] = {}

    async def poll_once(self) -> list[DeviceEvent]:
        events: list[DeviceEvent] = []
        for external_id in self._external_ids:
            device_id = await self._id_resolver(self._adapter.adapter_id, external_id)
            if device_id is None:
                continue
            try:
                current = await self._adapter.get_state(external_id)
            except (AdapterUnavailableError, AdapterTimeoutError, DeviceUnavailableError):
                previous = self._previous.get(external_id)
                if previous is not None and previous[0] != DeviceStateName.UNAVAILABLE:
                    events.append(
                        DeviceEvent(
                            event_type=DeviceEventType.DEVICE_UNAVAILABLE,
                            source=self._adapter.adapter_id,
                            subject_id=device_id,
                            payload={
                                "previous_state": previous[0].value,
                                "current_state": DeviceStateName.UNAVAILABLE.value,
                                "attributes": {},
                            },
                        )
                    )
                    self._previous[external_id] = (
                        DeviceStateName.UNAVAILABLE,
                        _attribute_fingerprint({}),
                    )
                continue

            fingerprint = _attribute_fingerprint(current.attributes)
            previous = self._previous.get(external_id)
            self._previous[external_id] = (current.state, fingerprint)
            if previous is None:
                continue

            if current.state == DeviceStateName.UNAVAILABLE:
                if previous[0] != DeviceStateName.UNAVAILABLE:
                    events.append(
                        self._event(
                            DeviceEventType.DEVICE_UNAVAILABLE,
                            device_id,
                            previous,
                            current,
                            self._adapter.adapter_id,
                        )
                    )
                continue
            if current.state != previous[0]:
                events.append(
                    self._event(
                        DeviceEventType.STATE_CHANGED,
                        device_id,
                        previous,
                        current,
                        self._adapter.adapter_id,
                    )
                )
                continue
            if fingerprint != previous[1] and await self._is_sensor(external_id):
                events.append(
                    self._event(
                        DeviceEventType.SENSOR_UPDATED,
                        device_id,
                        previous,
                        current,
                        self._adapter.adapter_id,
                    )
                )
        return events

    async def _is_sensor(self, external_id: str) -> bool:
        device = await self._adapter.get_device(external_id)
        return device.device_type in {
            DeviceType.SENSOR_TEMPERATURE,
            DeviceType.SENSOR_HUMIDITY,
            DeviceType.SENSOR_MOTION,
            DeviceType.SENSOR_CONTACT,
        }

    @staticmethod
    def _event(
        event_type: DeviceEventType,
        device_id: str,
        previous: tuple[DeviceStateName, str],
        current: DeviceState,
        source: str,
    ) -> DeviceEvent:
        return DeviceEvent(
            event_type=event_type,
            source=source,
            subject_id=device_id,
            payload={
                "previous_state": previous[0].value,
                "current_state": current.state.value,
                "attributes": current.attributes,
            },
            occurred_at=current.observed_at,
        )
