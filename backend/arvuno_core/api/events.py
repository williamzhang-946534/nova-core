from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime

from arvuno_core.api.security import require_api_token
from arvuno_core.errors import ArvunoError
from arvuno_core.events.service import EventQueryService
from arvuno_core.schemas.events import EventDetailData, EventItem, EventListData

router = APIRouter(prefix="/api/events", tags=["Events"], dependencies=[Depends(require_api_token)])


def get_query_service(request: Request) -> EventQueryService:
    factory = request.app.state.unit_of_work_factory
    if factory is None:
        raise RuntimeError("The database unit-of-work factory is unavailable.")
    return EventQueryService(factory)


def _item(payload: object) -> EventItem:
    event = payload  # type: ignore[assignment]
    return EventItem(
        id=event.id,
        event_type=event.event_type.value,
        source=event.source.value,
        subject_type=event.subject_type,
        subject_id=event.subject_id,
        payload=event.payload.model_dump(mode="json"),
        correlation_id=event.correlation_id,
        occurred_at=event.occurred_at,
        created_at=event.created_at,
    )


@router.get("", response_model=EventListData)
async def list_events(
    service: Annotated[EventQueryService, Depends(get_query_service)],
    event_type: str | None = Query(default=None, max_length=100),
    source: str | None = Query(default=None, max_length=100),
    subject_type: str | None = Query(default=None, max_length=100),
    subject_id: str | None = Query(default=None, max_length=255),
    correlation_id: str | None = Query(default=None, max_length=100),
    start_time: AwareDatetime | None = None,
    end_time: AwareDatetime | None = None,
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> EventListData:
    result = await service.list(
        event_type=event_type,
        source=source,
        subject_type=subject_type,
        subject_id=subject_id,
        correlation_id=correlation_id,
        start_time=start_time,
        end_time=end_time,
        order=order,
        page=page,
        page_size=page_size,
    )
    return EventListData(
        data=[_item(event) for event in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


@router.get("/{event_id}", response_model=EventDetailData)
async def get_event(
    event_id: str,
    service: Annotated[EventQueryService, Depends(get_query_service)],
) -> EventDetailData:
    event = await service.get(event_id)
    if event is None:
        raise ArvunoError(
            code="NOT_FOUND",
            message="The event does not exist.",
            status_code=404,
        )
    return EventDetailData(data=_item(event))
