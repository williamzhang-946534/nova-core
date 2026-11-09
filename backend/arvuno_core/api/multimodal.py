from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from arvuno_core.api.security import require_api_token
from arvuno_core.multimodal.errors import MultimodalError
from arvuno_core.multimodal.models import (
    MultimodalAnalysisResult,
    MultimodalAnalyzeRequest,
    MultimodalAuditEventView,
    MultimodalCapabilities,
    MultimodalCaptureSessionCreate,
    MultimodalCaptureSessionView,
    MultimodalConsentCreate,
    MultimodalConsentView,
    MultimodalDataAccessGrantCreate,
    MultimodalDataAccessGrantView,
    MultimodalExtractionView,
    MultimodalFusionQuery,
    MultimodalFusionResult,
    MultimodalMediaAssetView,
    MultimodalMediaUpload,
    MultimodalProviderView,
    MultimodalTTSRequest,
)
from arvuno_core.multimodal.service import MultimodalService


class MultimodalCapabilitiesData(BaseModel):
    data: MultimodalCapabilities


class MultimodalConsentData(BaseModel):
    data: MultimodalConsentView


class CaptureSessionData(BaseModel):
    data: MultimodalCaptureSessionView


class MultimodalMediaAssetData(BaseModel):
    data: MultimodalMediaAssetView


class MultimodalAnalysisData(BaseModel):
    data: MultimodalAnalysisResult


class MultimodalDataAccessGrantData(BaseModel):
    data: MultimodalDataAccessGrantView


class MultimodalFusionData(BaseModel):
    data: MultimodalFusionResult


router = APIRouter(
    prefix="/api/multimodal",
    tags=["Multimodal Perception"],
    dependencies=[Depends(require_api_token)],
)


def get_multimodal_service(request: Request) -> MultimodalService:
    service = getattr(request.app.state, "multimodal_service", None)
    if not isinstance(service, MultimodalService):
        raise RuntimeError("The multimodal service is unavailable.")
    return service


@router.get("/capabilities", response_model=MultimodalCapabilitiesData)
async def capabilities(
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> MultimodalCapabilitiesData:
    return MultimodalCapabilitiesData(data=await service.capabilities())


@router.get("/providers", response_model=list[MultimodalProviderView])
async def list_providers(
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> list[MultimodalProviderView]:
    return await service.list_providers()


@router.post("/consents", response_model=MultimodalConsentData, status_code=201)
async def create_consent(
    request: MultimodalConsentCreate,
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> MultimodalConsentData:
    return MultimodalConsentData(data=await service.create_consent(request))


@router.get("/consents", response_model=list[MultimodalConsentView])
async def list_consents(
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
    environment_id: str | None = None,
) -> list[MultimodalConsentView]:
    return await service.list_consents(environment_id)


@router.post("/consents/{consent_id}/revoke", response_model=MultimodalConsentData)
async def revoke_consent(
    consent_id: str,
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> MultimodalConsentData:
    return MultimodalConsentData(data=await service.revoke_consent(consent_id))


@router.post(
    "/data-access-grants",
    response_model=MultimodalDataAccessGrantData,
    status_code=201,
)
async def create_data_access_grant(
    request: MultimodalDataAccessGrantCreate,
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> MultimodalDataAccessGrantData:
    return MultimodalDataAccessGrantData(data=await service.create_data_access_grant(request))


@router.get("/data-access-grants", response_model=list[MultimodalDataAccessGrantView])
async def list_data_access_grants(
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
    environment_id: str | None = None,
) -> list[MultimodalDataAccessGrantView]:
    return await service.list_data_access_grants(environment_id)


@router.post(
    "/data-access-grants/{grant_id}/revoke",
    response_model=MultimodalDataAccessGrantData,
)
async def revoke_data_access_grant(
    grant_id: str,
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> MultimodalDataAccessGrantData:
    return MultimodalDataAccessGrantData(data=await service.revoke_data_access_grant(grant_id))


@router.post("/fusion/query", response_model=MultimodalFusionData)
async def query_multimodal_fusion(
    request: MultimodalFusionQuery,
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> MultimodalFusionData:
    return MultimodalFusionData(data=await service.query_fusion(request))


@router.get("/audit-events", response_model=list[MultimodalAuditEventView])
async def list_audit_events(
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
    environment_id: str,
    action: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[MultimodalAuditEventView]:
    return await service.list_audit_events(environment_id, action=action, limit=limit)


@router.post("/capture-sessions", response_model=CaptureSessionData, status_code=201)
async def create_capture_session(
    request: MultimodalCaptureSessionCreate,
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> CaptureSessionData:
    return CaptureSessionData(data=await service.create_capture_session(request))


@router.get("/capture-sessions/{session_id}", response_model=CaptureSessionData)
async def get_capture_session(
    session_id: str,
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> CaptureSessionData:
    return CaptureSessionData(data=await service.get_capture_session(session_id))


@router.post("/capture-sessions/{session_id}/upload", response_model=MultimodalMediaAssetData)
async def upload_media(
    session_id: str,
    consent_id: Annotated[
        str,
        Header(
            alias="X-Multimodal-Consent-ID",
            min_length=1,
            max_length=36,
        ),
    ],
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
    sensitivity: Annotated[Literal["normal", "sensitive"], Query()] = "normal",
    duration_ms: Annotated[int | None, Query(ge=1, le=300000)] = None,
    client_captured_at: Annotated[datetime | None, Query()] = None,
    client_time_source: Annotated[
        Literal["device_clock", "gateway_clock", "poll_clock", "user_asserted", "unknown"],
        Query(),
    ] = "unknown",
    client_time_uncertainty_ms: Annotated[int | None, Query(ge=0, le=86400000)] = None,
    content: Annotated[bytes, Body(media_type="application/octet-stream")] = b"",
) -> MultimodalMediaAssetData:
    request = MultimodalMediaUpload(
        consent_id=consent_id,
        sensitivity=sensitivity,
        duration_ms=duration_ms,
        client_captured_at=client_captured_at,
        client_time_source=client_time_source,
        client_time_uncertainty_ms=client_time_uncertainty_ms,
    )
    return MultimodalMediaAssetData(data=await service.upload_media(session_id, request, content))


@router.get("/media-assets/{asset_id}/content")
async def read_media(
    asset_id: str,
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> Response:
    content = await service.read_media(asset_id)
    return Response(content=content, media_type="application/octet-stream")


@router.post("/media-assets/{asset_id}/analyze", response_model=MultimodalAnalysisData)
async def analyze_media(
    asset_id: str,
    request: MultimodalAnalyzeRequest,
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> MultimodalAnalysisData:
    return MultimodalAnalysisData(data=await service.analyze(asset_id, request))


@router.post("/media-assets/{asset_id}/transcribe", response_model=MultimodalAnalysisData)
async def transcribe_media(
    asset_id: str,
    request: MultimodalAnalyzeRequest,
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> MultimodalAnalysisData:
    if request.capability != "stt":
        raise MultimodalError(code="MULTIMODAL_CAPABILITY_MEDIA_INVALID", status_code=400)
    return MultimodalAnalysisData(data=await service.analyze(asset_id, request))


@router.post("/media-assets/{asset_id}/audio-events", response_model=MultimodalAnalysisData)
async def detect_audio_events(
    asset_id: str,
    request: MultimodalAnalyzeRequest,
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> MultimodalAnalysisData:
    if request.capability != "audio_event":
        raise MultimodalError(code="MULTIMODAL_CAPABILITY_MEDIA_INVALID", status_code=400)
    return MultimodalAnalysisData(data=await service.analyze(asset_id, request))


@router.post("/tts", response_model=MultimodalAnalysisData)
async def synthesize_speech(
    request: MultimodalTTSRequest,
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> MultimodalAnalysisData:
    return MultimodalAnalysisData(data=await service.synthesize_speech(request))


@router.get("/extraction-results", response_model=list[MultimodalExtractionView])
async def list_extraction_results(
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> list[MultimodalExtractionView]:
    return await service.list_extractions()


@router.post("/media-assets/{asset_id}/purge", response_model=MultimodalMediaAssetData)
async def purge_media(
    asset_id: str,
    service: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> MultimodalMediaAssetData:
    return MultimodalMediaAssetData(data=await service.purge_asset(asset_id))


__all__ = ["router"]
