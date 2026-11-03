from collections.abc import Iterator
from typing import Any

from arvuno_core.devices.models import DeviceState, DeviceStateName, DeviceType
from arvuno_core.observations.models import ObservationInput


def map_device_state_to_observations(
    *,
    adapter_id: str,
    state: DeviceState,
    entity_id: str,
    device_type: str,
    batch_id: str,
    received_at: object,
    correlation_id: str | None = None,
) -> list[ObservationInput]:
    """Map one adapter state using the controlled ARS-02 attribute vocabulary."""
    common = {
        "adapter_id": adapter_id,
        "device_external_id": state.external_id,
        "entity_id": entity_id,
        "received_at": received_at,
        "correlation_id": correlation_id,
        "poll_window": f"{batch_id}:{state.external_id}",
    }
    observations = [
        ObservationInput.model_validate(
            {
                **common,
                "attribute": "device_availability",
                "raw_value": _availability(state.state),
                "raw_unit": None,
                "observed_at": _observed_at(state),
                "observed_at_source": _time_source(state),
                "observed_at_uncertainty_ms": _time_uncertainty_ms(state),
            }
        )
    ]
    observations.extend(_device_attributes(state, device_type, common))
    if _is_actuator(device_type, state):
        observations.append(
            ObservationInput.model_validate(
                {
                    **common,
                    "attribute": "actuator_state",
                    "raw_value": _actuator_value(state),
                    "raw_unit": None,
                    "observed_at": _observed_at(state),
                    "observed_at_source": _time_source(state),
                    "observed_at_uncertainty_ms": _time_uncertainty_ms(state),
                }
            )
        )
    return observations


def _device_attributes(
    state: DeviceState,
    device_type: str,
    common: dict[str, Any],
) -> Iterator[ObservationInput]:
    unit = str(state.attributes.get("unit_of_measurement") or "")
    device_class = str(state.attributes.get("device_class") or "").lower()

    numeric_attributes: list[tuple[str, str]] = []
    if "temperature" in state.attributes:
        numeric_attributes.append(("temperature", unit))
    if "humidity" in state.attributes:
        numeric_attributes.append(("humidity", unit))
    for keys, attribute, fallback_unit in (
        (("illumination", "illuminance", "lux"), "illumination", "lux"),
        (("co2", "carbon_dioxide"), "co2", "ppm"),
    ):
        if any(key in state.attributes for key in keys):
            numeric_attributes.append((attribute, unit or fallback_unit))

    for attribute, raw_unit in numeric_attributes:
        raw_value = state.attributes.get("temperature" if attribute == "temperature" else attribute)
        if attribute == "illumination":
            raw_value = next(
                (
                    state.attributes[key]
                    for key in ("illumination", "illuminance", "lux")
                    if key in state.attributes
                ),
                None,
            )
        elif attribute == "co2":
            raw_value = next(
                (
                    state.attributes[key]
                    for key in ("co2", "carbon_dioxide")
                    if key in state.attributes
                ),
                None,
            )
        yield ObservationInput.model_validate(
            {
                **common,
                "attribute": attribute,
                "raw_value": raw_value,
                "raw_unit": raw_unit,
                "observed_at": _observed_at(state),
                "observed_at_source": _time_source(state),
                "observed_at_uncertainty_ms": _time_uncertainty_ms(state),
            }
        )

    if device_class in {"occupancy", "presence"}:
        yield _enum_observation(common, state, "occupancy", _occupancy(state.state))
    elif device_type in {DeviceType.SENSOR_MOTION.value, "sensor_motion"}:
        yield _enum_observation(common, state, "motion", state.state.value)
    elif device_type in {DeviceType.SENSOR_CONTACT.value, "sensor_contact"}:
        yield _enum_observation(common, state, "contact", state.state.value)
    elif (
        device_type == DeviceType.SENSOR_TEMPERATURE.value and "temperature" not in state.attributes
    ):
        yield _measurement_from_raw_state(common, state, "temperature", unit)
    elif device_type == DeviceType.SENSOR_HUMIDITY.value and "humidity" not in state.attributes:
        yield _measurement_from_raw_state(common, state, "humidity", unit)


def _enum_observation(
    common: dict[str, Any],
    state: DeviceState,
    attribute: str,
    raw_value: object,
) -> ObservationInput:
    return ObservationInput.model_validate(
        {
            **common,
            "attribute": attribute,
            "raw_value": raw_value,
            "raw_unit": None,
            "observed_at": _observed_at(state),
            "observed_at_source": _time_source(state),
            "observed_at_uncertainty_ms": _time_uncertainty_ms(state),
        }
    )


def _measurement_from_raw_state(
    common: dict[str, Any],
    state: DeviceState,
    attribute: str,
    raw_unit: str,
) -> ObservationInput:
    return ObservationInput.model_validate(
        {
            **common,
            "attribute": attribute,
            "raw_value": state.raw_state,
            "raw_unit": raw_unit,
            "observed_at": _observed_at(state),
            "observed_at_source": _time_source(state),
            "observed_at_uncertainty_ms": _time_uncertainty_ms(state),
        }
    )


def _availability(state: DeviceStateName) -> str:
    if state == DeviceStateName.UNAVAILABLE:
        return "offline"
    if state == DeviceStateName.UNKNOWN:
        return "unknown"
    return "online"


def _occupancy(state: DeviceStateName) -> str:
    if state in {DeviceStateName.ON, DeviceStateName.DETECTED, DeviceStateName.OPEN}:
        return "occupied"
    if state in {DeviceStateName.OFF, DeviceStateName.CLEAR, DeviceStateName.CLOSED}:
        return "unoccupied"
    return "unknown"


def _actuator_value(state: DeviceState) -> dict[str, Any]:
    selected_keys = {
        "brightness_pct",
        "current_temperature",
        "temperature",
        "humidity",
        "fan_mode",
        "hvac_mode",
        "media_title",
        "volume_level",
    }
    return {
        "state": state.state.value,
        "raw_state": state.raw_state,
        "attributes": {
            key: value for key, value in state.attributes.items() if key in selected_keys
        },
    }


def _is_actuator(device_type: str, state: DeviceState) -> bool:
    if device_type in {
        DeviceType.LIGHT.value,
        DeviceType.SWITCH.value,
        DeviceType.CLIMATE.value,
        DeviceType.MEDIA_PLAYER.value,
    }:
        return True
    return state.external_id.split(".", 1)[0] in {"light", "switch", "climate", "media_player"}


def _observed_at(state: DeviceState) -> object:
    if state.observed_at_source in {"device_clock", "gateway_state_clock"}:
        return state.observed_at
    return None


def _time_source(state: DeviceState) -> str:
    return state.observed_at_source


def _time_uncertainty_ms(state: DeviceState) -> int | None:
    if state.observed_at_source == "gateway_state_clock":
        return 1000
    if state.observed_at_source == "device_clock":
        return 0
    return None


__all__ = ["map_device_state_to_observations"]
