from pydantic import AwareDatetime, BaseModel, Field

from arvuno_core.history.models import (
    CorrelatedHistory,
    EntityHistoryResult,
    HistoryQueryResult,
    NaturalHistoryAnswer,
    SnapshotDiffResult,
    SnapshotLookupResult,
    SpatialHistoryResult,
    TrendQueryResult,
)


class SnapshotDiffRequest(BaseModel):
    baseline_id: str | None = Field(default=None, min_length=1, max_length=36)
    target_id: str | None = Field(default=None, min_length=1, max_length=36)
    baseline_at: AwareDatetime | None = None
    target_at: AwareDatetime | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=100)


class HistoryAskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=100)
    now: AwareDatetime | None = None


class HistoryQueryData(BaseModel):
    data: HistoryQueryResult


class SpatialHistoryData(BaseModel):
    data: SpatialHistoryResult


class EntityHistoryData(BaseModel):
    data: EntityHistoryResult


class TrendHistoryData(BaseModel):
    data: TrendQueryResult


class SnapshotLookupData(BaseModel):
    data: SnapshotLookupResult


class SnapshotDiffData(BaseModel):
    data: SnapshotDiffResult


class CorrelatedHistoryData(BaseModel):
    data: CorrelatedHistory


class NaturalHistoryData(BaseModel):
    data: NaturalHistoryAnswer


__all__ = [
    "CorrelatedHistoryData",
    "EntityHistoryData",
    "HistoryAskRequest",
    "HistoryQueryData",
    "NaturalHistoryData",
    "SnapshotDiffData",
    "SnapshotDiffRequest",
    "SnapshotLookupData",
    "SpatialHistoryData",
    "TrendHistoryData",
]
