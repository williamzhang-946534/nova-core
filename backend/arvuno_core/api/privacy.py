from typing import Annotated

from fastapi import APIRouter, Depends, Request

from arvuno_core.api.security import require_api_token
from arvuno_core.privacy.models import (
    PrivacyErasureRequest,
    PrivacyErasureResult,
    PrivacyImpact,
)
from arvuno_core.privacy.service import PrivacyService

router = APIRouter(
    prefix="/api/privacy",
    tags=["Privacy"],
    dependencies=[Depends(require_api_token)],
)


def get_privacy_service(request: Request) -> PrivacyService:
    service = getattr(request.app.state, "privacy_service", None)
    if not isinstance(service, PrivacyService):
        raise RuntimeError("The privacy service is unavailable.")
    return service


@router.post("/erasure-requests/impact", response_model=PrivacyImpact)
async def erasure_impact(
    request: PrivacyErasureRequest,
    service: Annotated[PrivacyService, Depends(get_privacy_service)],
) -> PrivacyImpact:
    return await service.impact(request)


@router.post("/erasure-requests", response_model=PrivacyErasureResult, status_code=201)
async def erase(
    request: PrivacyErasureRequest,
    service: Annotated[PrivacyService, Depends(get_privacy_service)],
) -> PrivacyErasureResult:
    return await service.erase(request)
