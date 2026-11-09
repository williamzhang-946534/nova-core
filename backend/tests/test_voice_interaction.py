import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from arvuno_core.agent_runtime.models import AgentChatResult
from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.multimodal.errors import MultimodalError
from arvuno_core.multimodal.models import (
    MultimodalConsentCreate,
)
from arvuno_core.multimodal.providers import MockTTSProvider, ProviderResult
from arvuno_core.multimodal.service import MultimodalService
from arvuno_core.observations.service import ObservationService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import Environment, MultimodalMediaAsset
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.spatial.service import SpatialService
from arvuno_core.tasks.models import StoredTaskDetail, TaskRunResult, TaskStatus
from arvuno_core.voice.models import (
    VoiceConfirmationRequest,
    VoiceInteractionRequest,
    VoiceInteractionResult,
)
from arvuno_core.voice.service import VoiceInteractionService
from arvuno_core.voice.wake_word import VoiceWakeWordModule

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
WAV = b"RIFF" + (len(b"voice")).to_bytes(4, "little") + b"WAVE" + b"voice"
HEADERS = {"Authorization": "Bearer test-api-token"}


def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


class FakeSTTProvider:
    capability = "stt"
    provider_name = "mock"
    model_id = "test-stt"
    model_version = "2.3.4"
    processing_location = "local"

    def __init__(self, *, is_instruction: bool, transcript: str) -> None:
        self.is_instruction = is_instruction
        self.transcript = transcript

    async def process(
        self,
        *,
        capability: str,
        content: bytes,
        mime_type: str,
        text: str | None = None,
        output_path: Any = None,
    ) -> ProviderResult:
        if capability != "stt":
            raise MultimodalError(code="MULTIMODAL_PROVIDER_CAPABILITY_INVALID")
        return ProviderResult(
            result_kind="transcript",
            result={"transcript": self.transcript, "is_instruction": self.is_instruction},
            confidence=0.91,
            model_version=self.model_version,
            language="zh",
        )


class FakeAgentRuntime:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def chat(
        self,
        message: str,
        *,
        correlation_id: str,
        client_request_id: str | None = None,
    ) -> AgentChatResult:
        self.messages.append(message)
        return AgentChatResult(
            status="completed",
            reply="客厅温度是 24 摄氏度。",
            intent="environment_query",
            correlation_id=correlation_id,
            client_request_id=client_request_id,
        )


class FakeTaskSystem:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, bool]] = []

    async def confirm(
        self,
        task_id: str,
        *,
        confirmation_token: str,
        confirmed: bool,
    ) -> TaskRunResult:
        self.requests.append((task_id, confirmation_token, confirmed))
        return TaskRunResult(_task(confirmed))


class VoiceEnvironment:
    def __init__(self, tmp_path: Path, adapter: FakeSTTProvider) -> None:
        self.settings = settings(tmp_path)
        self.manager = DatabaseManager(self.settings)
        self.manager.initialize_database()

        def factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(self.manager.session_factory)

        self.factory = factory
        self.observation_service = ObservationService(factory)
        self.multimodal = MultimodalService(
            factory,
            self.observation_service,
            self.settings,
            adapters={"stt": adapter, "tts": MockTTSProvider()},
        )
        asyncio.run(self.multimodal.initialize_catalog())
        spatial = SpatialService(factory, environment_name="home")
        root = asyncio.run(spatial.ensure_root())
        self.space_id = asyncio.run(
            spatial.create_space(parent_id=root.id, name="Voice Room", space_type="room")
        ).id
        with self.manager.session_factory() as session:
            self.environment_id = session.scalars(select(Environment.id)).one()
        self.capture_consent = self._consent("capture", "speech_input")
        self.processing_consent = self._consent(
            "processing",
            "speech_input",
            provider_name="mock",
            processing_locations=["local"],
        )
        self.tts_consent = self._consent(
            "processing",
            "accessibility_output",
            provider_name="mock",
            processing_locations=["local"],
        )

    def _consent(
        self,
        consent_type: str,
        purpose: str,
        *,
        provider_name: str | None = None,
        processing_locations: list[str] | None = None,
    ) -> str:
        return asyncio.run(
            self.multimodal.create_consent(
                MultimodalConsentCreate(
                    environment_id=self.environment_id,
                    user_id="user-1",
                    consent_type=consent_type,  # type: ignore[arg-type]
                    modality="audio",
                    purpose=purpose,  # type: ignore[arg-type]
                    provider_name=provider_name,
                    processing_locations=processing_locations or ["local"],
                    space_ids=[self.space_id],
                )
            )
        ).id

    def request(self, *, require_wake_word: bool = False) -> VoiceInteractionRequest:
        return VoiceInteractionRequest(
            environment_id=self.environment_id,
            space_id=self.space_id,
            user_id="user-1",
            capture_consent_id=self.capture_consent,
            processing_consent_id=self.processing_consent,
            tts_consent_id=self.tts_consent,
            require_wake_word=require_wake_word,
            duration_ms=1500,
            client_captured_at=NOW,
            client_time_source="device_clock",
            client_time_uncertainty_ms=180,
        )

    def assets(self) -> list[MultimodalMediaAsset]:
        with self.manager.session_factory() as session:
            return list(session.scalars(select(MultimodalMediaAsset)).all())

    def dispose(self) -> None:
        self.manager.dispose()


def _task(completed: bool) -> StoredTaskDetail:
    return StoredTaskDetail(
        id="task-1",
        task_type="device.control",
        title="Turn off the light",
        description=None,
        status=TaskStatus.COMPLETED if completed else TaskStatus.CANCELLED,
        origin="user",
        conversation_id=None,
        plan={},
        result=None,
        error=None,
        correlation_id="correlation-voice-confirm",
        created_at=NOW,
        started_at=None,
        completed_at=None,
        steps=[],
        executions=[],
    )


def voice_result(
    environment: VoiceEnvironment,
    runtime: FakeAgentRuntime,
    *,
    require_wake_word: bool = False,
) -> VoiceInteractionResult:
    service = VoiceInteractionService(environment.multimodal, runtime, FakeTaskSystem())
    return asyncio.run(
        service.process(
            environment.request(require_wake_word=require_wake_word),
            WAV,
            correlation_id="correlation-voice",
            client_request_id="request-voice",
        )
    )


def test_voice_instruction_is_routed_and_sources_remain_traceable(tmp_path: Path) -> None:
    provider = FakeSTTProvider(is_instruction=True, transcript="Arvuno 客厅温度是多少")
    environment = VoiceEnvironment(tmp_path, provider)
    runtime = FakeAgentRuntime()
    try:
        result = voice_result(environment, runtime)
        assert result.interaction_state == "completed"
        assert result.transcript == "Arvuno 客厅温度是多少"
        assert runtime.messages == ["Arvuno 客厅温度是多少"]
        assert result.recognition is not None
        assert result.recognition.model_id == "test-stt"
        assert result.recognition.model_version == "2.3.4"
        assert result.recognition.result["is_instruction"] is True
        assert result.media_purged is True
        assert result.tts_asset_id is not None
        assets = environment.assets()
        assert len(assets) == 2
        assert assets[0].media_kind == "audio_clip"
        assert assets[0].purge_status == "purged"
        assert assets[1].media_kind == "tts_audio"
    finally:
        environment.dispose()


def test_non_instruction_transcript_does_not_reach_agent(tmp_path: Path) -> None:
    provider = FakeSTTProvider(is_instruction=False, transcript="This is mock speech input")
    environment = VoiceEnvironment(tmp_path, provider)
    runtime = FakeAgentRuntime()
    try:
        result = voice_result(environment, runtime)
        assert result.interaction_state == "not_instruction"
        assert runtime.messages == []
        assert result.agent_result is None
        assert result.media_purged is True
    finally:
        environment.dispose()


def test_required_wake_word_blocks_agent_and_omits_transcript(tmp_path: Path) -> None:
    provider = FakeSTTProvider(is_instruction=True, transcript="今天天气怎么样")
    environment = VoiceEnvironment(tmp_path, provider)
    runtime = FakeAgentRuntime()
    try:
        result = voice_result(environment, runtime, require_wake_word=True)
        assert result.interaction_state == "wake_word_not_detected"
        assert result.transcript is None
        assert result.wake_word_detected is False
        assert runtime.messages == []
        assert result.tts_asset_id is None
    finally:
        environment.dispose()


@pytest.mark.parametrize(
    ("transcript", "expected"),
    [
        ("please ask Arvuno for the temperature", True),
        ("阿夫努诺 打开客厅灯", True),
        ("please ask the temperature", False),
    ],
)
def test_wake_word_module_is_independent(transcript: str, expected: bool) -> None:
    assert VoiceWakeWordModule().match(transcript).detected is expected


def test_voice_confirmation_is_explicit_and_does_not_use_speech_intent(tmp_path: Path) -> None:
    provider = FakeSTTProvider(is_instruction=True, transcript="确认执行")
    environment = VoiceEnvironment(tmp_path, provider)
    tasks = FakeTaskSystem()
    service = VoiceInteractionService(
        environment.multimodal,
        FakeAgentRuntime(),
        tasks,
    )
    try:
        result = asyncio.run(
            service.confirm(
                VoiceConfirmationRequest(
                    environment_id=environment.environment_id,
                    user_id="user-1",
                    task_id="task-1",
                    confirmation_token="token-value",
                    confirmed=True,
                    tts_consent_id=environment.tts_consent,
                ),
                correlation_id="correlation-voice-confirm",
            )
        )
        assert result.interaction_state == "completed"
        assert result.task_id == "task-1"
        assert tasks.requests == [("task-1", "token-value", True)]
        assert result.tts_asset_id is not None
    finally:
        environment.dispose()


def test_voice_api_preserves_on_demand_capture_and_purges_audio(tmp_path: Path) -> None:
    app_settings = settings(tmp_path)
    manager = DatabaseManager(app_settings)
    manager.initialize_database()

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(manager.session_factory)

    app = create_app(app_settings, unit_of_work_factory=factory)
    asyncio.run(app.state.multimodal_service.initialize_catalog())
    spatial = SpatialService(factory, environment_name="home")
    root = asyncio.run(spatial.ensure_root())
    space_id = asyncio.run(
        spatial.create_space(parent_id=root.id, name="API Voice Room", space_type="room")
    ).id
    with manager.session_factory() as session:
        environment_id = session.scalars(select(Environment.id)).one()
    multimodal = app.state.multimodal_service
    capture = asyncio.run(
        multimodal.create_consent(
            MultimodalConsentCreate(
                environment_id=environment_id,
                user_id="user-1",
                consent_type="capture",
                modality="audio",
                purpose="speech_input",
                processing_locations=["local"],
                space_ids=[space_id],
            )
        )
    ).id
    processing = asyncio.run(
        multimodal.create_consent(
            MultimodalConsentCreate(
                environment_id=environment_id,
                user_id="user-1",
                consent_type="processing",
                modality="audio",
                purpose="speech_input",
                provider_name="mock",
                processing_locations=["local"],
                space_ids=[space_id],
            )
        )
    ).id
    client = TestClient(app)
    response = client.post(
        "/api/chat/voice",
        headers=HEADERS,
        files={"audio": ("speech.wav", WAV, "audio/wav")},
        data={
            "environment_id": environment_id,
            "space_id": space_id,
            "user_id": "user-1",
            "capture_consent_id": capture,
            "processing_consent_id": processing,
            "require_wake_word": "false",
            "duration_ms": "1200",
            "client_captured_at": NOW.isoformat(),
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["interaction_state"] == "not_instruction"
    assert payload["recognition"]["model_id"] == "mock"
    assert payload["media_purged"] is True
    state = client.get("/api/chat/voice/state", headers=HEADERS)
    assert state.status_code == 200
    assert state.json()["continuous_capture_enabled"] is False
    with manager.session_factory() as session:
        assets = list(session.scalars(select(MultimodalMediaAsset)).all())
    assert len(assets) == 1
    assert assets[0].purge_status == "purged"
    manager.dispose()


def test_upload_consent_is_required_before_voice_processing(tmp_path: Path) -> None:
    provider = FakeSTTProvider(is_instruction=True, transcript="Arvuno 查询")
    environment = VoiceEnvironment(tmp_path, provider)
    request = environment.request()
    request.capture_consent_id = "missing-consent"
    service = VoiceInteractionService(environment.multimodal, FakeAgentRuntime(), FakeTaskSystem())
    try:
        with pytest.raises(MultimodalError, match="MULTIMODAL_CONSENT_NOT_FOUND"):
            asyncio.run(
                service.process(
                    request,
                    WAV,
                    correlation_id="correlation-denied",
                    client_request_id="request-denied",
                )
            )
        assert environment.assets() == []
    finally:
        environment.dispose()
