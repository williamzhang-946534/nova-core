from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ObservationItem(BaseModel):
    observation_id: str
    source_id: str
    source_type: str
    entity_id: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    space_id: str | None = None
    attribute: str
    raw_value: Any | None = None
    raw_unit: str | None = None
    normalized_value: Any | None = None
    normalized_unit: str | None = None
    value_type: str
    observed_at: datetime | None = None
    observed_at_source: str | None = None
    observed_at_uncertainty_ms: int | None = None
    received_at: datetime
    processed_at: datetime | None = None
    quality_status: str
    quality_issues: list[dict[str, Any]] = Field(default_factory=list)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    freshness_policy: str | None = None
    freshness_evaluated_at: datetime | None = None
    correlation_id: str | None = None
    external_id: str | None = None
    dedupe_key: str
    payload_hash: str
    normalization_rule_version: str | None = None
    retention_class: str
    retention_until: datetime | None = None
    created_at: datetime | None = None


class ObservationListData(BaseModel):
    data: list[ObservationItem]
    page: int
    page_size: int
    total: int


class ObservationDetailData(BaseModel):
    data: ObservationItem


class ObservationSourceItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_type: str
    adapter_id: str | None
    name: str
    status: str
    trust_level: float
    time_trust: str
    config: dict[str, Any]
    privacy_scope: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ObservationSourceListData(BaseModel):
    data: list[ObservationSourceItem]


__all__ = [
    "ObservationDetailData",
    "ObservationItem",
    "ObservationListData",
    "ObservationSourceItem",
    "ObservationSourceListData",
]
