import asyncio
import json
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
    MultimodalDataAccessGrantCreate,
    MultimodalFusionQuery,
    MultimodalMediaUpload,
    MultimodalTTSRequest,
)
from arvuno_core.multimodal.service import MultimodalService
from arvuno_core.observations.models import ObservationInput
from arvuno_core.observations.service import ObservationService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import (
    Environment,
    MultimodalDataAccessGrant,
    MultimodalExtractionResult,
    MultimodalMediaAsset,
    Observation,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.spatial.service import SpatialService

HEADERS = {"Authorization": "Bearer test-api-token"}
PNG = b"\x89PNG\r\n\x1a\n" + b"fusion-image"
WAV = b"RIFF" + (len(b"secret audio")).to_bytes(4, "little") + b"WAVE" + b"secret audio"


def phase_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


class FusionEnvironment:
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
                name="Fusion Room",
                space_type="room",
            )
        ).id
        self.sensor_source_id = asyncio.run(
            self.observation_service.register_source(
                source_type="adapter",
                name="Fusion test sensor",
                adapter_id="fusion-test-sensor",
                time_trust="device_clock",
            )
        ).id
        with self.manager.session_factory() as session:
            self.environment_id = session.scalars(select(Environment.id)).one()

    def grant(
        self,
        *,
        modalities: list[str] | None = None,
        space_ids: list[str] | None = None,
        expires_at: datetime | None = None,
    ) -> str:
        return asyncio.run(
            self.service.create_data_access_grant(
                MultimodalDataAccessGrantCreate(
                    environment_id=self.environment_id,
                    user_id="user-1",
                    modalities=modalities or ["image", "sensor"],
                    space_ids=space_ids or [self.room_id],
                    expires_at=expires_at,
                )
            )
        ).id

    def upload_image(
        self,
        *,
        captured_at: datetime,
        sensitivity: str = "normal",
        correlation_id: str | None = None,
    ) -> str:
        session_id = asyncio.run(
            self.service.create_capture_session(
                MultimodalCaptureSessionCreate(
                    environment_id=self.environment_id,
                    space_id=self.room_id,
                    modality="image",
                    purpose="user_query",
                    requested_by="user-1",
                    correlation_id=correlation_id,
                )
            )
        ).id
        consent_id = asyncio.run(
            self.service.create_consent(
                MultimodalConsentCreate(
                    environment_id=self.environment_id,
                    user_id="user-1",
                    consent_type="capture",
                    modality="image",
                    purpose="user_query",
                    processing_locations=["local"],
                    space_ids=[self.room_id],
                )
            )
        ).id
        return asyncio.run(
            self.service.upload_media(
                session_id,
                MultimodalMediaUpload(
                    consent_id=consent_id,
                    sensitivity=sensitivity,  # type: ignore[arg-type]
                    client_captured_at=captured_at,
                    client_time_source="device_clock",
                    client_time_uncertainty_ms=100,
                ),
                PNG,
            )
        ).id

    def analyze(self, asset_id: str, capability: str, consent_id: str) -> object:
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

    def processing_consent(
        self,
        *,
        modality: str,
        purpose: str,
    ) -> str:
        return asyncio.run(
            self.service.create_consent(
                MultimodalConsentCreate(
                    environment_id=self.environment_id,
                    user_id="user-1",
                    consent_type="processing",
                    modality=modality,  # type: ignore[arg-type]
                    purpose=purpose,  # type: ignore[arg-type]
                    provider_name="mock",
                    processing_locations=["local"],
                    space_ids=[self.room_id],
                )
            )
        ).id

    def capture_consent(
        self,
        *,
        modality: str,
        purpose: str,
    ) -> str:
        return asyncio.run(
            self.service.create_consent(
                MultimodalConsentCreate(
                    environment_id=self.environment_id,
                    user_id="user-1",
                    consent_type="capture",
                    modality=modality,  # type: ignore[arg-type]
                    purpose=purpose,  # type: ignore[arg-type]
                    processing_locations=["local"],
                    space_ids=[self.room_id],
                )
            )
        ).id

    def add_sensor_value(
        self,
        value: dict[str, object],
        *,
        observed_at: datetime,
        external_id: str,
        correlation_id: str | None = None,
    ) -> None:
        result = asyncio.run(
            self.observation_service.record(
                ObservationInput(
                    source_id=self.sensor_source_id,
                    subject_type="space",
                    subject_id=self.room_id,
                    space_id=self.room_id,
                    attribute="actuator_state",
                    raw_value=value,
                    observed_at=observed_at,
                    observed_at_source="device_clock",
                    received_at=observed_at,
                    correlation_id=correlation_id,
                    external_id=external_id,
                )
            )
        )
        assert result.duplicate is False
        with self.manager.session_factory() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Observation)
                    .where(Observation.external_id == external_id)
                )
                == 1
            )

    def counts(self) -> tuple[int, int, int]:
        with self.manager.session_factory() as session:
            return (
                int(session.scalar(select(func.count()).select_from(Observation)) or 0),
                int(
                    session.scalar(select(func.count()).select_from(MultimodalExtractionResult))
                    or 0
                ),
                len(list(session.scalars(select(MultimodalDataAccessGrant.id)))),
            )

    def dispose(self) -> None:
        self.manager.dispose()


def fusion_query(
    environment: FusionEnvironment,
    grant_id: str,
    *,
    minutes: int = 30,
    **overrides: object,
) -> object:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "environment_id": environment.environment_id,
        "grant_id": grant_id,
        "from_at": now - timedelta(minutes=minutes),
        "to_at": now + timedelta(seconds=30),
    }
    values.update(overrides)
    return asyncio.run(environment.service.query_fusion(MultimodalFusionQuery(**values)))  # type: ignore[arg-type]


def test_time_space_fusion_preserves_sources_and_does_not_materialize_facts(
    tmp_path: Path,
) -> None:
    environment = FusionEnvironment(tmp_path)
    try:
        captured_at = datetime.now(UTC) - timedelta(minutes=1)
        asset_id = environment.upload_image(captured_at=captured_at)
        consent_id = environment.processing_consent(modality="image", purpose="user_query")
        environment.analyze(asset_id, "vision_scene", consent_id)
        environment.add_sensor_value(
            {"label": "desk"},
            observed_at=captured_at + timedelta(seconds=10),
            external_id="sensor-before-fusion",
            correlation_id="fusion-session",
        )
        grant_id = environment.grant()
        before = environment.counts()
        result = fusion_query(environment, grant_id)
        assert result.total_available == 3
        assert {item.modality for item in result.items} == {"image", "sensor"}
        assert result.causal_claim is False
        observations = [item for item in result.items if item.artifact_type == "observation"]
        assert len(observations) == 2
        observation = next(
            item for item in observations if item.source_id == environment.sensor_source_id
        )
        vision_observation = next(
            item for item in observations if item.source_id != environment.sensor_source_id
        )
        assert vision_observation.source_type == "vision"
        extraction = next(
            item for item in result.items if item.artifact_type == "extraction_result"
        )
        assert observation.source_id == environment.sensor_source_id
        assert observation.model_id is None
        assert extraction.source_type == "multimodal_provider"
        assert extraction.model_id == "mock"
        assert extraction.model_version == "1.0.0"
        assert extraction.quality_status == "valid_candidate"
        assert observation.id in extraction.association["related_ids"]
        assert vision_observation.id in extraction.association["related_ids"]
        assert extraction.id in observation.association["related_ids"]
        assert extraction.id in vision_observation.association["related_ids"]

        after = environment.counts()
        assert before == after
    finally:
        environment.dispose()


def test_fusion_marks_duplicates_and_conflicts_without_overwriting_sources(
    tmp_path: Path,
) -> None:
    environment = FusionEnvironment(tmp_path)
    try:
        observed_at = datetime.now(UTC) - timedelta(minutes=1)
        environment.add_sensor_value(
            {"label": "chair"},
            observed_at=observed_at,
            external_id="sensor-same-1",
        )
        environment.add_sensor_value(
            {"label": "chair"},
            observed_at=observed_at,
            external_id="sensor-same-2",
        )
        environment.add_sensor_value(
            {"label": "table"},
            observed_at=observed_at,
            external_id="sensor-conflict",
        )
        grant_id = environment.grant(modalities=["sensor"])

        result = fusion_query(environment, grant_id)
        assert result.total_available == 3
        items = {item.id: item for item in result.items}
        assert len(items) == 3
        for item in result.items:
            assert len(item.association["related_ids"]) == 2
            if item.value == {"label": "table"}:
                assert len(item.association["conflict_candidate_ids"]) == 2
                assert item.association["duplicate_candidate_ids"] == []
            else:
                assert item.association["duplicate_candidate_ids"]
    finally:
        environment.dispose()


def test_fusion_rejects_missing_revoked_expired_and_cross_environment_grants(
    tmp_path: Path,
) -> None:
    environment = FusionEnvironment(tmp_path)
    try:
        with pytest.raises(MultimodalError) as missing:
            fusion_query(environment, "00000000-0000-0000-0000-000000000000")
        assert missing.value.status_code == 404

        with environment.manager.session_factory() as session:
            expired_grant = MultimodalDataAccessGrant(
                environment_id=environment.environment_id,
                user_id="user-1",
                modalities=["sensor"],
                space_ids=[environment.room_id],
                granted_at=datetime.now(UTC) - timedelta(minutes=2),
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
                status="granted",
            )
            session.add(expired_grant)
            session.commit()
            expired_id = expired_grant.id
        with pytest.raises(MultimodalError) as expired:
            fusion_query(environment, expired_id)
        assert expired.value.status_code == 403

        revoked_id = environment.grant()
        asyncio.run(environment.service.revoke_data_access_grant(revoked_id))
        with pytest.raises(MultimodalError) as revoked:
            fusion_query(environment, revoked_id)
        assert revoked.value.status_code == 403

        other_environment = Environment(name="other", is_default=False)
        with environment.manager.session_factory() as session:
            session.add(other_environment)
            session.commit()
            foreign_grant = MultimodalDataAccessGrant(
                environment_id=other_environment.id,
                user_id="user-1",
                modalities=["sensor"],
                space_ids=[environment.room_id],
                granted_at=datetime.now(UTC),
                status="granted",
            )
            session.add(foreign_grant)
            session.commit()
            foreign_grant_id = foreign_grant.id
        with pytest.raises(MultimodalError) as foreign:
            fusion_query(environment, foreign_grant_id)
        assert foreign.value.code == "MULTIMODAL_GRANT_SCOPE_INVALID"
    finally:
        environment.dispose()


def test_sensitive_ocr_and_transcripts_are_physically_deleted_and_absent_from_audit(
    tmp_path: Path,
) -> None:
    environment = FusionEnvironment(tmp_path)
    try:
        captured_at = datetime.now(UTC) - timedelta(minutes=1)
        image_id = environment.upload_image(
            captured_at=captured_at,
            sensitivity="sensitive",
            correlation_id="sensitive-ocr",
        )
        image_consent = environment.processing_consent(
            modality="image",
            purpose="user_query",
        )
        environment.analyze(image_id, "ocr", image_consent)

        session_id = asyncio.run(
            environment.service.create_capture_session(
                MultimodalCaptureSessionCreate(
                    environment_id=environment.environment_id,
                    space_id=environment.room_id,
                    modality="audio",
                    purpose="speech_input",
                    requested_by="user-1",
                    correlation_id="sensitive-stt",
                )
            )
        ).id
        capture_consent = environment.capture_consent(
            modality="audio",
            purpose="speech_input",
        )
        processing_consent = environment.processing_consent(
            modality="audio",
            purpose="speech_input",
        )
        audio_id = asyncio.run(
            environment.service.upload_media(
                session_id,
                MultimodalMediaUpload(
                    consent_id=capture_consent,
                    sensitivity="sensitive",
                    client_captured_at=captured_at,
                    client_time_source="device_clock",
                ),
                WAV,
            )
        ).id
        environment.analyze(audio_id, "stt", processing_consent)

        purged_ids = []
        for asset_id in (image_id, audio_id):
            asset = asyncio.run(environment.service.purge_asset(asset_id))
            purged_ids.append(asset_id)
            assert asset.content_available is False
            assert asset.purge_reason in {
                "processed_then_deleted",
                "user_requested",
            }

        with environment.manager.session_factory() as session:
            kinds = list(session.scalars(select(MultimodalExtractionResult.result_kind)))
        assert "ocr_text" not in kinds
        assert "transcript" not in kinds
        with environment.manager.session_factory() as session:
            assets = list(session.scalars(select(MultimodalMediaAsset)))
        assert {asset.id for asset in assets} == set(purged_ids)
        assert all(asset.storage_key is None for asset in assets)
        assert all(not asset.content_available for asset in assets)
        assert all(
            asset.purge_reason in {"processed_then_deleted", "user_requested"} for asset in assets
        )

        events = asyncio.run(environment.service.list_audit_events(environment.environment_id))
        encoded_events = json.dumps(
            [event.model_dump(mode="json") for event in events],
            ensure_ascii=False,
        )
        assert "secret ocr text" not in encoded_events.lower()
        assert "secret audio" not in encoded_events.lower()
    finally:
        environment.dispose()


def test_revoking_processing_consent_purges_its_private_output(tmp_path: Path) -> None:
    environment = FusionEnvironment(tmp_path)
    try:
        consent_id = environment.processing_consent(
            modality="audio",
            purpose="accessibility_output",
        )
        result = asyncio.run(
            environment.service.synthesize_speech(
                MultimodalTTSRequest(
                    environment_id=environment.environment_id,
                    text="Temporary private output.",
                    requested_by="user-1",
                    consent_id=consent_id,
                )
            )
        )
        asset_id = result.media_asset.id
        with environment.manager.session_factory() as session:
            asset = session.get(MultimodalMediaAsset, asset_id)
            assert asset is not None
            storage_key = asset.storage_key
        assert storage_key is not None

        revoked = asyncio.run(environment.service.revoke_consent(consent_id))
        assert revoked.status == "revoked"
        purged = asyncio.run(environment.service.purge_asset(asset_id))
        assert purged.content_available is False
        assert purged.purge_reason == "consent_revoked"
        assert not (environment.service.media_root / storage_key).exists()
        with environment.manager.session_factory() as session:
            stored = session.get(MultimodalMediaAsset, asset_id)
            assert stored is not None
            assert stored.storage_key is None
            assert stored.content_available is False
            assert stored.purge_reason == "consent_revoked"
    finally:
        environment.dispose()


def test_fusion_api_requires_authorization_and_validates_range(tmp_path: Path) -> None:
    environment = FusionEnvironment(tmp_path)
    app = create_app(environment.settings, unit_of_work_factory=environment.factory)
    client = TestClient(app)
    try:
        grant_id = environment.grant()
        response = client.post(
            "/api/multimodal/fusion/query",
            json={
                "environment_id": environment.environment_id,
                "grant_id": grant_id,
                "from_at": datetime.now(UTC).isoformat(),
                "to_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            },
        )
        assert response.status_code == 401

        authorized = client.post(
            "/api/multimodal/fusion/query",
            headers=HEADERS,
            json={
                "environment_id": environment.environment_id,
                "grant_id": grant_id,
                "from_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                "to_at": datetime.now(UTC).isoformat(),
            },
        )
        assert authorized.status_code == 200
        assert authorized.json()["data"]["causal_claim"] is False

        with pytest.raises(MultimodalError) as invalid:
            fusion_query(
                environment,
                grant_id,
                minutes=-1,
            )
        assert invalid.value.code == "MULTIMODAL_FUSION_RANGE_INVALID"
    finally:
        client.close()
        environment.dispose()
