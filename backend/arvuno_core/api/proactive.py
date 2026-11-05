from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from arvuno_core.api.security import require_api_token
from arvuno_core.proactive.models import (
    ProactiveDeleteData,
    ProactiveDeleteWrapper,
    ProactiveQualityData,
    ProactiveSuggestionData,
    ProactiveSuggestionListData,
)
from arvuno_core.proactive.service import ProactiveService
from arvuno_core.schemas.proactive import (
    ProactiveAcceptRequest,
    ProactiveDismissRequest,
    ProactiveFeedbackRequest,
)

router = APIRouter(
    prefix="/api/proactive",
    tags=["Proactive"],
    dependencies=[Depends(require_api_token)],
)


def get_proactive_service(request: Request) -> ProactiveService:
    service = getattr(request.app.state, "proactive_service", None)
    if not isinstance(service, ProactiveService):
        raise RuntimeError("The proactive service is unavailable.")
    return service


@router.get("/suggestions", response_model=ProactiveSuggestionListData)
async def list_suggestions(
    service: Annotated[ProactiveService, Depends(get_proactive_service)],
    environment_id: str | None = Query(default=None, min_length=1, max_length=36),
    status: Literal[
        "evaluated",
        "suppressed",
        "queued",
        "delivered",
        "opened",
        "accepted",
        "dismissed",
        "expired",
    ]
    | None = None,
    trigger_type: Literal[
        "trend",
        "anomaly",
        "goal_deviation",
        "task_failure",
        "coverage_gap",
        "device_fault",
        "cost_risk",
    ]
    | None = None,
    importance: Literal["low", "normal", "high"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ProactiveSuggestionListData:
    suggestions, total = await service.list_suggestions(
        environment_id=environment_id,
        status=status,
        trigger_type=trigger_type,
        importance=importance,
        page=page,
        page_size=page_size,
    )
    return ProactiveSuggestionListData(
        data=suggestions,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/suggestions/{suggestion_id}", response_model=ProactiveSuggestionData)
async def get_suggestion(
    suggestion_id: str,
    service: Annotated[ProactiveService, Depends(get_proactive_service)],
) -> ProactiveSuggestionData:
    return ProactiveSuggestionData(data=await service.get_suggestion(suggestion_id))


@router.post("/suggestions/{suggestion_id}/open", response_model=ProactiveSuggestionData)
async def mark_opened(
    suggestion_id: str,
    service: Annotated[ProactiveService, Depends(get_proactive_service)],
) -> ProactiveSuggestionData:
    return ProactiveSuggestionData(data=await service.mark_opened(suggestion_id))


@router.post("/suggestions/{suggestion_id}/accept", response_model=ProactiveSuggestionData)
async def accept_suggestion(
    suggestion_id: str,
    request: ProactiveAcceptRequest,
    service: Annotated[ProactiveService, Depends(get_proactive_service)],
) -> ProactiveSuggestionData:
    return ProactiveSuggestionData(
        data=await service.accept_suggestion(suggestion_id, feedback=request.feedback)
    )


@router.post("/suggestions/{suggestion_id}/dismiss", response_model=ProactiveSuggestionData)
async def dismiss_suggestion(
    suggestion_id: str,
    request: ProactiveDismissRequest,
    service: Annotated[ProactiveService, Depends(get_proactive_service)],
) -> ProactiveSuggestionData:
    return ProactiveSuggestionData(
        data=await service.dismiss_suggestion(
            suggestion_id,
            feedback=request.feedback,
            suppress_future=request.suppress_future,
            suppression_hours=request.suppression_hours,
        )
    )


@router.post("/suggestions/{suggestion_id}/feedback", response_model=ProactiveSuggestionData)
async def submit_feedback(
    suggestion_id: str,
    request: ProactiveFeedbackRequest,
    service: Annotated[ProactiveService, Depends(get_proactive_service)],
) -> ProactiveSuggestionData:
    return ProactiveSuggestionData(
        data=await service.submit_feedback(
            suggestion_id,
            useful=request.useful,
            correct=request.correct,
            comment=request.comment,
            desired_action=request.desired_action,
        )
    )


@router.get("/quality/{trigger_type}", response_model=ProactiveQualityData)
async def quality_summary(
    trigger_type: Literal[
        "trend",
        "anomaly",
        "goal_deviation",
        "task_failure",
        "coverage_gap",
        "device_fault",
        "cost_risk",
    ],
    service: Annotated[ProactiveService, Depends(get_proactive_service)],
    environment_id: str | None = Query(default=None, min_length=1, max_length=36),
) -> ProactiveQualityData:
    return ProactiveQualityData(
        data=await service.quality_summary(
            environment_id=environment_id,
            trigger_type=trigger_type,
        )
    )


@router.delete("/suggestions/{suggestion_id}", response_model=ProactiveDeleteWrapper)
async def delete_suggestion(
    suggestion_id: str,
    service: Annotated[ProactiveService, Depends(get_proactive_service)],
) -> ProactiveDeleteWrapper:
    result = await service.delete_suggestion(suggestion_id)
    return ProactiveDeleteWrapper(data=ProactiveDeleteData(**result))
