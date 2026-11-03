from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from arvuno_core.api.security import require_api_token
from arvuno_core.schemas.spaces import (
    DeviceAssignmentData,
    DeviceAssignmentHistoryData,
    DeviceAssignmentRequest,
    SpaceCreateRequest,
    SpaceDetailData,
    SpaceDeviceListData,
    SpaceListData,
    SpaceMoveRequest,
    SpaceTreeData,
    SpaceUpdateRequest,
)
from arvuno_core.spatial.service import SpatialService

router = APIRouter(
    prefix="/api/spaces",
    tags=["Spaces"],
    dependencies=[Depends(require_api_token)],
)
device_router = APIRouter(
    prefix="/api/devices",
    tags=["Spaces"],
    dependencies=[Depends(require_api_token)],
)


def get_spatial_service(request: Request) -> SpatialService:
    service = getattr(request.app.state, "spatial_service", None)
    if not isinstance(service, SpatialService):
        raise RuntimeError("The spatial service is unavailable.")
    return service


@router.get("", response_model=SpaceListData)
async def list_spaces(
    service: Annotated[SpatialService, Depends(get_spatial_service)],
    space_type: str | None = Query(default=None, max_length=50),
    status: str | None = Query(default=None, max_length=50),
) -> SpaceListData:
    return SpaceListData(data=await service.list_spaces(space_type=space_type, status=status))


@router.get("/tree", response_model=SpaceTreeData)
async def get_space_tree(
    service: Annotated[SpatialService, Depends(get_spatial_service)],
) -> SpaceTreeData:
    return SpaceTreeData(data=await service.tree())


@router.post("", response_model=SpaceDetailData)
async def create_space(
    request: SpaceCreateRequest,
    service: Annotated[SpatialService, Depends(get_spatial_service)],
) -> SpaceDetailData:
    space = await service.create_space(
        parent_id=request.parent_id,
        name=request.name,
        space_type=request.space_type,
        slug=request.slug,
        sort_order=request.sort_order,
        external_space_id=request.external_space_id,
        external_source=request.external_source,
        geometry=request.geometry,
        metadata=request.metadata,
    )
    return SpaceDetailData(data=space)


@router.get("/{space_id}", response_model=SpaceDetailData)
async def get_space(
    space_id: str,
    service: Annotated[SpatialService, Depends(get_spatial_service)],
) -> SpaceDetailData:
    return SpaceDetailData(data=await service.get_space(space_id))


@router.patch("/{space_id}", response_model=SpaceDetailData)
async def update_space(
    space_id: str,
    request: SpaceUpdateRequest,
    service: Annotated[SpatialService, Depends(get_spatial_service)],
) -> SpaceDetailData:
    space = await service.update_space(
        space_id,
        name=request.name,
        slug=request.slug,
        sort_order=request.sort_order,
        status=request.status,
        external_space_id=request.external_space_id,
        external_source=request.external_source,
        geometry=request.geometry,
        metadata=request.metadata,
    )
    return SpaceDetailData(data=space)


@router.post("/{space_id}/move", response_model=SpaceDetailData)
async def move_space(
    space_id: str,
    request: SpaceMoveRequest,
    service: Annotated[SpatialService, Depends(get_spatial_service)],
) -> SpaceDetailData:
    return SpaceDetailData(
        data=await service.move_space(space_id, new_parent_id=request.new_parent_id)
    )


@router.post("/{space_id}/archive", response_model=SpaceDetailData)
async def archive_space(
    space_id: str,
    service: Annotated[SpatialService, Depends(get_spatial_service)],
) -> SpaceDetailData:
    return SpaceDetailData(data=await service.archive_space(space_id))


@router.get("/{space_id}/devices", response_model=SpaceDeviceListData)
async def list_space_devices(
    space_id: str,
    service: Annotated[SpatialService, Depends(get_spatial_service)],
    include_descendants: bool = False,
) -> SpaceDeviceListData:
    return SpaceDeviceListData(
        data=await service.devices_in_space(
            space_id,
            include_descendants=include_descendants,
        )
    )


@device_router.post("/{device_id}/assignment", response_model=DeviceAssignmentData)
async def assign_device_space(
    device_id: str,
    request: DeviceAssignmentRequest,
    service: Annotated[SpatialService, Depends(get_spatial_service)],
) -> DeviceAssignmentData:
    return DeviceAssignmentData(
        data=await service.assign_device(
            device_id,
            space_id=request.space_id,
            assignment_type=request.assignment_type,
            confidence=request.confidence,
            source_type=request.source_type,
            source_id=request.source_id,
            reason=request.reason,
        )
    )


@device_router.get("/{device_id}/space-history", response_model=DeviceAssignmentHistoryData)
async def get_device_space_history(
    device_id: str,
    service: Annotated[SpatialService, Depends(get_spatial_service)],
) -> DeviceAssignmentHistoryData:
    return DeviceAssignmentHistoryData(data=await service.device_history(device_id))


__all__ = ["device_router", "router"]
