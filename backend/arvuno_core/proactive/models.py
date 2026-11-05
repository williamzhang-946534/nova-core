from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ProactiveTriggerType = Literal[
    "trend",
    "anomaly",
    "goal_deviation",
    "task_failure",
    "coverage_gap",
    "device_fault",
    "cost_risk",
]

ProactiveImportance = Literal["low", "normal", "high"]

ProactiveStatus = Literal[
    "evaluated",
    "suppressed",
    "queued",
    "delivered",
    "opened",
    "accepted",
    "dismissed",
    "expired",
]


class ProactiveSuggestionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    environment_id: str
    reasoning_session_id: str | None = None
    hypothesis_id: str | None = None
    goal_id: str | None = None
    trigger_type: str
    title: str
    message: str
    importance: str
    autonomy_level: int = Field(ge=0, le=4)
    candidate_action: dict[str, Any]
    evidence_refs: list[dict[str, Any]]
    dedupe_key: str
    status: str
    suppression_count: int = Field(default=0, ge=0)
    delivered_at: datetime | None = None
    opened_at: datetime | None = None
    accepted_at: datetime | None = None
    dismissed_at: datetime | None = None
    user_feedback: dict[str, Any] | None = None
    cooldown_until: datetime | None = None
    quality_score: float | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None


class ProactiveSuggestionData(BaseModel):
    data: ProactiveSuggestionView


class ProactiveSuggestionListData(BaseModel):
    data: list[ProactiveSuggestionView]
    page: int
    page_size: int
    total: int


class ProactiveDeleteData(BaseModel):
    id: str
    deleted: bool


class ProactiveDeleteWrapper(BaseModel):
    data: ProactiveDeleteData


class SuppressionDecision(BaseModel):
    """Explains why a suggestion was or was not delivered."""

    model_config = ConfigDict(extra="forbid")

    suppressed: bool
    reason: Literal[
        "allowed",
        "duplicate_active",
        "cooldown",
        "quiet_hours",
        "rate_limit_hour",
        "rate_limit_day",
        "user_suppressed",
        "expired",
    ]
    active_suggestion_id: str | None = None
    delivered_last_hour: int | None = None
    delivered_last_day: int | None = None


class ProactiveQualitySummary(BaseModel):
    """Aggregated quality metrics for a trigger rule."""

    model_config = ConfigDict(extra="forbid")

    trigger_type: str
    total: int = 0
    evaluated: int = 0
    suppressed: int = 0
    queued: int = 0
    delivered: int = 0
    opened: int = 0
    accepted: int = 0
    dismissed: int = 0
    expired: int = 0
    quality_score: float | None = None


class ProactiveQualityData(BaseModel):
    data: ProactiveQualitySummary


__all__ = [
    "ProactiveDeleteData",
    "ProactiveDeleteWrapper",
    "ProactiveImportance",
    "ProactiveQualityData",
    "ProactiveQualitySummary",
    "ProactiveStatus",
    "ProactiveSuggestionData",
    "ProactiveSuggestionListData",
    "ProactiveSuggestionView",
    "ProactiveTriggerType",
    "SuppressionDecision",
]
