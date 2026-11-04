from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

HistoryRecordType = Literal["observation", "event", "task", "snapshot"]
QueryTimeBasis = Literal["received_at", "occurred_at", "created_at"]
SnapshotRecoverability = Literal[
    "device_command_candidate",
    "physical_observation",
    "system_projection",
    "metadata_only",
    "unknown",
]


class TimeSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_timezone: str = "UTC"
    local_timezone: str
    query_time_basis: QueryTimeBasis
    collected_time_available: int = 0
    received_time_available: int = 0
    processed_time_available: int = 0
    late_arrival_threshold_seconds: int = 60
    clock_skew_tolerance_seconds: int = 30
    late_observations: list[str] = Field(default_factory=list)
    future_clock_skew_observations: list[str] = Field(default_factory=list)
    observations_without_collected_time: list[str] = Field(default_factory=list)


class HistoryTimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_time: datetime
    end_time: datetime
    local_start_time: str
    local_end_time: str


class TimeGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_time: datetime
    end_time: datetime
    duration_seconds: int
    reason: str


class HistoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: HistoryRecordType
    record_id: str
    collected_at: datetime | None = None
    received_at: datetime | None = None
    processed_at: datetime | None = None
    occurred_at: datetime | None = None
    local_time: str | None = None
    source: str | None = None
    entity_id: str | None = None
    space_id: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    attribute: str | None = None
    value: Any | None = None
    unit: str | None = None
    quality_status: str | None = None
    correlation_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class TrendStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_key: str
    label: str
    attribute: str
    observation_count: int
    valid_count: int
    numeric_count: int
    minimum: float | None = None
    maximum: float | None = None
    average: float | None = None
    first_value: float | None = None
    last_value: float | None = None
    change: float | None = None
    change_per_hour: float | None = None
    first_at: datetime | None = None
    last_at: datetime | None = None
    unit: str | None = None


class HistoryQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    range: HistoryTimeRange
    time_semantics: TimeSemantics
    records: list[HistoryRecord] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    missing_ranges: list[TimeGap] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime


class SpatialHistoryResult(HistoryQueryResult):
    model_config = ConfigDict(extra="forbid")

    space_id: str
    space_name: str | None = None
    include_descendants: bool = True
    descendants: list[str] = Field(default_factory=list)
    assignments_in_range: list[dict[str, Any]] = Field(default_factory=list)


class EntityHistoryResult(HistoryQueryResult):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    entity_name: str | None = None
    device_id: str | None = None
    space_assignments: list[dict[str, Any]] = Field(default_factory=list)


class TrendQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    range: HistoryTimeRange
    time_semantics: TimeSemantics
    attribute: str
    group_by: Literal["space", "entity"]
    include_descendants: bool = True
    statistics: list[TrendStatistics] = Field(default_factory=list)
    missing_ranges: list[TimeGap] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime


class EnvironmentSnapshotView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    environment_id: str
    context: dict[str, Any]
    active_task_ids: list[str] = Field(default_factory=list)
    anomaly_count: int
    context_version: int
    state_generated_at: datetime | None = None
    created_at: datetime
    local_created_at: str


class SnapshotLookupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_at: datetime
    snapshot: EnvironmentSnapshotView | None = None
    local_requested_at: str
    selection: Literal["at_or_before", "nearest"]
    distance_seconds: int | None = None
    state_as_of: datetime | None = None
    warning: str | None = None


class SnapshotDiffEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    before: Any | None = None
    after: Any | None = None
    change_type: Literal["added", "removed", "changed"]
    recoverability: SnapshotRecoverability
    recoverable_by_device: bool = False
    physical_rollback_possible: bool = False
    explanation: str


class SnapshotDiffResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline: EnvironmentSnapshotView
    target: EnvironmentSnapshotView
    changes: list[SnapshotDiffEntry] = Field(default_factory=list)
    unchanged_count: int
    device_recoverable_paths: list[str] = Field(default_factory=list)
    physical_change_paths: list[str] = Field(default_factory=list)
    missing_data_paths: list[str] = Field(default_factory=list)
    reality_git: dict[str, str] = Field(default_factory=dict)
    generated_at: datetime


class CorrelatedHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: HistoryRecord
    events: list[HistoryRecord] = Field(default_factory=list)
    tasks: list[HistoryRecord] = Field(default_factory=list)
    observations: list[HistoryRecord] = Field(default_factory=list)
    snapshots: list[EnvironmentSnapshotView] = Field(default_factory=list)
    relation_basis: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class NaturalHistoryInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_type: Literal[
        "events_in_space",
        "space_ranking",
        "entity_attribute_trend",
        "running_devices",
        "unsupported",
    ]
    confidence: float
    explanation: str
    action: str | None = None
    action_resolved: bool = False
    space_id: str | None = None
    entity_id: str | None = None
    attribute: str | None = None


class NaturalHistoryAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    interpretation: NaturalHistoryInterpretation
    range: HistoryTimeRange
    time_semantics: TimeSemantics
    answer: str
    based_on_record_count: int
    records: list[HistoryRecord] = Field(default_factory=list)
    statistics: list[TrendStatistics] = Field(default_factory=list)
    snapshots: list[EnvironmentSnapshotView] = Field(default_factory=list)
    missing_ranges: list[TimeGap] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime


__all__ = [
    "CorrelatedHistory",
    "EntityHistoryResult",
    "EnvironmentSnapshotView",
    "HistoryQueryResult",
    "HistoryRecord",
    "HistoryRecordType",
    "HistoryTimeRange",
    "QueryTimeBasis",
    "NaturalHistoryAnswer",
    "NaturalHistoryInterpretation",
    "SnapshotDiffEntry",
    "SnapshotDiffResult",
    "SnapshotLookupResult",
    "SpatialHistoryResult",
    "TimeGap",
    "TimeSemantics",
    "TrendQueryResult",
    "TrendStatistics",
]
