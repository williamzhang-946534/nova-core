from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class GoalCompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=2000)
    environment_id: str | None = Field(default=None, min_length=1, max_length=36)
    description: str | None = Field(default=None, max_length=5000)
    desired_state: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    prohibitions: list[dict[str, Any]] = Field(default_factory=list)
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    authorization_scope: dict[str, Any] = Field(default_factory=dict)
    time_window: dict[str, Any] | None = None
    reasoning_session_id: str | None = Field(default=None, min_length=1, max_length=36)
    origin_type: Literal["user", "model", "automation", "system"] = "user"
    source_record_id: str | None = Field(default=None, min_length=1, max_length=255)
    now: AwareDatetime | None = None


class GoalConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorization_scope: dict[str, Any] | None = None
    reason: str | None = Field(default=None, max_length=2000)


class GoalCloseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "failed", "cancelled", "expired"]
    reason: str = Field(min_length=1, max_length=2000)


class PlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["analyze", "suggest", "plan"] = "plan"
    reasoning_session_id: str | None = Field(default=None, min_length=1, max_length=36)
    auto_execute: bool = False
    now: AwareDatetime | None = None


class PlanDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)


class ReplanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger_type: Literal[
        "precondition_failed",
        "tool_failed",
        "verification_failed",
        "goal_changed",
        "environment_changed",
        "user_cancelled",
        "priority_preempted",
        "timeout",
    ]
    task_id: str | None = Field(default=None, min_length=1, max_length=36)
    trigger_record_type: str | None = Field(default=None, min_length=1, max_length=50)
    trigger_record_id: str | None = Field(default=None, min_length=1, max_length=255)
    change_summary: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=2000)
    auto_execute: bool = False
    now: AwareDatetime | None = None


__all__ = [
    "GoalCloseRequest",
    "GoalCompileRequest",
    "GoalConfirmRequest",
    "PlanCreateRequest",
    "PlanDecisionRequest",
    "ReplanRequest",
]
