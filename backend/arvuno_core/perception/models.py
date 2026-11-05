from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from arvuno_core.observations.models import ObservationInput

GapType = Literal[
    "space_coverage",
    "time_coverage",
    "quality",
    "entity_identity",
    "post_action_verification",
    "procedure",
]

PrivacyLevel = Literal["normal", "sensitive"]

RequestStatus = Literal[
    "proposed",
    "awaiting_consent",
    "rejected",
    "queued",
    "executed",
    "fulfilled",
    "unavailable",
    "expired",
]


class ActivePerceptionRequestView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    environment_id: str
    reasoning_session_id: str
    hypothesis_id: str | None = None
    question: str
    gap_type: GapType
    subject_type: str
    subject_id: str
    space_id: str | None = None
    entity_id: str | None = None
    attribute: str | None = None
    needed_time_range: dict[str, Any]
    current_coverage: dict[str, Any]
    expected_value: dict[str, Any]
    would_resolve: dict[str, Any]
    proposed_capability: str | None = None
    proposed_input: dict[str, Any]
    privacy_level: PrivacyLevel
    requires_user_consent: bool
    authorized_at: datetime | None = None
    authorization_scope: dict[str, Any] | None = None
    cost_estimate: dict[str, Any]
    status: RequestStatus
    fulfilled_by_type: str | None = None
    fulfilled_by_id: str | None = None
    follow_up_reasoning_session_id: str | None = None
    unavailable_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None


class ActivePerceptionRequestData(BaseModel):
    data: ActivePerceptionRequestView


class ActivePerceptionRequestListData(BaseModel):
    data: list[ActivePerceptionRequestView]
    page: int
    page_size: int
    total: int


class ActivePerceptionDeleteData(BaseModel):
    id: str
    deleted: bool
    expired_count: int = 0


class ActivePerceptionDeleteWrapper(BaseModel):
    data: ActivePerceptionDeleteData


class PerceptionObserverProtocol(Protocol):
    """Read-only observer contract used to acquire a real observation."""

    async def observe(
        self,
        request: ActivePerceptionRequestView,
    ) -> ObservationInput | None:
        raise NotImplementedError


__all__ = [
    "ActivePerceptionDeleteData",
    "ActivePerceptionDeleteWrapper",
    "ActivePerceptionRequestData",
    "ActivePerceptionRequestListData",
    "ActivePerceptionRequestView",
    "GapType",
    "PerceptionObserverProtocol",
    "PrivacyLevel",
    "RequestStatus",
]
