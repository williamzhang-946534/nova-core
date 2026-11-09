from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Request
from pydantic import BaseModel

from arvuno_core.agent_runtime.runtime import AgentRuntime
from arvuno_core.api.security import require_api_token
from arvuno_core.logging_config import correlation_id_var
from arvuno_core.multimodal.service import MultimodalService
from arvuno_core.tasks.service import TaskService
from arvuno_core.voice.models import (
    VoiceConfirmationRequest,
    VoiceInteractionRequest,
    VoiceInteractionResult,
)
from arvuno_core.voice.service import VoiceInteractionService
from arvuno_core.voice.wake_word import VoiceWakeWordModule


class VoiceInteractionData(BaseModel):
    data: VoiceInteractionResult


router = APIRouter(
    prefix="/api/chat/voice",
    tags=["Voice Interaction"],
    dependencies=[Depends(require_api_token)],
)


def get_multimodal_service(request: Request) -> MultimodalService:
    service = getattr(request.app.state, "multimodal_service", None)
    if not isinstance(service, MultimodalService):
        raise RuntimeError("The multimodal service is unavailable.")
    return service


def get_agent_runtime(request: Request) -> AgentRuntime:
    runtime = getattr(request.app.state, "agent_runtime", None)
    if not isinstance(runtime, AgentRuntime):
        raise RuntimeError("The agent runtime is unavailable.")
    return runtime


def get_task_service(request: Request) -> TaskService:
    service = getattr(request.app.state, "task_service", None)
    if not isinstance(service, TaskService):
        raise RuntimeError("The task service is unavailable.")
    return service


def get_voice_service(
    multimodal: Annotated[MultimodalService, Depends(get_multimodal_service)],
    runtime: Annotated[AgentRuntime, Depends(get_agent_runtime)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> VoiceInteractionService:
    return VoiceInteractionService(multimodal, runtime, tasks, VoiceWakeWordModule())


@router.post("", response_model=VoiceInteractionData)
async def process_voice(
    service: Annotated[VoiceInteractionService, Depends(get_voice_service)],
    raw_request: Request,
    audio: Annotated[bytes, File(media_type="audio/wav")],
    environment_id: Annotated[str, Form(min_length=1, max_length=36)],
    user_id: Annotated[str, Form(min_length=1, max_length=255)],
    capture_consent_id: Annotated[str, Form(min_length=1, max_length=36)],
    processing_consent_id: Annotated[str, Form(min_length=1, max_length=36)],
    space_id: Annotated[str | None, Form(max_length=36)] = None,
    tts_consent_id: Annotated[str | None, Form(max_length=36)] = None,
    require_wake_word: Annotated[bool, Form()] = False,
    duration_ms: Annotated[int | None, Form(ge=1, le=300000)] = None,
    client_captured_at: Annotated[datetime | None, Form()] = None,
    client_time_source: Annotated[
        Literal["device_clock", "gateway_clock", "poll_clock", "user_asserted", "unknown"],
        Form(),
    ] = "device_clock",
    client_time_uncertainty_ms: Annotated[int, Form(ge=0, le=86400000)] = 250,
    sensitivity: Annotated[Literal["normal", "sensitive"], Form()] = "sensitive",
) -> VoiceInteractionData:
    request = VoiceInteractionRequest(
        environment_id=environment_id,
        space_id=space_id,
        user_id=user_id,
        capture_consent_id=capture_consent_id,
        processing_consent_id=processing_consent_id,
        tts_consent_id=tts_consent_id,
        require_wake_word=require_wake_word,
        duration_ms=duration_ms,
        client_captured_at=client_captured_at,
        client_time_source=client_time_source,
        client_time_uncertainty_ms=client_time_uncertainty_ms,
        sensitivity=sensitivity,
    )
    correlation_id = (
        correlation_id_var.get() or raw_request.headers.get("X-Correlation-ID") or str(uuid4())
    )
    result = await service.process(
        request,
        audio,
        correlation_id=correlation_id,
        client_request_id=str(uuid4()),
    )
    return VoiceInteractionData(data=result)


@router.post("/confirmation", response_model=VoiceInteractionData)
async def confirm_voice_task(
    request: VoiceConfirmationRequest,
    service: Annotated[VoiceInteractionService, Depends(get_voice_service)],
    raw_request: Request,
) -> VoiceInteractionData:
    correlation_id = (
        correlation_id_var.get() or raw_request.headers.get("X-Correlation-ID") or str(uuid4())
    )
    result = await service.confirm(request, correlation_id=correlation_id)
    return VoiceInteractionData(data=result)


@router.get("/state")
async def voice_state(
    multimodal: Annotated[MultimodalService, Depends(get_multimodal_service)],
) -> dict[str, object]:
    capabilities = await multimodal.capabilities()
    return {
        "supported_interaction_states": [
            "idle",
            "listening",
            "recognizing",
            "executing",
            "speaking",
        ],
        "microphone_capture_enabled": capabilities["microphone_capture_enabled"],
        "continuous_capture_enabled": False,
        "capture_mode": "user_upload_only",
    }


__all__ = ["router"]
