from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(StrEnum):
    PENDING = "pending"
    PLANNING = "planning"
    WAITING_CONFIRMATION = "waiting_confirmation"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


_TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.PLANNING, TaskStatus.CANCELLED},
    TaskStatus.PLANNING: {
        TaskStatus.RUNNING,
        TaskStatus.WAITING_CONFIRMATION,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_CONFIRMATION: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.WAITING_CONFIRMATION,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}

_TASK_STEP_TRANSITIONS: dict[TaskStepStatus, set[TaskStepStatus]] = {
    TaskStepStatus.PENDING: {
        TaskStepStatus.RUNNING,
        TaskStepStatus.CANCELLED,
    },
    TaskStepStatus.RUNNING: {
        TaskStepStatus.WAITING_CONFIRMATION,
        TaskStepStatus.COMPLETED,
        TaskStepStatus.FAILED,
        TaskStepStatus.TIMED_OUT,
        TaskStepStatus.CANCELLED,
    },
    TaskStepStatus.WAITING_CONFIRMATION: {
        TaskStepStatus.RUNNING,
        TaskStepStatus.CANCELLED,
    },
    TaskStepStatus.COMPLETED: set(),
    TaskStepStatus.FAILED: set(),
    TaskStepStatus.TIMED_OUT: set(),
    TaskStepStatus.CANCELLED: set(),
}


def validate_task_transition(current: TaskStatus, target: TaskStatus) -> None:
    if target not in _TASK_TRANSITIONS[current]:
        raise ValueError(f"Invalid task transition: {current.value} -> {target.value}")


def validate_task_step_transition(current: TaskStepStatus, target: TaskStepStatus) -> None:
    if target not in _TASK_STEP_TRANSITIONS[current]:
        raise ValueError(f"Invalid task step transition: {current.value} -> {target.value}")


class TaskPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    tool_name: str = Field(min_length=1, max_length=255)
    input: dict[str, Any] = Field(default_factory=dict)


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    origin: str = Field(default="api", pattern="^(user|api|system|automation)$")
    steps: list[TaskPlanStep] = Field(min_length=1, max_length=50)
    timeout_seconds: float = Field(default=60.0, gt=0, le=86400)


@dataclass(frozen=True)
class TaskStepCreateRecord:
    id: str
    step_index: int
    name: str
    description: str | None
    tool_name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class TaskCreateRecord:
    id: str
    task_type: str
    title: str
    description: str | None
    origin: str
    plan: dict[str, Any]
    correlation_id: str
    created_at: datetime
    steps: list[TaskStepCreateRecord]


@dataclass(frozen=True)
class TaskRunResult:
    task: StoredTaskDetail
    confirmation_token: str | None = None


class StoredTaskStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    task_id: str
    step_index: int
    name: str
    description: str | None
    tool_name: str | None
    status: TaskStepStatus
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    error: dict[str, Any] | None
    started_at: datetime | None
    completed_at: datetime | None


class StoredToolExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    tool_name: str
    task_id: str | None
    task_step_id: str | None
    status: str
    input: dict[str, Any]
    output: dict[str, Any] | None
    validation: dict[str, Any] | None
    risk_level: str
    permission_result: str
    error: dict[str, Any] | None
    correlation_id: str | None
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None


class StoredTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    task_type: str
    title: str
    description: str | None
    status: TaskStatus
    origin: str
    conversation_id: str | None
    plan: dict[str, Any]
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    correlation_id: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class StoredTaskDetail(StoredTask):
    steps: list[StoredTaskStep] = Field(default_factory=list)
    executions: list[StoredToolExecution] = Field(default_factory=list)


class TaskPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[StoredTask]
    total: int
