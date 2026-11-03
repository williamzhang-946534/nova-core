from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime

from arvuno_core.api.security import require_api_token
from arvuno_core.observations.models import (
    ObservationRecord,
    ObservationSourceRecord,
)
from arvuno_core.observations.service import ObservationService
from arvuno_core.schemas.observations import (
    ObservationDetailData,
    ObservationItem,
    ObservationListData,
    ObservationSourceItem,
    ObservationSourceListData,
)

router = APIRouter(
    prefix="/api/observations",
    tags=["Observations"],
    dependencies=[Depends(require_api_token)],
)
source_router = APIRouter(
    prefix="/api/observation-sources",
    tags=["Observations"],
    dependencies=[Depends(require_api_token)],
)


def get_observation_service(request: Request) -> ObservationService:
    service = getattr(request.app.state, "observation_service", None)
    if not isinstance(service, ObservationService):
        raise RuntimeError("The observation service is unavailable.")
    return service


def _item(record: ObservationRecord, *, include_raw: bool) -> ObservationItem:
    return ObservationItem(
        **record.model_dump(
            exclude={"raw_value"},
        ),
        raw_value=record.raw_value if include_raw else None,
    )


def _source_item(record: ObservationSourceRecord) -> ObservationSourceItem:
    return ObservationSourceItem.model_validate(record)


@router.get("", response_model=ObservationListData)
async def list_observations(
    service: Annotated[ObservationService, Depends(get_observation_service)],
    source_id: str | None = Query(default=None, min_length=1),
    entity_id: str | None = Query(default=None, min_length=1),
    space_id: str | None = Query(default=None, min_length=1),
    attribute: str | None = Query(default=None, min_length=1, max_length=50),
    quality_status: Literal["pending", "valid", "warning", "invalid"] | None = None,
    start_time: AwareDatetime | None = None,
    end_time: AwareDatetime | None = None,
    correlation_id: str | None = Query(default=None, min_length=1, max_length=100),
    external_id: str | None = Query(default=None, min_length=1, max_length=255),
    include_raw: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ObservationListData:
    result = await service.query(
        source_id=source_id,
        entity_id=entity_id,
        space_id=space_id,
        attribute=attribute,
        quality_status=quality_status,
        start_time=start_time,
        end_time=end_time,
        correlation_id=correlation_id,
        external_id=external_id,
        page=page,
        page_size=page_size,
    )
    return ObservationListData(
        data=[_item(item, include_raw=include_raw) for item in result.data],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )


@router.get("/{observation_id}", response_model=ObservationDetailData)
async def get_observation(
    observation_id: str,
    service: Annotated[ObservationService, Depends(get_observation_service)],
    include_raw: bool = False,
) -> ObservationDetailData:
    record = await service.get(observation_id)
    return ObservationDetailData(data=_item(record, include_raw=include_raw))


@source_router.get("", response_model=ObservationSourceListData)
async def list_observation_sources(
    service: Annotated[ObservationService, Depends(get_observation_service)],
) -> ObservationSourceListData:
    sources = await service.list_sources()
    return ObservationSourceListData(data=[_source_item(source) for source in sources])


__all__ = ["router", "source_router"]
