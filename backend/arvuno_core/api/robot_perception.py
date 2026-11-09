from typing import Annotated

from fastapi import APIRouter, Depends, Request

from arvuno_core.api.security import require_api_token
from arvuno_core.perception.models import ActivePerceptionRequestData
from arvuno_core.perception.robot_mobile import RobotMobilePerceptionService
from arvuno_core.schemas.perception import (
    RobotMobilePerceptionAuthorizeRequest,
    RobotMobilePerceptionEvaluateRequest,
)

router = APIRouter(
    prefix="/api/robot-perception",
    tags=["Mobile Perception"],
    dependencies=[Depends(require_api_token)],
)


def get_robot_mobile_perception_service(
    request: Request,
) -> RobotMobilePerceptionService:
    service = getattr(request.app.state, "robot_mobile_perception_service", None)
    if not isinstance(service, RobotMobilePerceptionService):
        raise RuntimeError("The mobile perception service is unavailable.")
    return service


@router.post("/requests/evaluate", response_model=ActivePerceptionRequestData, status_code=201)
async def evaluate_request(
    request: RobotMobilePerceptionEvaluateRequest,
    service: Annotated[
        RobotMobilePerceptionService,
        Depends(get_robot_mobile_perception_service),
    ],
) -> ActivePerceptionRequestData:
    result = await service.evaluate(request.request, robot_id=request.robot_id)
    return ActivePerceptionRequestData(data=result)


@router.post("/requests/{request_id}/authorize", response_model=ActivePerceptionRequestData)
async def authorize_request(
    request_id: str,
    request: RobotMobilePerceptionAuthorizeRequest,
    service: Annotated[
        RobotMobilePerceptionService,
        Depends(get_robot_mobile_perception_service),
    ],
) -> ActivePerceptionRequestData:
    result = await service.authorize(
        request_id,
        confirmed_navigation=request.confirmed_navigation,
        confirmed_camera_capture=request.confirmed_camera_capture,
        authorization_seconds=request.authorization_seconds,
    )
    return ActivePerceptionRequestData(data=result)


@router.post("/requests/{request_id}/execute", response_model=ActivePerceptionRequestData)
async def execute_request(
    request_id: str,
    service: Annotated[
        RobotMobilePerceptionService,
        Depends(get_robot_mobile_perception_service),
    ],
) -> ActivePerceptionRequestData:
    return ActivePerceptionRequestData(data=await service.execute(request_id))


@router.get("/requests/{request_id}", response_model=ActivePerceptionRequestData)
async def get_request(
    request_id: str,
    service: Annotated[
        RobotMobilePerceptionService,
        Depends(get_robot_mobile_perception_service),
    ],
) -> ActivePerceptionRequestData:
    return ActivePerceptionRequestData(data=await service.get_request(request_id))


__all__ = ["router"]
