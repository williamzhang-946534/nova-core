from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

TimeSource = Literal[
    "device_clock",
    "gateway_state_clock",
    "poll_clock",
    "user_asserted",
    "derived",
    "unknown",
]
QualityStatus = Literal["pending", "valid", "warning", "invalid"]


class ObservationInput(BaseModel):
    source_id: str | None = Field(default=None, min_length=1)
    adapter_id: str | None = Field(default=None, min_length=1)
    device_id: str | None = Field(default=None, min_length=1)
    device_external_id: str | None = Field(default=None, min_length=1, max_length=255)
    entity_id: str | None = Field(default=None, min_length=1)
    subject_type: str | None = Field(default=None, min_length=1, max_length=50)
    subject_id: str | None = Field(default=None, min_length=1, max_length=255)
    space_id: str | None = Field(default=None, min_length=1)
    attribute: str = Field(min_length=1, max_length=50)
    raw_value: Any
    raw_unit: str | None = Field(default=None, max_length=50)
    observed_at: datetime | None = None
    observed_at_source: TimeSource | None = None
    observed_at_uncertainty_ms: int | None = Field(default=None, ge=0)
    received_at: datetime
    correlation_id: str | None = Field(default=None, max_length=100)
    external_id: str | None = Field(default=None, max_length=255)
    poll_window: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_identity(self) -> "ObservationInput":
        if (self.subject_type is None) != (self.subject_id is None):
            raise ValueError("subject_type and subject_id must be provided together.")
        has_subject = self.subject_type is not None and self.subject_id is not None
        if self.adapter_id is not None and self.device_id is not None:
            raise ValueError("Use adapter_id or device_id, not both.")
        if self.entity_id is not None and has_subject:
            raise ValueError("An entity and a non-entity subject cannot both be primary.")
        if (
            self.entity_id is None
            and not has_subject
            and self.adapter_id is None
            and self.device_id is None
        ):
            raise ValueError("An observation requires a subject or a device identity.")
        return self


class ObservationRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    observation_id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str
    source_type: str
    entity_id: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    space_id: str | None = None
    attribute: str
    raw_value: Any
    raw_unit: str | None = None
    normalized_value: Any = None
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


class ObservationResult(BaseModel):
    data: ObservationRecord
    duplicate: bool = False


class ObservationSourceRecord(BaseModel):
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


class ObservationPage(BaseModel):
    data: list[ObservationRecord]
    page: int
    page_size: int
    total: int


__all__ = [
    "ObservationInput",
    "ObservationPage",
    "ObservationRecord",
    "ObservationResult",
    "ObservationSourceRecord",
    "QualityStatus",
]
