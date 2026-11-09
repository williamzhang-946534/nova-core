from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from arvuno_core.api.security import require_api_token
from arvuno_core.robots.models import (
    RegisteredRobot,
    RegisteredRobotTaskRequest,
    RobotCapability,
    RobotEvent,
    RobotTaskRequestCreate,
    RobotTaskStatus,
)
from arvuno_core.robots.service import RobotApplicationService


class RobotData(BaseModel):
    data: RegisteredRobot


class RobotCapabilityData(BaseModel):
    data: list[RobotCapability]


class RobotTaskRequestData(BaseModel):
    data: RegisteredRobotTaskRequest


class RobotTaskConfirmation(BaseModel):
    confirmed: bool = True
    confirmed_by: str = Field(default="api-user", min_length=1, max_length=255)


class RobotTaskCancellation(BaseModel):
    cancelled_by: str = Field(default="api-user", min_length=1, max_length=255)


router = APIRouter(
    prefix="/api/robots",
    tags=["Embodied Intelligence"],
    dependencies=[Depends(require_api_token)],
)


def get_robot_service(request: Request) -> RobotApplicationService:
    service = getattr(request.app.state, "robot_service", None)
    if not isinstance(service, RobotApplicationService):
        raise RuntimeError("The robot service is unavailable.")
    return service


@router.get("", response_model=list[RobotData])
async def list_robots(
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
    enabled_only: Annotated[bool, Query()] = False,
) -> list[RobotData]:
    robots = await service.list_robots(enabled_only=enabled_only)
    return [RobotData(data=robot) for robot in robots]


@router.post("/{robot_id}/enable", response_model=RobotData)
async def enable_robot(
    robot_id: str,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
) -> RobotData:
    return RobotData(data=await service.enable_robot(robot_id, enabled=True))


@router.get("/{robot_id}", response_model=RobotData)
async def get_robot(
    robot_id: str,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
) -> RobotData:
    return RobotData(data=await service.get_robot(robot_id))


@router.get("/{robot_id}/capabilities", response_model=RobotCapabilityData)
async def capabilities(
    robot_id: str,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
) -> RobotCapabilityData:
    return RobotCapabilityData(data=await service.capabilities(robot_id))


@router.get("/{robot_id}/state", response_model=RobotData)
async def state(
    robot_id: str,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
) -> RobotData:
    return RobotData(data=await service.state(robot_id))


@router.get("/{robot_id}/events", response_model=list[RobotEvent])
async def events(
    robot_id: str,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
    task_request_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[RobotEvent]:
    return await service.events(
        robot_id,
        task_request_id=task_request_id,
        limit=limit,
    )


@router.post("/{robot_id}/task-requests", response_model=RobotTaskRequestData, status_code=201)
async def create_task_request(
    robot_id: str,
    request: RobotTaskRequestCreate,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
) -> RobotTaskRequestData:
    return RobotTaskRequestData(
        data=await service.create_task_request(robot_id, request),
    )


@router.post(
    "/task-requests/{request_id}/confirm",
    response_model=RobotTaskRequestData,
)
async def confirm_task_request(
    request_id: str,
    confirmation: RobotTaskConfirmation,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
) -> RobotTaskRequestData:
    task = await service.task_request_by_id(request_id)
    return RobotTaskRequestData(
        data=await service.confirm_task_request(
            task.robot_id,
            request_id,
            confirmed=confirmation.confirmed,
            confirmed_by=confirmation.confirmed_by,
        )
    )


@router.post(
    "/task-requests/{request_id}/cancel",
    response_model=RobotTaskRequestData,
)
async def cancel_task_request(
    request_id: str,
    cancellation: RobotTaskCancellation,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
) -> RobotTaskRequestData:
    task = await service.task_request_by_id(request_id)
    return RobotTaskRequestData(
        data=await service.cancel_task_request(
            task.robot_id,
            request_id,
            cancelled_by=cancellation.cancelled_by,
        )
    )


@router.get("/task-requests/{request_id}", response_model=RobotTaskRequestData)
async def get_task_request(
    request_id: str,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
) -> RobotTaskRequestData:
    return RobotTaskRequestData(data=await service.task_request_by_id(request_id))


@router.get("/{robot_id}/task-requests", response_model=list[RobotTaskRequestData])
async def list_task_requests(
    robot_id: str,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
    status: RobotTaskStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[RobotTaskRequestData]:
    tasks = await service.list_task_requests(robot_id, status=status, limit=limit)
    return [RobotTaskRequestData(data=task) for task in tasks]


__all__ = ["router"]
