from typing import Literal

from pydantic import BaseModel, Field


class ProactiveFeedbackRequest(BaseModel):
    useful: bool | None = None
    correct: bool | None = None
    comment: str | None = Field(default=None, max_length=2000)
    desired_action: Literal["accept", "dismiss", "do_not_remind", "more_detail"] | None = None


class ProactiveDismissRequest(BaseModel):
    feedback: str | None = Field(default=None, max_length=2000)
    suppress_future: bool = False
    suppression_hours: int = Field(default=24, ge=1, le=24 * 365)


class ProactiveAcceptRequest(BaseModel):
    feedback: str | None = Field(default=None, max_length=2000)


__all__ = [
    "ProactiveAcceptRequest",
    "ProactiveDismissRequest",
    "ProactiveFeedbackRequest",
]
