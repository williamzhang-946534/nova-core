from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from arvuno_core.api.security import require_api_token
from arvuno_core.perception.errors import PerceptionStateError
from arvuno_core.perception.models import (
    ActivePerceptionDeleteData,
    ActivePerceptionDeleteWrapper,
    ActivePerceptionRequestData,
    ActivePerceptionRequestListData,
    ActivePerceptionRequestView,
)
from arvuno_core.perception.service import ActivePerceptionService
from arvuno_core.schemas.perception import (
    ActivePerceptionAuthorizeRequest,
    ActivePerceptionEvaluateRequest,
    ActivePerceptionRejectRequest,
)
from arvuno_core.tasks.models import TaskCreate, TaskPlanStep

router = APIRouter(
    prefix="/api/active-perception",
    tags=["Active Perception"],
    dependencies=[Depends(require_api_token)],
)


def get_perception_service(request: Request) -> ActivePerceptionService:
    service = getattr(request.app.state, "perception_service", None)
    if not isinstance(service, ActivePerceptionService):
        raise RuntimeError("The active perception service is unavailable.")
    return service


@router.post("/requests/evaluate", response_model=ActivePerceptionRequestData, status_code=201)
async def evaluate_gap(
    request: ActivePerceptionEvaluateRequest,
    service: Annotated[ActivePerceptionService, Depends(get_perception_service)],
) -> ActivePerceptionRequestData:
    return ActivePerceptionRequestData(data=await service.evaluate_gap(request))


@router.get("/requests", response_model=ActivePerceptionRequestListData)
async def list_requests(
    service: Annotated[ActivePerceptionService, Depends(get_perception_service)],
    environment_id: str | None = Query(default=None, min_length=1, max_length=36),
    status: Literal[
        "proposed",
        "awaiting_consent",
        "rejected",
        "queued",
        "executed",
        "fulfilled",
        "unavailable",
        "expired",
    ]
    | None = None,
    gap_type: Literal[
        "space_coverage",
        "time_coverage",
        "quality",
        "entity_identity",
        "post_action_verification",
        "procedure",
    ]
    | None = None,
    privacy_level: Literal["normal", "sensitive"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ActivePerceptionRequestListData:
    requests, total = await service.list_requests(
        environment_id=environment_id,
        status=status,
        gap_type=gap_type,
        privacy_level=privacy_level,
        page=page,
        page_size=page_size,
    )
    return ActivePerceptionRequestListData(
        data=requests,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/requests/{request_id}", response_model=ActivePerceptionRequestData)
async def get_request(
    request_id: str,
    service: Annotated[ActivePerceptionService, Depends(get_perception_service)],
) -> ActivePerceptionRequestData:
    return ActivePerceptionRequestData(data=await service.get_request(request_id))


@router.post("/requests/{request_id}/authorize", response_model=ActivePerceptionRequestData)
async def authorize_request(
    request_id: str,
    request: ActivePerceptionAuthorizeRequest,
    service: Annotated[ActivePerceptionService, Depends(get_perception_service)],
) -> ActivePerceptionRequestData:
    return ActivePerceptionRequestData(
        data=await service.authorize(
            request_id,
            scope=request.scope,
            authorization_seconds=request.authorization_seconds,
        )
    )


@router.post("/requests/{request_id}/reject", response_model=ActivePerceptionRequestData)
async def reject_request(
    request_id: str,
    request: ActivePerceptionRejectRequest,
    service: Annotated[ActivePerceptionService, Depends(get_perception_service)],
) -> ActivePerceptionRequestData:
    return ActivePerceptionRequestData(data=await service.reject(request_id, reason=request.reason))


@router.post("/requests/{request_id}/execute", response_model=ActivePerceptionRequestData)
async def execute_request(
    request: Request,
    request_id: str,
    service: Annotated[ActivePerceptionService, Depends(get_perception_service)],
) -> ActivePerceptionRequestData:
    task_service = getattr(request.app.state, "task_service", None)
    if task_service is None:
        return ActivePerceptionRequestData(data=await service.execute(request_id, None))
    result = await task_service.create_and_run(
        TaskCreate(
            task_type="active_perception.execute",
            title=f"Execute active perception {request_id}",
            origin="api",
            steps=[
                TaskPlanStep(
                    name="Execute authorized observation",
                    tool_name="active_perception_execute",
                    input={"request_id": request_id},
                )
            ],
            timeout_seconds=30.0,
        ),
        correlation_id=f"active-perception:{request_id}",
    )
    detail = result.task
    step = detail.steps[0]
    if detail.status == "completed" and step.output is not None:
        request_view = step.output.get("request")
        if isinstance(request_view, dict):
            return ActivePerceptionRequestData(
                data=ActivePerceptionRequestView.model_validate(request_view)
            )
    status = step.status.value if hasattr(step.status, "value") else str(step.status)
    if status == "failed":
        error = step.error or {}
        message = error.get("message", "The active perception task failed.")
        current = await service.get_request(request_id)
        if current.status == "unavailable":
            return ActivePerceptionRequestData(data=current)
        raise PerceptionStateError(message)
    raise PerceptionStateError(f"The active perception task ended in status '{status}'.")


@router.post("/requests/expire", response_model=ActivePerceptionDeleteWrapper)
async def expire_requests(
    service: Annotated[ActivePerceptionService, Depends(get_perception_service)],
) -> ActivePerceptionDeleteWrapper:
    count = await service.expire_stale()
    return ActivePerceptionDeleteWrapper(
        data=ActivePerceptionDeleteData(
            id="bulk",
            deleted=count > 0,
            expired_count=count,
        )
    )


@router.delete("/requests/{request_id}", response_model=ActivePerceptionDeleteWrapper)
async def delete_request(
    request_id: str,
    service: Annotated[ActivePerceptionService, Depends(get_perception_service)],
) -> ActivePerceptionDeleteWrapper:
    result = await service.delete_request(request_id)
    return ActivePerceptionDeleteWrapper(
        data=ActivePerceptionDeleteData(id=result["id"], deleted=result["deleted"] == "true")
    )


__all__ = ["router"]
