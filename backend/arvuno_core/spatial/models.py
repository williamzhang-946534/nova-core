from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SpaceType = Literal["home", "floor", "room", "zone"]
SpaceStatus = Literal["active", "inactive", "archived"]
AssignmentType = Literal[
    "fixed_installation",
    "current_placement",
    "observed_presence",
    "user_asserted",
]


class SpaceDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_id: str | None
    space_type: SpaceType
    name: str
    normalized_name: str
    slug: str
    path: str
    sort_order: int
    external_space_id: str | None = None
    external_source: str | None = None
    status: SpaceStatus
    geometry: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(
        validation_alias="metadata_summary",
        serialization_alias="metadata",
    )
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class SpaceTreeNode(SpaceDetail):
    children: list["SpaceTreeNode"] = Field(default_factory=list)


class AssignedDevice(BaseModel):
    device_id: str
    entity_id: str
    adapter_id: str
    external_id: str
    name: str
    device_type: str
    is_online: bool
    is_enabled: bool
    assignment_id: str
    assignment_type: AssignmentType
    valid_from: datetime
    valid_until: datetime | None = None
    confidence: float | None = None
    source_type: str
    source_id: str | None = None
    reason: str | None = None


class AssignmentHistoryItem(BaseModel):
    id: str
    entity_id: str
    device_id: str | None = None
    space_id: str
    space_name: str
    space_path: str
    assignment_type: AssignmentType
    valid_from: datetime
    valid_until: datetime | None = None
    confidence: float | None = None
    source_type: str
    source_id: str | None = None
    source_observation_id: str | None = None
    reason: str | None = None
    created_at: datetime
    updated_at: datetime


class DeviceAssignmentResult(BaseModel):
    assignment: AssignmentHistoryItem
    space: SpaceDetail


__all__ = [
    "AssignedDevice",
    "AssignmentHistoryItem",
    "AssignmentType",
    "DeviceAssignmentResult",
    "SpaceDetail",
    "SpaceStatus",
    "SpaceTreeNode",
    "SpaceType",
]
