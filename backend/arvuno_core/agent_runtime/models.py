from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentIntentType(StrEnum):
    ENVIRONMENT_QUERY = "environment_query"
    DEVICE_QUERY = "device_query"
    EVENT_QUERY = "event_query"
    DEVICE_CONTROL = "device_control"
    AUTOMATION_REQUEST = "automation_request"
    SMALL_TALK = "smalltalk"
    UNSUPPORTED = "unsupported"


class AgentIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: AgentIntentType
    confidence: float = Field(ge=0.0, le=1.0)
    target: str | None = Field(default=None, max_length=255)
    action: str | None = Field(default=None, max_length=100)


class CandidatePlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    tool_name: str = Field(min_length=1, max_length=255)
    input: dict[str, Any] = Field(default_factory=dict)


class AgentCandidateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: AgentIntent
    requires_tool: bool
    plan: list[CandidatePlanStep] = Field(min_length=0, max_length=20)
    reply_to_user: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def validate_plan_shape(self) -> "AgentCandidateOutput":
        if self.requires_tool != bool(self.plan):
            raise ValueError("requires_tool must match whether the candidate plan is empty")
        tool_names = {step.tool_name for step in self.plan}
        if len(tool_names) != len(self.plan):
            raise ValueError("Duplicate tool calls are not allowed in a candidate plan")
        allowed = _INTENT_TOOLS[self.intent.type]
        if self.intent.type in {
            AgentIntentType.AUTOMATION_REQUEST,
            AgentIntentType.SMALL_TALK,
            AgentIntentType.UNSUPPORTED,
        }:
            if tool_names:
                raise ValueError("This intent must not include tool calls")
            return self
        if not tool_names:
            raise ValueError("Fact-seeking and action intents require a candidate tool call")
        if self.intent.type is AgentIntentType.DEVICE_QUERY and not tool_names.intersection(
            allowed
        ):
            raise ValueError("The intent does not match its selected tools")
        if any(name not in allowed for name in tool_names):
            raise ValueError("The intent is not compatible with its selected tools")
        return self


class AgentToolDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    description: str
    category: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: str
    default_permission: str
    requires_confirmation: bool
    enabled: bool


class ValidatedToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: AgentToolDescriptor
    input: dict[str, Any]


class AgentEnvironmentSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_name: str
    updated_at: datetime
    devices: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    sensors: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    areas: dict[str, dict[str, int | list[str]]] = Field(default_factory=dict)


class AgentErrorSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class AgentConfirmationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    risk_level: str
    input: dict[str, Any]


class AgentChatResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "waiting_confirmation", "failed", "cancelled"]
    reply: str
    intent: AgentIntentType
    task_id: str | None = None
    confirmation_token: str | None = None
    confirmation: AgentConfirmationSummary | None = None
    provider_log_id: str | None = None
    correlation_id: str
    client_request_id: str | None = None
    error: AgentErrorSummary | None = None


class TaskSystemPort(Protocol):
    async def create_and_run(
        self,
        request: Any,
        *,
        correlation_id: str | None = None,
    ) -> Any: ...


class ToolCatalogPort(Protocol):
    async def catalog(self) -> list[AgentToolDescriptor]: ...

    async def validate(
        self,
        tool_name: str,
        raw_input: dict[str, object],
    ) -> ValidatedToolCall: ...


class EnvironmentSnapshotProviderPort(Protocol):
    async def __call__(self) -> AgentEnvironmentSnapshot: ...


_INTENT_TOOLS: dict[AgentIntentType, set[str]] = {
    AgentIntentType.ENVIRONMENT_QUERY: {"get_environment_state"},
    AgentIntentType.DEVICE_QUERY: {"list_devices", "get_device_state"},
    AgentIntentType.EVENT_QUERY: {"query_events"},
    AgentIntentType.DEVICE_CONTROL: {"control_device"},
    AgentIntentType.AUTOMATION_REQUEST: set(),
    AgentIntentType.SMALL_TALK: set(),
    AgentIntentType.UNSUPPORTED: set(),
}


__all__ = [
    "AgentCandidateOutput",
    "AgentChatResult",
    "AgentConfirmationSummary",
    "AgentEnvironmentSnapshot",
    "AgentErrorSummary",
    "AgentIntent",
    "AgentIntentType",
    "AgentToolDescriptor",
    "CandidatePlanStep",
    "EnvironmentSnapshotProviderPort",
    "TaskSystemPort",
    "ToolCatalogPort",
    "ValidatedToolCall",
]
