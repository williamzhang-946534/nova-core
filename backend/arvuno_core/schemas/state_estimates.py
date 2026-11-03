from pydantic import BaseModel

from arvuno_core.estimation.models import (
    EnvironmentContextV2,
    SpaceContextV2,
    StateEstimateEvidence,
    StateEstimateView,
    StateRebuildResult,
)


class StateEstimateListData(BaseModel):
    data: list[StateEstimateView]
    page: int
    page_size: int
    total: int


class StateEstimateDetailData(BaseModel):
    data: StateEstimateView


class StateEstimateEvidenceListData(BaseModel):
    data: list[StateEstimateEvidence]


class StateRebuildDataWrapper(BaseModel):
    data: StateRebuildResult


class EnvironmentContextV2DataWrapper(BaseModel):
    data: EnvironmentContextV2


class EnvironmentContextV2RebuildData(BaseModel):
    context: EnvironmentContextV2
    anomaly_count: int


class EnvironmentContextV2RebuildDataWrapper(BaseModel):
    data: EnvironmentContextV2RebuildData


class SpaceStateDataWrapper(BaseModel):
    data: SpaceContextV2


__all__ = [
    "EnvironmentContextV2DataWrapper",
    "EnvironmentContextV2RebuildDataWrapper",
    "SpaceStateDataWrapper",
    "StateEstimateDetailData",
    "StateEstimateEvidenceListData",
    "StateEstimateListData",
    "StateRebuildDataWrapper",
]
