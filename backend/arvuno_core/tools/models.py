from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from arvuno_core.devices.models import DeviceActionName, DeviceStateName


class ToolRiskLevel(StrEnum):
    READ_ONLY = "read_only"
    LOW = "low_risk"
    MEDIUM = "medium_risk"
    HIGH = "high_risk"


class ToolPermission(StrEnum):
    ALLOW = "allow"
    ALLOW_READ_ONLY = "allow_read_only"
    ALLOW_LOW_RISK = "allow_low_risk"
    REQUIRE_CONFIRMATION = "require_confirmation"
    DENY = "deny"


class PermissionResult(StrEnum):
    ALLOWED = "allowed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    DENIED = "denied"
    TOOL_DISABLED = "tool_disabled"
    RISK_EXCEEDED = "risk_exceeded"
    DEVICE_NOT_FOUND = "device_not_found"
    DEVICE_DISABLED = "device_disabled"
    ACTION_NOT_ALLOWED = "action_not_allowed"
    DEVICE_UNAVAILABLE = "device_unavailable"


class ToolErrorCode(StrEnum):
    VALIDATION = "TOOL_VALIDATION_ERROR"
    NOT_FOUND = "TOOL_NOT_FOUND"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RISK_REJECTED = "RISK_POLICY_REJECTED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    DEVICE_UNAVAILABLE = "DEVICE_UNAVAILABLE"
    STATE_CONFLICT = "STATE_CONFLICT"
    ADAPTER_TIMEOUT = "ADAPTER_TIMEOUT"
    ADAPTER_ERROR = "ADAPTER_ERROR"
    EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    PERSISTENCE_FAILED = "TOOL_PERSISTENCE_FAILED"


@dataclass(frozen=True)
class ToolExecutionContext:
    correlation_id: str
    task_id: str | None = None
    task_step_id: str | None = None


class ListDevicesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area: str | None = Field(default=None, min_length=1, max_length=255)
    device_type: str | None = Field(default=None, min_length=1, max_length=100)
    online: bool | None = None


class DeviceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    device_type: str
    area: str | None
    is_online: bool
    state: str | None = None


class ListDevicesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    devices: list[DeviceSummary]


class GetDeviceStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=36)


class GetDeviceStateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    state: DeviceStateName
    attributes: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime


class GetEnvironmentStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area: str | None = Field(default=None, min_length=1, max_length=255)
    include_devices: bool = True
    include_recent_events: bool = True


class EnvironmentDeviceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    name: str
    device_type: str
    area: str | None
    state: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime


class EnvironmentSensorSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    sensor_type: str
    value: float | int | bool | str
    unit: str | None = None
    updated_at: datetime


class GetEnvironmentStateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str | None = None
    environment_name: str
    updated_at: datetime
    devices: list[EnvironmentDeviceSummary] = Field(default_factory=list)
    sensors: list[EnvironmentSensorSummary] = Field(default_factory=list)
    areas: dict[str, dict[str, int | list[str]]] = Field(default_factory=dict)
    recent_events: list[dict[str, Any]] = Field(default_factory=list)


class ControlDeviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=36)
    action: DeviceActionName
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_state: DeviceStateName | None = None

    @model_validator(mode="after")
    def validate_action_parameters(self) -> "ControlDeviceInput":
        if self.action in {
            DeviceActionName.TURN_ON,
            DeviceActionName.TURN_OFF,
            DeviceActionName.TOGGLE,
            DeviceActionName.READ_STATE,
        }:
            if self.parameters:
                raise ValueError(f"{self.action.value} does not accept parameters")
            return self

        if self.action == DeviceActionName.SET_BRIGHTNESS:
            if set(self.parameters) != {"brightness_pct"}:
                raise ValueError("set_brightness requires only brightness_pct")
            value = self.parameters["brightness_pct"]
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
                raise ValueError("brightness_pct must be an integer from 1 to 100")
            return self

        if self.action == DeviceActionName.SET_TEMPERATURE:
            if set(self.parameters) != {"temperature"}:
                raise ValueError("set_temperature requires only temperature")
            value = self.parameters["temperature"]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("temperature must be a number")
            if not 7 <= float(value) <= 35:
                raise ValueError("temperature must be between 7 and 35")
            return self

        raise ValueError("Unsupported device action")


class ControlDeviceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    action: DeviceActionName
    executed: bool
    verified: bool
    actual_state: DeviceStateName
    attributes: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime


class ToolErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ToolErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str
    tool_name: str
    status: str
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    verified: bool = False
    risk_level: ToolRiskLevel
    permission_result: PermissionResult
    error: ToolErrorDetail | None = None
    correlation_id: str
