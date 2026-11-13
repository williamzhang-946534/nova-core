from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ReasoningEvidenceSource = Literal["observation", "state_estimate", "event", "task", "memory"]
ReasoningEvidenceClassification = Literal[
    "observed", "derived", "inferred_candidate", "verified_cause", "unknown"
]
ReasoningHypothesisType = Literal[
    "deterministic_rule",
    "correlation",
    "ai_candidate",
    "verified_cause",
    "data_quality",
    "unknown",
]
ReasoningOrigin = Literal["rule", "model", "user", "system"]
ReasoningHypothesisStatus = Literal[
    "unsupported",
    "plausible",
    "supported",
    "conflicted",
    "refuted",
    "expired",
    "superseded",
]
ReasoningConfidence = Literal["unknown", "low", "medium", "high"]


class ReasoningEvidenceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_type: ReasoningEvidenceSource
    source_record_id: str
    classification: ReasoningEvidenceClassification
    statement: str
    snapshot: dict[str, Any]
    scope: dict[str, Any]
    source_time: datetime | None = None
    received_time: datetime | None = None
    quality_status: Literal["valid", "suspect", "invalid", "unavailable"]
    quality_issues: list[dict[str, Any]]
    trust_level: float
    source_available: bool
    created_at: datetime


class ReasoningEvidenceLinkView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    relationship: Literal["supports", "contradicts", "context"]
    weight: float
    rationale: str
    evidence: ReasoningEvidenceView


class ReasoningHypothesisView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    environment_id: str
    statement: str
    hypothesis_type: ReasoningHypothesisType
    origin_type: ReasoningOrigin
    status: ReasoningHypothesisStatus
    confidence_level: ReasoningConfidence
    causal_claim: bool
    explanation: str
    limitations: list[str]
    unknowns: list[str]
    rule_id: str | None = None
    rule_version: str | None = None
    superseded_by_id: str | None = None
    created_at: datetime
    updated_at: datetime
    evidence: list[ReasoningEvidenceLinkView] = Field(default_factory=list)


class ReasoningDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_facts: list[str] = Field(default_factory=list)
    deterministic_findings: list[str] = Field(default_factory=list)
    candidate_causes: list[str] = Field(default_factory=list)
    verified_causes: list[str] = Field(default_factory=list)
    data_quality_issues: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    causal_limitations: list[str] = Field(default_factory=list)


class ReasoningAICandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=1000)
    explanation: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1, max_length=5)
    causal_claim: bool = True
    limitations: list[str] = Field(default_factory=list, max_length=5)
    unknowns: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence_ids must not contain duplicates")
        return value


class ReasoningAICandidateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[ReasoningAICandidate] = Field(max_length=5)


class ReasoningCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_count: int
    by_source: dict[str, int]
    by_classification: dict[str, int]
    invalid_count: int
    missing_collected_time: int
    late_arrivals: int
    future_clock_skew: int


class ReasoningBundleView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    environment_id: str
    name: str
    selection_basis: dict[str, Any]
    coverage: dict[str, Any]
    created_at: datetime


class ReasoningSessionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    environment_id: str
    question: str
    trigger: Literal["user", "system", "automation"]
    status: Literal["running", "completed", "failed"]
    scope: dict[str, Any]
    diagnosis: ReasoningDiagnosis
    analyzer_versions: dict[str, str]
    actor_type: str
    actor_id: str
    started_at: datetime
    completed_at: datetime | None = None
    created_at: datetime
    bundle: ReasoningBundleView | None = None
    hypotheses: list[ReasoningHypothesisView] = Field(default_factory=list)


class ReasoningSessionListData(BaseModel):
    data: list[ReasoningSessionView]
    page: int
    page_size: int
    total: int


class ReasoningSessionData(BaseModel):
    data: ReasoningSessionView


class ReasoningEvidenceListData(BaseModel):
    data: list[ReasoningEvidenceView]
    page: int
    page_size: int
    total: int


class ReasoningHypothesisListData(BaseModel):
    data: list[ReasoningHypothesisView]
    page: int
    page_size: int
    total: int


class ReasoningHypothesisData(BaseModel):
    data: ReasoningHypothesisView


class ReasoningSourceData(BaseModel):
    data: dict[str, Any]


__all__ = [
    "ReasoningAICandidate",
    "ReasoningAICandidateOutput",
    "ReasoningBundleView",
    "ReasoningConfidence",
    "ReasoningCoverage",
    "ReasoningDiagnosis",
    "ReasoningEvidenceClassification",
    "ReasoningEvidenceLinkView",
    "ReasoningEvidenceListData",
    "ReasoningEvidenceSource",
    "ReasoningEvidenceView",
    "ReasoningHypothesisData",
    "ReasoningHypothesisListData",
    "ReasoningHypothesisStatus",
    "ReasoningHypothesisType",
    "ReasoningHypothesisView",
    "ReasoningOrigin",
    "ReasoningSessionData",
    "ReasoningSessionListData",
    "ReasoningSessionView",
    "ReasoningSourceData",
]
