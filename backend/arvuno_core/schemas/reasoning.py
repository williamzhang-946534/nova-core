from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field


class ReasoningDiagnoseRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    environment_id: str | None = Field(default=None, min_length=1, max_length=36)
    space_id: str | None = Field(default=None, min_length=1, max_length=36)
    space_name: str | None = Field(default=None, min_length=1, max_length=255)
    entity_id: str | None = Field(default=None, min_length=1, max_length=36)
    attribute: str | None = Field(default=None, min_length=1, max_length=50)
    start_time: AwareDatetime | None = None
    end_time: AwareDatetime | None = None
    now: AwareDatetime | None = None
    lookback_seconds: int = Field(default=86400, ge=60, le=366 * 86400)
    trigger: Literal["user", "system", "automation"] = "user"
    actor_type: str = Field(default="user", min_length=1, max_length=50)
    actor_id: str = Field(default="local_user", min_length=1, max_length=100)


class ReasoningDeleteData(BaseModel):
    id: str
    deleted: bool


class ReasoningDeleteWrapper(BaseModel):
    data: ReasoningDeleteData


__all__ = [
    "ReasoningDeleteData",
    "ReasoningDeleteWrapper",
    "ReasoningDiagnoseRequest",
]
