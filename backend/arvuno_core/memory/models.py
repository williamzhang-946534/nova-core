from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MemoryType = Literal["episodic", "semantic", "procedural"]
MemoryStatus = Literal["active", "candidate", "corrected", "superseded", "expired", "archived"]
MemorySourceType = Literal[
    "user",
    "observation",
    "event",
    "task",
    "conversation",
    "ai_inference",
    "procedure_execution",
    "system",
]
EvidenceType = Literal[
    "observation",
    "event",
    "task",
    "conversation",
    "procedure_execution",
    "user_statement",
    "environment_snapshot",
]
QuestionType = Literal[
    "preference",
    "semantic_fact",
    "spatial_fact",
    "historical_event",
    "task_record",
    "procedure",
    "any",
]


class MemoryEvidenceView(BaseModel):
    id: str
    evidence_type: EvidenceType
    evidence_id: str | None = None
    source_type: str
    source_record_id: str | None = None
    trust_level: float
    snapshot: dict[str, Any]
    occurred_at: datetime | None = None
    created_at: datetime
    record: dict[str, Any] | None = None


class MemoryRevisionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    revision_type: str
    previous_content: str
    changed_fields: dict[str, Any]
    actor_type: str
    actor_id: str
    reason: str | None = None
    created_at: datetime


class MemoryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    memory_type: MemoryType
    title: str
    content: str
    summary: str | None = None
    keywords: list[str]
    importance: int
    source_type: MemorySourceType
    source_id: str | None = None
    user_confirmed: bool
    status: MemoryStatus
    confidence: float
    verification_status: Literal["unverified", "verified", "rejected"]
    owner_id: str
    access_level: str
    scope: dict[str, Any]
    environment_id: str | None = None
    space_id: str | None = None
    entity_id: str | None = None
    conversation_id: str | None = None
    task_id: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    predicate: str | None = None
    object_value: Any | None = None
    valid_from: datetime
    expires_at: datetime | None = None
    retention_until: datetime | None = None
    last_reviewed_at: datetime | None = None
    correction_count: int
    created_at: datetime
    updated_at: datetime


class PreferenceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    value: dict[str, Any]
    category: str
    description: str | None = None
    source: str
    source_type: str
    source_record_id: str
    status: Literal["draft", "active", "revoked"]
    scope: dict[str, Any]
    conversation_id: str | None = None
    consent_id: str | None = None
    confirmed: bool
    confirmed_at: datetime | None = None
    valid_from: datetime
    expires_at: datetime | None = None
    retention_until: datetime | None = None
    superseded_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MemoryRetrievalResult(BaseModel):
    question_type: QuestionType
    query: str
    memories: list[MemoryView]
    preferences: list[PreferenceView]
    source_references: list[MemoryEvidenceView] = Field(default_factory=list)
    retrieval_strategy: Literal["bounded_lexical_hybrid"] = "bounded_lexical_hybrid"
    retrieved_at: datetime


class HistoryReference(BaseModel):
    evidence: MemoryEvidenceView
    record: dict[str, Any] | None = None


class MemoryGraphNode(BaseModel):
    id: str
    node_type: Literal["memory", "space", "entity", "task"]
    label: str
    memory_type: MemoryType | None = None
    status: str | None = None


class MemoryGraphEdge(BaseModel):
    source: str
    target: str
    relation: str


class MemoryGraph(BaseModel):
    nodes: list[MemoryGraphNode] = Field(default_factory=list)
    edges: list[MemoryGraphEdge] = Field(default_factory=list)
    truncated: bool = False
    generated_at: datetime


__all__ = [
    "EvidenceType",
    "HistoryReference",
    "MemoryEvidenceView",
    "MemoryGraph",
    "MemoryGraphEdge",
    "MemoryGraphNode",
    "MemoryRevisionView",
    "MemoryRetrievalResult",
    "MemorySourceType",
    "MemoryStatus",
    "MemoryType",
    "MemoryView",
    "PreferenceView",
    "QuestionType",
]
