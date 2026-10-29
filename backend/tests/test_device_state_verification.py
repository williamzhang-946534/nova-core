import pytest

from arvuno_core.devices.errors import StateVerificationFailedError
from arvuno_core.devices.models import DeviceAction, DeviceState, DeviceStateName
from arvuno_core.devices.verification import DeviceStateVerifier


def test_state_verifier_compares_expected_state_and_action_parameter() -> None:
    verifier = DeviceStateVerifier()
    before = DeviceState(external_id="light.living", state=DeviceStateName.OFF)
    action = DeviceAction(action="set_brightness", parameters={"brightness_pct": 70})
    actual = DeviceState(
        external_id="light.living",
        state=DeviceStateName.ON,
        attributes={"brightness_pct": 70},
    )

    result = verifier.verify(action, before, actual)
    assert result.verified
    assert result.expected_attributes == {"brightness_pct": 70}


def test_state_verifier_reports_structured_failure() -> None:
    verifier = DeviceStateVerifier()
    before = DeviceState(external_id="switch.airer", state=DeviceStateName.OFF)
    action = DeviceAction(action="turn_on")
    actual = DeviceState(external_id="switch.airer", state=DeviceStateName.OFF)

    with pytest.raises(StateVerificationFailedError) as error:
        verifier.verify(action, before, actual)

    assert error.value.code == "state_verification_failed"
    assert "expected=on" in error.value.detail
