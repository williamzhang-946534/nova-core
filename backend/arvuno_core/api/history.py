from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime

from arvuno_core.api.security import require_api_token
from arvuno_core.history.service import HistoryService
from arvuno_core.schemas.history import (
    CorrelatedHistoryData,
    EntityHistoryData,
    HistoryAskRequest,
    HistoryQueryData,
    NaturalHistoryData,
    SnapshotDiffData,
    SnapshotDiffRequest,
    SnapshotLookupData,
    SpatialHistoryData,
    TrendHistoryData,
)

router = APIRouter(
    prefix="/api/history",
    tags=["History"],
    dependencies=[Depends(require_api_token)],
)


def get_history_service(request: Request) -> HistoryService:
    service = getattr(request.app.state, "history_service", None)
    if not isinstance(service, HistoryService):
        raise RuntimeError("The history service is unavailable.")
    return service


@router.get("/time-range", response_model=HistoryQueryData)
async def time_range_history(
    service: Annotated[HistoryService, Depends(get_history_service)],
    start_time: AwareDatetime,
    end_time: AwareDatetime,
    timezone: str = Query(default="UTC", min_length=1, max_length=100),
    entity_id: str | None = Query(default=None, min_length=1, max_length=36),
    space_id: str | None = Query(default=None, min_length=1, max_length=36),
    include_descendants: bool = True,
    attribute: str | None = Query(default=None, min_length=1, max_length=50),
    quality_status: str | None = Query(default=None, min_length=1, max_length=50),
    expected_interval_seconds: int | None = Query(default=None, ge=1),
    limit: int = Query(default=500, ge=1, le=2000),
) -> HistoryQueryData:
    return HistoryQueryData(
        data=await service.time_range(
            start_time=start_time,
            end_time=end_time,
            timezone=timezone,
            entity_id=entity_id,
            space_id=space_id,
            include_descendants=include_descendants,
            attribute=attribute,
            quality_status=quality_status,
            expected_interval_seconds=expected_interval_seconds,
            limit=limit,
        )
    )


@router.get("/spaces/{space_id}", response_model=SpatialHistoryData)
async def spatial_history(
    space_id: str,
    service: Annotated[HistoryService, Depends(get_history_service)],
    start_time: AwareDatetime,
    end_time: AwareDatetime,
    timezone: str = Query(default="UTC", min_length=1, max_length=100),
    include_descendants: bool = True,
    attribute: str | None = Query(default=None, min_length=1, max_length=50),
    expected_interval_seconds: int | None = Query(default=None, ge=1),
    limit: int = Query(default=500, ge=1, le=2000),
) -> SpatialHistoryData:
    return SpatialHistoryData(
        data=await service.spatial_history(
            space_id,
            start_time=start_time,
            end_time=end_time,
            timezone=timezone,
            include_descendants=include_descendants,
            attribute=attribute,
            expected_interval_seconds=expected_interval_seconds,
            limit=limit,
        )
    )


@router.get("/entities/{entity_id}", response_model=EntityHistoryData)
async def entity_history(
    entity_id: str,
    service: Annotated[HistoryService, Depends(get_history_service)],
    start_time: AwareDatetime,
    end_time: AwareDatetime,
    timezone: str = Query(default="UTC", min_length=1, max_length=100),
    attribute: str | None = Query(default=None, min_length=1, max_length=50),
    expected_interval_seconds: int | None = Query(default=None, ge=1),
    limit: int = Query(default=500, ge=1, le=2000),
) -> EntityHistoryData:
    return EntityHistoryData(
        data=await service.entity_history(
            entity_id,
            start_time=start_time,
            end_time=end_time,
            timezone=timezone,
            attribute=attribute,
            expected_interval_seconds=expected_interval_seconds,
            limit=limit,
        )
    )


@router.get("/trends", response_model=TrendHistoryData)
async def history_trends(
    service: Annotated[HistoryService, Depends(get_history_service)],
    start_time: AwareDatetime,
    end_time: AwareDatetime,
    attribute: str = Query(min_length=1, max_length=50),
    timezone: str = Query(default="UTC", min_length=1, max_length=100),
    group_by: Literal["space", "entity"] = "space",
    space_id: str | None = Query(default=None, min_length=1, max_length=36),
    entity_id: str | None = Query(default=None, min_length=1, max_length=36),
    include_descendants: bool = True,
    limit: int = Query(default=1000, ge=1, le=5000),
) -> TrendHistoryData:
    return TrendHistoryData(
        data=await service.trends(
            start_time=start_time,
            end_time=end_time,
            attribute=attribute,
            timezone=timezone,
            group_by=group_by,
            space_id=space_id,
            entity_id=entity_id,
            include_descendants=include_descendants,
            limit=limit,
        )
    )


@router.get("/environment/snapshot", response_model=SnapshotLookupData)
async def environment_snapshot(
    service: Annotated[HistoryService, Depends(get_history_service)],
    at_time: AwareDatetime,
    timezone: str = Query(default="UTC", min_length=1, max_length=100),
    environment_id: str | None = Query(default=None, min_length=1, max_length=36),
    nearest: bool = False,
) -> SnapshotLookupData:
    return SnapshotLookupData(
        data=await service.snapshot_at(
            at_time=at_time,
            timezone=timezone,
            environment_id=environment_id,
            nearest=nearest,
        )
    )


@router.post("/environment/snapshots/diff", response_model=SnapshotDiffData)
async def environment_snapshot_diff(
    request: SnapshotDiffRequest,
    service: Annotated[HistoryService, Depends(get_history_service)],
) -> SnapshotDiffData:
    return SnapshotDiffData(
        data=await service.snapshot_diff(
            baseline_id=request.baseline_id,
            target_id=request.target_id,
            baseline_at=request.baseline_at,
            target_at=request.target_at,
            timezone=request.timezone,
        )
    )


@router.get("/correlations/{record_type}/{record_id}", response_model=CorrelatedHistoryData)
async def correlated_history(
    record_type: Literal["observation", "event", "task"],
    record_id: str,
    service: Annotated[HistoryService, Depends(get_history_service)],
    timezone: str = Query(default="UTC", min_length=1, max_length=100),
) -> CorrelatedHistoryData:
    return CorrelatedHistoryData(
        data=await service.correlate(
            record_type=record_type,
            record_id=record_id,
            timezone=timezone,
        )
    )


@router.post("/ask", response_model=NaturalHistoryData)
async def ask_history(
    request: HistoryAskRequest,
    service: Annotated[HistoryService, Depends(get_history_service)],
) -> NaturalHistoryData:
    return NaturalHistoryData(
        data=await service.ask(request.query, timezone=request.timezone, now=request.now)
    )


__all__ = ["router"]
