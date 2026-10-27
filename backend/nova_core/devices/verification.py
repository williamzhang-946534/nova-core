from dataclasses import dataclass
from typing import Any

from nova_core.devices.errors import StateVerificationFailedError
from nova_core.devices.models import (
    DeviceAction,
    DeviceActionName,
    DeviceState,
    DeviceStateName,
)


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    expected_state: DeviceStateName
    actual_state: DeviceStateName
    expected_attributes: dict[str, Any]
    actual_attributes: dict[str, Any]


class DeviceStateVerifier:
    """Validates the normalized state produced by a low-risk action."""

    def expected(
        self, action: DeviceAction, before: DeviceState
    ) -> tuple[DeviceStateName, dict[str, Any]]:
        if action.action == DeviceActionName.TURN_ON:
            return DeviceStateName.ON, {}
        if action.action == DeviceActionName.TURN_OFF:
            return DeviceStateName.OFF, {}
        if action.action == DeviceActionName.TOGGLE:
            expected = (
                DeviceStateName.OFF if before.state == DeviceStateName.ON else DeviceStateName.ON
            )
            return expected, {}
        if action.action == DeviceActionName.SET_BRIGHTNESS:
            brightness = action.parameters["brightness_pct"]
            return DeviceStateName.ON, {"brightness_pct": brightness}
        if action.action == DeviceActionName.SET_TEMPERATURE:
            return before.state, {"temperature": action.parameters["temperature"]}
        return before.state, {}

    def verify(
        self,
        action: DeviceAction,
        before: DeviceState,
        actual: DeviceState,
        *,
        required_state: DeviceStateName | None = None,
    ) -> VerificationResult:
        expected_state, expected_attributes = self.expected(action, before)
        if required_state is not None:
            expected_state = required_state
        verified = actual.state == expected_state
        for key, value in expected_attributes.items():
            verified = verified and actual.attributes.get(key) == value
        result = VerificationResult(
            verified=verified,
            expected_state=expected_state,
            actual_state=actual.state,
            expected_attributes=expected_attributes,
            actual_attributes=actual.attributes,
        )
        if not verified:
            raise StateVerificationFailedError(
                "The device did not reach its expected state.",
                detail=(
                    f"expected={expected_state.value}"
                    f"{expected_attributes or ''}; actual={actual.state.value}"
                    f"{actual.attributes or ''}"
                ),
            )
        return result
