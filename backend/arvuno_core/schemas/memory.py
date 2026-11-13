from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from arvuno_core.memory.models import (
    HistoryReference,
    MemoryEvidenceView,
    MemoryGraph,
    MemoryRetrievalResult,
    MemoryRevisionView,
    MemorySourceType,
    MemoryType,
    MemoryView,
    PreferenceView,
    QuestionType,
)


class MemoryEvidenceRequest(BaseModel):
    evidence_type: Literal[
        "observation",
        "event",
        "task",
        "conversation",
        "procedure_execution",
        "user_statement",
        "environment_snapshot",
    ]
    evidence_id: str | None = Field(default=None, min_length=1, max_length=255)
    source_type: str = Field(min_length=1, max_length=100)
    source_record_id: str | None = Field(default=None, max_length=255)
    trust_level: float = Field(default=0.5, ge=0, le=1)
    snapshot: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class MemoryCreateRequest(BaseModel):
    memory_type: MemoryType
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    summary: str | None = None
    keywords: list[str] = Field(default_factory=list, max_length=30)
    importance: int = Field(default=2, ge=1, le=5)
    source_type: MemorySourceType
    source_id: str | None = Field(default=None, max_length=255)
    user_confirmed: bool = False
    confidence: float = Field(default=0.5, ge=0, le=1)
    owner_id: str = Field(default="local_user", min_length=1, max_length=100)
    access_level: Literal["owner_only", "household"] = "owner_only"
    scope: dict[str, Any] = Field(default_factory=dict)
    environment_id: str | None = Field(default=None, max_length=36)
    space_id: str | None = Field(default=None, max_length=36)
    entity_id: str | None = Field(default=None, max_length=36)
    conversation_id: str | None = Field(default=None, max_length=36)
    task_id: str | None = Field(default=None, max_length=36)
    subject_type: str | None = Field(default=None, max_length=100)
    subject_id: str | None = Field(default=None, max_length=255)
    predicate: str | None = Field(default=None, max_length=255)
    object_value: Any | None = None
    valid_from: datetime | None = None
    expires_at: datetime | None = None
    retention_until: datetime | None = None
    status: (
        Literal["active", "candidate", "corrected", "superseded", "expired", "archived"] | None
    ) = None
    evidence: list[MemoryEvidenceRequest] = Field(default_factory=list, max_length=50)


class MemoryUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1)
    summary: str | None = None
    keywords: list[str] | None = Field(default=None, max_length=30)
    importance: int | None = Field(default=None, ge=1, le=5)
    scope: dict[str, Any] | None = None
    space_id: str | None = Field(default=None, max_length=36)
    entity_id: str | None = Field(default=None, max_length=36)
    expires_at: datetime | None = None
    retention_until: datetime | None = None
    status: Literal["active", "archived"] | None = None
    previous_content: str | None = None
    reason: str | None = Field(default=None, max_length=2000)


class MemoryCorrectRequest(BaseModel):
    content: str = Field(min_length=1)
    summary: str | None = None
    reason: str | None = Field(default=None, max_length=2000)


class MemoryProcedureVersionRequest(BaseModel):
    version: str = Field(min_length=1, max_length=50)
    tool_name: str | None = Field(default=None, min_length=1, max_length=255)
    steps: list[dict[str, Any]] = Field(min_length=1)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    risk_level: Literal["read_only", "low_risk", "medium_risk", "high_risk"] = "read_only"
    required_successes: int = Field(default=3, ge=1, le=100)


class MemoryProcedureValidationRequest(BaseModel):
    version: str = Field(min_length=1, max_length=50)
    task_id: str | None = Field(default=None, max_length=36)
    tool_execution_id: str | None = Field(default=None, max_length=36)
    status: Literal["passed", "failed"]
    result: dict[str, Any] = Field(default_factory=dict)
    validator_type: str = Field(default="user", min_length=1, max_length=50)


class PreferenceCreateRequest(BaseModel):
    key: str = Field(min_length=1, max_length=255)
    value: dict[str, Any]
    category: str = Field(default="general", min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    source_type: Literal["user"] = "user"
    source_record_id: str = Field(min_length=1, max_length=255)
    conversation_id: str | None = Field(default=None, max_length=36)
    consent_statement: str = Field(min_length=1)
    scope: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False
    confirmed_at: datetime | None = None
    valid_from: datetime | None = None
    expires_at: datetime | None = None
    retention_until: datetime | None = None


class PreferenceUpdateRequest(BaseModel):
    value: dict[str, Any] | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    scope: dict[str, Any] | None = None
    expires_at: datetime | None = None


class MemoryRetrievalRequest(BaseModel):
    question_type: QuestionType = "any"
    query: str | None = Field(default=None, max_length=500)


class MemoryCompressRequest(BaseModel):
    memory_ids: list[str] = Field(min_length=2, max_length=50)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    summary: str | None = Field(default=None, max_length=2000)
    expires_in_days: int = Field(default=7, ge=1, le=365)


class MemoryDistillRequest(BaseModel):
    memory_ids: list[str] = Field(min_length=1, max_length=50)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    summary: str | None = Field(default=None, max_length=2000)
    subject_type: str | None = Field(default=None, min_length=1, max_length=100)
    subject_id: str | None = Field(default=None, min_length=1, max_length=255)
    predicate: str | None = Field(default=None, min_length=1, max_length=255)
    object_value: Any | None = None
    expires_in_days: int = Field(default=7, ge=1, le=365)


class MemoryGraphQuery(BaseModel):
    memory_type: MemoryType | None = None
    keyword: str | None = Field(default=None, max_length=200)
    space_id: str | None = Field(default=None, max_length=36)
    entity_id: str | None = Field(default=None, max_length=36)
    max_memories: int = Field(default=100, ge=1, le=100)


class MemoryListData(BaseModel):
    data: list[MemoryView]
    page: int
    page_size: int
    total: int


class PreferenceListData(BaseModel):
    data: list[PreferenceView]
    page: int
    page_size: int
    total: int


class MemoryData(BaseModel):
    data: MemoryView


class PreferenceData(BaseModel):
    data: PreferenceView


class MemoryRevisionListData(BaseModel):
    data: list[MemoryRevisionView]


class HistoryReferenceListData(BaseModel):
    data: list[HistoryReference]


class EvidenceListData(BaseModel):
    data: list[MemoryEvidenceView]


class MemoryRetrievalData(BaseModel):
    data: MemoryRetrievalResult


class MemoryOperationData(BaseModel):
    data: MemoryView
    source_memory_ids: list[str]
    operation: Literal["compress", "distill"]


class MemoryGraphData(BaseModel):
    data: MemoryGraph


class MemoryProcedureData(BaseModel):
    data: dict[str, Any]


class MemoryCleanupData(BaseModel):
    expired: int
    deleted: int


class MemoryCleanupWrapper(BaseModel):
    data: MemoryCleanupData


class MemoryDeleteData(BaseModel):
    id: str
    deleted: bool


class MemoryDeleteWrapper(BaseModel):
    data: MemoryDeleteData


__all__ = [
    "EvidenceListData",
    "HistoryReferenceListData",
    "MemoryCleanupData",
    "MemoryCleanupWrapper",
    "MemoryCorrectRequest",
    "MemoryCreateRequest",
    "MemoryData",
    "MemoryDeleteData",
    "MemoryDeleteWrapper",
    "MemoryEvidenceRequest",
    "MemoryGraphData",
    "MemoryGraphQuery",
    "MemoryListData",
    "MemoryOperationData",
    "MemoryProcedureData",
    "MemoryProcedureValidationRequest",
    "MemoryProcedureVersionRequest",
    "MemoryRetrievalData",
    "MemoryRetrievalRequest",
    "MemoryRevisionListData",
    "MemoryUpdateRequest",
    "PreferenceCreateRequest",
    "PreferenceData",
    "PreferenceListData",
    "PreferenceUpdateRequest",
]
