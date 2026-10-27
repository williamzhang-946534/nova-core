from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class DeviceType(StrEnum):
    LIGHT = "light"
    SWITCH = "switch"
    SENSOR_TEMPERATURE = "sensor_temperature"
    SENSOR_HUMIDITY = "sensor_humidity"
    SENSOR_MOTION = "sensor_motion"
    SENSOR_CONTACT = "sensor_contact"
    CLIMATE = "climate"
    MEDIA_PLAYER = "media_player"
    UNKNOWN = "unknown"


class DeviceStateName(StrEnum):
    ON = "on"
    OFF = "off"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    OPEN = "open"
    CLOSED = "closed"
    DETECTED = "detected"
    CLEAR = "clear"


class DeviceActionName(StrEnum):
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    TOGGLE = "toggle"
    SET_BRIGHTNESS = "set_brightness"
    SET_TEMPERATURE = "set_temperature"
    READ_STATE = "read_state"


class DeviceRiskLevel(StrEnum):
    LOW = "low_risk"
    MEDIUM = "medium_risk"
    HIGH = "high_risk"


class DeviceEventType(StrEnum):
    STATE_CHANGED = "device_state_changed"
    SENSOR_UPDATED = "sensor_updated"
    DEVICE_UNAVAILABLE = "device_unavailable"


AdapterHealthStatus = Literal["healthy", "degraded", "disconnected"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class DeviceCapability(BaseModel):
    capability: str = Field(min_length=1, max_length=100)
    actions: list[DeviceActionName] = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk_level: DeviceRiskLevel = DeviceRiskLevel.LOW
    requires_confirmation: bool = False


class DevicePermissions(BaseModel):
    allowed_actions: list[DeviceActionName] = Field(default_factory=list)
    max_risk_level: DeviceRiskLevel = DeviceRiskLevel.LOW
    requires_confirmation: bool = False


class Device(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    device_type: DeviceType
    area: str | None = Field(default=None, max_length=255)
    capabilities: list[DeviceCapability] = Field(default_factory=list)
    risk_level: DeviceRiskLevel = DeviceRiskLevel.LOW
    is_online: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    permissions: DevicePermissions = Field(default_factory=DevicePermissions)

    @property
    def supported_actions(self) -> set[DeviceActionName]:
        return {action for capability in self.capabilities for action in capability.actions}


class DeviceState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=255)
    state: DeviceStateName
    attributes: dict[str, Any] = Field(default_factory=dict)
    raw_state: str | None = Field(default=None, max_length=255)
    observed_at: datetime = Field(default_factory=utc_now)


class DeviceErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    detail: str | None = None


class DeviceAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: DeviceActionName
    parameters: dict[str, Any] = Field(default_factory=dict)
    action_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)


class ActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    action_id: str = Field(min_length=1)
    external_id: str = Field(min_length=1, max_length=255)
    message: str = Field(default="")
    error: DeviceErrorDetail | None = None


class AdapterHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AdapterHealthStatus
    adapter_id: str = Field(min_length=1, max_length=100)
    detail: str = Field(default="")
    checked_at: datetime = Field(default_factory=utc_now)


class DeviceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: DeviceEventType
    source: str = Field(min_length=1, max_length=100)
    subject_type: Literal["device"] = "device"
    subject_id: str = Field(min_length=1, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = Field(default=None, max_length=100)
    occurred_at: datetime = Field(default_factory=utc_now)
