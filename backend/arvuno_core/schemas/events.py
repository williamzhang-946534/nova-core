from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class EventItem(BaseModel):
    id: str
    event_type: str
    source: str
    subject_type: str | None = None
    subject_id: str | None = None
    payload: dict[str, Any]
    correlation_id: str | None = None
    occurred_at: datetime
    created_at: datetime


class EventListData(BaseModel):
    data: list[EventItem]
    page: int
    page_size: int
    total: int


class EventDetailData(BaseModel):
    data: EventItem


class ApiTokenRequiredError(BaseModel):
    code: Literal["UNAUTHORIZED"]
    message: str
