from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from arvuno_core.api.security import require_api_token
from arvuno_core.devices.registry import DeviceRegistry
from arvuno_core.devices.service import DeviceApplicationService
from arvuno_core.errors import ArvunoError
from arvuno_core.events.service import EventQueryService
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.schemas.console import (
    DeviceDetailData,
    DeviceDetailDataWrapper,
    DeviceListData,
    DeviceStateData,
    DeviceStateDataWrapper,
)
from arvuno_core.schemas.events import EventItem

router = APIRouter(
    prefix="/api/devices", tags=["Devices"], dependencies=[Depends(require_api_token)]
)


def get_registry(request: Request) -> DeviceRegistry:
    registry = getattr(request.app.state, "device_registry", None)
    if not isinstance(registry, DeviceRegistry):
        raise RuntimeError("The device registry is unavailable.")
    return registry


def get_device_service(request: Request) -> DeviceApplicationService:
    service = getattr(request.app.state, "device_service", None)
    if not isinstance(service, DeviceApplicationService):
        raise RuntimeError("The device service is unavailable.")
    return service


def get_unit_of_work_factory(request: Request) -> Callable[[], SqlAlchemyUnitOfWork]:
    factory = getattr(request.app.state, "unit_of_work_factory", None)
    if not callable(factory):
        raise RuntimeError("The database unit-of-work factory is unavailable.")
    return factory


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


@router.get("", response_model=DeviceListData)
async def list_devices(
    registry: Annotated[DeviceRegistry, Depends(get_registry)],
    area: str | None = Query(default=None, max_length=255),
    device_type: str | None = Query(default=None, max_length=100),
    online: bool | None = None,
    keyword: str | None = Query(default=None, max_length=255),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> DeviceListData:
    devices = await registry.list_devices(
        area=area,
        device_type=device_type,
        is_online=online,
        is_enabled=True,
        keyword=keyword,
    )
    start = (page - 1) * page_size
    return DeviceListData(
        data=devices[start : start + page_size],
        page=page,
        page_size=page_size,
        total=len(devices),
    )


@router.get("/{device_id}", response_model=DeviceDetailDataWrapper)
async def get_device(
    device_id: str,
    registry: Annotated[DeviceRegistry, Depends(get_registry)],
    unit_of_work_factory: Annotated[
        Callable[[], SqlAlchemyUnitOfWork], Depends(get_unit_of_work_factory)
    ],
) -> DeviceDetailDataWrapper:
    device = await registry.get_by_id(device_id)
    if device is None or not device.is_enabled:
        raise ArvunoError(
            code="NOT_FOUND",
            message="The device does not exist.",
            status_code=404,
        )
    state = await registry.latest_state(device_id)
    recent = await EventQueryService(unit_of_work_factory).list(
        subject_type="device",
        subject_id=device_id,
        page=1,
        page_size=10,
    )
    return DeviceDetailDataWrapper(
        data=DeviceDetailData(
            device=device,
            latest_state=state,
            recent_events=[_event_item(event) for event in recent.items],
        )
    )


@router.get("/{device_id}/state", response_model=DeviceStateDataWrapper)
async def get_device_state(
    device_id: str,
    device_service: Annotated[DeviceApplicationService, Depends(get_device_service)],
) -> DeviceStateDataWrapper:
    device = await device_service.get_registered_device(device_id)
    state = await device_service.get_state(device_id)
    return DeviceStateDataWrapper(
        data=DeviceStateData(
            device_id=device_id,
            external_id=device.external_id,
            state=state.actual_state,
            attributes=state.attributes,
            observed_at=state.observed_at,
            verified=state.verified,
        )
    )


__all__ = ["router"]
