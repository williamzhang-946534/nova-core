import asyncio

import pytest

from arvuno_core.devices.errors import (
    ActionFailedError,
    AdapterTimeoutError,
    DeviceUnavailableError,
    DeviceWriteDisabledError,
    StateVerificationFailedError,
)
from arvuno_core.devices.mock import MockDeviceAdapter
from arvuno_core.devices.models import DeviceAction, DeviceEvent, DeviceStateName


def run(coroutine):
    return asyncio.run(coroutine)


def test_mock_adapter_lists_builtins_and_executes_verified_actions() -> None:
    adapter = MockDeviceAdapter()

    devices = run(adapter.get_devices())
    health = run(adapter.health_check())
    result = run(
        adapter.execute_action(
            "mock.light.living_room",
            DeviceAction(action="set_brightness", parameters={"brightness_pct": 72}),
        )
    )
    state = run(adapter.get_state("mock.light.living_room"))

    assert {device.device_type.value for device in devices} >= {
        "light",
        "switch",
        "sensor_temperature",
        "sensor_humidity",
        "sensor_motion",
        "sensor_contact",
    }
    assert health.status == "healthy"
    assert result.success
    assert state.state == DeviceStateName.ON
    assert state.attributes["brightness_pct"] == 72


def test_mock_adapter_simulates_offline_timeout_failure_and_write_gate() -> None:
    adapter = MockDeviceAdapter()
    adapter.set_offline("mock.switch.airer")
    with pytest.raises(DeviceUnavailableError):
        run(adapter.get_state("mock.switch.airer"))

    adapter.set_offline("mock.switch.airer", offline=False)
    adapter.set_timeout("mock.switch.airer")
    with pytest.raises(AdapterTimeoutError):
        run(adapter.get_state("mock.switch.airer"))

    adapter.set_timeout("mock.switch.airer", timeout=False)
    adapter.set_action_failure("mock.switch.airer")
    with pytest.raises(ActionFailedError):
        run(adapter.execute_action("mock.switch.airer", DeviceAction(action="turn_on")))

    adapter.set_action_failure("mock.switch.airer", enabled=False)
    disabled_adapter = MockDeviceAdapter(write_enabled=False)
    with pytest.raises(DeviceWriteDisabledError):
        run(
            disabled_adapter.execute_action(
                "mock.switch.airer",
                DeviceAction(action="turn_on"),
            )
        )


def test_mock_adapter_can_force_state_verification_failure() -> None:
    adapter = MockDeviceAdapter()
    adapter.set_verification_failure("mock.light.living_room")

    with pytest.raises(StateVerificationFailedError):
        run(adapter.execute_action("mock.light.living_room", DeviceAction(action="turn_on")))

    assert run(adapter.get_state("mock.light.living_room")).state == DeviceStateName.OFF


def test_mock_adapter_triggers_subscribed_state_event() -> None:
    adapter = MockDeviceAdapter()
    received: list[DeviceEvent] = []

    async def subscriber(event: DeviceEvent) -> None:
        received.append(event)

    subscription = run(adapter.subscribe_events(subscriber))
    event = run(adapter.trigger_state_change("mock.switch.airer", DeviceStateName.ON))

    assert event.event_type.value == "device_state_changed"
    assert received == [event]
    subscription.close()
    run(adapter.trigger_state_change("mock.switch.airer", DeviceStateName.OFF))
    assert len(received) == 1
