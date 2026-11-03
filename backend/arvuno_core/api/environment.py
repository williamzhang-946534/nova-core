import asyncio
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from arvuno_core.api.security import require_api_token
from arvuno_core.environment.context import EnvironmentContextService, area_summary
from arvuno_core.environment.context_v2 import EnvironmentContextV2Service
from arvuno_core.events.service import EventQueryService
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.schemas.console import (
    EnvironmentDataWrapper,
    EnvironmentSnapshotItem,
    EnvironmentSnapshotListData,
    EnvironmentSummary,
)
from arvuno_core.schemas.events import EventItem
from arvuno_core.schemas.state_estimates import (
    EnvironmentContextV2DataWrapper,
    EnvironmentContextV2RebuildDataWrapper,
)


def get_unit_of_work_factory(request: Request) -> Callable[[], SqlAlchemyUnitOfWork]:
    factory = getattr(request.app.state, "unit_of_work_factory", None)
    if not callable(factory):
        raise RuntimeError("The database unit-of-work factory is unavailable.")
    return factory


router = APIRouter(
    prefix="/api/environment",
    tags=["Environment"],
    dependencies=[Depends(require_api_token)],
)


def get_environment_service(request: Request) -> EnvironmentContextService:
    service = getattr(request.app.state, "environment_context", None)
    if not isinstance(service, EnvironmentContextService):
        raise RuntimeError("The environment service is unavailable.")
    return service


def get_environment_v2_service(request: Request) -> EnvironmentContextV2Service:
    service = getattr(request.app.state, "environment_context_v2", None)
    if not isinstance(service, EnvironmentContextV2Service):
        raise RuntimeError("The environment context v2 service is unavailable.")
    return service


def _event_item(payload: object) -> EventItem:
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


def _active_task_count(factory: Callable[[], SqlAlchemyUnitOfWork]) -> int:
    with factory() as unit_of_work:
        if unit_of_work.tasks is None:
            raise RuntimeError("The task repository is unavailable.")
        return unit_of_work.tasks.count_active()


@router.get("", response_model=EnvironmentDataWrapper)
async def get_environment(
    request: Request,
    service: Annotated[EnvironmentContextService, Depends(get_environment_service)],
    unit_of_work_factory: Annotated[
        Callable[[], SqlAlchemyUnitOfWork], Depends(get_unit_of_work_factory)
    ],
) -> EnvironmentDataWrapper:
    if service.state.environment_id is None:
        await service.initialize()
    state = service.state
    active_task_count, recent = await asyncio.gather(
        asyncio.to_thread(_active_task_count, unit_of_work_factory),
        EventQueryService(unit_of_work_factory).list(page=1, page_size=10),
    )
    return EnvironmentDataWrapper(
        data=EnvironmentSummary(
            environment=state,
            areas=area_summary(state),
            online_device_count=sum(
                device.state != "unavailable" for device in state.devices.values()
            ),
            unavailable_device_ids=state.unavailable_device_ids,
            active_task_count=active_task_count,
            recent_events=[_event_item(event) for event in recent.items],
        )
    )


@router.get("/context-v2", response_model=EnvironmentContextV2DataWrapper)
async def get_environment_context_v2(
    service: Annotated[EnvironmentContextV2Service, Depends(get_environment_v2_service)],
) -> EnvironmentContextV2DataWrapper:
    return EnvironmentContextV2DataWrapper(data=await service.build())


@router.post("/context-v2/rebuild", response_model=EnvironmentContextV2RebuildDataWrapper)
async def rebuild_environment_context_v2(
    service: Annotated[EnvironmentContextV2Service, Depends(get_environment_v2_service)],
) -> EnvironmentContextV2RebuildDataWrapper:
    context, anomaly_count = await service.rebuild_snapshot()
    return EnvironmentContextV2RebuildDataWrapper(
        data={"context": context, "anomaly_count": anomaly_count}
    )


@router.get("/snapshots", response_model=EnvironmentSnapshotListData)
async def list_environment_snapshots(
    request: Request,
    unit_of_work_factory: Annotated[
        Callable[[], SqlAlchemyUnitOfWork], Depends(get_unit_of_work_factory)
    ],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> EnvironmentSnapshotListData:
    service = get_environment_service(request)
    if service.state.environment_id is None:
        await service.initialize()
    environment_id = service.state.environment_id
    if environment_id is None:
        return EnvironmentSnapshotListData(data=[], page=page, page_size=page_size, total=0)

    def query() -> tuple[list[EnvironmentSnapshotItem], int]:
        with unit_of_work_factory() as unit_of_work:
            if unit_of_work.environments is None:
                raise RuntimeError("The environment repository is unavailable.")
            records, total = unit_of_work.environments.list_snapshots(
                environment_id=environment_id,
                page=page,
                page_size=page_size,
            )
            return [
                EnvironmentSnapshotItem(
                    id=record.id,
                    environment_id=record.environment_id,
                    context=record.context,
                    active_task_ids=record.active_task_ids,
                    anomaly_count=record.anomaly_count,
                    context_version=record.context_version,
                    state_generated_at=record.state_generated_at,
                    created_at=record.created_at,
                )
                for record in records
            ], total

    snapshots, total = await asyncio.to_thread(query)
    return EnvironmentSnapshotListData(
        data=snapshots,
        page=page,
        page_size=page_size,
        total=total,
    )


__all__ = ["router"]
