from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from arvuno_core.api.security import require_api_token
from arvuno_core.automation.notifications import NotificationService
from arvuno_core.automation.service import AutomationService
from arvuno_core.schemas.automations import (
    AutomationCreateDataWrapper,
    AutomationCreateRequest,
    AutomationDetailData,
    AutomationListData,
    AutomationRunListData,
    AutomationUpdateDataWrapper,
    AutomationUpdateRequest,
    NotificationDetailData,
    NotificationListData,
)

router = APIRouter(tags=["Automations"], dependencies=[Depends(require_api_token)])


def get_automation_service(request: Request) -> AutomationService:
    service = getattr(request.app.state, "automation_service", None)
    if not isinstance(service, AutomationService):
        raise RuntimeError("The automation service is unavailable.")
    return service


def get_notification_service(request: Request) -> NotificationService:
    service = getattr(request.app.state, "notification_service", None)
    if not isinstance(service, NotificationService):
        raise RuntimeError("The notification service is unavailable.")
    return service


@router.get("/api/automations", response_model=AutomationListData)
async def list_automations(
    service: Annotated[AutomationService, Depends(get_automation_service)],
    enabled: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AutomationListData:
    result = await service.list(enabled=enabled, page=page, page_size=page_size)
    return AutomationListData(
        data=[item.model_dump(mode="json") for item in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


@router.post("/api/automations", response_model=AutomationCreateDataWrapper)
async def create_automation(
    request: AutomationCreateRequest,
    service: Annotated[AutomationService, Depends(get_automation_service)],
) -> AutomationCreateDataWrapper:
    automation = await service.create(request)
    return AutomationCreateDataWrapper(data=automation.model_dump(mode="json"))


@router.get("/api/automations/{automation_id}", response_model=AutomationDetailData)
async def get_automation(
    automation_id: str,
    service: Annotated[AutomationService, Depends(get_automation_service)],
) -> AutomationDetailData:
    automation = await service.get(automation_id)
    return AutomationDetailData(data=automation.model_dump(mode="json"))


@router.patch("/api/automations/{automation_id}", response_model=AutomationUpdateDataWrapper)
async def update_automation(
    automation_id: str,
    request: AutomationUpdateRequest,
    service: Annotated[AutomationService, Depends(get_automation_service)],
) -> AutomationUpdateDataWrapper:
    automation = await service.update(automation_id, request)
    return AutomationUpdateDataWrapper(data=automation.model_dump(mode="json"))


@router.post("/api/automations/{automation_id}/enable", response_model=AutomationDetailData)
async def enable_automation(
    automation_id: str,
    service: Annotated[AutomationService, Depends(get_automation_service)],
) -> AutomationDetailData:
    automation = await service.set_enabled(automation_id, True)
    return AutomationDetailData(data=automation.model_dump(mode="json"))


@router.post("/api/automations/{automation_id}/disable", response_model=AutomationDetailData)
async def disable_automation(
    automation_id: str,
    service: Annotated[AutomationService, Depends(get_automation_service)],
) -> AutomationDetailData:
    automation = await service.set_enabled(automation_id, False)
    return AutomationDetailData(data=automation.model_dump(mode="json"))


@router.get("/api/automations/{automation_id}/runs", response_model=AutomationRunListData)
async def list_automation_runs(
    automation_id: str,
    service: Annotated[AutomationService, Depends(get_automation_service)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AutomationRunListData:
    result = await service.list_runs(automation_id, page=page, page_size=page_size)
    return AutomationRunListData(
        data=[item.model_dump(mode="json") for item in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


@router.get("/api/notifications", response_model=NotificationListData)
async def list_notifications(
    service: Annotated[NotificationService, Depends(get_notification_service)],
    level: Literal["info", "warning", "error"] | None = None,
    unread_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> NotificationListData:
    result = await service.list(
        level=level,
        unread_only=unread_only,
        page=page,
        page_size=page_size,
    )
    return NotificationListData(
        data=[item.model_dump(mode="json") for item in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


@router.post("/api/notifications/{notification_id}/read", response_model=NotificationDetailData)
async def mark_notification_read(
    notification_id: str,
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> NotificationDetailData:
    notification = await service.mark_read(notification_id)
    return NotificationDetailData(data=notification.model_dump(mode="json"))
