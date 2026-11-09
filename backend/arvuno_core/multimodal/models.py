from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Modality = Literal["image", "video_frame", "audio"]
ConsentType = Literal["capture", "processing", "retention"]
Sensitivity = Literal["normal", "sensitive"]
DataAccessModality = Literal["image", "video_frame", "audio", "sensor", "device"]


class MultimodalConsentCreate(BaseModel):
    environment_id: str = Field(min_length=1, max_length=36)
    user_id: str = Field(min_length=1, max_length=255)
    consent_type: ConsentType
    modality: Modality
    purpose: Literal[
        "user_query",
        "scene_check",
        "ocr",
        "speech_input",
        "audio_event",
        "active_perception",
        "accessibility_output",
    ]
    provider_name: str | None = Field(default=None, max_length=100)
    processing_locations: list[Literal["local"]] = Field(min_length=1)
    space_ids: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    scope: dict[str, Any] = Field(default_factory=dict)


class MultimodalCaptureSessionCreate(BaseModel):
    environment_id: str = Field(min_length=1, max_length=36)
    space_id: str | None = Field(default=None, max_length=36)
    entity_id: str | None = Field(default=None, max_length=36)
    modality: Modality
    purpose: Literal[
        "user_query",
        "scene_check",
        "ocr",
        "speech_input",
        "audio_event",
        "active_perception",
    ]
    origin_type: Literal["user", "active_perception", "task_validation", "system"] = "user"
    origin_record_id: str | None = Field(default=None, max_length=255)
    requested_by: str = Field(min_length=1, max_length=255)
    requires_capture_consent: bool = False
    max_duration_ms: int | None = Field(default=None, ge=1, le=300000)
    correlation_id: str | None = Field(default=None, max_length=100)


class MultimodalMediaUpload(BaseModel):
    consent_id: str = Field(min_length=1, max_length=36)
    sensitivity: Sensitivity = "normal"
    duration_ms: int | None = Field(default=None, ge=1, le=300000)
    client_captured_at: datetime | None = None
    client_time_source: Literal[
        "device_clock",
        "gateway_clock",
        "poll_clock",
        "user_asserted",
        "unknown",
    ] = "unknown"
    client_time_uncertainty_ms: int | None = Field(default=None, ge=0, le=86400000)


class MultimodalAnalyzeRequest(BaseModel):
    capability: Literal["vision_scene", "vision_object", "ocr", "stt", "audio_event"]
    provider_name: str = Field(min_length=1, max_length=100)
    consent_id: str = Field(min_length=1, max_length=36)


class MultimodalTTSRequest(BaseModel):
    environment_id: str = Field(min_length=1, max_length=36)
    text: str = Field(min_length=1, max_length=5000)
    requested_by: str = Field(min_length=1, max_length=255)
    consent_id: str = Field(min_length=1, max_length=36)


class MultimodalDataAccessGrantCreate(BaseModel):
    environment_id: str = Field(min_length=1, max_length=36)
    user_id: str = Field(min_length=1, max_length=255)
    modalities: list[DataAccessModality] = Field(min_length=1)
    space_ids: list[str] = Field(min_length=1)
    expires_at: datetime | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] | None = None


class MultimodalDataAccessGrantView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    environment_id: str
    user_id: str
    modalities: list[str]
    space_ids: list[str]
    granted_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    status: str
    scope: dict[str, Any]
    evidence: dict[str, Any] | None


class MultimodalFusionQuery(BaseModel):
    environment_id: str = Field(min_length=1, max_length=36)
    grant_id: str = Field(min_length=1, max_length=36)
    from_at: datetime
    to_at: datetime
    space_id: str | None = Field(default=None, max_length=36)
    entity_id: str | None = Field(default=None, max_length=36)
    correlation_id: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=200, ge=1, le=1000)


class MultimodalProviderView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider_name: str
    capability: str
    media_kinds: list[str]
    processing_location: str
    data_sent_policy: dict[str, Any]
    model_id: str
    model_version: str
    max_bytes: int
    max_duration_ms: int | None
    timeout_ms: int
    requires_explicit_consent: bool
    is_default: bool
    priority: int
    enabled: bool


class MultimodalConsentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    environment_id: str
    user_id: str
    consent_type: str
    modality: str
    purpose: str
    provider_name: str | None
    processing_locations: list[str]
    space_ids: list[str]
    granted_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    status: str
    scope: dict[str, Any]
    evidence: dict[str, Any] | None


class MultimodalCaptureSessionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    environment_id: str
    space_id: str | None
    entity_id: str | None
    modality: str
    purpose: str
    origin_type: str
    origin_record_id: str | None
    requested_by: str
    status: str
    requires_capture_consent: bool
    expected_media_count: int
    max_duration_ms: int | None
    state_visibility: dict[str, Any]
    correlation_id: str | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None


class MultimodalMediaAssetView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    capture_session_id: str | None
    environment_id: str
    media_kind: str
    mime_type: str
    size_bytes: int
    sha256: str | None
    storage_backend: str
    content_available: bool
    validation_status: str
    sensitivity: str
    purpose: str
    consent_id: str
    retention_class: str
    retention_until: datetime
    purge_status: str
    purge_reason: str | None
    duration_ms: int | None
    client_captured_at: datetime | None
    client_time_source: str | None
    client_time_uncertainty_ms: int | None
    received_at: datetime
    processed_at: datetime | None
    space_id: str | None
    entity_id: str | None
    metadata_summary: dict[str, Any]


class MultimodalInvocationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    media_asset_id: str
    provider_id: str
    capability: str
    model_id: str
    model_version: str
    processing_location: str
    input_summary: dict[str, Any]
    request_digest: str
    response_digest: str | None
    sent_media_to_external: bool
    status: str
    error_code: str | None
    error_summary: str | None
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    correlation_id: str | None


class MultimodalExtractionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    media_asset_id: str
    invocation_id: str
    result_kind: str
    schema_version: str
    result: dict[str, Any]
    confidence: float | None
    confidence_level: str
    quality_status: str
    language: str | None
    alternatives: list[Any] | None
    model_id: str
    model_version: str
    valid_from: datetime
    valid_until: datetime | None


class MultimodalArtifactLinkView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    artifact_type: str
    artifact_id: str
    target_type: str
    target_id: str
    relation: str
    confidence: float | None
    correlation_id: str | None


class MultimodalObservationSource(BaseModel):
    observation_id: str
    source_id: str
    source_type: str
    attribute: str
    quality_status: str


class MultimodalFusionItem(BaseModel):
    artifact_type: Literal["observation", "extraction_result"]
    id: str
    modality: str
    source_type: str
    source_id: str
    space_id: str | None
    entity_id: str | None
    subject_id: str | None
    attribute: str
    observed_at: datetime
    received_at: datetime
    processed_at: datetime | None
    value: Any
    confidence: float | None
    quality_status: str
    model_id: str | None
    model_version: str | None
    capture_session_id: str | None
    correlation_id: str | None
    association: dict[str, Any]


class MultimodalFusionResult(BaseModel):
    items: list[MultimodalFusionItem]
    total_available: int
    association_type: str = "time_space_correlation"
    causal_claim: bool = False
    missing_data_note: str | None = None


class MultimodalAuditEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    environment_id: str | None
    actor_id: str | None
    action: str
    subject_type: str | None
    subject_id: str | None
    details: dict[str, Any]
    occurred_at: datetime


class MultimodalAnalysisResult(BaseModel):
    capture_session: MultimodalCaptureSessionView | None = None
    media_asset: MultimodalMediaAssetView | None = None
    invocation: MultimodalInvocationView
    extraction: MultimodalExtractionView
    observations: list[MultimodalObservationSource] = Field(default_factory=list)
    artifact_links: list[MultimodalArtifactLinkView] = Field(default_factory=list)


class MultimodalCapabilities(BaseModel):
    camera_capture_enabled: bool = False
    microphone_capture_enabled: bool = False
    continuous_video_analysis_enabled: bool = False
    cloud_processing_enabled: bool = False
    providers: list[MultimodalProviderView]
