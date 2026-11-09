from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field


class ActivePerceptionEvaluateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    environment_id: str | None = Field(default=None, min_length=1, max_length=36)
    reasoning_session_id: str | None = Field(default=None, min_length=1, max_length=36)
    hypothesis_id: str | None = Field(default=None, min_length=1, max_length=36)
    space_id: str | None = Field(default=None, min_length=1, max_length=36)
    entity_id: str | None = Field(default=None, min_length=1, max_length=36)
    attribute: str = Field(min_length=1, max_length=50)
    preferred_source_type: str | None = Field(default=None, max_length=50)
    gap_type: Literal[
        "space_coverage",
        "time_coverage",
        "quality",
        "entity_identity",
        "post_action_verification",
        "procedure",
    ] = "space_coverage"
    start_time: AwareDatetime | None = None
    end_time: AwareDatetime | None = None
    now: AwareDatetime | None = None
    time_limit_seconds: int = Field(default=300, ge=30, le=86400)
    max_cost_score: float = Field(default=10.0, ge=0, le=100)
    min_trust_level: float = Field(default=0.2, ge=0, le=1)


class ActivePerceptionAuthorizeRequest(BaseModel):
    scope: dict[str, str | bool | int | float] | None = None
    authorization_seconds: int = Field(default=3600, ge=60, le=86400)


class RobotMobilePerceptionAuthorizeRequest(BaseModel):
    confirmed_navigation: bool
    confirmed_camera_capture: bool
    authorization_seconds: int = Field(default=3600, ge=60, le=86400)


class RobotMobilePerceptionEvaluateRequest(BaseModel):
    request: ActivePerceptionEvaluateRequest
    robot_id: str | None = Field(default=None, min_length=1, max_length=36)


class ActivePerceptionRejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


__all__ = [
    "ActivePerceptionAuthorizeRequest",
    "ActivePerceptionEvaluateRequest",
    "ActivePerceptionRejectRequest",
    "RobotMobilePerceptionAuthorizeRequest",
    "RobotMobilePerceptionEvaluateRequest",
]
