import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.errors import ArvunoError
from arvuno_core.events.bus import EventBus
from arvuno_core.events.models import ArvunoEvent
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import (
    Conversation,
    ConversationMessage,
    Environment,
    Event,
    Memory,
    MemoryConsent,
    MultimodalCaptureSession,
    MultimodalConsent,
    MultimodalDataAccessGrant,
    MultimodalMediaAsset,
    ProviderLog,
    UserPreference,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.privacy.models import PrivacyErasureRequest
from arvuno_core.privacy.service import PrivacyService

OWNER = "privacy-user"
OTHER = "privacy-other"
CONVERSATION_ID = "privacy-conversation"


def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


class RecordingEventBus(EventBus):
    def __init__(self) -> None:
        self.published: list[ArvunoEvent] = []

    async def publish(self, event: ArvunoEvent) -> None:
        self.published.append(event)


class PrivacyEnvironment:
    def __init__(self, tmp_path: Path) -> None:
        self.settings = settings(tmp_path)
        self.manager = DatabaseManager(self.settings)
        self.manager.initialize_database()
        self.media_root = self.settings.resolved_data_dir / "media" / "multimodal"
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.event_bus = RecordingEventBus()

        def factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(self.manager.session_factory)

        self.factory = factory
        self.service = PrivacyService(factory, self.media_root, self.event_bus)

    def seed(self) -> None:
        (self.media_root / "private-user.bin").write_bytes(b"owner media")
        (self.media_root / "private-other.bin").write_bytes(b"other media")
        with self.manager.session_factory() as session:
            session.add(Environment(id="privacy-env", name="Privacy Home", is_default=True))
            session.add_all(
                [
                    Memory(
                        id="owner-memory",
                        memory_type="semantic",
                        title="Owner memory",
                        content="private owner content",
                        keywords=[],
                        importance=2,
                        source_type="user",
                        user_confirmed=True,
                        owner_id=OWNER,
                    ),
                    Memory(
                        id="other-memory",
                        memory_type="semantic",
                        title="Other memory",
                        content="private other content",
                        keywords=[],
                        importance=2,
                        source_type="user",
                        user_confirmed=True,
                        owner_id=OTHER,
                    ),
                    MemoryConsent(
                        id="owner-memory-consent",
                        subject_id=OWNER,
                        grant_type="memory_store",
                        statement="store owner memories",
                    ),
                    UserPreference(
                        id="owner-preference",
                        key="privacy-owner",
                        value={"unit": "C"},
                        category="environment",
                        source="chat",
                        source_type="user",
                        source_record_id="owner-message",
                        scope={"owner_id": OWNER},
                        confirmed=True,
                        confirmed_at=datetime.now(UTC),
                    ),
                    UserPreference(
                        id="other-preference",
                        key="privacy-other",
                        value={"unit": "F"},
                        category="environment",
                        source="chat",
                        source_type="user",
                        source_record_id="other-message",
                        scope={"owner_id": OTHER},
                        confirmed=True,
                        confirmed_at=datetime.now(UTC),
                    ),
                    Conversation(
                        id=CONVERSATION_ID,
                        title="Owner conversation",
                        status="active",
                    ),
                    ConversationMessage(
                        id="owner-message",
                        conversation_id=CONVERSATION_ID,
                        role="user",
                        content="private message",
                        correlation_id=CONVERSATION_ID,
                    ),
                    ProviderLog(
                        id="owner-provider-log",
                        provider="mock",
                        model="mock-model",
                        request_kind="chat",
                        input_summary={
                            "schema_version": 2,
                            "correlation_id": CONVERSATION_ID,
                            "message_count": 1,
                            "role_distribution": {"user": 1},
                        },
                        output_summary={"schema_version": 2},
                        status="succeeded",
                    ),
                    ProviderLog(
                        id="other-provider-log",
                        provider="mock",
                        model="mock-model",
                        request_kind="chat",
                        input_summary={
                            "schema_version": 2,
                            "correlation_id": "other-conversation",
                            "message_count": 1,
                            "role_distribution": {"user": 1},
                        },
                        output_summary={"schema_version": 2},
                        status="succeeded",
                    ),
                    MultimodalConsent(
                        id="owner-consent",
                        environment_id="privacy-env",
                        user_id=OWNER,
                        consent_type="capture",
                        modality="image",
                        purpose="user_query",
                        processing_locations=["local"],
                        space_ids=[],
                        granted_at=datetime.now(UTC),
                    ),
                    MultimodalConsent(
                        id="other-consent",
                        environment_id="privacy-env",
                        user_id=OTHER,
                        consent_type="capture",
                        modality="image",
                        purpose="user_query",
                        processing_locations=["local"],
                        space_ids=[],
                        granted_at=datetime.now(UTC),
                    ),
                    MultimodalCaptureSession(
                        id="owner-capture-session",
                        environment_id="privacy-env",
                        modality="image",
                        purpose="user_query",
                        origin_type="user",
                        requested_by=OWNER,
                    ),
                    MultimodalMediaAsset(
                        id="owner-media",
                        capture_session_id="owner-capture-session",
                        environment_id="privacy-env",
                        media_kind="image",
                        mime_type="image/png",
                        size_bytes=11,
                        storage_backend="private_local_file",
                        storage_key="private-user.bin",
                        content_available=True,
                        purpose="user_query",
                        consent_id="owner-consent",
                        retention_class="process_then_delete_24h",
                        retention_until=datetime.now(UTC),
                        received_at=datetime.now(UTC),
                    ),
                    MultimodalMediaAsset(
                        id="other-media",
                        environment_id="privacy-env",
                        media_kind="image",
                        mime_type="image/png",
                        size_bytes=11,
                        storage_backend="private_local_file",
                        storage_key="private-other.bin",
                        content_available=True,
                        purpose="user_query",
                        consent_id="other-consent",
                        retention_class="process_then_delete_24h",
                        retention_until=datetime.now(UTC),
                        received_at=datetime.now(UTC),
                    ),
                    MultimodalDataAccessGrant(
                        id="owner-access-grant",
                        environment_id="privacy-env",
                        user_id=OWNER,
                        modalities=["image"],
                        space_ids=[],
                        granted_at=datetime.now(UTC),
                    ),
                    Event(
                        id="owner-audit-event",
                        event_type="privacy_erasure_completed",
                        source="api",
                        subject_type="user",
                        subject_id=OWNER,
                        payload={},
                        occurred_at=datetime.now(UTC),
                    ),
                ]
            )
            session.commit()

    def counts(self) -> dict[str, Any]:
        with self.manager.session_factory() as session:
            scalar = select
            return {
                "memories": len(session.scalars(scalar(Memory.id)).all()),
                "memory_consents": len(session.scalars(scalar(MemoryConsent.id)).all()),
                "preferences": len(session.scalars(scalar(UserPreference.id)).all()),
                "conversations": len(session.scalars(scalar(Conversation.id)).all()),
                "messages": len(session.scalars(scalar(ConversationMessage.id)).all()),
                "provider_logs": len(session.scalars(scalar(ProviderLog.id)).all()),
                "media_assets": len(session.scalars(scalar(MultimodalMediaAsset.id)).all()),
                "capture_sessions": len(session.scalars(scalar(MultimodalCaptureSession.id)).all()),
                "access_grants": len(session.scalars(scalar(MultimodalDataAccessGrant.id)).all()),
                "events": len(session.scalars(scalar(Event.id)).all()),
            }

    def dispose(self) -> None:
        self.manager.dispose()


def test_privacy_api_requires_token(tmp_path: Path) -> None:
    environment = PrivacyEnvironment(tmp_path)
    try:
        app = create_app(environment.settings, unit_of_work_factory=environment.factory)
        client = TestClient(app)
        assert client.post("/api/privacy/erasure-requests/impact").status_code == 401
        assert client.post("/api/privacy/erasure-requests").status_code == 401
    finally:
        environment.dispose()


def test_local_user_erasure_requires_explicit_confirmation(tmp_path: Path) -> None:
    environment = PrivacyEnvironment(tmp_path)
    try:
        with pytest.raises(ArvunoError) as exc_info:
            asyncio.run(environment.service.erase(PrivacyErasureRequest(owner_id="local_user")))
        assert exc_info.value.code == "PRIVACY_LOCAL_USER_CONFIRMATION_REQUIRED"
    finally:
        environment.dispose()


def test_impact_and_erasure_are_scoped_to_owner(tmp_path: Path) -> None:
    environment = PrivacyEnvironment(tmp_path)
    try:
        environment.seed()
        request = PrivacyErasureRequest(
            owner_id=OWNER,
            conversation_ids=[CONVERSATION_ID, "other-conversation"],
        )
        impact = asyncio.run(environment.service.impact(request))
        assert impact.memories == 1
        assert impact.memory_consents == 1
        assert impact.preferences == 1
        assert impact.media_assets == 1
        assert impact.capture_sessions == 1
        assert impact.data_access_grants == 1
        assert impact.conversations == 1
        assert impact.messages == 1
        assert impact.provider_logs == 2
        assert impact.audit_records_preserved == 1

        result = asyncio.run(environment.service.erase(request))
        assert result.media_files_failed == []
        assert result.result["memories_deleted"] == 1
        assert result.result["preferences_deleted"] == 1
        assert result.result["media_assets_deleted"] == 1
        assert result.result["provider_logs_deleted"] == 2
        assert result.audit_records_preserved == 1
        assert len(environment.event_bus.published) == 1
        assert environment.counts() == {
            "memories": 1,
            "memory_consents": 0,
            "preferences": 1,
            "conversations": 0,
            "messages": 0,
            "provider_logs": 0,
            "media_assets": 1,
            "capture_sessions": 0,
            "access_grants": 0,
            "events": 1,
        }
        assert not (environment.media_root / "private-user.bin").exists()
        assert (environment.media_root / "private-other.bin").exists()
    finally:
        environment.dispose()


def test_media_failure_preserves_database_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = PrivacyEnvironment(tmp_path)
    try:
        environment.seed()

        def reject_owner_media(path: Path, **_kwargs: object) -> None:
            if path.name == "private-user.bin":
                raise OSError("blocked by test")

        monkeypatch.setattr(Path, "unlink", reject_owner_media)
        with pytest.raises(ArvunoError) as exc_info:
            asyncio.run(environment.service.erase(PrivacyErasureRequest(owner_id=OWNER)))
        assert exc_info.value.code == "PRIVACY_MEDIA_ERASURE_FAILED"
        assert environment.event_bus.published == []
        assert environment.counts() == {
            "memories": 2,
            "memory_consents": 1,
            "preferences": 2,
            "conversations": 1,
            "messages": 1,
            "provider_logs": 2,
            "media_assets": 2,
            "capture_sessions": 1,
            "access_grants": 1,
            "events": 1,
        }
        assert (environment.media_root / "private-user.bin").exists()
    finally:
        environment.dispose()
