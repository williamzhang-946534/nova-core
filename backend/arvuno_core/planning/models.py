from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

GoalStatus = Literal["candidate", "active", "paused", "completed", "failed", "cancelled", "expired"]
PlanStatus = Literal[
    "draft",
    "validated",
    "awaiting_confirmation",
    "approved",
    "submitted",
    "superseded",
    "cancelled",
    "rejected",
]
RunMode = Literal[
    "analyze_only",
    "suggest_only",
    "awaiting_confirmation",
    "confirm_then_execute",
    "limited_auto_execute",
]
RiskLevel = Literal["read_only", "low_risk", "medium_risk", "high_risk"]


class GoalView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    environment_id: str
    title: str
    description: str | None = None
    objective: str
    origin_type: Literal["user", "model", "automation", "system"]
    origin_record_id: str | None = None
    status: GoalStatus
    goal_type: Literal[
        "comfort", "energy", "device_state", "routine", "diagnosis", "safety_check", "other"
    ]
    scope: dict[str, Any]
    desired_state: dict[str, Any]
    constraints: dict[str, Any]
    prohibitions: list[dict[str, Any]]
    clarifications: list[str]
    unknowns: list[str]
    success_conditions: list[dict[str, Any]]
    failure_conditions: list[dict[str, Any]]
    priority: Literal["low", "normal", "high", "critical"]
    authorization_scope: dict[str, Any]
    time_window: dict[str, Any] | None = None
    reasoning_session_id: str | None = None
    parent_goal_id: str | None = None
    confirmed_by_user: bool
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None


class ReplanningRecordView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    environment_id: str
    old_plan_id: str
    new_plan_id: str | None = None
    task_id: str | None = None
    trigger_type: str
    trigger_record_type: str | None = None
    trigger_record_id: str | None = None
    change_summary: dict[str, Any]
    risk_delta: dict[str, Any]
    already_executed_steps: list[dict[str, Any]]
    reversible_steps: list[dict[str, Any]]
    decision: Literal["replan", "stop", "wait_user_confirmation", "reject"]
    reason: str
    created_at: datetime


class PlanStepView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    plan_id: str
    step_index: int
    name: str
    purpose: str
    tool_name: str
    tool_version: str | None = None
    input: dict[str, Any]
    preconditions: dict[str, Any]
    expected_effect: dict[str, Any]
    postconditions: dict[str, Any]
    verification: dict[str, Any]
    risk_level: RiskLevel
    requires_confirmation: bool
    idempotency_key: str | None = None
    retry_policy: dict[str, Any]
    on_failure: Literal["stop", "request_user_confirmation", "request_replan"]
    depends_on: list[str]
    created_at: datetime


class PlanView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    environment_id: str
    goal_id: str
    reasoning_session_id: str | None = None
    version: int
    status: PlanStatus
    planner_type: Literal["rule", "model", "hybrid", "template", "user"]
    run_mode: RunMode
    strategy: dict[str, Any]
    constraints: dict[str, Any]
    max_risk_level: RiskLevel
    estimated_duration: dict[str, Any] | None = None
    resource_requirements: dict[str, Any]
    validation_errors: list[dict[str, Any]]
    success_criteria: list[dict[str, Any]]
    failure_policy: dict[str, Any]
    submitted_task_id: str | None = None
    superseded_by_id: str | None = None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    steps: list[PlanStepView] = Field(default_factory=list)
    replanning_records: list[ReplanningRecordView] = Field(default_factory=list)


class GoalRevisionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    goal_id: str
    revision: int
    change_type: str
    before: dict[str, Any] | None = None
    after: dict[str, Any]
    reason: str
    source_type: str
    source_id: str | None = None
    created_at: datetime


class GoalListData(BaseModel):
    data: list[GoalView]
    page: int
    page_size: int
    total: int


class GoalData(BaseModel):
    data: GoalView


class PlanListData(BaseModel):
    data: list[PlanView]
    page: int
    page_size: int
    total: int


class PlanData(BaseModel):
    data: PlanView


class GoalAnalysisData(BaseModel):
    data: dict[str, Any]


class AIPlanStepCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=2000)
    tool_name: str = Field(min_length=1, max_length=255)
    input: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[int] = Field(default_factory=list)


class AIPlanCandidateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: str = Field(min_length=1, max_length=2000)
    steps: list[AIPlanStepCandidate] = Field(min_length=1, max_length=8)


class ReplanningRecordData(BaseModel):
    data: ReplanningRecordView


__all__ = [
    "AIPlanCandidateOutput",
    "AIPlanStepCandidate",
    "GoalData",
    "GoalListData",
    "GoalRevisionView",
    "GoalStatus",
    "GoalView",
    "PlanData",
    "PlanListData",
    "PlanStatus",
    "PlanStepView",
    "PlanView",
    "ReplanningRecordData",
    "ReplanningRecordView",
    "RiskLevel",
    "RunMode",
]
