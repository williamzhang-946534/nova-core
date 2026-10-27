import asyncio

from nova_core.devices.mock import MockDeviceAdapter
from nova_core.devices.models import DeviceStateName
from nova_core.devices.polling import DeviceStatePoller


def test_poller_suppresses_initial_state_and_emits_normalized_changes() -> None:
    adapter = MockDeviceAdapter()
    resolver_calls: list[tuple[str, str]] = []

    async def resolver(adapter_id: str, external_id: str) -> str:
        resolver_calls.append((adapter_id, external_id))
        return f"nova-{external_id}"

    poller = DeviceStatePoller(
        adapter,
        ["mock.switch.airer", "mock.sensor.temperature"],
        resolver,
    )
    assert asyncio.run(poller.poll_once()) == []
    assert resolver_calls == [
        ("mock", "mock.switch.airer"),
        ("mock", "mock.sensor.temperature"),
    ]

    asyncio.run(adapter.set_state("mock.switch.airer", DeviceStateName.ON))
    events = asyncio.run(poller.poll_once())
    assert [event.event_type.value for event in events] == ["device_state_changed"]
    assert events[0].source == "mock"
    assert events[0].subject_id == "nova-mock.switch.airer"
    assert events[0].payload == {
        "previous_state": "off",
        "current_state": "on",
        "attributes": {},
    }

    assert asyncio.run(poller.poll_once()) == []


def test_poller_emits_unavailable_for_offline_device() -> None:
    adapter = MockDeviceAdapter()

    async def resolver(_adapter_id: str, _external_id: str) -> str:
        return "nova-device"

    poller = DeviceStatePoller(adapter, ["mock.switch.airer"], resolver)
    asyncio.run(poller.poll_once())
    adapter.set_offline("mock.switch.airer")
    events = asyncio.run(poller.poll_once())

    assert [event.event_type.value for event in events] == ["device_unavailable"]
    assert events[0].payload["current_state"] == "unavailable"
