import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from arvuno_core.devices.errors import (
    ActionFailedError,
    ActionUnsupportedError,
    AdapterTimeoutError,
    DeviceNotFoundError,
    DeviceUnavailableError,
    DeviceWriteDisabledError,
    InvalidActionParameterError,
)
from arvuno_core.devices.interface import DeviceEventSubscriber, SubscriptionHandle
from arvuno_core.devices.models import (
    ActionResult,
    AdapterHealth,
    Device,
    DeviceAction,
    DeviceActionName,
    DeviceCapability,
    DeviceEvent,
    DeviceEventType,
    DevicePermissions,
    DeviceRiskLevel,
    DeviceState,
    DeviceStateName,
    DeviceType,
    utc_now,
)
from arvuno_core.devices.verification import DeviceStateVerifier


@dataclass
class _MockDevice:
    definition: Device
    state: DeviceStateName
    attributes: dict[str, Any] = field(default_factory=dict)
    offline: bool = False
    timeout: bool = False
    action_failure: bool = False
    verification_failure: bool = False


class MockDeviceAdapter:
    """Deterministic adapter for local development and automated tests."""

    adapter_id = "mock"
    version = "1.0.0"

    def __init__(
        self,
        *,
        clock: Callable[[], Any] = utc_now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        write_enabled: bool = True,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._write_enabled = write_enabled
        self._verifier = DeviceStateVerifier()
        self._devices: dict[str, _MockDevice] = {
            device.definition.external_id: device for device in _default_devices()
        }
        self._subscribers: dict[int, DeviceEventSubscriber] = {}
        self._next_subscription_id = 1

    async def health_check(self) -> AdapterHealth:
        offline = [device for device in self._devices.values() if device.offline]
        return AdapterHealth(
            status="degraded" if offline else "healthy",
            adapter_id=self.adapter_id,
            detail=f"{len(offline)} mock device(s) are offline.",
            checked_at=self._clock(),
        )

    async def get_devices(self) -> list[Device]:
        return [self._device_projection(item) for item in self._devices.values()]

    async def get_device(self, external_id: str) -> Device:
        return self._device_projection(self._require(external_id))

    async def get_state(self, external_id: str) -> DeviceState:
        item = self._require(external_id)
        self._raise_for_simulated_failure(item)
        return self._state(item)

    async def execute_action(self, external_id: str, action: DeviceAction) -> ActionResult:
        item = self._require(external_id)
        self._validate_action(item.definition, action)
        self._raise_for_simulated_failure(item)
        if item.offline or item.definition.is_online is False:
            raise DeviceUnavailableError("The mock device is offline.")
        if action.action == DeviceActionName.READ_STATE:
            return ActionResult(
                success=True,
                action_id=action.action_id,
                external_id=external_id,
                message="Mock device state was read.",
            )
        if not self._write_enabled:
            raise DeviceWriteDisabledError("Mock device write operations are disabled.")
        if item.action_failure:
            raise ActionFailedError("The mock device was configured to fail this action.")

        before = self._state(item)
        if not item.verification_failure:
            self._apply_action(item, action)
        actual = self._state(item)
        self._verifier.verify(action, before, actual)
        return ActionResult(
            success=True,
            action_id=action.action_id,
            external_id=external_id,
            message="The mock action completed and state was verified.",
        )

    async def subscribe_events(self, subscriber: DeviceEventSubscriber) -> SubscriptionHandle:
        subscription_id = self._next_subscription_id
        self._next_subscription_id += 1
        self._subscribers[subscription_id] = subscriber
        return SubscriptionHandle(lambda: self._subscribers.pop(subscription_id, None))

    def set_offline(self, external_id: str, *, offline: bool = True) -> None:
        self._require(external_id).offline = offline

    def set_timeout(self, external_id: str, *, timeout: bool = True) -> None:
        self._require(external_id).timeout = timeout

    def set_action_failure(self, external_id: str, *, enabled: bool = True) -> None:
        self._require(external_id).action_failure = enabled

    def set_verification_failure(self, external_id: str, *, enabled: bool = True) -> None:
        self._require(external_id).verification_failure = enabled

    async def set_state(
        self,
        external_id: str,
        state: DeviceStateName,
        *,
        attributes: dict[str, Any] | None = None,
    ) -> DeviceEvent:
        item = self._require(external_id)
        previous = self._state(item)
        item.state = state
        item.attributes = dict(attributes or {})
        current = self._state(item)
        return await self._emit_state_change(item, previous, current)

    async def trigger_state_change(
        self,
        external_id: str,
        state: DeviceStateName,
        *,
        attributes: dict[str, Any] | None = None,
    ) -> DeviceEvent:
        return await self.set_state(external_id, state, attributes=attributes)

    async def _emit_state_change(
        self,
        item: _MockDevice,
        previous: DeviceState,
        current: DeviceState,
    ) -> DeviceEvent:
        event_type = DeviceEventType.STATE_CHANGED
        if current.state == DeviceStateName.UNAVAILABLE:
            event_type = DeviceEventType.DEVICE_UNAVAILABLE
        elif item.definition.device_type in {
            DeviceType.SENSOR_TEMPERATURE,
            DeviceType.SENSOR_HUMIDITY,
            DeviceType.SENSOR_MOTION,
            DeviceType.SENSOR_CONTACT,
        }:
            event_type = DeviceEventType.SENSOR_UPDATED
        event = DeviceEvent(
            id=str(uuid4()),
            event_type=event_type,
            source=self.adapter_id,
            subject_id=item.definition.external_id,
            external_id=item.definition.external_id,
            payload={
                "previous_state": previous.state.value,
                "current_state": current.state.value,
                "previous_attributes": previous.attributes,
                "attributes": current.attributes,
            },
            occurred_at=self._clock(),
        )
        for subscriber in list(self._subscribers.values()):
            await subscriber(event)
        return event

    def _require(self, external_id: str) -> _MockDevice:
        item = self._devices.get(external_id)
        if item is None:
            raise DeviceNotFoundError("The mock device does not exist.")
        return item

    def _raise_for_simulated_failure(self, item: _MockDevice) -> None:
        if item.timeout:
            raise AdapterTimeoutError("The mock device request timed out.")
        if item.offline:
            raise DeviceUnavailableError("The mock device is offline.")

    def _device_projection(self, item: _MockDevice) -> Device:
        return item.definition.model_copy(update={"is_online": not item.offline})

    def _state(self, item: _MockDevice) -> DeviceState:
        if item.offline:
            state = DeviceStateName.UNAVAILABLE
            raw_state = "offline"
        else:
            state = item.state
            raw_state = state.value
        return DeviceState(
            external_id=item.definition.external_id,
            state=state,
            attributes=dict(item.attributes),
            raw_state=raw_state,
            observed_at=self._clock(),
        )

    def _validate_action(self, device: Device, action: DeviceAction) -> None:
        if action.action not in device.supported_actions:
            raise ActionUnsupportedError("The mock device does not support this action.")
        if action.action == DeviceActionName.SET_BRIGHTNESS:
            value = action.parameters.get("brightness_pct")
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
                raise InvalidActionParameterError(
                    "brightness_pct must be an integer from 1 to 100."
                )
        if action.action == DeviceActionName.SET_TEMPERATURE:
            value = action.parameters.get("temperature")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise InvalidActionParameterError("temperature must be a number.")
            if not 7 <= float(value) <= 35:
                raise InvalidActionParameterError("temperature must be between 7 and 35.")

    def _apply_action(self, item: _MockDevice, action: DeviceAction) -> None:
        if action.action == DeviceActionName.TURN_ON:
            item.state = DeviceStateName.ON
        elif action.action == DeviceActionName.TURN_OFF:
            item.state = DeviceStateName.OFF
        elif action.action == DeviceActionName.TOGGLE:
            item.state = (
                DeviceStateName.OFF if item.state == DeviceStateName.ON else DeviceStateName.ON
            )
        elif action.action == DeviceActionName.SET_BRIGHTNESS:
            item.state = DeviceStateName.ON
            item.attributes["brightness_pct"] = action.parameters["brightness_pct"]
        elif action.action == DeviceActionName.SET_TEMPERATURE:
            item.attributes["temperature"] = action.parameters["temperature"]


def _default_devices() -> list[_MockDevice]:
    return [
        _MockDevice(
            definition=_device(
                external_id="mock.light.living_room",
                name="Virtual Living Room Light",
                device_type=DeviceType.LIGHT,
                area="Living Room",
                actions=[
                    DeviceActionName.TURN_ON,
                    DeviceActionName.TURN_OFF,
                    DeviceActionName.TOGGLE,
                    DeviceActionName.SET_BRIGHTNESS,
                ],
                parameters={"brightness_pct": {"type": "integer", "minimum": 1, "maximum": 100}},
                aliases=["living light"],
            ),
            state=DeviceStateName.OFF,
            attributes={"brightness_pct": 0},
        ),
        _MockDevice(
            definition=_device(
                external_id="mock.switch.airer",
                name="Virtual Switch",
                device_type=DeviceType.SWITCH,
                area="Balcony",
                actions=[
                    DeviceActionName.TURN_ON,
                    DeviceActionName.TURN_OFF,
                    DeviceActionName.TOGGLE,
                ],
            ),
            state=DeviceStateName.OFF,
        ),
        _MockDevice(
            definition=_device(
                external_id="mock.sensor.temperature",
                name="Virtual Temperature Sensor",
                device_type=DeviceType.SENSOR_TEMPERATURE,
                area="Living Room",
                actions=[DeviceActionName.READ_STATE],
            ),
            state=DeviceStateName.UNKNOWN,
            attributes={"temperature": 24.5, "unit_of_measurement": "C"},
        ),
        _MockDevice(
            definition=_device(
                external_id="mock.sensor.humidity",
                name="Virtual Humidity Sensor",
                device_type=DeviceType.SENSOR_HUMIDITY,
                area="Living Room",
                actions=[DeviceActionName.READ_STATE],
            ),
            state=DeviceStateName.UNKNOWN,
            attributes={"humidity": 55, "unit_of_measurement": "%"},
        ),
        _MockDevice(
            definition=_device(
                external_id="mock.sensor.motion",
                name="Virtual Motion Sensor",
                device_type=DeviceType.SENSOR_MOTION,
                area="Hallway",
                actions=[DeviceActionName.READ_STATE],
            ),
            state=DeviceStateName.CLEAR,
        ),
        _MockDevice(
            definition=_device(
                external_id="mock.sensor.contact",
                name="Virtual Contact Sensor",
                device_type=DeviceType.SENSOR_CONTACT,
                area="Entrance",
                actions=[DeviceActionName.READ_STATE],
            ),
            state=DeviceStateName.CLOSED,
        ),
    ]


def _device(
    *,
    external_id: str,
    name: str,
    device_type: DeviceType,
    area: str,
    actions: list[DeviceActionName],
    parameters: dict[str, Any] | None = None,
    aliases: list[str] | None = None,
) -> Device:
    capabilities = [
        DeviceCapability(
            capability="control"
            if device_type in {DeviceType.LIGHT, DeviceType.SWITCH}
            else "measurement",
            actions=actions,
            parameters=parameters or {},
            risk_level=DeviceRiskLevel.LOW,
        )
    ]
    return Device(
        external_id=external_id,
        name=name,
        device_type=device_type,
        area=area,
        capabilities=capabilities,
        risk_level=DeviceRiskLevel.LOW,
        metadata={"virtual": True},
        aliases=aliases or [],
        permissions=DevicePermissions(
            allowed_actions=actions,
            max_risk_level=DeviceRiskLevel.LOW,
        ),
    )
