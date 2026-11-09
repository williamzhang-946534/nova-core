import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.multimodal.errors import MultimodalError
from arvuno_core.multimodal.models import (
    MultimodalAnalyzeRequest,
    MultimodalCaptureSessionCreate,
    MultimodalConsentCreate,
    MultimodalMediaUpload,
    MultimodalTTSRequest,
)
from arvuno_core.multimodal.providers import ProviderResult
from arvuno_core.multimodal.service import MultimodalService
from arvuno_core.observations.service import ObservationService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import (
    Entity,
    Environment,
    MultimodalCaptureSession,
    MultimodalMediaAsset,
    MultimodalProvider,
    MultimodalProviderInvocation,
    Observation,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.spatial.service import SpatialService

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
PNG = b"\x89PNG\r\n\x1a\n" + b"test-image"
WAV = b"RIFF" + (len(b"test-audio")).to_bytes(4, "little") + b"WAVE" + b"test-audio"
HEADERS = {"Authorization": "Bearer test-api-token"}


class SlowVisionProvider:
    capability = "vision_scene"
    provider_name = "mock"
    model_id = "mock"
    model_version = "slow-test"
    processing_location = "local"

    async def process(self, **_kwargs: object) -> ProviderResult:
        await asyncio.sleep(0.2)
        raise AssertionError("The provider should have been cancelled.")


class SlowTTSProvider:
    capability = "tts"
    provider_name = "mock"
    model_id = "mock"
    model_version = "slow-test"
    processing_location = "local"

    async def process(self, **_kwargs: object) -> ProviderResult:
        await asyncio.sleep(0.2)
        raise AssertionError("The provider should have been cancelled.")


class FailingVisionProvider:
    capability = "vision_scene"
    provider_name = "mock"
    model_id = "mock"
    model_version = "failing-test"
    processing_location = "local"

    async def process(self, **_kwargs: object) -> ProviderResult:
        raise RuntimeError("simulated local provider crash")


def phase_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


class MultimodalEnvironment:
    def __init__(self, tmp_path: Path) -> None:
        self.settings = phase_settings(tmp_path)
        self.manager = DatabaseManager(self.settings)
        self.manager.initialize_database()

        def factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(self.manager.session_factory)

        self.factory = factory
        self.observation_service = ObservationService(factory)
        self.service = MultimodalService(factory, self.observation_service, self.settings)
        asyncio.run(self.service.initialize_catalog())
        self.spatial = SpatialService(factory, environment_name="home")
        root = asyncio.run(self.spatial.ensure_root())
        self.room_id = asyncio.run(
            self.spatial.create_space(
                parent_id=root.id,
                name="Multimodal Room",
                space_type="room",
            )
        ).id
        with self.manager.session_factory() as session:
            self.environment_id = session.scalars(select(Environment.id)).one()

    def grant(self, **overrides: object) -> str:
        values: dict[str, object] = {
            "environment_id": self.environment_id,
            "user_id": "user-1",
            "consent_type": "capture",
            "modality": "image",
            "purpose": "user_query",
            "processing_locations": ["local"],
        }
        values.update(overrides)
        return asyncio.run(
            self.service.create_consent(MultimodalConsentCreate(**values))  # type: ignore[arg-type]
        ).id

    def session(self, **overrides: object) -> str:
        values: dict[str, object] = {
            "environment_id": self.environment_id,
            "space_id": self.room_id,
            "modality": "image",
            "purpose": "user_query",
            "requested_by": "user-1",
        }
        values.update(overrides)
        return asyncio.run(
            self.service.create_capture_session(MultimodalCaptureSessionCreate(**values))  # type: ignore[arg-type]
        ).id

    def analyze(
        self,
        asset_id: str,
        capability: str,
        consent_id: str,
    ) -> object:
        return asyncio.run(
            self.service.analyze(
                asset_id,
                MultimodalAnalyzeRequest(
                    capability=capability,  # type: ignore[arg-type]
                    provider_name="mock",
                    consent_id=consent_id,
                ),
            )
        )

    def asset(self, asset_id: str) -> MultimodalMediaAsset:
        with self.manager.session_factory() as session:
            asset = session.get(MultimodalMediaAsset, asset_id)
            assert asset is not None
            return asset

    def dispose(self) -> None:
        self.manager.dispose()


def vision_consent(environment: MultimodalEnvironment, purpose: str = "user_query") -> str:
    return environment.grant(
        consent_type="capture",
        modality="image",
        purpose=purpose,
        space_ids=[environment.room_id],
    )


def processing_consent(
    environment: MultimodalEnvironment,
    *,
    modality: str = "image",
    purpose: str = "user_query",
) -> str:
    return environment.grant(
        consent_type="processing",
        modality=modality,
        purpose=purpose,
        provider_name="mock",
        processing_locations=["local"],
        space_ids=[environment.room_id],
    )


def upload(
    environment: MultimodalEnvironment,
    *,
    content: bytes = PNG,
    sensitivity: str = "normal",
    **session_overrides: object,
) -> str:
    modality = str(session_overrides.get("modality", "image"))
    session_id = environment.session(**session_overrides)
    upload_consent = environment.grant(
        consent_type="capture",
        modality=modality,
        purpose=str(session_overrides.get("purpose", "user_query")),
        space_ids=[environment.room_id],
    )
    asset = asyncio.run(
        environment.service.upload_media(
            session_id,
            MultimodalMediaUpload(
                consent_id=upload_consent,
                sensitivity=sensitivity,  # type: ignore[arg-type]
                client_captured_at=NOW,
                client_time_source="device_clock",
                client_time_uncertainty_ms=120,
            ),
            content,
        )
    )
    return asset.id


def observation_count(environment: MultimodalEnvironment) -> int:
    with environment.manager.session_factory() as session:
        return int(session.scalar(select(func.count()).select_from(Observation)) or 0)


def test_image_processing_creates_candidate_observation_then_deletes_raw_media(
    tmp_path: Path,
) -> None:
    environment = MultimodalEnvironment(tmp_path)
    try:
        asset_id = upload(environment, sensitivity="sensitive")
        asset = environment.asset(asset_id)
        assert asset.content_available is True
        assert asset.storage_key is not None
        media_path = environment.service.media_root / asset.storage_key
        assert media_path.is_file()

        result = environment.analyze(asset_id, "vision_scene", processing_consent(environment))
        assert result.extraction.result_kind == "scene_labels"
        assert result.extraction.confidence == 0.8
        assert result.extraction.model_id == "mock"
        assert len(result.observations) == 1
        assert result.observations[0].source_type == "vision"
        assert len(result.artifact_links) == 1
        assert result.artifact_links[0].target_type == "observation"

        purged = environment.asset(asset_id)
        assert purged.content_available is False
        assert purged.storage_key is None
        assert purged.purge_status == "purged"
        assert not media_path.exists()
        assert observation_count(environment) == 1
    finally:
        environment.dispose()


def test_vision_objects_are_candidates_and_never_create_entities(tmp_path: Path) -> None:
    environment = MultimodalEnvironment(tmp_path)
    try:
        asset_id = upload(environment)
        result = environment.analyze(asset_id, "vision_object", processing_consent(environment))
        extraction_result = result.extraction.result
        assert extraction_result["identity_state"] == "candidate"
        assert all(item["confidence"] < 1 for item in extraction_result["objects"])
        assert result.observations[0].attribute == "object_presence"

        with environment.manager.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Entity)) == 0
    finally:
        environment.dispose()


def test_processing_requires_matching_explicit_consent(tmp_path: Path) -> None:
    environment = MultimodalEnvironment(tmp_path)
    try:
        asset_id = upload(environment)
        wrong_modality = processing_consent(environment, modality="audio")
        with pytest.raises(MultimodalError, match="MULTIMODAL_CONSENT_MODALITY_INVALID"):
            environment.analyze(asset_id, "vision_scene", wrong_modality)
        missing_consent = environment.grant(
            consent_type="processing",
            modality="image",
            purpose="user_query",
            provider_name="mock",
            processing_locations=["local"],
            space_ids=[environment.room_id],
        )
        asyncio.run(environment.service.revoke_consent(missing_consent))
        with pytest.raises(MultimodalError, match="MULTIMODAL_CONSENT_NOT_ACTIVE"):
            environment.analyze(asset_id, "vision_scene", missing_consent)
    finally:
        environment.dispose()


def test_capture_consent_required_session_rejects_upload(tmp_path: Path) -> None:
    environment = MultimodalEnvironment(tmp_path)
    try:
        session_id = environment.session(requires_capture_consent=True)
        consent_id = vision_consent(environment)
        with pytest.raises(MultimodalError) as error:
            asyncio.run(
                environment.service.upload_media(
                    session_id,
                    MultimodalMediaUpload(
                        consent_id=consent_id,
                        client_captured_at=NOW,
                        client_time_source="device_clock",
                        client_time_uncertainty_ms=120,
                    ),
                    PNG,
                )
            )
        assert error.value.code == "MULTIMODAL_CAPTURE_NOT_AUTHORIZED"
        assert observation_count(environment) == 0
    finally:
        environment.dispose()


def test_speech_to_text_is_data_and_not_an_observation(tmp_path: Path) -> None:
    environment = MultimodalEnvironment(tmp_path)
    try:
        asset_id = upload(
            environment,
            content=WAV,
            modality="audio",
            purpose="speech_input",
            sensitivity="sensitive",
        )
        consent_id = processing_consent(environment, modality="audio", purpose="speech_input")
        result = environment.analyze(asset_id, "stt", consent_id)
        assert result.extraction.result_kind == "transcript"
        assert result.extraction.result["is_instruction"] is False
        assert result.observations == []
        assert observation_count(environment) == 0
    finally:
        environment.dispose()


def test_tts_creates_private_output_without_an_observation(tmp_path: Path) -> None:
    environment = MultimodalEnvironment(tmp_path)
    try:
        consent_id = environment.grant(
            consent_type="processing",
            modality="audio",
            purpose="accessibility_output",
            provider_name="mock",
            processing_locations=["local"],
        )
        result = asyncio.run(
            environment.service.synthesize_speech(
                MultimodalTTSRequest(
                    environment_id=environment.environment_id,
                    text="Please say this locally.",
                    requested_by="user-1",
                    consent_id=consent_id,
                )
            )
        )
        asset = environment.asset(result.media_asset.id)
        assert asset.media_kind == "tts_audio"
        assert asset.storage_key is not None
        assert (environment.service.media_root / asset.storage_key).is_file()
        assert result.extraction.result["synthesized"] is True
        assert result.observations == []
        assert observation_count(environment) == 0
    finally:
        environment.dispose()


def test_vision_provider_timeout_marks_invocation_and_purges_media(tmp_path: Path) -> None:
    environment = MultimodalEnvironment(tmp_path)
    try:
        with environment.manager.session_factory() as session:
            provider = session.scalar(
                select(MultimodalProvider).where(
                    MultimodalProvider.capability == "vision_scene",
                )
            )
            assert provider is not None
            provider.timeout_ms = 20
            session.commit()

        timeout_service = MultimodalService(
            environment.factory,
            environment.observation_service,
            environment.settings,
            adapters={"vision_scene": SlowVisionProvider()},
        )
        asset_id = upload(environment)
        with pytest.raises(MultimodalError) as error:
            asyncio.run(
                timeout_service.analyze(
                    asset_id,
                    MultimodalAnalyzeRequest(
                        capability="vision_scene",
                        provider_name="mock",
                        consent_id=processing_consent(environment),
                    ),
                )
            )
        assert error.value.code == "MULTIMODAL_PROVIDER_TIMEOUT"
        assert error.value.status_code == 504

        purged = environment.asset(asset_id)
        assert purged.content_available is False
        assert purged.storage_key is None
        assert purged.purge_status == "purged"
        assert purged.purge_reason == "processing_failed"
        assert observation_count(environment) == 0
        with environment.manager.session_factory() as session:
            invocation = session.scalar(select(MultimodalProviderInvocation))
            assert invocation is not None
            assert invocation.status == "timeout"
            assert invocation.error_code == "MULTIMODAL_PROVIDER_TIMEOUT"
            capture_session = session.scalar(select(MultimodalCaptureSession))
            assert capture_session is not None
            assert capture_session.status == "failed"
    finally:
        environment.dispose()


def test_tts_provider_timeout_cleans_output_and_fails_session(tmp_path: Path) -> None:
    environment = MultimodalEnvironment(tmp_path)
    try:
        with environment.manager.session_factory() as session:
            provider = session.scalar(
                select(MultimodalProvider).where(MultimodalProvider.capability == "tts")
            )
            assert provider is not None
            provider.timeout_ms = 20
            session.commit()

        timeout_service = MultimodalService(
            environment.factory,
            environment.observation_service,
            environment.settings,
            adapters={"tts": SlowTTSProvider()},
        )
        consent_id = environment.grant(
            consent_type="processing",
            modality="audio",
            purpose="accessibility_output",
            provider_name="mock",
            processing_locations=["local"],
        )
        with pytest.raises(MultimodalError) as error:
            asyncio.run(
                timeout_service.synthesize_speech(
                    MultimodalTTSRequest(
                        environment_id=environment.environment_id,
                        text="This call should time out.",
                        requested_by="user-1",
                        consent_id=consent_id,
                    )
                )
            )
        assert error.value.code == "MULTIMODAL_PROVIDER_TIMEOUT"
        assert error.value.status_code == 504

        assert not any(environment.service.media_root.glob("*.wav"))
        with environment.manager.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(MultimodalMediaAsset)) == 0
            capture_session = session.scalar(select(MultimodalCaptureSession))
            assert capture_session is not None
            assert capture_session.status == "failed"
    finally:
        environment.dispose()


def test_vision_provider_failure_purges_media_and_marks_invocation_failed(
    tmp_path: Path,
) -> None:
    environment = MultimodalEnvironment(tmp_path)
    try:
        failing_service = MultimodalService(
            environment.factory,
            environment.observation_service,
            environment.settings,
            adapters={"vision_scene": FailingVisionProvider()},
        )
        asset_id = upload(environment)
        with pytest.raises(MultimodalError) as error:
            asyncio.run(
                failing_service.analyze(
                    asset_id,
                    MultimodalAnalyzeRequest(
                        capability="vision_scene",
                        provider_name="mock",
                        consent_id=processing_consent(environment),
                    ),
                )
            )
        assert error.value.code == "MULTIMODAL_PROVIDER_FAILED"
        assert error.value.status_code == 502

        purged = environment.asset(asset_id)
        assert purged.content_available is False
        assert purged.storage_key is None
        assert purged.purge_status == "purged"
        assert observation_count(environment) == 0
        with environment.manager.session_factory() as session:
            invocation = session.scalar(select(MultimodalProviderInvocation))
            assert invocation is not None
            assert invocation.status == "failed"
            assert invocation.error_code == "MULTIMODAL_PROVIDER_FAILED"
    finally:
        environment.dispose()


def test_audio_events_become_candidate_observations(tmp_path: Path) -> None:
    environment = MultimodalEnvironment(tmp_path)
    try:
        asset_id = upload(
            environment,
            content=WAV,
            modality="audio",
            purpose="audio_event",
        )
        consent_id = processing_consent(environment, modality="audio", purpose="audio_event")
        result = environment.analyze(asset_id, "audio_event", consent_id)
        assert result.extraction.result_kind == "audio_events"
        assert result.extraction.result["interpretation"] == "candidate_only"
        assert result.observations[0].attribute == "audio_event"
        assert observation_count(environment) == 1
    finally:
        environment.dispose()


def test_expired_retention_physically_purges_media(tmp_path: Path) -> None:
    environment = MultimodalEnvironment(tmp_path)
    try:
        consent_id = environment.grant(
            consent_type="processing",
            modality="audio",
            purpose="accessibility_output",
            provider_name="mock",
            processing_locations=["local"],
        )
        result = asyncio.run(
            environment.service.synthesize_speech(
                MultimodalTTSRequest(
                    environment_id=environment.environment_id,
                    text="Retained briefly.",
                    requested_by="user-1",
                    consent_id=consent_id,
                )
            )
        )
        asset_id = result.media_asset.id
        asset = environment.asset(asset_id)
        storage_key = asset.storage_key
        assert storage_key is not None

        purged_count = asyncio.run(
            environment.service.purge_expired(datetime.now(UTC) + timedelta(hours=2))
        )
        purged = environment.asset(asset_id)
        assert purged_count == 1
        assert purged.storage_key is None
        assert purged.purge_reason == "retention_expired"
        assert not (environment.service.media_root / storage_key).exists()
    finally:
        environment.dispose()


def test_purged_content_and_storage_keys_are_unavailable(tmp_path: Path) -> None:
    environment = MultimodalEnvironment(tmp_path)
    app = create_app(environment.settings, unit_of_work_factory=environment.factory)
    app.state.multimodal_service = environment.service
    client = TestClient(app)
    try:
        asset_id = upload(environment, sensitivity="sensitive")
        environment.analyze(asset_id, "vision_scene", processing_consent(environment))
        response = client.get(
            f"/api/multimodal/media-assets/{asset_id}/content",
            headers=HEADERS,
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "MULTIMODAL_MEDIA_UNAVAILABLE"

        listed = client.get("/api/multimodal/extraction-results", headers=HEADERS)
        assert listed.status_code == 200
        assert listed.json() != []
        assert all("storage_key" not in item for item in listed.json())
    finally:
        client.close()
        environment.dispose()


def test_multimodal_api_requires_authorization(tmp_path: Path) -> None:
    environment = MultimodalEnvironment(tmp_path)
    app = create_app(environment.settings, unit_of_work_factory=environment.factory)
    client = TestClient(app)
    try:
        assert client.get("/api/multimodal/capabilities").status_code == 401
        assert client.get("/api/multimodal/capabilities", headers=HEADERS).status_code == 200
        capabilities = client.get("/api/multimodal/capabilities", headers=HEADERS).json()["data"]
        assert capabilities["camera_capture_enabled"] is False
        assert capabilities["microphone_capture_enabled"] is False
        assert capabilities["continuous_video_analysis_enabled"] is False
        assert capabilities["cloud_processing_enabled"] is False
    finally:
        client.close()
        environment.dispose()
