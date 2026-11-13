from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from arvuno_core.api.security import require_api_token
from arvuno_core.robots.errors import RobotExecutionLockedError
from arvuno_core.robots.models import (
    RegisteredRobot,
    RegisteredRobotTaskRequest,
    RobotCapability,
    RobotCapabilityName,
    RobotConsent,
    RobotConsentGrant,
    RobotEvent,
    RobotHeartbeatReport,
    RobotHeartbeatResult,
    RobotRuntimeStatus,
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


class RobotRuntimeStatusData(BaseModel):
    data: RobotRuntimeStatus


class RobotHeartbeatRequest(BaseModel):
    report: RobotHeartbeatReport


class RobotHeartbeatData(BaseModel):
    data: RobotHeartbeatResult


class RobotTaskConfirmation(BaseModel):
    confirmed: bool = True
    confirmed_by: str = Field(default="api-user", min_length=1, max_length=255)


class RobotTaskCancellation(BaseModel):
    cancelled_by: str = Field(default="api-user", min_length=1, max_length=255)


class RobotCapabilityGovernanceRequest(BaseModel):
    enabled: bool


class RobotConsentRevokeRequest(BaseModel):
    revoked_by: str = Field(default="web-console-user", min_length=1, max_length=255)


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


def reject_locked_robot_write() -> None:
    raise RobotExecutionLockedError()


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
) -> RobotData:
    reject_locked_robot_write()


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


@router.post(
    "/{robot_id}/capabilities/{capability}/governance",
    response_model=RobotCapabilityData,
)
async def set_capability_governance(
    robot_id: str,
    capability: RobotCapabilityName,
    request: RobotCapabilityGovernanceRequest,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
) -> RobotCapabilityData:
    updated = await service.set_capability_governance(
        robot_id,
        capability,
        enabled=request.enabled,
        approved_by="web-console-user",
    )
    return RobotCapabilityData(data=await service.capabilities(updated.robot_id or robot_id))


@router.get("/{robot_id}/consents", response_model=list[RobotConsent])
async def list_consents(
    robot_id: str,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
    capability: RobotCapabilityName | None = None,
    active_only: Annotated[bool, Query()] = False,
) -> list[RobotConsent]:
    return await service.list_consents(
        robot_id,
        capability=capability,
        active_only=active_only,
    )


@router.post("/{robot_id}/consents", response_model=RobotConsent, status_code=201)
async def grant_consent(
    robot_id: str,
    grant: RobotConsentGrant,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
) -> RobotConsent:
    return await service.grant_consent(robot_id, grant)


@router.post("/{robot_id}/consents/{consent_id}/revoke", response_model=RobotConsent)
async def revoke_consent(
    robot_id: str,
    consent_id: str,
    request: RobotConsentRevokeRequest,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
) -> RobotConsent:
    return await service.revoke_consent(
        robot_id,
        consent_id,
        revoked_by=request.revoked_by,
    )


@router.get("/{robot_id}/state", response_model=RobotData)
async def state(
    robot_id: str,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
) -> RobotData:
    return RobotData(data=await service.state(robot_id))


@router.get(
    "/{robot_id}/runtime-state",
    response_model=RobotRuntimeStatusData,
)
async def runtime_state(
    robot_id: str,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
) -> RobotRuntimeStatusData:
    return RobotRuntimeStatusData(data=await service.runtime_status(robot_id))


@router.post(
    "/{robot_id}/heartbeat",
    response_model=RobotHeartbeatData,
)
async def heartbeat(
    robot_id: str,
    heartbeat: RobotHeartbeatRequest,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
) -> RobotHeartbeatData:
    result = await service.heartbeat(robot_id, heartbeat.report)
    return RobotHeartbeatData(data=result)


@router.post(
    "/{robot_id}/reconnect",
    response_model=RobotRuntimeStatusData,
)
async def reconnect(
    robot_id: str,
    service: Annotated[RobotApplicationService, Depends(get_robot_service)],
) -> RobotRuntimeStatusData:
    return RobotRuntimeStatusData(data=await service.resynchronize(robot_id))


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
) -> RobotTaskRequestData:
    del robot_id, request
    reject_locked_robot_write()


@router.post(
    "/task-requests/{request_id}/confirm",
    response_model=RobotTaskRequestData,
)
async def confirm_task_request(
    request_id: str,
    confirmation: RobotTaskConfirmation,
) -> RobotTaskRequestData:
    del request_id, confirmation
    reject_locked_robot_write()


@router.post(
    "/task-requests/{request_id}/cancel",
    response_model=RobotTaskRequestData,
)
async def cancel_task_request(
    request_id: str,
    cancellation: RobotTaskCancellation,
) -> RobotTaskRequestData:
    del request_id, cancellation
    reject_locked_robot_write()


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
