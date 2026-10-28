from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime

from nova_core.api.security import require_api_token
from nova_core.logging_config import correlation_id_var
from nova_core.schemas.tasks import (
    TaskCancelRequest,
    TaskConfirmRequest,
    TaskCreateDataWrapper,
    TaskCreateRequest,
    TaskDetailData,
    TaskDetailDataWrapper,
    TaskListData,
)
from nova_core.tasks.service import TaskService

router = APIRouter(prefix="/api/tasks", tags=["Tasks"], dependencies=[Depends(require_api_token)])


def get_task_service(request: Request) -> TaskService:
    service = getattr(request.app.state, "task_service", None)
    if not isinstance(service, TaskService):
        raise RuntimeError("The task service is unavailable.")
    return service


@router.post("", response_model=TaskCreateDataWrapper)
async def create_task(
    request: TaskCreateRequest,
    raw_request: Request,
    service: Annotated[TaskService, Depends(get_task_service)],
) -> TaskCreateDataWrapper:
    correlation_id = (
        correlation_id_var.get() or raw_request.headers.get("X-Correlation-ID") or str(uuid4())
    )
    result = await service.create_and_run(request, correlation_id=correlation_id)
    return TaskCreateDataWrapper.model_validate(
        {
            "data": {
                **result.task.model_dump(mode="json"),
                "confirmation_token": result.confirmation_token,
            }
        }
    )


@router.get("", response_model=TaskListData)
async def list_tasks(
    service: Annotated[TaskService, Depends(get_task_service)],
    status: str | None = Query(default=None, max_length=50),
    task_type: str | None = Query(default=None, max_length=100),
    conversation_id: str | None = Query(default=None, max_length=36),
    start_time: AwareDatetime | None = None,
    end_time: AwareDatetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> TaskListData:
    result = await service.list(
        status=status,
        task_type=task_type,
        conversation_id=conversation_id,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )
    return TaskListData(
        data=[item.model_dump(mode="json") for item in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


@router.get("/{task_id}", response_model=TaskDetailDataWrapper)
async def get_task(
    task_id: str,
    service: Annotated[TaskService, Depends(get_task_service)],
) -> TaskDetailDataWrapper:
    task = await service.get_task_detail(task_id)
    return TaskDetailDataWrapper(data=TaskDetailData.model_validate(task.model_dump(mode="json")))


@router.post("/{task_id}/confirm", response_model=TaskDetailDataWrapper)
async def confirm_task(
    task_id: str,
    request: TaskConfirmRequest,
    service: Annotated[TaskService, Depends(get_task_service)],
) -> TaskDetailDataWrapper:
    result = await service.confirm(
        task_id,
        confirmation_token=request.confirmation_token,
        confirmed=request.confirmed,
    )
    return TaskDetailDataWrapper(
        data=TaskDetailData.model_validate(result.task.model_dump(mode="json"))
    )


@router.post("/{task_id}/cancel", response_model=TaskDetailDataWrapper)
async def cancel_task(
    task_id: str,
    service: Annotated[TaskService, Depends(get_task_service)],
    request: TaskCancelRequest | None = None,
) -> TaskDetailDataWrapper:
    reason = request.reason if request is not None else "Cancelled by the user."
    task = await service.cancel(task_id, reason=reason)
    return TaskDetailDataWrapper(data=TaskDetailData.model_validate(task.model_dump(mode="json")))
