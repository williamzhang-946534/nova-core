from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from arvuno_core.api.security import require_api_token
from arvuno_core.estimation.service import StateEstimationService
from arvuno_core.schemas.state_estimates import (
    StateEstimateDetailData,
    StateEstimateEvidenceListData,
    StateEstimateListData,
    StateRebuildDataWrapper,
)

router = APIRouter(
    prefix="/api/state-estimates",
    tags=["State Estimates"],
    dependencies=[Depends(require_api_token)],
)


def get_state_estimation_service(request: Request) -> StateEstimationService:
    service = getattr(request.app.state, "state_estimation_service", None)
    if not isinstance(service, StateEstimationService):
        raise RuntimeError("The state estimation service is unavailable.")
    return service


@router.get("", response_model=StateEstimateListData)
async def list_state_estimates(
    service: Annotated[StateEstimationService, Depends(get_state_estimation_service)],
    environment_id: str | None = Query(default=None, min_length=1),
    target_id: str | None = Query(default=None, min_length=1),
    entity_id: str | None = Query(default=None, min_length=1),
    space_id: str | None = Query(default=None, min_length=1),
    attribute: str | None = Query(default=None, min_length=1, max_length=50),
    status: Literal[
        "observed", "derived", "inferred", "unknown", "stale", "unavailable", "conflict"
    ]
    | None = None,
    include_history: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> StateEstimateListData:
    items, total = await service.list(
        environment_id=environment_id,
        target_id=target_id,
        entity_id=entity_id,
        space_id=space_id,
        attribute=attribute,
        status=status,
        include_history=include_history,
        page=page,
        page_size=page_size,
    )
    return StateEstimateListData(
        data=items,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/rebuild", response_model=StateRebuildDataWrapper)
async def rebuild_state_estimates(
    service: Annotated[StateEstimationService, Depends(get_state_estimation_service)],
) -> StateRebuildDataWrapper:
    return StateRebuildDataWrapper(data=await service.rebuild())


@router.get("/{estimate_id}", response_model=StateEstimateDetailData)
async def get_state_estimate(
    estimate_id: str,
    service: Annotated[StateEstimationService, Depends(get_state_estimation_service)],
) -> StateEstimateDetailData:
    return StateEstimateDetailData(data=await service.get(estimate_id))


@router.get("/{estimate_id}/evidence", response_model=StateEstimateEvidenceListData)
async def get_state_estimate_evidence(
    estimate_id: str,
    service: Annotated[StateEstimationService, Depends(get_state_estimation_service)],
) -> StateEstimateEvidenceListData:
    return StateEstimateEvidenceListData(data=await service.evidence(estimate_id))


__all__ = ["router"]
