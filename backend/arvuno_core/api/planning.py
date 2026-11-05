from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from arvuno_core.api.security import require_api_token
from arvuno_core.planning.models import (
    GoalAnalysisData,
    GoalData,
    GoalListData,
    GoalView,
    PlanData,
    PlanListData,
)
from arvuno_core.planning.service import PlanningService
from arvuno_core.schemas.planning import (
    GoalCloseRequest,
    GoalCompileRequest,
    GoalConfirmRequest,
    PlanCreateRequest,
    PlanDecisionRequest,
    ReplanRequest,
)

router = APIRouter(
    prefix="/api/planning",
    tags=["Planning"],
    dependencies=[Depends(require_api_token)],
)


def get_planning_service(request: Request) -> PlanningService:
    service = getattr(request.app.state, "planning_service", None)
    if not isinstance(service, PlanningService):
        raise RuntimeError("The planning service is unavailable.")
    return service


@router.post("/goals", response_model=GoalData, status_code=201)
async def compile_goal(
    request: GoalCompileRequest,
    service: Annotated[PlanningService, Depends(get_planning_service)],
) -> GoalData:
    return GoalData(data=await service.compile_goal(request))


@router.get("/goals", response_model=GoalListData)
async def list_goals(
    service: Annotated[PlanningService, Depends(get_planning_service)],
    environment_id: str | None = Query(default=None, min_length=1, max_length=36),
    status: Literal[
        "candidate",
        "active",
        "paused",
        "completed",
        "failed",
        "cancelled",
        "expired",
    ]
    | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> GoalListData:
    goals, total = await service.list_goals(
        environment_id=environment_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return GoalListData(data=goals, page=page, page_size=page_size, total=total)


@router.get("/goals/{goal_id}", response_model=GoalData)
async def get_goal(
    goal_id: str,
    service: Annotated[PlanningService, Depends(get_planning_service)],
) -> GoalData:
    return GoalData(data=await service.get_goal(goal_id))


@router.post("/goals/{goal_id}/confirm", response_model=GoalData)
async def confirm_goal(
    goal_id: str,
    request: GoalConfirmRequest,
    service: Annotated[PlanningService, Depends(get_planning_service)],
) -> GoalData:
    return GoalData(
        data=await service.confirm_goal(
            goal_id,
            requested_authorization=request.authorization_scope,
            reason=request.reason,
        )
    )


@router.post("/goals/{goal_id}/close", response_model=GoalData)
async def close_goal(
    goal_id: str,
    request: GoalCloseRequest,
    service: Annotated[PlanningService, Depends(get_planning_service)],
) -> GoalData:
    return GoalData(data=await service.close_goal(goal_id, request.status, request.reason))


@router.post("/goals/{goal_id}/analysis", response_model=GoalAnalysisData)
async def analyze_goal(
    goal_id: str,
    service: Annotated[PlanningService, Depends(get_planning_service)],
) -> GoalAnalysisData:
    result = await service.analyze_goal(goal_id)
    result["goal"] = GoalView.model_validate(result["goal"]).model_dump(mode="json")
    return GoalAnalysisData(data=result)


@router.post("/goals/{goal_id}/plans", response_model=PlanData, status_code=201)
async def create_plan(
    goal_id: str,
    request: PlanCreateRequest,
    service: Annotated[PlanningService, Depends(get_planning_service)],
) -> PlanData:
    return PlanData(data=await service.create_plan(goal_id, request))


@router.get("/plans", response_model=PlanListData)
async def list_plans(
    service: Annotated[PlanningService, Depends(get_planning_service)],
    goal_id: str | None = Query(default=None, min_length=1, max_length=36),
    status: Literal[
        "draft",
        "validated",
        "awaiting_confirmation",
        "approved",
        "submitted",
        "superseded",
        "cancelled",
        "rejected",
    ]
    | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> PlanListData:
    plans, total = await service.list_plans(
        goal_id=goal_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return PlanListData(data=plans, page=page, page_size=page_size, total=total)


@router.get("/plans/{plan_id}", response_model=PlanData)
async def get_plan(
    plan_id: str,
    service: Annotated[PlanningService, Depends(get_planning_service)],
) -> PlanData:
    return PlanData(data=await service.get_plan(plan_id))


@router.post("/plans/{plan_id}/approve", response_model=PlanData)
async def approve_plan(
    plan_id: str,
    request: PlanDecisionRequest,
    service: Annotated[PlanningService, Depends(get_planning_service)],
) -> PlanData:
    return PlanData(data=await service.approve_plan(plan_id, request.reason))


@router.post("/plans/{plan_id}/reject", response_model=PlanData)
async def reject_plan(
    plan_id: str,
    request: PlanDecisionRequest,
    service: Annotated[PlanningService, Depends(get_planning_service)],
) -> PlanData:
    reason = request.reason or "Rejected by the user."
    return PlanData(data=await service.reject_plan(plan_id, reason))


@router.post("/plans/{plan_id}/submit", response_model=PlanData)
async def submit_plan(
    plan_id: str,
    service: Annotated[PlanningService, Depends(get_planning_service)],
) -> PlanData:
    return PlanData(data=await service.submit_plan(plan_id))


@router.post("/plans/{plan_id}/replan", response_model=PlanData)
async def replan_plan(
    plan_id: str,
    request: ReplanRequest,
    service: Annotated[PlanningService, Depends(get_planning_service)],
) -> PlanData:
    return PlanData(data=await service.replan(plan_id, request))


__all__ = ["router"]
