from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AutomationActionType(StrEnum):
    NOTIFICATION = "notification"
    TOOL = "tool"


class AutomationRiskLevel(StrEnum):
    READ_ONLY = "read_only"
    LOW_RISK = "low_risk"
    MEDIUM_RISK = "medium_risk"
    HIGH_RISK = "high_risk"


AutomationEventTypeName = Literal[
    "device_state_changed",
    "sensor_updated",
    "device_unavailable",
]

AUTOMATION_EVENT_TYPES = frozenset[AutomationEventTypeName](
    ("device_state_changed", "sensor_updated", "device_unavailable")
)


class AutomationTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: AutomationEventTypeName
    subject_id: str | None = Field(default=None, min_length=1, max_length=255)


ConditionOperator = Literal[
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "contains",
    "in",
]


class AutomationCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=200)
    operator: ConditionOperator
    value: Any = Field(default=None)


class AutomationNotificationAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[AutomationActionType.NOTIFICATION] = AutomationActionType.NOTIFICATION
    title: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=2000)
    level: Literal["info", "warning", "error"] = "info"


class AutomationToolAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[AutomationActionType.TOOL] = AutomationActionType.TOOL
    tool_name: str = Field(min_length=1, max_length=255)
    input: dict[str, Any] = Field(default_factory=dict)
    title: str = Field(min_length=1, max_length=255)
    risk_level: AutomationRiskLevel = Field(default=AutomationRiskLevel.LOW_RISK)


AutomationAction = AutomationNotificationAction | AutomationToolAction


class AutomationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool = True
    trigger: AutomationTrigger
    conditions: list[AutomationCondition] = Field(default_factory=list, max_length=20)
    action: AutomationAction
    cooldown_seconds: int = Field(default=0, ge=0, le=86400)


class AutomationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None
    trigger: AutomationTrigger | None = None
    conditions: list[AutomationCondition] | None = Field(default=None, max_length=20)
    action: AutomationAction | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)


class StoredAutomation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str | None
    enabled: bool
    trigger: AutomationTrigger
    conditions: list[AutomationCondition]
    action: AutomationAction
    cooldown_seconds: int
    risk_level: str
    created_at: datetime
    updated_at: datetime


class AutomationPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[StoredAutomation]
    total: int


class AutomationRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    COOLDOWN_SKIPPED = "cooldown_skipped"
    CONDITION_NOT_MET = "condition_not_met"
    RISK_REJECTED = "risk_rejected"


class StoredAutomationRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    automation_id: str
    event_id: str | None
    status: AutomationRunStatus
    matched_context: dict[str, Any]
    task_id: str | None
    notification_id: str | None
    error: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None


class AutomationRunPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[StoredAutomationRun]
    total: int


class NotificationLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class NotificationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str = Field(default="web_console", min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=5000)
    level: NotificationLevel = NotificationLevel.INFO
    related_event_id: str | None = Field(default=None, min_length=1, max_length=36)
    related_task_id: str | None = Field(default=None, min_length=1, max_length=36)


class NotificationStatus(StrEnum):
    SENT = "sent"
    READ = "read"


class StoredNotification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    channel: str
    title: str
    content: str
    level: NotificationLevel
    status: NotificationStatus
    related_event_id: str | None
    related_task_id: str | None
    created_at: datetime
    sent_at: datetime | None


class NotificationPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[StoredNotification]
    total: int
