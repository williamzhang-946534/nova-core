from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from arvuno_core.estimation.models import StateEstimateEvidence, StateEstimateView

EnvironmentCoverageStatus = Literal["covered", "partial", "blind", "lost"]


class EnvironmentStateQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=36)
    space_path: str | None = Field(default=None, min_length=1, max_length=1024)
    attributes: list[str] = Field(default_factory=list)
    include_descendants: bool = True
    include_evidence: bool = False

    @model_validator(mode="after")
    def validate_space_selection(self) -> "EnvironmentStateQueryInput":
        if self.space_id is not None and self.space_path is not None:
            raise ValueError("Provide either space_id or space_path, not both")
        if len(set(self.attributes)) != len(self.attributes):
            raise ValueError("attributes must not contain duplicates")
        if any(not attribute.strip() for attribute in self.attributes):
            raise ValueError("attributes must not contain blank values")
        return self


class QueriedSpaceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str
    parent_id: str | None = None
    space_type: str
    name: str
    path: list[str]
    status: str
    state_ids: list[str] = Field(default_factory=list)


class QueriedEntitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    name: str
    entity_type: str
    device_id: str | None = None
    space_id: str | None = None
    state_ids: list[str] = Field(default_factory=list)


class StateCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str
    attribute: str
    coverage: EnvironmentCoverageStatus
    state_status: str | None = None
    source_count: int = 0
    explanation: str


class QuerySourceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_type: str | None = None
    observation_count: int
    entity_ids: list[str] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)


class QueryExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    space_id: str | None = None
    entity_id: str | None = None
    attribute: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class EnvironmentQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_available: bool = True
    environment_id: str | None = None
    environment_name: str | None = None
    root_space_id: str | None = None
    selected_space: QueriedSpaceSummary | None = None
    spaces: list[QueriedSpaceSummary] = Field(default_factory=list)
    entities: list[QueriedEntitySummary] = Field(default_factory=list)
    states: list[StateEstimateView] = Field(default_factory=list)
    coverage: list[StateCoverage] = Field(default_factory=list)
    sources: list[QuerySourceSummary] = Field(default_factory=list)
    explanations: list[QueryExplanation] = Field(default_factory=list)
    evidence: list[StateEstimateEvidence] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)
    include_descendants: bool = True
    generated_at: datetime


__all__ = [
    "EnvironmentCoverageStatus",
    "EnvironmentQueryResult",
    "EnvironmentStateQueryInput",
    "QueriedEntitySummary",
    "QueriedSpaceSummary",
    "QueryExplanation",
    "QuerySourceSummary",
    "StateCoverage",
]
