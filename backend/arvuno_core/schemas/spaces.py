from typing import Any

from pydantic import BaseModel, Field

from arvuno_core.environment.query_models import EnvironmentQueryResult, StateCoverage
from arvuno_core.spatial.models import (
    AssignedDevice,
    AssignmentHistoryItem,
    DeviceAssignmentResult,
    SpaceDetail,
    SpaceStatus,
    SpaceTreeNode,
    SpaceType,
)


class SpaceCreateRequest(BaseModel):
    parent_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=255)
    space_type: SpaceType
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    sort_order: int = Field(default=0, ge=0)
    external_space_id: str | None = Field(default=None, max_length=255)
    external_source: str | None = Field(default=None, max_length=100)
    geometry: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SpaceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=255)
    sort_order: int | None = Field(default=None, ge=0)
    status: SpaceStatus | None = None
    external_space_id: str | None = Field(default=None, max_length=255)
    external_source: str | None = Field(default=None, max_length=100)
    geometry: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class SpaceMoveRequest(BaseModel):
    new_parent_id: str = Field(min_length=1)


class DeviceAssignmentRequest(BaseModel):
    space_id: str = Field(min_length=1)
    assignment_type: str = Field(
        default="fixed_installation",
        pattern="^(fixed_installation|current_placement|observed_presence|user_asserted)$",
    )
    confidence: float = Field(default=1.0, ge=0, le=1)
    source_type: str = Field(default="user", max_length=50)
    source_id: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=2000)


class SpaceListData(BaseModel):
    data: list[SpaceDetail]


class SpaceTreeData(BaseModel):
    data: SpaceTreeNode


class SpaceDetailData(BaseModel):
    data: SpaceDetail


class SpaceDeviceListData(BaseModel):
    data: list[AssignedDevice]


class SpaceOverviewData(BaseModel):
    data: EnvironmentQueryResult


class SpaceCoverageData(BaseModel):
    data: list[StateCoverage]


class DeviceAssignmentData(BaseModel):
    data: DeviceAssignmentResult


class DeviceAssignmentHistoryData(BaseModel):
    data: list[AssignmentHistoryItem]


__all__ = [
    "DeviceAssignmentData",
    "DeviceAssignmentHistoryData",
    "DeviceAssignmentRequest",
    "SpaceCreateRequest",
    "SpaceDetailData",
    "SpaceDeviceListData",
    "SpaceCoverageData",
    "SpaceListData",
    "SpaceOverviewData",
    "SpaceMoveRequest",
    "SpaceTreeData",
    "SpaceUpdateRequest",
]
