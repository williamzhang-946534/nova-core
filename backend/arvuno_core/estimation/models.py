from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

StateEstimationStatus = Literal[
    "observed",
    "derived",
    "inferred",
    "unknown",
    "stale",
    "unavailable",
    "conflict",
]


class RuleInfo(BaseModel):
    id: str
    version: str


class StateEstimateEvidence(BaseModel):
    observation_id: str
    source_id: str
    source_type: str
    entity_id: str | None = None
    space_id: str | None = None
    attribute: str
    normalized_value: Any | None = None
    normalized_unit: str | None = None
    observed_at: datetime | None = None
    observed_at_source: str | None = None
    received_at: datetime
    quality_status: str
    contribution: str
    weight: float | None = None
    exclusion_reason: str | None = None


class StateEstimateView(BaseModel):
    id: str
    target_id: str
    environment_id: str
    target_type: str
    entity_id: str | None = None
    space_id: str | None = None
    attribute: str
    status: StateEstimationStatus
    value: Any | None = None
    unit: str | None = None
    confidence: float | None = None
    evidence_summary: dict[str, Any]
    conflict_details: dict[str, Any] | None = None
    rule: RuleInfo
    input_cutoff_at: datetime
    effective_from: datetime
    generated_at: datetime
    valid_until: datetime | None = None
    superseded_at: datetime | None = None
    created_at: datetime


class StateRebuildResult(BaseModel):
    environment_id: str
    targets: int
    appended: int
    unchanged: int
    generated_at: datetime


class SpaceLayout(BaseModel):
    space_id: str
    parent_id: str | None
    space_type: str
    name: str
    path: list[str]
    status: str


class EntityLayout(BaseModel):
    entity_id: str
    name: str
    entity_type: str
    device_id: str | None = None
    space_id: str | None = None


class ContextInputs(BaseModel):
    environment_id: str
    root_space_id: str
    spaces: list[SpaceLayout]
    entities: list[EntityLayout]
    states: list[StateEstimateView]


class EntityContextV2(BaseModel):
    entity_id: str
    name: str
    entity_type: str
    device_id: str | None = None
    space_id: str | None = None
    states: dict[str, StateEstimateView] = Field(default_factory=dict)


class SpaceContextV2(BaseModel):
    space_id: str
    parent_id: str | None
    space_type: str
    name: str
    path: list[str]
    status: str
    states: dict[str, StateEstimateView] = Field(default_factory=dict)
    entities: list[EntityContextV2] = Field(default_factory=list)
    children: list["SpaceContextV2"] = Field(default_factory=list)


class EnvironmentContextV2(BaseModel):
    environment_id: str
    root_space_id: str
    generated_at: datetime
    spaces: list[SpaceContextV2]
    quality: dict[str, int]


__all__ = [
    "EntityContextV2",
    "EnvironmentContextV2",
    "RuleInfo",
    "ContextInputs",
    "EntityLayout",
    "SpaceLayout",
    "SpaceContextV2",
    "StateEstimateEvidence",
    "StateEstimateView",
    "StateEstimationStatus",
    "StateRebuildResult",
]
