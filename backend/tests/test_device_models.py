from arvuno_core.devices.errors import DeviceWriteDisabledError
from arvuno_core.devices.models import (
    Device,
    DeviceAction,
    DeviceCapability,
    DeviceEvent,
    DeviceEventType,
    DevicePermissions,
    DeviceRiskLevel,
    DeviceState,
    DeviceStateName,
    DeviceType,
)


def test_device_model_normalizes_domain_shape() -> None:
    device = Device(
        external_id="light.living_room",
        name="Living Room Light",
        device_type=DeviceType.LIGHT,
        area="Living Room",
        capabilities=[
            DeviceCapability(
                capability="brightness",
                actions=["set_brightness"],
                parameters={"brightness_pct": {"type": "integer", "minimum": 1, "maximum": 100}},
            )
        ],
        risk_level=DeviceRiskLevel.LOW,
        aliases=["living light"],
        permissions=DevicePermissions(allowed_actions=["set_brightness"]),
    )

    state = DeviceState(
        external_id=device.external_id,
        state=DeviceStateName.UNAVAILABLE,
        raw_state="unavailable",
    )
    event = DeviceEvent(
        event_type=DeviceEventType.DEVICE_UNAVAILABLE,
        source="home_assistant",
        subject_id="arvuno-device-id",
        payload={"previous_state": "on", "current_state": "unavailable"},
    )

    assert device.supported_actions == {DeviceAction(action="set_brightness").action}
    assert state.state == DeviceStateName.UNAVAILABLE
    assert event.model_dump(mode="json")["event_type"] == "device_unavailable"
    assert DeviceWriteDisabledError("disabled").code == "write_disabled"
