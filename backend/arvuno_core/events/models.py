from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ArvunoEventType(StrEnum):
    DEVICE_STATE_CHANGED = "device_state_changed"
    SENSOR_UPDATED = "sensor_updated"
    DEVICE_UNAVAILABLE = "device_unavailable"
    AUTOMATION_TRIGGERED = "automation_triggered"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TOOL_EXECUTED = "tool_executed"
    USER_CONFIRMED = "user_confirmed"


class ArvunoEventSource(StrEnum):
    HOME_ASSISTANT = "home_assistant"
    MOCK_ADAPTER = "mock_adapter"
    AGENT = "agent"
    TASK = "task"
    TOOL = "tool"
    AUTOMATION = "automation"
    API = "api"
    SYSTEM = "system"


SensorType = Literal["temperature", "humidity", "motion", "contact"]
SensorValue = float | int | bool | str


def utc_now() -> datetime:
    return datetime.now(UTC)


class DeviceStateChangedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=255)
    previous_state: str = Field(min_length=1, max_length=100)
    current_state: str = Field(min_length=1, max_length=100)
    attributes: dict[str, Any] = Field(default_factory=dict)


class SensorUpdatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=255)
    sensor_type: SensorType
    value: SensorValue
    unit: str | None = Field(default=None, max_length=50)
    previous_value: SensorValue | None = None


class DeviceUnavailablePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)
    observed_state: str = Field(min_length=1, max_length=100)


class AutomationTriggeredPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    automation_id: str = Field(min_length=1, max_length=255)
    trigger_event_id: str = Field(min_length=1, max_length=36)
    matched_conditions: list[dict[str, Any]] = Field(default_factory=list)


class TaskStartedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=36)
    task_type: str = Field(min_length=1, max_length=100)
    origin: str = Field(min_length=1, max_length=100)


class TaskCompletedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=36)
    result_summary: str = Field(min_length=1, max_length=2000)
    completed_at: datetime


class TaskFailedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=36)
    error_code: str = Field(min_length=1, max_length=100)
    error_message: str = Field(min_length=1, max_length=2000)
    failed_step_id: str | None = Field(default=None, min_length=1, max_length=36)


class ToolExecutedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1, max_length=255)
    tool_execution_id: str = Field(min_length=1, max_length=36)
    status: Literal["success", "failure"]
    risk_level: str = Field(min_length=1, max_length=50)
    verified: bool


class UserConfirmedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=36)
    confirmed: bool
    confirmation_token_hash: str = Field(min_length=1, max_length=255)


EventPayload = (
    DeviceStateChangedPayload
    | SensorUpdatedPayload
    | DeviceUnavailablePayload
    | AutomationTriggeredPayload
    | TaskStartedPayload
    | TaskCompletedPayload
    | TaskFailedPayload
    | ToolExecutedPayload
    | UserConfirmedPayload
)

_PAYLOAD_TYPES: dict[ArvunoEventType, type[EventPayload]] = {
    ArvunoEventType.DEVICE_STATE_CHANGED: DeviceStateChangedPayload,
    ArvunoEventType.SENSOR_UPDATED: SensorUpdatedPayload,
    ArvunoEventType.DEVICE_UNAVAILABLE: DeviceUnavailablePayload,
    ArvunoEventType.AUTOMATION_TRIGGERED: AutomationTriggeredPayload,
    ArvunoEventType.TASK_STARTED: TaskStartedPayload,
    ArvunoEventType.TASK_COMPLETED: TaskCompletedPayload,
    ArvunoEventType.TASK_FAILED: TaskFailedPayload,
    ArvunoEventType.TOOL_EXECUTED: ToolExecutedPayload,
    ArvunoEventType.USER_CONFIRMED: UserConfirmedPayload,
}

UuidString = Annotated[str, Field(min_length=36, max_length=36)]


class ArvunoEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UuidString = Field(default_factory=lambda: str(uuid4()))
    event_type: ArvunoEventType
    source: ArvunoEventSource
    subject_type: str | None = Field(default=None, min_length=1, max_length=100)
    subject_id: str | None = Field(default=None, min_length=1, max_length=255)
    payload: EventPayload
    correlation_id: str | None = Field(default=None, min_length=1, max_length=100)
    occurred_at: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("id")
    @classmethod
    def validate_uuid(cls, value: str) -> str:
        UUID(value)
        return value

    @field_validator("occurred_at", "created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Event timestamps must include a UTC offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_payload_and_subject(self) -> "ArvunoEvent":
        expected_payload = _PAYLOAD_TYPES[self.event_type]
        if type(self.payload) is not expected_payload:
            raise ValueError(f"{self.event_type.value} requires a {expected_payload.__name__}")

        device_event_types = {
            ArvunoEventType.DEVICE_STATE_CHANGED,
            ArvunoEventType.SENSOR_UPDATED,
            ArvunoEventType.DEVICE_UNAVAILABLE,
        }
        if self.event_type in device_event_types:
            if self.subject_type != "device":
                raise ValueError("Device events must use subject_type='device'")
            if self.subject_id is None:
                raise ValueError("Device events require subject_id")
            if self.payload.device_id != self.subject_id:
                raise ValueError("payload.device_id must match subject_id")
        return self
