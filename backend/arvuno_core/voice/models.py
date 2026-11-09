from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from arvuno_core.agent_runtime.models import AgentChatResult
from arvuno_core.multimodal.models import MultimodalExtractionView

VoiceInteractionStatus = Literal[
    "completed",
    "waiting_confirmation",
    "failed",
    "cancelled",
    "not_instruction",
    "wake_word_not_detected",
]


class VoiceInteractionRequest(BaseModel):
    environment_id: str = Field(min_length=1, max_length=36)
    space_id: str | None = Field(default=None, max_length=36)
    user_id: str = Field(min_length=1, max_length=255)
    capture_consent_id: str = Field(min_length=1, max_length=36)
    processing_consent_id: str = Field(min_length=1, max_length=36)
    tts_consent_id: str | None = Field(default=None, max_length=36)
    require_wake_word: bool = False
    duration_ms: int | None = Field(default=None, ge=1, le=300000)
    client_captured_at: datetime | None = None
    client_time_source: Literal[
        "device_clock",
        "gateway_clock",
        "poll_clock",
        "user_asserted",
        "unknown",
    ] = "device_clock"
    client_time_uncertainty_ms: int = Field(default=250, ge=0, le=86400000)
    sensitivity: Literal["normal", "sensitive"] = "sensitive"


class VoiceConfirmationRequest(BaseModel):
    environment_id: str = Field(min_length=1, max_length=36)
    user_id: str = Field(min_length=1, max_length=255)
    task_id: str = Field(min_length=1, max_length=36)
    confirmation_token: str = Field(min_length=1, max_length=255)
    confirmed: bool
    tts_consent_id: str | None = Field(default=None, max_length=36)


class VoiceInteractionResult(BaseModel):
    interaction_state: VoiceInteractionStatus
    transcript: str | None = None
    wake_word_detected: bool | None = None
    recognition: MultimodalExtractionView | None = None
    agent_result: AgentChatResult | None = None
    task_id: str | None = None
    reply: str
    tts_asset_id: str | None = None
    media_purged: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "VoiceConfirmationRequest",
    "VoiceInteractionRequest",
    "VoiceInteractionResult",
    "VoiceInteractionStatus",
]
