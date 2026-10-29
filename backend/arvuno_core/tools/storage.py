from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolDefinitionRecord:
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


@dataclass(frozen=True)
class ToolExecutionCreate:
    id: str
    tool_name: str
    task_id: str | None
    task_step_id: str | None
    status: str
    input: dict[str, Any]
    risk_level: str
    permission_result: str
    correlation_id: str
    started_at: datetime


@dataclass(frozen=True)
class ToolExecutionUpdate:
    status: str
    output: dict[str, Any] | None
    validation: dict[str, Any] | None
    risk_level: str
    permission_result: str
    error: dict[str, Any] | None
    completed_at: datetime
    duration_ms: int


@dataclass(frozen=True)
class StoredToolExecution:
    id: str
    tool_name: str
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


class ToolExecutionStoreProtocol(Protocol):
    def register_definition(self, record: ToolDefinitionRecord) -> None: ...

    def create_execution(self, record: ToolExecutionCreate) -> None: ...

    def update_execution(self, execution_id: str, record: ToolExecutionUpdate) -> None: ...

    def get_execution(self, execution_id: str) -> StoredToolExecution | None: ...


__all__ = [
    "StoredToolExecution",
    "ToolDefinitionRecord",
    "ToolExecutionCreate",
    "ToolExecutionStoreProtocol",
    "ToolExecutionUpdate",
]
