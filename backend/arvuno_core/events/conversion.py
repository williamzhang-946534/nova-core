from typing import Any

from arvuno_core.devices.models import DeviceEvent, DeviceType
from arvuno_core.events.models import (
    ArvunoEvent,
    ArvunoEventSource,
    ArvunoEventType,
    DeviceStateChangedPayload,
    DeviceUnavailablePayload,
    SensorUpdatedPayload,
)


def device_event_to_arvuno_event(
    event: DeviceEvent,
    *,
    device_id: str,
    device_type: DeviceType,
) -> ArvunoEvent:
    payload = event.payload
    current_state = str(payload.get("current_state", ""))
    attributes = _dict(payload.get("attributes"))
    previous_attributes = _dict(payload.get("previous_attributes"))
    source = _source(event.source)

    if event.event_type.value == ArvunoEventType.DEVICE_STATE_CHANGED:
        normalized_payload = DeviceStateChangedPayload(
            device_id=device_id,
            previous_state=str(payload.get("previous_state", "")),
            current_state=current_state,
            attributes=attributes,
        )
    elif event.event_type.value == ArvunoEventType.SENSOR_UPDATED:
        sensor_type, value, previous_value, unit = _sensor_values(
            device_type,
            current_state,
            str(payload.get("previous_state", "")),
            attributes,
            previous_attributes,
        )
        normalized_payload = SensorUpdatedPayload(
            device_id=device_id,
            sensor_type=sensor_type,
            value=value,
            unit=unit,
            previous_value=previous_value,
        )
    else:
        normalized_payload = DeviceUnavailablePayload(
            device_id=device_id,
            reason=str(payload.get("reason") or "The device became unavailable."),
            observed_state=current_state or "unavailable",
        )

    return ArvunoEvent(
        id=event.id,
        event_type=ArvunoEventType(event.event_type.value),
        source=source,
        subject_type="device",
        subject_id=device_id,
        payload=normalized_payload,
        correlation_id=event.correlation_id,
        occurred_at=event.occurred_at,
    )


def _source(source: str) -> ArvunoEventSource:
    if source == "mock":
        return ArvunoEventSource.MOCK_ADAPTER
    return ArvunoEventSource(source)


def _sensor_values(
    device_type: DeviceType,
    current_state: str,
    previous_state: str,
    attributes: dict[str, Any],
    previous_attributes: dict[str, Any],
) -> tuple[str, Any, Any, str | None]:
    unit = attributes.get("unit_of_measurement")
    unit_value = str(unit) if unit is not None else None
    if device_type == DeviceType.SENSOR_TEMPERATURE:
        return (
            "temperature",
            attributes.get("temperature", current_state),
            previous_attributes.get("temperature", previous_state),
            unit_value,
        )
    if device_type == DeviceType.SENSOR_HUMIDITY:
        return (
            "humidity",
            attributes.get("humidity", current_state),
            previous_attributes.get("humidity", previous_state),
            unit_value,
        )
    if device_type == DeviceType.SENSOR_MOTION:
        return "motion", current_state, previous_state, unit_value
    if device_type == DeviceType.SENSOR_CONTACT:
        return "contact", current_state, previous_state, unit_value
    raise ValueError(f"Device type {device_type.value} is not a sensor")


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
