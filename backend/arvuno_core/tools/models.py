from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from arvuno_core.devices.models import DeviceActionName, DeviceStateName
from arvuno_core.history.models import (
    CorrelatedHistory,
    EntityHistoryResult,
    HistoryQueryResult,
    NaturalHistoryAnswer,
    SnapshotDiffResult,
    SnapshotLookupResult,
    SpatialHistoryResult,
    TrendQueryResult,
)
from arvuno_core.memory.models import MemoryView, PreferenceView, QuestionType


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


class MemoryRetrievalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_type: QuestionType = "any"
    query: str | None = Field(default=None, max_length=500)


class MemoryRetrievalOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_available: bool
    question_type: QuestionType
    query: str | None = None
    memories: list[MemoryView] = Field(default_factory=list)
    preferences: list[PreferenceView] = Field(default_factory=list)
    source_references: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_at: datetime | None = None


class HistoryQueryOperation(StrEnum):
    ASK = "ask"
    TIME_RANGE = "time_range"
    SPATIAL_HISTORY = "spatial_history"
    ENTITY_HISTORY = "entity_history"
    TRENDS = "trends"
    SNAPSHOT_AT = "snapshot_at"
    SNAPSHOT_DIFF = "snapshot_diff"
    CORRELATE = "correlate"


class HistoryQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: HistoryQueryOperation
    query: str | None = Field(default=None, min_length=1, max_length=500)
    start_time: AwareDatetime | None = None
    end_time: AwareDatetime | None = None
    at_time: AwareDatetime | None = None
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=100)
    now: AwareDatetime | None = None
    entity_id: str | None = Field(default=None, min_length=1, max_length=36)
    space_id: str | None = Field(default=None, min_length=1, max_length=36)
    attribute: str | None = Field(default=None, min_length=1, max_length=50)
    quality_status: str | None = Field(default=None, min_length=1, max_length=50)
    include_descendants: bool = True
    expected_interval_seconds: int | None = Field(default=None, ge=1)
    limit: int = Field(default=200, ge=1, le=2000)
    group_by: str = Field(default="space", pattern="^(space|entity)$")
    environment_id: str | None = Field(default=None, min_length=1, max_length=36)
    nearest: bool = False
    baseline_id: str | None = Field(default=None, min_length=1, max_length=36)
    target_id: str | None = Field(default=None, min_length=1, max_length=36)
    baseline_at: AwareDatetime | None = None
    target_at: AwareDatetime | None = None
    record_type: str | None = Field(default=None, pattern="^(observation|event|task)$")
    record_id: str | None = Field(default=None, min_length=1, max_length=36)

    @model_validator(mode="after")
    def validate_operation_fields(self) -> "HistoryQueryInput":
        if self.operation is HistoryQueryOperation.ASK:
            if self.query is None:
                raise ValueError("ask requires query")
        elif self.operation is HistoryQueryOperation.TIME_RANGE:
            if self.start_time is None or self.end_time is None:
                raise ValueError("time_range requires start_time and end_time")
        elif self.operation is HistoryQueryOperation.SPATIAL_HISTORY:
            if self.space_id is None or self.start_time is None or self.end_time is None:
                raise ValueError("spatial_history requires space_id and a time range")
        elif self.operation is HistoryQueryOperation.ENTITY_HISTORY:
            if self.entity_id is None or self.start_time is None or self.end_time is None:
                raise ValueError("entity_history requires entity_id and a time range")
        elif self.operation is HistoryQueryOperation.TRENDS:
            if self.attribute is None or self.start_time is None or self.end_time is None:
                raise ValueError("trends requires attribute and a time range")
        elif self.operation is HistoryQueryOperation.SNAPSHOT_AT:
            if self.at_time is None:
                raise ValueError("snapshot_at requires at_time")
        elif self.operation is HistoryQueryOperation.SNAPSHOT_DIFF:
            if (self.baseline_id is None) == (self.baseline_at is None) or (
                self.target_id is None
            ) == (self.target_at is None):
                raise ValueError(
                    "snapshot_diff requires one baseline selector and one target selector"
                )
        elif self.operation is HistoryQueryOperation.CORRELATE and (
            self.record_type is None or self.record_id is None
        ):
            raise ValueError("correlate requires record_type and record_id")
        return self


class HistoryQueryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_available: bool
    operation: HistoryQueryOperation
    time_range: HistoryQueryResult | None = None
    spatial_history: SpatialHistoryResult | None = None
    entity_history: EntityHistoryResult | None = None
    trends: TrendQueryResult | None = None
    snapshot: SnapshotLookupResult | None = None
    snapshot_diff: SnapshotDiffResult | None = None
    correlation: CorrelatedHistory | None = None
    natural_history: NaturalHistoryAnswer | None = None
