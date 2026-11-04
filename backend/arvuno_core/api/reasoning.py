from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from arvuno_core.api.security import require_api_token
from arvuno_core.reasoning.models import (
    ReasoningEvidenceListData,
    ReasoningHypothesisData,
    ReasoningHypothesisListData,
    ReasoningSessionData,
    ReasoningSessionListData,
    ReasoningSourceData,
)
from arvuno_core.reasoning.service import ReasoningService
from arvuno_core.schemas.reasoning import (
    ReasoningDeleteWrapper,
    ReasoningDiagnoseRequest,
)

router = APIRouter(
    prefix="/api/reasoning",
    tags=["Reasoning"],
    dependencies=[Depends(require_api_token)],
)


def get_reasoning_service(request: Request) -> ReasoningService:
    service = getattr(request.app.state, "reasoning_service", None)
    if not isinstance(service, ReasoningService):
        raise RuntimeError("The reasoning service is unavailable.")
    return service


@router.post("/sessions", response_model=ReasoningSessionData, status_code=201)
async def diagnose_environment(
    request: ReasoningDiagnoseRequest,
    service: Annotated[ReasoningService, Depends(get_reasoning_service)],
) -> ReasoningSessionData:
    return ReasoningSessionData(data=await service.diagnose(request))


@router.get("/sessions", response_model=ReasoningSessionListData)
async def list_reasoning_sessions(
    service: Annotated[ReasoningService, Depends(get_reasoning_service)],
    environment_id: str | None = Query(default=None, min_length=1, max_length=36),
    status: Literal["running", "completed", "failed"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ReasoningSessionListData:
    sessions, total = await service.list_sessions(
        environment_id=environment_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return ReasoningSessionListData(data=sessions, page=page, page_size=page_size, total=total)


@router.get("/sessions/{session_id}", response_model=ReasoningSessionData)
async def get_reasoning_session(
    session_id: str,
    service: Annotated[ReasoningService, Depends(get_reasoning_service)],
) -> ReasoningSessionData:
    return ReasoningSessionData(data=await service.get_session(session_id))


@router.delete("/sessions/{session_id}", response_model=ReasoningDeleteWrapper)
async def delete_reasoning_session(
    session_id: str,
    service: Annotated[ReasoningService, Depends(get_reasoning_service)],
) -> ReasoningDeleteWrapper:
    result = await service.delete_session(session_id)
    return ReasoningDeleteWrapper(data={"id": result["id"], "deleted": result["deleted"] == "true"})


@router.get("/sessions/{session_id}/evidence", response_model=ReasoningEvidenceListData)
async def list_reasoning_evidence(
    session_id: str,
    service: Annotated[ReasoningService, Depends(get_reasoning_service)],
    classification: Literal[
        "observed", "derived", "inferred_candidate", "verified_cause", "unknown"
    ]
    | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> ReasoningEvidenceListData:
    evidence, total = await service.evidence(
        session_id,
        classification=classification,
        page=page,
        page_size=page_size,
    )
    return ReasoningEvidenceListData(
        data=evidence,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/evidence/{evidence_id}/source", response_model=ReasoningSourceData)
async def get_reasoning_evidence_source(
    evidence_id: str,
    service: Annotated[ReasoningService, Depends(get_reasoning_service)],
) -> ReasoningSourceData:
    return ReasoningSourceData(data=await service.source(evidence_id))


@router.get("/hypotheses", response_model=ReasoningHypothesisListData)
async def list_reasoning_hypotheses(
    service: Annotated[ReasoningService, Depends(get_reasoning_service)],
    session_id: str | None = Query(default=None, min_length=1, max_length=36),
    environment_id: str | None = Query(default=None, min_length=1, max_length=36),
    status: Literal[
        "unsupported",
        "plausible",
        "supported",
        "conflicted",
        "refuted",
        "expired",
        "superseded",
    ]
    | None = None,
    hypothesis_type: Literal[
        "deterministic_rule",
        "correlation",
        "ai_candidate",
        "verified_cause",
        "data_quality",
        "unknown",
    ]
    | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> ReasoningHypothesisListData:
    hypotheses, total = await service.hypotheses(
        session_id=session_id,
        environment_id=environment_id,
        status=status,
        hypothesis_type=hypothesis_type,
        page=page,
        page_size=page_size,
    )
    return ReasoningHypothesisListData(
        data=hypotheses,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/hypotheses/{hypothesis_id}", response_model=ReasoningHypothesisData)
async def get_reasoning_hypothesis(
    hypothesis_id: str,
    service: Annotated[ReasoningService, Depends(get_reasoning_service)],
) -> ReasoningHypothesisData:
    return ReasoningHypothesisData(data=await service.hypothesis(hypothesis_id))


__all__ = ["router"]
