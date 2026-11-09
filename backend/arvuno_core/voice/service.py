from typing import Any, Protocol

from arvuno_core.agent_runtime.runtime import AgentRuntime
from arvuno_core.multimodal.errors import MultimodalError
from arvuno_core.multimodal.models import (
    MultimodalAnalyzeRequest,
    MultimodalCaptureSessionCreate,
    MultimodalMediaUpload,
    MultimodalTTSRequest,
)
from arvuno_core.multimodal.service import MultimodalService
from arvuno_core.tasks.models import StoredTaskDetail
from arvuno_core.voice.models import (
    VoiceConfirmationRequest,
    VoiceInteractionRequest,
    VoiceInteractionResult,
)
from arvuno_core.voice.wake_word import VoiceWakeWordModule


class VoiceTaskSystemPort(Protocol):
    async def confirm(
        self,
        task_id: str,
        *,
        confirmation_token: str,
        confirmed: bool,
    ) -> Any: ...


class VoiceInteractionService:
    """Coordinates on-demand speech, Agent Runtime, and optional speech output."""

    def __init__(
        self,
        multimodal_service: MultimodalService,
        agent_runtime: AgentRuntime,
        task_system: VoiceTaskSystemPort,
        wake_word_module: VoiceWakeWordModule | None = None,
    ) -> None:
        self._multimodal = multimodal_service
        self._agent_runtime = agent_runtime
        self._task_system = task_system
        self._wake_word_module = wake_word_module or VoiceWakeWordModule()

    async def process(
        self,
        request: VoiceInteractionRequest,
        audio: bytes,
        *,
        correlation_id: str,
        client_request_id: str,
    ) -> VoiceInteractionResult:
        session = await self._multimodal.create_capture_session(
            MultimodalCaptureSessionCreate(
                environment_id=request.environment_id,
                space_id=request.space_id,
                modality="audio",
                purpose="speech_input",
                origin_type="user",
                requested_by=request.user_id,
                requires_capture_consent=False,
                max_duration_ms=request.duration_ms,
                correlation_id=client_request_id,
            )
        )
        uploaded_media = await self._multimodal.upload_media(
            session.id,
            MultimodalMediaUpload(
                consent_id=request.capture_consent_id,
                sensitivity=request.sensitivity,
                duration_ms=request.duration_ms,
                client_captured_at=request.client_captured_at,
                client_time_source=request.client_time_source,
                client_time_uncertainty_ms=request.client_time_uncertainty_ms,
            ),
            audio,
        )
        recognition = await self._multimodal.analyze(
            uploaded_media.id,
            MultimodalAnalyzeRequest(
                capability="stt",
                provider_name="mock",
                consent_id=request.processing_consent_id,
            ),
        )
        extraction = recognition.extraction
        transcript = str(extraction.result.get("transcript", "")).strip()
        if not transcript:
            raise MultimodalError(
                code="VOICE_TRANSCRIPT_EMPTY",
                message="The speech provider did not return usable text.",
                status_code=502,
            )

        provider_instruction = extraction.result.get("is_instruction")
        if provider_instruction is not True:
            return VoiceInteractionResult(
                interaction_state="not_instruction",
                transcript=transcript,
                recognition=extraction,
                reply="语音已识别，但提供方标记其不适合作为指令处理。",
                details={"provider_is_instruction": False},
            )

        wake_match = self._wake_word_module.match(transcript)
        if request.require_wake_word and not wake_match.detected:
            return VoiceInteractionResult(
                interaction_state="wake_word_not_detected",
                recognition=extraction,
                reply="未检测到唤醒词，语音内容未进入 Agent。",
                wake_word_detected=False,
            )

        agent_result = await self._agent_runtime.chat(
            transcript,
            correlation_id=correlation_id,
            client_request_id=client_request_id,
        )
        tts_asset_id = await self._speak(
            request.environment_id,
            request.user_id,
            request.tts_consent_id,
            agent_result.reply,
        )
        return VoiceInteractionResult(
            interaction_state=agent_result.status,
            transcript=transcript,
            wake_word_detected=None if not request.require_wake_word else wake_match.detected,
            recognition=extraction,
            agent_result=agent_result,
            task_id=agent_result.task_id,
            reply=agent_result.reply,
            tts_asset_id=tts_asset_id,
            media_purged=recognition.media_asset.purge_status == "purged",
        )

    async def confirm(
        self,
        request: VoiceConfirmationRequest,
        *,
        correlation_id: str,
    ) -> VoiceInteractionResult:
        task_run = await self._task_system.confirm(
            request.task_id,
            confirmation_token=request.confirmation_token,
            confirmed=request.confirmed,
        )
        task = task_run.task
        reply = _confirmation_reply(task, request.confirmed)
        tts_asset_id = await self._speak(
            request.environment_id,
            request.user_id,
            request.tts_consent_id,
            reply,
        )
        state = {
            "pending": "waiting_confirmation",
            "running": "waiting_confirmation",
            "completed": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
        }.get(str(task.status.value), "failed")
        return VoiceInteractionResult(
            interaction_state=state,  # type: ignore[arg-type]
            task_id=task.id,
            reply=reply,
            tts_asset_id=tts_asset_id,
            details={"confirmed": request.confirmed},
        )

    async def _speak(
        self,
        environment_id: str,
        user_id: str,
        consent_id: str | None,
        text: str,
    ) -> str | None:
        if consent_id is None:
            return None
        try:
            result = await self._multimodal.synthesize_speech(
                MultimodalTTSRequest(
                    environment_id=environment_id,
                    text=text[:5000],
                    requested_by=user_id,
                    consent_id=consent_id,
                )
            )
        except MultimodalError as exc:
            if exc.code == "MULTIMODAL_PROVIDER_UNAVAILABLE":
                return None
            raise
        return result.media_asset.id if result.media_asset is not None else None


def _confirmation_reply(task: StoredTaskDetail, confirmed: bool) -> str:
    if not confirmed:
        return "已拒绝执行该任务。"
    if task.status.value == "completed":
        for step in task.steps:
            output = step.output or {}
            if "actual_state" in output:
                return (
                    f"任务已执行，设备 {output.get('device_id')} 当前为 "
                    f"{output.get('actual_state')}。"
                )
        return "任务已确认并执行完成。"
    if task.status.value == "waiting_confirmation":
        return "任务还需要下一步确认。"
    if task.status.value == "failed":
        return "任务确认后执行失败，已安全停止。"
    return f"任务当前状态为 {task.status.value}。"


__all__ = ["VoiceInteractionService", "VoiceTaskSystemPort"]
