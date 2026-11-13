import asyncio
import hashlib
import json
from collections.abc import Callable as CallableType
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from arvuno_core.config import Settings
from arvuno_core.multimodal.errors import MultimodalError
from arvuno_core.multimodal.models import (
    MultimodalAnalysisResult,
    MultimodalAnalyzeRequest,
    MultimodalArtifactLinkView,
    MultimodalAuditEventView,
    MultimodalCaptureSessionCreate,
    MultimodalCaptureSessionView,
    MultimodalConsentCreate,
    MultimodalConsentView,
    MultimodalDataAccessGrantCreate,
    MultimodalDataAccessGrantView,
    MultimodalExtractionView,
    MultimodalFusionItem,
    MultimodalFusionQuery,
    MultimodalFusionResult,
    MultimodalInvocationView,
    MultimodalMediaAssetView,
    MultimodalMediaUpload,
    MultimodalObservationSource,
    MultimodalProviderView,
    MultimodalTTSRequest,
)
from arvuno_core.multimodal.providers import (
    MultimodalProviderAdapter,
    ProviderResult,
    default_adapters,
)
from arvuno_core.observations.models import ObservationInput
from arvuno_core.observations.service import ObservationService
from arvuno_core.persistence.models import (
    MultimodalArtifactLink,
    MultimodalAuditEvent,
    MultimodalCaptureSession,
    MultimodalConsent,
    MultimodalDataAccessGrant,
    MultimodalExtractionResult,
    MultimodalMediaAsset,
    MultimodalProvider,
    MultimodalProviderInvocation,
    ObservationSource,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork

MAGIC_BYTES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}
MAX_MEDIA_BYTES = 10 * 1024 * 1024
MAX_FUSION_DURATION = timedelta(days=7)
FUSION_DUPLICATION_WINDOW = timedelta(minutes=5)
ACCESS_MODALITIES = {"image", "video_frame", "audio", "sensor", "device"}
PROVIDER_CAPABILITY_IDS = {
    "vision_scene": "a518de10-5e4c-5f31-9453-d2b2c2383a01",
    "vision_object": "a518de10-5e4c-5f31-9453-d2b2c2383a02",
    "ocr": "a518de10-5e4c-5f31-9453-d2b2c2383a03",
    "stt": "a518de10-5e4c-5f31-9453-d2b2c2383a04",
    "tts": "a518de10-5e4c-5f31-9453-d2b2c2383a05",
    "audio_event": "a518de10-5e4c-5f31-9453-d2b2c2383a06",
}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _confidence_level(confidence: float) -> str:
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"


def _sniff_mime(content: bytes, declared_media_kind: str) -> str:
    for magic, mime_type in MAGIC_BYTES.items():
        if content.startswith(magic):
            return mime_type
    if len(content) >= 12 and content[:4] == b"RIFF":
        if declared_media_kind in {"audio_clip"} and content[8:12] == b"WAVE":
            return "audio/wav"
        if declared_media_kind == "image" and content[8:12] == b"WEBP":
            return "image/webp"
    raise MultimodalError(
        code="MULTIMODAL_MEDIA_TYPE_INVALID",
        message="Only PNG, JPEG, WebP, or WAV media is accepted.",
    )


def _media_kind_for_modality(modality: str) -> str:
    return "audio_clip" if modality == "audio" else modality


def _kind_supports_capability(media_kind: str, capability: str) -> bool:
    if capability in {"vision_scene", "vision_object", "ocr"}:
        return media_kind in {"image", "video_frame"}
    if capability in {"stt", "audio_event"}:
        return media_kind == "audio_clip"
    if capability == "tts":
        return media_kind == "tts_audio"
    return False


def _provider_view(provider: MultimodalProvider) -> MultimodalProviderView:
    return MultimodalProviderView.model_validate(provider)


def _consent_view(consent: MultimodalConsent) -> MultimodalConsentView:
    return MultimodalConsentView.model_validate(consent)


def _session_view(session: MultimodalCaptureSession) -> MultimodalCaptureSessionView:
    return MultimodalCaptureSessionView.model_validate(session)


def _asset_view(asset: MultimodalMediaAsset) -> MultimodalMediaAssetView:
    return MultimodalMediaAssetView.model_validate(asset)


def _invocation_view(invocation: MultimodalProviderInvocation) -> MultimodalInvocationView:
    return MultimodalInvocationView.model_validate(invocation)


def _extraction_view(result: MultimodalExtractionResult) -> MultimodalExtractionView:
    return MultimodalExtractionView.model_validate(result)


def _link_view(link: MultimodalArtifactLink) -> MultimodalArtifactLinkView:
    return MultimodalArtifactLinkView.model_validate(link)


def _value_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _media_modality(media_kind: str) -> str | None:
    return {
        "image": "image",
        "video_frame": "video_frame",
        "audio_clip": "audio",
    }.get(media_kind)


def _observation_modality(source_type: str, attribute: str) -> str:
    if source_type == "vision":
        return "audio" if attribute == "audio_event" else "image"
    if source_type in {"sensor", "device"}:
        return source_type
    return "sensor"


def _fusion_series_attribute(attribute: str) -> str:
    return {
        "scene_labels": "scene_label",
        "objects": "object_presence",
        "audio_events": "audio_event",
    }.get(attribute, attribute)


def _grant_view(grant: MultimodalDataAccessGrant) -> MultimodalDataAccessGrantView:
    return MultimodalDataAccessGrantView.model_validate(grant)


def _audit_view(event: MultimodalAuditEvent) -> MultimodalAuditEventView:
    return MultimodalAuditEventView.model_validate(event)


class MultimodalService:
    """Owns the on-demand perception pipeline and its authorization boundaries."""

    def __init__(
        self,
        unit_of_work_factory: CallableType[[], SqlAlchemyUnitOfWork],
        observation_service: ObservationService,
        settings: Settings,
        adapters: dict[str, MultimodalProviderAdapter] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._observation_service = observation_service
        self._settings = settings
        self._adapters = adapters or default_adapters()
        self._vision_source_id: str | None = None

    @property
    def media_root(self) -> Path:
        path = (self._settings.resolved_data_dir / "media" / "multimodal").resolve()
        data_root = self._settings.resolved_data_dir.resolve()
        if data_root not in path.parents:
            raise MultimodalError(
                code="MULTIMODAL_STORAGE_PATH_INVALID",
                message="The media storage path is outside the configured private data directory.",
            )
        return path

    async def initialize_catalog(self) -> None:
        await asyncio.to_thread(self._initialize_catalog)

    async def capabilities(self) -> dict[str, Any]:
        providers = await asyncio.to_thread(self._list_providers)
        return {
            "camera_capture_enabled": False,
            "microphone_capture_enabled": False,
            "continuous_video_analysis_enabled": False,
            "cloud_processing_enabled": False,
            "providers": providers,
        }

    async def list_providers(self) -> list[MultimodalProviderView]:
        return await asyncio.to_thread(self._list_providers)

    async def create_consent(self, request: MultimodalConsentCreate) -> MultimodalConsentView:
        return await asyncio.to_thread(self._create_consent, request)

    async def list_consents(self, environment_id: str | None = None) -> list[MultimodalConsentView]:
        return await asyncio.to_thread(self._list_consents, environment_id)

    async def revoke_consent(self, consent_id: str) -> MultimodalConsentView:
        return await asyncio.to_thread(self._revoke_consent, consent_id)

    async def create_data_access_grant(
        self,
        request: MultimodalDataAccessGrantCreate,
    ) -> MultimodalDataAccessGrantView:
        return await asyncio.to_thread(self._create_data_access_grant, request)

    async def list_data_access_grants(
        self,
        environment_id: str | None = None,
    ) -> list[MultimodalDataAccessGrantView]:
        return await asyncio.to_thread(self._list_data_access_grants, environment_id)

    async def revoke_data_access_grant(self, grant_id: str) -> MultimodalDataAccessGrantView:
        return await asyncio.to_thread(self._revoke_data_access_grant, grant_id)

    async def query_fusion(self, request: MultimodalFusionQuery) -> MultimodalFusionResult:
        return await asyncio.to_thread(self._query_fusion, request)

    async def list_audit_events(
        self,
        environment_id: str,
        *,
        action: str | None = None,
        limit: int = 100,
    ) -> list[MultimodalAuditEventView]:
        return await asyncio.to_thread(
            self._list_audit_events,
            environment_id,
            action,
            limit,
        )

    async def create_capture_session(
        self,
        request: MultimodalCaptureSessionCreate,
    ) -> MultimodalCaptureSessionView:
        return await asyncio.to_thread(self._create_capture_session, request)

    async def get_capture_session(self, session_id: str) -> MultimodalCaptureSessionView:
        return await asyncio.to_thread(self._get_capture_session, session_id)

    async def upload_media(
        self,
        session_id: str,
        request: MultimodalMediaUpload,
        content: bytes,
    ) -> MultimodalMediaAssetView:
        validated = await asyncio.to_thread(
            self._validate_upload,
            session_id,
            request,
            content,
        )
        asset_id, storage_key, suffix = validated
        path = await asyncio.to_thread(self._write_private_file, storage_key, content)
        try:
            return await asyncio.to_thread(self._complete_upload, asset_id)
        except Exception:
            await asyncio.to_thread(self._cancel_failed_upload, asset_id, path)
            raise

    async def read_media(self, asset_id: str) -> bytes:
        content, asset = await asyncio.to_thread(self._read_media_with_asset, asset_id)
        await asyncio.to_thread(
            self._record_audit_sync,
            environment_id=asset.environment_id,
            actor_id=asset.metadata_summary.get("requested_by"),
            action="asset_read",
            subject_type="media_asset",
            subject_id=asset.id,
            details={"media_kind": asset.media_kind},
        )
        return content

    async def analyze(
        self,
        asset_id: str,
        request: MultimodalAnalyzeRequest,
    ) -> MultimodalAnalysisResult:
        adapter = self._adapters.get(request.capability)
        if adapter is None:
            raise MultimodalError(
                code="MULTIMODAL_PROVIDER_UNAVAILABLE",
                message="No provider is registered for the requested capability.",
                status_code=409,
            )
        return await asyncio.to_thread(self._analyze_sync, asset_id, request, adapter)

    async def synthesize_speech(self, request: MultimodalTTSRequest) -> MultimodalAnalysisResult:
        adapter = self._adapters.get("tts")
        if adapter is None:
            raise MultimodalError(
                code="MULTIMODAL_PROVIDER_UNAVAILABLE",
                message="No TTS provider is registered.",
                status_code=409,
            )
        return await asyncio.to_thread(self._synthesize_sync, request, adapter)

    async def purge_expired(
        self,
        now: datetime | None = None,
        *,
        limit: int | None = None,
    ) -> int:
        return await asyncio.to_thread(
            self._purge_expired_sync,
            now or datetime.now(UTC),
            limit,
        )

    async def list_extractions(self) -> list[MultimodalExtractionView]:
        return await asyncio.to_thread(self._list_extractions)

    async def purge_asset(self, asset_id: str) -> MultimodalMediaAssetView:
        return await asyncio.to_thread(self._purge_asset_sync, asset_id)

    def _initialize_catalog(self) -> None:
        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            expected_capabilities = {
                "vision_scene",
                "vision_object",
                "ocr",
                "stt",
                "tts",
                "audio_event",
            }
            for provider in uow.multimodal.list_providers():
                expected_capabilities.discard(provider.capability)
            if expected_capabilities:
                raise MultimodalError(
                    code="MULTIMODAL_PROVIDER_CATALOG_INVALID",
                    message="The multimodal provider catalog migration is incomplete.",
                    status_code=500,
                )

        def execute() -> str:
            with self._unit_of_work_factory() as uow:
                assert uow.observation_sources is not None
                sources = uow.observation_sources.list_sources(source_type="vision")
                source = next(iter(sources), None)
                if source is None:
                    source = ObservationSource(
                        source_type="vision",
                        adapter_id="arvuno_multimodal",
                        name="Arvuno multimodal on-demand perception",
                        status="active",
                        trust_level=0.5,
                        time_trust="poll_clock",
                        config={
                            "capture_mode": "user_upload_only",
                            "continuous_analysis": False,
                            "supported_capabilities": [
                                "vision_scene",
                                "vision_object",
                                "ocr",
                                "audio_event",
                            ],
                        },
                        privacy_scope={
                            "media_storage": "private_local_file",
                            "raw_media_default": "delete_after_processing",
                        },
                    )
                    uow.observation_sources.add(source)
                    uow.commit()
                return source.id

        self._vision_source_id = execute()

    def _list_providers(self) -> list[MultimodalProviderView]:
        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            return [_provider_view(row) for row in uow.multimodal.list_providers()]

    def _create_consent(self, request: MultimodalConsentCreate) -> MultimodalConsentView:
        if request.expires_at is not None and _utc(request.expires_at) <= datetime.now(UTC):
            raise MultimodalError(code="MULTIMODAL_CONSENT_EXPIRY_INVALID")
        now = datetime.now(UTC)
        consent = MultimodalConsent(
            environment_id=request.environment_id,
            user_id=request.user_id,
            consent_type=request.consent_type,
            modality=request.modality,
            purpose=request.purpose,
            provider_name=request.provider_name,
            processing_locations=request.processing_locations,
            space_ids=request.space_ids,
            granted_at=now,
            expires_at=_utc(request.expires_at) if request.expires_at else None,
            status="granted",
            scope=request.scope,
            evidence={"source": "api_explicit_request"},
        )
        with self._unit_of_work_factory() as uow:
            assert uow.environments is not None
            assert uow.multimodal is not None
            if uow.environments.get(request.environment_id) is None:
                raise MultimodalError(
                    code="MULTIMODAL_ENVIRONMENT_NOT_FOUND",
                    message="The environment does not exist.",
                    status_code=404,
                )
            stored = uow.multimodal.add_consent(consent)
            uow.commit()
            return _consent_view(stored)

    def _list_consents(self, environment_id: str | None) -> list[MultimodalConsentView]:
        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            return [_consent_view(row) for row in uow.multimodal.list_consents(environment_id)]

    def _revoke_consent(self, consent_id: str) -> MultimodalConsentView:
        now = datetime.now(UTC)
        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            consent = uow.multimodal.get_consent(consent_id)
            if consent is None:
                raise MultimodalError(
                    code="MULTIMODAL_CONSENT_NOT_FOUND",
                    message="The consent does not exist.",
                    status_code=404,
                )
            consent.status = "revoked"
            consent.revoked_at = now
            assets = uow.multimodal.list_assets_by_consent(consent_id)
            purge_count = 0
            for asset in assets:
                if asset.purge_status != "purged":
                    self._purge_asset(uow, asset, "consent_revoked")
                    purge_count += 1
            self._record_audit(
                uow,
                environment_id=consent.environment_id,
                actor_id=consent.user_id,
                action="consent_revoked",
                subject_type="multimodal_consent",
                subject_id=consent.id,
                details={"purged_asset_count": purge_count},
            )
            uow.commit()
            return _consent_view(consent)

    def _create_data_access_grant(
        self,
        request: MultimodalDataAccessGrantCreate,
    ) -> MultimodalDataAccessGrantView:
        now = datetime.now(UTC)
        if request.expires_at is not None and _utc(request.expires_at) <= now:
            raise MultimodalError(code="MULTIMODAL_GRANT_EXPIRY_INVALID")
        modalities = list(dict.fromkeys(request.modalities))
        if any(modality not in ACCESS_MODALITIES for modality in modalities):
            raise MultimodalError(code="MULTIMODAL_GRANT_MODALITY_INVALID")
        space_ids = list(dict.fromkeys(request.space_ids))
        grant = MultimodalDataAccessGrant(
            environment_id=request.environment_id,
            user_id=request.user_id,
            modalities=modalities,
            space_ids=space_ids,
            granted_at=now,
            expires_at=_utc(request.expires_at) if request.expires_at else None,
            status="granted",
            scope=request.scope,
            evidence=request.evidence or {"source": "api_explicit_request"},
        )
        with self._unit_of_work_factory() as uow:
            assert uow.environments is not None
            assert uow.spaces is not None
            assert uow.multimodal is not None
            if uow.environments.get(request.environment_id) is None:
                raise MultimodalError(
                    code="MULTIMODAL_ENVIRONMENT_NOT_FOUND",
                    status_code=404,
                )
            for space_id in space_ids:
                space = uow.spaces.get(space_id)
                environment = uow.environments.get(request.environment_id)
                if space is None:
                    raise MultimodalError(
                        code="MULTIMODAL_SPACE_NOT_FOUND",
                        status_code=404,
                    )
                if (
                    environment is None
                    or environment.root_space_id is None
                    or uow.spaces.root_of(space).id != environment.root_space_id
                ):
                    raise MultimodalError(
                        code="MULTIMODAL_GRANT_SCOPE_INVALID",
                        status_code=403,
                    )
            stored = uow.multimodal.add_data_access_grant(grant)
            self._record_audit(
                uow,
                environment_id=stored.environment_id,
                actor_id=stored.user_id,
                action="grant_created",
                subject_type="data_access_grant",
                subject_id=stored.id,
                details={"modalities": stored.modalities, "space_count": len(stored.space_ids)},
            )
            uow.commit()
            return _grant_view(stored)

    def _list_data_access_grants(
        self,
        environment_id: str | None,
    ) -> list[MultimodalDataAccessGrantView]:
        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            rows = uow.multimodal.list_data_access_grants(environment_id)
            return [_grant_view(row) for row in rows]

    def _revoke_data_access_grant(self, grant_id: str) -> MultimodalDataAccessGrantView:
        now = datetime.now(UTC)
        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            grant = uow.multimodal.get_data_access_grant(grant_id)
            if grant is None:
                raise MultimodalError(
                    code="MULTIMODAL_GRANT_NOT_FOUND",
                    status_code=404,
                )
            grant.status = "revoked"
            grant.revoked_at = now
            self._record_audit(
                uow,
                environment_id=grant.environment_id,
                actor_id=grant.user_id,
                action="grant_revoked",
                subject_type="data_access_grant",
                subject_id=grant.id,
                details={},
            )
            uow.commit()
            return _grant_view(grant)

    def _active_data_access_grant(
        self,
        uow: SqlAlchemyUnitOfWork,
        *,
        grant_id: str,
        environment_id: str,
        now: datetime,
    ) -> MultimodalDataAccessGrant:
        assert uow.multimodal is not None
        grant = uow.multimodal.get_data_access_grant(grant_id)
        if grant is None:
            raise MultimodalError(code="MULTIMODAL_GRANT_NOT_FOUND", status_code=404)
        if grant.environment_id != environment_id:
            raise MultimodalError(code="MULTIMODAL_GRANT_SCOPE_INVALID", status_code=403)
        if grant.status != "granted":
            raise MultimodalError(code="MULTIMODAL_GRANT_NOT_ACTIVE", status_code=403)
        if grant.expires_at is not None and _utc(grant.expires_at) <= now:
            raise MultimodalError(code="MULTIMODAL_GRANT_EXPIRED", status_code=403)
        return grant

    def _observation_fusion_item(self, row: object) -> MultimodalFusionItem:
        assert isinstance(row, object)
        observation = row
        observed_at = observation.observed_at or observation.received_at
        return MultimodalFusionItem(
            artifact_type="observation",
            id=observation.observation_id,
            modality=_observation_modality(observation.source_type, observation.attribute),
            source_type=observation.source_type,
            source_id=observation.source_id,
            space_id=observation.space_id,
            entity_id=observation.entity_id,
            subject_id=observation.subject_id,
            attribute=observation.attribute,
            observed_at=observed_at,
            received_at=observation.received_at,
            processed_at=observation.processed_at,
            value=observation.raw_value,
            confidence=None,
            quality_status=observation.quality_status,
            model_id=None,
            model_version=None,
            capture_session_id=None,
            correlation_id=observation.correlation_id,
            association={"type": "time_space_correlation", "causal_claim": False},
        )

    def _extraction_fusion_item(
        self,
        extraction: MultimodalExtractionResult,
        asset: MultimodalMediaAsset,
    ) -> MultimodalFusionItem:
        session_correlation = asset.metadata_summary.get("correlation_id")
        observed_at = asset.client_captured_at or asset.received_at
        return MultimodalFusionItem(
            artifact_type="extraction_result",
            id=extraction.id,
            modality=_media_modality(asset.media_kind) or asset.media_kind,
            source_type="multimodal_provider",
            source_id=extraction.invocation_id,
            space_id=asset.space_id,
            entity_id=asset.entity_id,
            subject_id=str(asset.entity_id) if asset.entity_id is not None else None,
            attribute=extraction.result_kind,
            observed_at=observed_at,
            received_at=asset.received_at,
            processed_at=asset.processed_at,
            value=extraction.result,
            confidence=extraction.confidence,
            quality_status=extraction.quality_status,
            model_id=extraction.model_id,
            model_version=extraction.model_version,
            capture_session_id=asset.capture_session_id,
            correlation_id=session_correlation if isinstance(session_correlation, str) else None,
            association={"type": "time_space_correlation", "causal_claim": False},
        )

    def _query_fusion(self, request: MultimodalFusionQuery) -> MultimodalFusionResult:
        from_at = _utc(request.from_at)
        to_at = _utc(request.to_at)
        now = datetime.now(UTC)
        if to_at <= from_at:
            raise MultimodalError(code="MULTIMODAL_FUSION_RANGE_INVALID")
        if to_at - from_at > MAX_FUSION_DURATION:
            raise MultimodalError(code="MULTIMODAL_FUSION_RANGE_TOO_LARGE")
        if to_at > now + timedelta(minutes=5):
            raise MultimodalError(code="MULTIMODAL_FUSION_RANGE_FUTURE")
        items: list[MultimodalFusionItem] = []
        with self._unit_of_work_factory() as uow:
            assert uow.environments is not None
            assert uow.entities is not None
            assert uow.spaces is not None
            assert uow.multimodal is not None
            if uow.environments.get(request.environment_id) is None:
                raise MultimodalError(
                    code="MULTIMODAL_ENVIRONMENT_NOT_FOUND",
                    status_code=404,
                )
            grant = self._active_data_access_grant(
                uow,
                grant_id=request.grant_id,
                environment_id=request.environment_id,
                now=now,
            )
            if request.space_id is not None:
                space = uow.spaces.get(request.space_id)
                environment = uow.environments.get(request.environment_id)
                if (
                    space is None
                    or environment is None
                    or environment.root_space_id is None
                    or uow.spaces.root_of(space).id != environment.root_space_id
                ):
                    raise MultimodalError(code="MULTIMODAL_SPACE_SCOPE_INVALID", status_code=403)
                if request.space_id not in grant.space_ids:
                    raise MultimodalError(
                        code="MULTIMODAL_GRANT_SPACE_NOT_ALLOWED",
                        status_code=403,
                    )
            if request.entity_id is not None:
                entity = uow.entities.get(request.entity_id)
                if entity is None or entity.environment_id != request.environment_id:
                    raise MultimodalError(code="MULTIMODAL_ENTITY_SCOPE_INVALID", status_code=403)
            allowed_spaces = set(grant.space_ids)
            observation_rows = uow.multimodal.list_fusion_observations(
                environment_id=request.environment_id,
                from_at=from_at,
                to_at=to_at,
                space_id=request.space_id,
                entity_id=request.entity_id,
                correlation_id=request.correlation_id,
            )
            extraction_rows = uow.multimodal.list_fusion_extractions(
                environment_id=request.environment_id,
                from_at=from_at,
                to_at=to_at,
                space_id=request.space_id,
                entity_id=request.entity_id,
                correlation_id=request.correlation_id,
            )
            for row in observation_rows:
                item = self._observation_fusion_item(row)
                if item.space_id not in allowed_spaces:
                    continue
                if item.modality not in grant.modalities:
                    continue
                items.append(item)
            for extraction, asset in extraction_rows:
                item = self._extraction_fusion_item(extraction, asset)
                if item.space_id not in allowed_spaces:
                    continue
                if item.modality not in grant.modalities:
                    continue
                items.append(item)
            self._mark_fusion_associations(items)
            self._record_audit(
                uow,
                environment_id=request.environment_id,
                actor_id=grant.user_id,
                action="fusion_queried",
                subject_type="data_access_grant",
                subject_id=grant.id,
                details={
                    "from_at": from_at.isoformat(),
                    "to_at": to_at.isoformat(),
                    "space_id": request.space_id,
                    "correlation_id": request.correlation_id,
                    "returned_count": min(len(items), request.limit),
                    "total_available": len(items),
                },
            )
            uow.commit()
        missing_note = (
            "No authorized records matched the requested time, space, entity, "
            "or correlation filters."
            if not items
            else None
        )
        return MultimodalFusionResult(
            items=items[: request.limit],
            total_available=len(items),
            missing_data_note=missing_note,
        )

    def _mark_fusion_associations(self, items: list[MultimodalFusionItem]) -> None:
        groups: dict[str, list[MultimodalFusionItem]] = {}
        for item in items:
            scope = item.space_id or item.entity_id or item.subject_id or "unscoped"
            groups.setdefault(scope, []).append(item)
        for members in groups.values():
            for _index, item in enumerate(members):
                related: list[str] = []
                duplicates: list[str] = []
                conflicts: list[str] = []
                item_hash = _value_hash(item.value)
                for other in members:
                    if other.id == item.id:
                        continue
                    delta = abs(_utc(item.observed_at) - _utc(other.observed_at))
                    if delta > FUSION_DUPLICATION_WINDOW:
                        continue
                    related.append(other.id)
                    same_series = _fusion_series_attribute(item.attribute) == (
                        _fusion_series_attribute(other.attribute)
                    ) and (
                        item.entity_id == other.entity_id and item.subject_id == other.subject_id
                    )
                    if not same_series:
                        continue
                    if item_hash == _value_hash(other.value):
                        duplicates.append(other.id)
                    else:
                        conflicts.append(other.id)
                item.association = {
                    "type": "time_space_correlation",
                    "causal_claim": False,
                    "related_ids": sorted(related),
                    "duplicate_candidate_ids": sorted(duplicates),
                    "conflict_candidate_ids": sorted(conflicts),
                }

    def _record_audit(
        self,
        uow: SqlAlchemyUnitOfWork,
        *,
        environment_id: str | None,
        actor_id: str | None,
        action: str,
        subject_type: str | None,
        subject_id: str | None,
        details: dict[str, Any],
    ) -> None:
        assert uow.multimodal is not None
        uow.multimodal.add_audit_event(
            MultimodalAuditEvent(
                environment_id=environment_id,
                actor_id=actor_id,
                action=action,
                subject_type=subject_type,
                subject_id=subject_id,
                details=details,
                occurred_at=datetime.now(UTC),
            )
        )

    def _record_audit_sync(
        self,
        *,
        environment_id: str | None,
        actor_id: str | None,
        action: str,
        subject_type: str | None,
        subject_id: str | None,
        details: dict[str, Any],
    ) -> None:
        with self._unit_of_work_factory() as uow:
            self._record_audit(
                uow,
                environment_id=environment_id,
                actor_id=actor_id,
                action=action,
                subject_type=subject_type,
                subject_id=subject_id,
                details=details,
            )
            uow.commit()

    def _list_audit_events(
        self,
        environment_id: str,
        action: str | None,
        limit: int,
    ) -> list[MultimodalAuditEventView]:
        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            rows = uow.multimodal.list_audit_events(
                environment_id,
                action=action,
                limit=min(max(limit, 1), 500),
            )
            return [_audit_view(row) for row in rows]

    def _active_consent(
        self,
        uow: SqlAlchemyUnitOfWork,
        consent_id: str,
        *,
        consent_type: str,
        environment_id: str,
        modality: str,
        purpose: str,
        space_id: str | None,
        provider_name: str | None,
        processing_location: str | None = None,
    ) -> MultimodalConsent:
        assert uow.multimodal is not None
        consent = uow.multimodal.get_consent(consent_id)
        now = datetime.now(UTC)
        invalid_codes = {
            (consent is None, "MULTIMODAL_CONSENT_NOT_FOUND", 404),
            (
                consent is not None and consent.environment_id != environment_id,
                "MULTIMODAL_CONSENT_SCOPE_INVALID",
                403,
            ),
            (
                consent is not None and consent.consent_type != consent_type,
                "MULTIMODAL_CONSENT_TYPE_INVALID",
                403,
            ),
            (
                consent is not None and consent.modality != modality,
                "MULTIMODAL_CONSENT_MODALITY_INVALID",
                403,
            ),
            (
                consent is not None and consent.purpose != purpose,
                "MULTIMODAL_CONSENT_PURPOSE_INVALID",
                403,
            ),
            (
                consent is not None and consent.status != "granted",
                "MULTIMODAL_CONSENT_NOT_ACTIVE",
                403,
            ),
            (
                consent is not None
                and consent.expires_at is not None
                and _utc(consent.expires_at) <= now,
                "MULTIMODAL_CONSENT_EXPIRED",
                403,
            ),
            (
                consent is not None and space_id is not None and space_id not in consent.space_ids,
                "MULTIMODAL_CONSENT_SPACE_NOT_ALLOWED",
                403,
            ),
            (
                consent is not None
                and provider_name is not None
                and consent.provider_name not in {None, provider_name},
                "MULTIMODAL_CONSENT_PROVIDER_NOT_ALLOWED",
                403,
            ),
            (
                consent is not None
                and processing_location is not None
                and processing_location not in consent.processing_locations,
                "MULTIMODAL_CONSENT_PROCESSING_NOT_ALLOWED",
                403,
            ),
        }
        for failed, code, status_code in invalid_codes:
            if failed:
                raise MultimodalError(code=code, status_code=status_code)
        assert consent is not None
        return consent

    def _create_capture_session(
        self,
        request: MultimodalCaptureSessionCreate,
    ) -> MultimodalCaptureSessionView:
        state_visibility = {
            "camera_on": False,
            "microphone_on": False,
            "capture_mode": (
                "awaiting_consent" if request.requires_capture_consent else "user_upload_only"
            ),
        }
        session = MultimodalCaptureSession(
            environment_id=request.environment_id,
            space_id=request.space_id,
            entity_id=request.entity_id,
            modality=request.modality,
            purpose=request.purpose,
            origin_type=request.origin_type,
            origin_record_id=request.origin_record_id,
            requested_by=request.requested_by,
            status="awaiting_consent" if request.requires_capture_consent else "requested",
            requires_capture_consent=request.requires_capture_consent,
            expected_media_count=1,
            max_duration_ms=request.max_duration_ms,
            state_visibility=state_visibility,
            correlation_id=request.correlation_id,
        )
        with self._unit_of_work_factory() as uow:
            assert uow.environments is not None
            assert uow.entities is not None
            assert uow.multimodal is not None
            assert uow.spaces is not None
            if uow.environments.get(request.environment_id) is None:
                raise MultimodalError(
                    code="MULTIMODAL_ENVIRONMENT_NOT_FOUND",
                    message="The environment does not exist.",
                    status_code=404,
                )
            if request.space_id is not None and uow.spaces.get(request.space_id) is None:
                raise MultimodalError(
                    code="MULTIMODAL_SPACE_NOT_FOUND",
                    message="The target space does not exist.",
                    status_code=404,
                )
            if request.entity_id is not None and uow.entities.get(request.entity_id) is None:
                raise MultimodalError(
                    code="MULTIMODAL_ENTITY_NOT_FOUND",
                    message="The target entity does not exist.",
                    status_code=404,
                )
            stored = uow.multimodal.add_capture_session(session)
            uow.commit()
            return _session_view(stored)

    def _get_capture_session(self, session_id: str) -> MultimodalCaptureSessionView:
        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            session = uow.multimodal.get_capture_session(session_id)
            if session is None:
                raise MultimodalError(
                    code="MULTIMODAL_SESSION_NOT_FOUND",
                    message="The capture session does not exist.",
                    status_code=404,
                )
            return _session_view(session)

    def _validate_upload(
        self,
        session_id: str,
        request: MultimodalMediaUpload,
        content: bytes,
    ) -> tuple[str, str, str]:
        if not content:
            raise MultimodalError(code="MULTIMODAL_MEDIA_EMPTY")
        if len(content) > MAX_MEDIA_BYTES:
            raise MultimodalError(
                code="MULTIMODAL_MEDIA_TOO_LARGE",
                message=f"Media must not exceed {MAX_MEDIA_BYTES} bytes.",
            )
        media_kind = ""
        now = datetime.now(UTC)
        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            session = uow.multimodal.get_capture_session(session_id)
            if session is None:
                raise MultimodalError(
                    code="MULTIMODAL_SESSION_NOT_FOUND",
                    message="The capture session does not exist.",
                    status_code=404,
                )
            if session.requires_capture_consent:
                raise MultimodalError(
                    code="MULTIMODAL_CAPTURE_NOT_AUTHORIZED",
                    message="Camera and microphone capture is disabled and was not authorized.",
                    status_code=403,
                )
            if session.status != "requested":
                raise MultimodalError(code="MULTIMODAL_SESSION_NOT_UPLOADABLE", status_code=409)
            if uow.multimodal.count_session_assets(session_id) >= session.expected_media_count:
                raise MultimodalError(code="MULTIMODAL_SESSION_MEDIA_FULL", status_code=409)
            media_kind = _media_kind_for_modality(session.modality)
            mime_type = _sniff_mime(content, media_kind)
            self._active_consent(
                uow,
                request.consent_id,
                consent_type="capture",
                environment_id=session.environment_id,
                modality=session.modality,
                purpose=session.purpose,
                space_id=session.space_id,
                provider_name=None,
            )
            suffix = mime_type.split("/")[-1].replace("jpeg", "jpg")
            storage_key = f"{uuid4().hex}.{suffix}"
            retention_hours = 1 if request.sensitivity == "sensitive" else 24
            asset = MultimodalMediaAsset(
                capture_session_id=session.id,
                environment_id=session.environment_id,
                media_kind=media_kind,
                mime_type=mime_type,
                size_bytes=len(content),
                sha256=_digest(content),
                storage_backend="local_private_file",
                storage_key=storage_key,
                content_available=True,
                validation_status="quarantined",
                sensitivity=request.sensitivity,
                purpose=session.purpose,
                consent_id=request.consent_id,
                retention_class=f"process_then_delete_{retention_hours}h",
                retention_until=now + timedelta(hours=retention_hours),
                purge_status="pending",
                duration_ms=request.duration_ms,
                client_captured_at=(
                    _utc(request.client_captured_at) if request.client_captured_at else None
                ),
                client_time_source=request.client_time_source,
                client_time_uncertainty_ms=request.client_time_uncertainty_ms,
                received_at=now,
                space_id=session.space_id,
                entity_id=session.entity_id,
                metadata_summary={
                    "server_validated_mime": mime_type,
                    "requested_by": session.requested_by,
                    "correlation_id": session.correlation_id,
                },
            )
            stored = uow.multimodal.add_asset(asset)
            session.status = "uploaded"
            uow.commit()
            return stored.id, storage_key, suffix

    def _write_private_file(self, storage_key: str, content: bytes) -> Path:
        root = self.media_root
        root.mkdir(parents=True, exist_ok=True)
        path = (root / storage_key).resolve()
        if root not in path.parents:
            raise MultimodalError(code="MULTIMODAL_STORAGE_PATH_INVALID")
        try:
            with path.open("xb") as media_file:
                media_file.write(content)
        except FileExistsError as exc:
            raise MultimodalError(
                code="MULTIMODAL_STORAGE_KEY_COLLISION",
                message="The generated media key collided with an existing object.",
                status_code=409,
            ) from exc
        except OSError as exc:
            raise MultimodalError(
                code="MULTIMODAL_STORAGE_WRITE_FAILED",
                message="The private media store rejected the upload.",
                status_code=500,
            ) from exc
        return path

    def _complete_upload(self, asset_id: str) -> MultimodalMediaAssetView:
        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            asset = uow.multimodal.get_asset(asset_id)
            if asset is None:
                raise MultimodalError(
                    code="MULTIMODAL_ASSET_NOT_FOUND",
                    message="The media asset does not exist.",
                    status_code=404,
                )
            asset.validation_status = "valid"
            self._record_audit(
                uow,
                environment_id=asset.environment_id,
                actor_id=asset.metadata_summary.get("requested_by"),
                action="asset_uploaded",
                subject_type="media_asset",
                subject_id=asset.id,
                details={
                    "media_kind": asset.media_kind,
                    "mime_type": asset.mime_type,
                    "sensitivity": asset.sensitivity,
                },
            )
            uow.commit()
            return _asset_view(asset)

    def _cancel_failed_upload(self, asset_id: str, path: Path) -> None:
        path.unlink(missing_ok=True)
        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            asset = uow.multimodal.get_asset(asset_id)
            if asset is not None:
                asset.validation_status = "invalid"
                asset.content_available = False
                asset.storage_key = None
                asset.sha256 = None
                asset.purge_status = "purged"
                asset.purge_reason = "upload_failed"
                session = (
                    uow.multimodal.get_capture_session(asset.capture_session_id)
                    if asset.capture_session_id
                    else None
                )
                if session is not None:
                    session.status = "failed"
                    session.closed_at = datetime.now(UTC)
                uow.commit()

    def _read_media_with_asset(self, asset_id: str) -> tuple[bytes, MultimodalMediaAsset]:
        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            asset = uow.multimodal.get_asset(asset_id)
            if asset is None:
                raise MultimodalError(
                    code="MULTIMODAL_ASSET_NOT_FOUND",
                    message="The media asset does not exist.",
                    status_code=404,
                )
            if not asset.content_available or asset.storage_key is None:
                raise MultimodalError(
                    code="MULTIMODAL_MEDIA_UNAVAILABLE",
                    message="The media object has been deleted or is unavailable.",
                    status_code=404,
                )
            storage_key = asset.storage_key
        path = (self.media_root / storage_key).resolve()
        if self.media_root not in path.parents or not path.is_file():
            raise MultimodalError(
                code="MULTIMODAL_MEDIA_UNAVAILABLE",
                message="The media object is unavailable.",
                status_code=404,
            )
        return path.read_bytes(), asset

    def _read_media(self, asset_id: str) -> bytes:
        content, _asset = self._read_media_with_asset(asset_id)
        return content

    def _start_invocation(
        self,
        asset: MultimodalMediaAsset,
        provider: MultimodalProvider,
        request: MultimodalAnalyzeRequest,
        now: datetime,
    ) -> MultimodalProviderInvocation:
        session_id = asset.capture_session_id
        assert session_id is not None
        invocation = MultimodalProviderInvocation(
            media_asset_id=asset.id,
            provider_id=provider.id,
            capability=request.capability,
            model_id=provider.model_id,
            model_version=provider.model_version,
            processing_location=provider.processing_location,
            input_summary={
                "media_kind": asset.media_kind,
                "mime_type": asset.mime_type,
                "size_bytes": asset.size_bytes,
            },
            request_digest=_digest(
                f"{asset.id}:{request.capability}:{request.provider_name}".encode()
            ),
            sent_media_to_external=False,
            status="running",
            started_at=now,
            correlation_id=None,
        )
        return invocation

    def _analyze_sync(
        self,
        asset_id: str,
        request: MultimodalAnalyzeRequest,
        adapter: MultimodalProviderAdapter,
    ) -> MultimodalAnalysisResult:
        now = datetime.now(UTC)
        invocation_id: str | None = None
        try:
            with self._unit_of_work_factory() as uow:
                assert uow.multimodal is not None
                asset = uow.multimodal.get_asset(asset_id)
                if asset is None:
                    raise MultimodalError(
                        code="MULTIMODAL_ASSET_NOT_FOUND",
                        message="The media asset does not exist.",
                        status_code=404,
                    )
                session_id = asset.capture_session_id
                if session_id is None:
                    raise MultimodalError(code="MULTIMODAL_SESSION_REQUIRED", status_code=409)
                session = uow.multimodal.get_capture_session(session_id)
                if session is None:
                    raise MultimodalError(
                        code="MULTIMODAL_SESSION_NOT_FOUND",
                        message="The capture session does not exist.",
                        status_code=404,
                    )
                providers = [
                    row
                    for row in uow.multimodal.list_providers()
                    if row.capability == request.capability
                ]
                provider = next(
                    (
                        row
                        for row in providers
                        if row.provider_name == request.provider_name
                        and row.enabled
                        and row.processing_location == adapter.processing_location
                    ),
                    None,
                )
                if provider is None:
                    raise MultimodalError(
                        code="MULTIMODAL_PROVIDER_UNAVAILABLE",
                        message="The requested provider is disabled or unavailable.",
                        status_code=409,
                    )
                if not _kind_supports_capability(asset.media_kind, request.capability):
                    raise MultimodalError(
                        code="MULTIMODAL_CAPABILITY_MEDIA_INVALID",
                        status_code=400,
                    )
                self._active_consent(
                    uow,
                    request.consent_id,
                    consent_type="processing",
                    environment_id=asset.environment_id,
                    modality=session.modality,
                    purpose=session.purpose,
                    space_id=session.space_id,
                    provider_name=provider.provider_name,
                    processing_location=provider.processing_location,
                )
                self._record_audit(
                    uow,
                    environment_id=asset.environment_id,
                    actor_id=asset.metadata_summary.get("requested_by"),
                    action="asset_analyzed",
                    subject_type="media_asset",
                    subject_id=asset.id,
                    details={
                        "capability": request.capability,
                        "provider": provider.provider_name,
                        "processing_location": provider.processing_location,
                    },
                )
                invocation = self._start_invocation(asset, provider, request, now)
                stored_invocation = uow.multimodal.add_invocation(invocation)
                invocation_id = stored_invocation.id
                session.status = "processing"
                asset.validation_status = "valid"
                uow.commit()
                asset_id_value = asset.id
                mime_type = asset.mime_type
                content = self._read_media(asset_id_value)
            try:
                provider_result = asyncio.run(
                    asyncio.wait_for(
                        adapter.process(
                            capability=request.capability,
                            content=content,
                            mime_type=mime_type,
                        ),
                        timeout=provider.timeout_ms / 1000,
                    )
                )
            except TimeoutError as exc:
                self._fail_invocation(
                    invocation_id,
                    "MULTIMODAL_PROVIDER_TIMEOUT",
                    status="timeout",
                )
                raise MultimodalError(
                    code="MULTIMODAL_PROVIDER_TIMEOUT",
                    message="The provider call timed out.",
                    status_code=504,
                ) from exc
            except MultimodalError:
                self._fail_invocation(invocation_id, "MULTIMODAL_PROVIDER_FAILED")
                raise
            except Exception as exc:
                self._fail_invocation(invocation_id, "MULTIMODAL_PROVIDER_FAILED")
                raise MultimodalError(
                    code="MULTIMODAL_PROVIDER_FAILED",
                    message="The provider call failed.",
                    status_code=502,
                ) from exc
            return self._complete_analysis(
                asset_id_value,
                invocation_id,
                request,
                provider_result,
                adapter,
            )
        except MultimodalError as exc:
            if invocation_id is not None and exc.code != "MULTIMODAL_PROVIDER_TIMEOUT":
                self._fail_invocation(invocation_id, "MULTIMODAL_PROVIDER_FAILED")
            raise
        except Exception as exc:
            if invocation_id is not None:
                self._fail_invocation(invocation_id, "MULTIMODAL_PROVIDER_FAILED")
            raise MultimodalError(
                code="MULTIMODAL_PROVIDER_FAILED",
                message="The provider call failed.",
                status_code=502,
            ) from exc

    def _validate_provider_result(self, result: ProviderResult) -> None:
        if not isinstance(result.result, dict) or not result.result_kind:
            raise MultimodalError(code="MULTIMODAL_PROVIDER_OUTPUT_INVALID", status_code=502)
        if not 0 <= result.confidence <= 1:
            raise MultimodalError(code="MULTIMODAL_PROVIDER_OUTPUT_INVALID", status_code=502)
        if result.result_kind == "transcript" and not isinstance(
            result.result.get("is_instruction"), bool
        ):
            raise MultimodalError(code="MULTIMODAL_PROVIDER_OUTPUT_INVALID", status_code=502)

    def _complete_analysis(
        self,
        asset_id: str,
        invocation_id: str,
        request: MultimodalAnalyzeRequest,
        provider_result: ProviderResult,
        adapter: MultimodalProviderAdapter,
    ) -> MultimodalAnalysisResult:
        self._validate_provider_result(provider_result)
        now = datetime.now(UTC)
        observation_sources: list[MultimodalObservationSource] = []
        links: list[MultimodalArtifactLink] = []
        response_digest = _digest(
            json.dumps(
                provider_result.result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
        observation = None
        extraction = MultimodalExtractionResult(
            id=str(uuid4()),
            media_asset_id=asset_id,
            invocation_id=invocation_id,
            result_kind=provider_result.result_kind,
            schema_version="1.0.0",
            result=provider_result.result,
            confidence=provider_result.confidence,
            confidence_level=_confidence_level(provider_result.confidence),
            quality_status="valid_candidate",
            language=provider_result.language,
            alternatives=provider_result.alternatives,
            model_id=adapter.model_id,
            model_version=provider_result.model_version,
            valid_from=now,
            valid_until=now + timedelta(minutes=30),
        )
        if provider_result.result_kind in {"scene_labels", "objects", "audio_events"}:
            with self._unit_of_work_factory() as uow:
                assert uow.multimodal is not None
                asset = uow.multimodal.get_asset(asset_id)
                if asset is None:
                    raise MultimodalError(
                        code="MULTIMODAL_ASSET_NOT_FOUND",
                        message="The media asset does not exist.",
                        status_code=404,
                    )
                observation = self._record_candidate_observation(asset, extraction, now)

        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            asset = uow.multimodal.get_asset(asset_id)
            if asset is None:
                raise MultimodalError(
                    code="MULTIMODAL_ASSET_NOT_FOUND",
                    message="The media asset does not exist.",
                    status_code=404,
                )
            stored_extraction = uow.multimodal.add_extraction(extraction)
            if observation is not None:
                observation_sources.append(observation)
                links.append(
                    MultimodalArtifactLink(
                        artifact_type="extraction_result",
                        artifact_id=stored_extraction.id,
                        target_type="observation",
                        target_id=observation.observation_id,
                        relation="produced_observation",
                        confidence=provider_result.confidence,
                        correlation_id=asset.capture_session_id,
                    )
                )
            for link in links:
                uow.multimodal.add_artifact_link(link)
            stored_links = list(links)
            completed_at = datetime.now(UTC)
            invocation = self._load_invocation(uow, invocation_id)
            invocation.status = "succeeded"
            invocation.response_digest = response_digest
            invocation.completed_at = completed_at
            invocation.duration_ms = max(
                0,
                int((completed_at - _utc(invocation.started_at)).total_seconds() * 1000),
            )
            invocation.correlation_id = asset.capture_session_id
            session = (
                uow.multimodal.get_capture_session(asset.capture_session_id)
                if asset.capture_session_id
                else None
            )
            if session is not None:
                session.status = "processed"
                session.closed_at = completed_at
            self._purge_asset(uow, asset, "processed_then_deleted")
            uow.commit()
            return MultimodalAnalysisResult(
                media_asset=_asset_view(asset),
                invocation=_invocation_view(self._load_invocation(uow, invocation_id)),
                extraction=_extraction_view(stored_extraction),
                observations=observation_sources,
                artifact_links=[_link_view(link) for link in stored_links],
            )

    def _load_invocation(
        self,
        uow: SqlAlchemyUnitOfWork,
        invocation_id: str,
    ) -> MultimodalProviderInvocation:
        assert uow.multimodal is not None
        invocation = uow.multimodal.get_invocation(invocation_id)
        if invocation is None:
            raise MultimodalError(
                code="MULTIMODAL_INVOCATION_NOT_FOUND",
                message="The provider invocation does not exist.",
                status_code=404,
            )
        return invocation

    def _record_candidate_observation(
        self,
        asset: MultimodalMediaAsset,
        extraction: MultimodalExtractionResult,
        now: datetime,
    ) -> MultimodalObservationSource | None:
        if asset.space_id is None or self._vision_source_id is None:
            return None
        attribute_map = {
            "scene_labels": "scene_label",
            "objects": "object_presence",
            "audio_events": "audio_event",
        }
        attribute = attribute_map.get(extraction.result_kind)
        if attribute is None:
            return None
        observed_at = _utc(asset.client_captured_at) if asset.client_captured_at else now
        observed_at_source = (
            "user_asserted" if asset.client_captured_at is not None else "poll_clock"
        )
        result = asyncio.run(
            self._observation_service.record(
                ObservationInput(
                    source_id=self._vision_source_id,
                    subject_type="space",
                    subject_id=asset.space_id,
                    space_id=asset.space_id,
                    attribute=attribute,
                    raw_value=extraction.result,
                    observed_at=observed_at,
                    observed_at_source=observed_at_source,  # type: ignore[arg-type]
                    observed_at_uncertainty_ms=asset.client_time_uncertainty_ms,
                    received_at=now,
                    correlation_id=asset.capture_session_id,
                    external_id=extraction.id,
                )
            )
        )
        record = result.data
        return MultimodalObservationSource(
            observation_id=record.observation_id,
            source_id=record.source_id,
            source_type=record.source_type,
            attribute=record.attribute,
            quality_status=record.quality_status,
        )

    def _fail_invocation(
        self,
        invocation_id: str,
        error_code: str,
        *,
        status: str = "failed",
    ) -> None:
        try:
            with self._unit_of_work_factory() as uow:
                assert uow.multimodal is not None
                invocation = self._load_invocation(uow, invocation_id)
                invocation.status = status
                invocation.error_code = error_code
                invocation.error_summary = "Provider processing failed without media content."
                invocation.completed_at = datetime.now(UTC)
                asset = uow.multimodal.get_asset(invocation.media_asset_id)
                if asset is not None:
                    self._purge_asset(uow, asset, "processing_failed")
                    session = (
                        uow.multimodal.get_capture_session(asset.capture_session_id)
                        if asset.capture_session_id
                        else None
                    )
                    if session is not None:
                        session.status = "failed"
                        session.closed_at = datetime.now(UTC)
                uow.commit()
        except Exception:
            return

    def _purge_asset(
        self,
        uow: SqlAlchemyUnitOfWork,
        asset: MultimodalMediaAsset,
        reason: str,
    ) -> bool:
        if asset.storage_key is not None:
            path = (self.media_root / asset.storage_key).resolve()
            if self.media_root in path.parents:
                path.unlink(missing_ok=True)
        deleted_extraction_count = uow.multimodal.delete_sensitive_extractions(asset.id)
        asset.content_available = False
        asset.storage_key = None
        asset.sha256 = None
        asset.purge_status = "purged"
        asset.purge_reason = reason
        asset.processed_at = datetime.now(UTC)
        if asset.capture_session_id is not None:
            assert uow.multimodal is not None
            session = uow.multimodal.get_capture_session(asset.capture_session_id)
            if session is not None and session.status not in {"failed", "cancelled", "expired"}:
                session.status = "purged"
                session.closed_at = asset.processed_at
        self._record_audit(
            uow,
            environment_id=asset.environment_id,
            actor_id=asset.metadata_summary.get("requested_by"),
            action="asset_purged",
            subject_type="media_asset",
            subject_id=asset.id,
            details={
                "reason": reason,
                "deleted_sensitive_extraction_count": deleted_extraction_count,
            },
        )
        return True

    def _synthesize_sync(
        self,
        request: MultimodalTTSRequest,
        adapter: MultimodalProviderAdapter,
    ) -> MultimodalAnalysisResult:
        now = datetime.now(UTC)
        storage_key = f"{uuid4().hex}.wav"
        output_path = (self.media_root / storage_key).resolve()
        self.media_root.mkdir(parents=True, exist_ok=True)
        with self._unit_of_work_factory() as uow:
            assert uow.environments is not None
            assert uow.multimodal is not None
            if uow.environments.get(request.environment_id) is None:
                raise MultimodalError(
                    code="MULTIMODAL_ENVIRONMENT_NOT_FOUND",
                    message="The environment does not exist.",
                    status_code=404,
                )
            providers = [row for row in uow.multimodal.list_providers() if row.capability == "tts"]
            provider = next((row for row in providers if row.enabled), None)
            if provider is None:
                raise MultimodalError(
                    code="MULTIMODAL_PROVIDER_UNAVAILABLE",
                    message="TTS is unavailable.",
                    status_code=409,
                )
            self._active_consent(
                uow,
                request.consent_id,
                consent_type="processing",
                environment_id=request.environment_id,
                modality="audio",
                purpose="accessibility_output",
                space_id=None,
                provider_name=provider.provider_name,
                processing_location="local",
            )
            self._record_audit(
                uow,
                environment_id=request.environment_id,
                actor_id=request.requested_by,
                action="speech_synthesized",
                subject_type="capture_session",
                subject_id=None,
                details={"character_count": len(request.text)},
            )
            session = MultimodalCaptureSession(
                environment_id=request.environment_id,
                modality="audio",
                purpose="accessibility_output",
                origin_type="user",
                requested_by=request.requested_by,
                status="processing",
                requires_capture_consent=False,
                expected_media_count=1,
                state_visibility={"camera_on": False, "microphone_on": False, "speaking": True},
            )
            stored_session = uow.multimodal.add_capture_session(session)
            session_id = stored_session.id
            uow.commit()
        try:
            provider_result = asyncio.run(
                asyncio.wait_for(
                    adapter.process(
                        capability="tts",
                        content=b"",
                        mime_type="audio/wav",
                        text=request.text,
                        output_path=output_path,
                    ),
                    timeout=provider.timeout_ms / 1000,
                )
            )
        except TimeoutError as exc:
            self._fail_tts_session(session_id, output_path)
            raise MultimodalError(
                code="MULTIMODAL_PROVIDER_TIMEOUT",
                message="The TTS provider timed out.",
                status_code=504,
            ) from exc
        except MultimodalError:
            self._fail_tts_session(session_id, output_path)
            raise
        except Exception as exc:
            self._fail_tts_session(session_id, output_path)
            raise MultimodalError(
                code="MULTIMODAL_PROVIDER_FAILED",
                message="The TTS provider call failed.",
                status_code=502,
            ) from exc
        try:
            with self._unit_of_work_factory() as uow:
                assert uow.multimodal is not None
                size = output_path.stat().st_size
                asset = MultimodalMediaAsset(
                    capture_session_id=session_id,
                    environment_id=request.environment_id,
                    media_kind="tts_audio",
                    mime_type="audio/wav",
                    size_bytes=size,
                    sha256=_digest(output_path.read_bytes()),
                    storage_backend="local_private_file",
                    storage_key=storage_key,
                    content_available=True,
                    validation_status="valid",
                    sensitivity="normal",
                    purpose="accessibility_output",
                    consent_id=request.consent_id,
                    retention_class="process_then_delete_1h",
                    retention_until=now + timedelta(hours=1),
                    purge_status="pending",
                    received_at=now,
                    metadata_summary={"kind": "tts_output"},
                )
                stored_asset = uow.multimodal.add_asset(asset)
                invocation = MultimodalProviderInvocation(
                    media_asset_id=stored_asset.id,
                    provider_id=provider.id,
                    capability="tts",
                    model_id=provider.model_id,
                    model_version=provider.model_version,
                    processing_location="local",
                    input_summary={"character_count": len(request.text)},
                    request_digest=_digest(request.text.encode("utf-8")),
                    response_digest=_digest(output_path.read_bytes()),
                    sent_media_to_external=False,
                    status="succeeded",
                    started_at=now,
                    completed_at=datetime.now(UTC),
                    duration_ms=0,
                )
                stored_invocation = uow.multimodal.add_invocation(invocation)
                extraction = MultimodalExtractionResult(
                    media_asset_id=stored_asset.id,
                    invocation_id=stored_invocation.id,
                    result_kind="structured_scene",
                    schema_version="1.0.0",
                    result=provider_result.result,
                    confidence=1.0,
                    confidence_level="high",
                    quality_status="valid_candidate",
                    model_id=provider.model_id,
                    model_version=provider_result.model_version,
                    valid_from=now,
                    valid_until=now + timedelta(hours=1),
                )
                stored_extraction = uow.multimodal.add_extraction(extraction)
                stored_session = uow.multimodal.get_capture_session(session_id)
                if stored_session is not None:
                    stored_session.status = "processed"
                    stored_session.closed_at = datetime.now(UTC)
                uow.commit()
                return MultimodalAnalysisResult(
                    capture_session=_session_view(stored_session),
                    media_asset=_asset_view(stored_asset),
                    invocation=_invocation_view(stored_invocation),
                    extraction=_extraction_view(stored_extraction),
                )
        except MultimodalError:
            output_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            raise MultimodalError(
                code="MULTIMODAL_TTS_OUTPUT_FAILED",
                message="The synthesized audio could not be stored.",
                status_code=502,
            ) from exc

    def _purge_expired_sync(self, now: datetime, limit: int | None = None) -> int:
        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            assets = [
                row
                for row in uow.multimodal.list_assets_pending_purge(limit=limit)
                if _utc(row.retention_until) <= _utc(now)
            ]
            for asset in assets:
                self._purge_asset(uow, asset, "retention_expired")
            uow.commit()
            return len(assets)

    def _list_extractions(self) -> list[MultimodalExtractionView]:
        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            return [_extraction_view(row) for row in uow.multimodal.list_extractions()]

    def _purge_asset_sync(self, asset_id: str) -> MultimodalMediaAssetView:
        with self._unit_of_work_factory() as uow:
            assert uow.multimodal is not None
            asset = uow.multimodal.get_asset(asset_id)
            if asset is None:
                raise MultimodalError(
                    code="MULTIMODAL_ASSET_NOT_FOUND",
                    message="The media asset does not exist.",
                    status_code=404,
                )
            if asset.purge_status != "purged":
                self._purge_asset(uow, asset, "user_requested")
                uow.commit()
            return _asset_view(asset)

    def _fail_tts_session(self, session_id: str, output_path: Path) -> None:
        output_path.unlink(missing_ok=True)
        try:
            with self._unit_of_work_factory() as uow:
                assert uow.multimodal is not None
                session = uow.multimodal.get_capture_session(session_id)
                if session is not None:
                    session.status = "failed"
                    session.closed_at = datetime.now(UTC)
                    uow.commit()
        except Exception:
            return


__all__ = ["MultimodalService"]
