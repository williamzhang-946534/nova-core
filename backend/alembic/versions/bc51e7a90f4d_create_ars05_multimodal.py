"""create ARS-05 multimodal observation access

Revision ID: bc51e7a90f4d
Revises: a7d4f83c1092
Create Date: 2026-11-06
"""

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "bc51e7a90f4d"
down_revision: str | None = "a7d4f83c1092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PROVIDERS = (
    ("a518de10-5e4c-5f31-9453-d2b2c2383a01", "mock", "vision_scene", ["image", "video_frame"]),
    ("a518de10-5e4c-5f31-9453-d2b2c2383a02", "mock", "vision_object", ["image", "video_frame"]),
    ("a518de10-5e4c-5f31-9453-d2b2c2383a03", "mock", "ocr", ["image", "video_frame"]),
    ("a518de10-5e4c-5f31-9453-d2b2c2383a04", "mock", "stt", ["audio_clip"]),
    ("a518de10-5e4c-5f31-9453-d2b2c2383a05", "mock", "tts", ["tts_audio"]),
    ("a518de10-5e4c-5f31-9453-d2b2c2383a06", "mock", "audio_event", ["audio_clip"]),
)

ATTRIBUTES = {
    "scene_label": {
        "display_name": "Scene labels",
        "freshness": 3600,
        "retention": 30,
    },
    "object_presence": {
        "display_name": "Candidate object presence",
        "freshness": 1800,
        "retention": 7,
    },
    "audio_event": {
        "display_name": "Audio event candidates",
        "freshness": 600,
        "retention": 7,
    },
}


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _seed_providers() -> None:
    timestamp = datetime.now(UTC).isoformat()
    for provider_id, name, capability, kinds in PROVIDERS:
        op.execute(
            sa.text(
                """
                INSERT INTO multimodal_providers (
                    id, provider_name, capability, media_kinds, processing_location,
                    data_sent_policy, model_id, model_version, max_bytes, max_duration_ms,
                    timeout_ms, requires_explicit_consent, is_default, priority, enabled,
                    created_at, updated_at
                ) VALUES (
                    :id, :provider_name, :capability, :media_kinds, 'local',
                    :data_sent_policy, 'mock', '1.0.0', 10485760,
                    :max_duration_ms, 5000, 1, 1, 100, 1,
                    :created_at, :updated_at
                )
                """
            ).bindparams(
                id=provider_id,
                provider_name=name,
                capability=capability,
                media_kinds=_json(kinds),
                data_sent_policy=_json(
                    {
                        "media": "current upload only",
                        "metadata": "mime, size, and digest",
                        "retained_by_provider": False,
                        "used_for_training": False,
                        "external_transfer": False,
                    }
                ),
                max_duration_ms=60000 if capability in {"stt", "tts", "audio_event"} else None,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )


def _seed_attributes() -> None:
    timestamp = datetime.now(UTC).isoformat()
    for attribute, values in ATTRIBUTES.items():
        sensitivity = "normal" if attribute == "scene_label" else "sensitive"
        policy_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"arvuno:multimodal:{attribute}:1.0.0"))
        op.execute(
            sa.text(
                """
                INSERT INTO observation_attribute_definitions (
                    attribute, display_name, value_type, canonical_unit,
                    normalization_rule_version, valid_range, quality_policy,
                    freshness_policy, sampling_policy, retention_policy,
                    sensitivity, created_at, updated_at
                ) VALUES (
                    :attribute, :display_name, 'json', NULL, '1.0.0', '{}',
                    '{"delay_warning_seconds": 300, "future_warning_seconds": 60}',
                    :freshness, '{"on_change_only": true}', :retention,
                    :sensitivity, :created_at, :updated_at
                )
                """
            ).bindparams(
                attribute=attribute,
                display_name=values["display_name"],
                freshness=_json({"valid_seconds": values["freshness"]}),
                retention=_json(
                    {
                        "retention_days": values["retention"],
                        "class": f"multimodal_{values['retention']}d",
                    }
                ),
                sensitivity=sensitivity,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        op.execute(
            sa.text(
                """
                INSERT INTO observation_attribute_policies (
                    id, attribute, sensitivity, requires_consent, allowed_source_types,
                    allowed_spaces, raw_storage_allowed, record_retention_days,
                    normalized_only, redaction_rule, version, created_at, updated_at
                ) VALUES (
                    :id, :attribute, :sensitivity, 0, '["vision"]', NULL, 1,
                    :retention_days, 0, NULL, '1.0.0', :created_at, :updated_at
                )
                """
            ).bindparams(
                id=policy_id,
                attribute=attribute,
                sensitivity=sensitivity,
                retention_days=values["retention"],
                created_at=timestamp,
                updated_at=timestamp,
            )
        )


def _create_table(name: str, *columns: sa.Column, constraints: tuple[object, ...] = ()) -> None:
    op.create_table(name, *columns, *constraints)


def upgrade() -> None:
    _create_table(
        "multimodal_consents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("consent_type", sa.String(length=40), nullable=False),
        sa.Column("modality", sa.String(length=30), nullable=False),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=True),
        sa.Column("processing_locations", sa.JSON(), nullable=False),
        sa.Column("space_ids", sa.JSON(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.PrimaryKeyConstraint("id", name="pk_multimodal_consents"),
            sa.ForeignKeyConstraint(
                ["environment_id"],
                ["environments.id"],
                name="fk_multimodal_consents_environment",
                ondelete="CASCADE",
            ),
            sa.CheckConstraint(
                "consent_type IN ('capture', 'processing', 'retention')",
                name="ck_multimodal_consents_type",
            ),
            sa.CheckConstraint(
                "modality IN ('image', 'video_frame', 'audio')",
                name="ck_multimodal_consents_modality",
            ),
            sa.CheckConstraint(
                "status IN ('granted', 'revoked', 'expired')",
                name="ck_multimodal_consents_status",
            ),
        ),
    )
    op.create_index(
        "ix_multimodal_consents_subject",
        "multimodal_consents",
        ["environment_id", "user_id", "status"],
    )

    _create_table(
        "multimodal_providers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("capability", sa.String(length=50), nullable=False),
        sa.Column("media_kinds", sa.JSON(), nullable=False),
        sa.Column("processing_location", sa.String(length=20), nullable=False),
        sa.Column("data_sent_policy", sa.JSON(), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("max_bytes", sa.Integer(), nullable=False),
        sa.Column("max_duration_ms", sa.Integer(), nullable=True),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
        sa.Column("requires_explicit_consent", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.PrimaryKeyConstraint("id", name="pk_multimodal_providers"),
            sa.UniqueConstraint(
                "provider_name",
                "capability",
                "processing_location",
                name="uq_multimodal_providers_identity",
            ),
            sa.CheckConstraint(
                "capability IN ('vision_scene', 'vision_object', 'ocr', 'stt', 'tts', "
                "'audio_event')",
                name="ck_multimodal_providers_capability",
            ),
            sa.CheckConstraint(
                "processing_location IN ('local', 'cloud')",
                name="ck_multimodal_providers_location",
            ),
            sa.CheckConstraint(
                "processing_location != 'cloud' OR requires_explicit_consent = 1",
                name="ck_multimodal_providers_cloud_consent",
            ),
        ),
    )
    op.create_index(
        "ix_multimodal_providers_capability_enabled",
        "multimodal_providers",
        ["capability", "enabled"],
    )

    _create_table(
        "multimodal_capture_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("space_id", sa.String(length=36), nullable=True),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.Column("modality", sa.String(length=30), nullable=False),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("origin_type", sa.String(length=40), nullable=False),
        sa.Column("origin_record_id", sa.String(length=255), nullable=True),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("requires_capture_consent", sa.Boolean(), nullable=False),
        sa.Column("expected_media_count", sa.Integer(), nullable=False),
        sa.Column("max_duration_ms", sa.Integer(), nullable=True),
        sa.Column("state_visibility", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        constraints=(
            sa.PrimaryKeyConstraint("id", name="pk_multimodal_capture_sessions"),
            sa.ForeignKeyConstraint(
                ["environment_id"],
                ["environments.id"],
                name="fk_multimodal_sessions_environment",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["space_id"], ["spaces.id"], name="fk_multimodal_sessions_space", ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["entity_id"],
                ["entities.id"],
                name="fk_multimodal_sessions_entity",
                ondelete="CASCADE",
            ),
            sa.CheckConstraint(
                "modality IN ('image', 'video_frame', 'audio')",
                name="ck_multimodal_capture_sessions_modality",
            ),
            sa.CheckConstraint(
                "purpose IN ('user_query', 'scene_check', 'ocr', 'speech_input', "
                "'audio_event', 'active_perception', 'accessibility_output')",
                name="ck_multimodal_capture_sessions_purpose",
            ),
            sa.CheckConstraint(
                "origin_type IN ('user', 'active_perception', 'task_validation', 'system')",
                name="ck_multimodal_capture_sessions_origin",
            ),
            sa.CheckConstraint(
                "status IN ('requested', 'awaiting_consent', 'uploaded', 'processing', "
                "'processed', 'purging', 'purged', 'failed', 'cancelled', 'expired')",
                name="ck_multimodal_capture_sessions_status",
            ),
            sa.CheckConstraint(
                "expected_media_count = 1", name="ck_multimodal_capture_single_media"
            ),
        ),
    )
    op.create_index(
        "ix_multimodal_capture_sessions_environment_status",
        "multimodal_capture_sessions",
        ["environment_id", "status"],
    )
    op.create_index(
        "ix_multimodal_capture_sessions_correlation",
        "multimodal_capture_sessions",
        ["correlation_id"],
    )

    _create_table(
        "multimodal_media_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("capture_session_id", sa.String(length=36), nullable=True),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("media_kind", sa.String(length=30), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("storage_backend", sa.String(length=40), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=True),
        sa.Column("content_available", sa.Boolean(), nullable=False),
        sa.Column("validation_status", sa.String(length=30), nullable=False),
        sa.Column("sensitivity", sa.String(length=20), nullable=False),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("consent_id", sa.String(length=36), nullable=False),
        sa.Column("retention_class", sa.String(length=40), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purge_status", sa.String(length=20), nullable=False),
        sa.Column("purge_reason", sa.String(length=100), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("client_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_time_source", sa.String(length=50), nullable=True),
        sa.Column("client_time_uncertainty_ms", sa.Integer(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("space_id", sa.String(length=36), nullable=True),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.PrimaryKeyConstraint("id", name="pk_multimodal_media_assets"),
            sa.ForeignKeyConstraint(
                ["capture_session_id"],
                ["multimodal_capture_sessions.id"],
                name="fk_multimodal_assets_session",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["environment_id"],
                ["environments.id"],
                name="fk_multimodal_assets_environment",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["consent_id"],
                ["multimodal_consents.id"],
                name="fk_multimodal_assets_consent",
            ),
            sa.ForeignKeyConstraint(
                ["space_id"], ["spaces.id"], name="fk_multimodal_assets_space", ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["entity_id"],
                ["entities.id"],
                name="fk_multimodal_assets_entity",
                ondelete="CASCADE",
            ),
            sa.CheckConstraint(
                "media_kind IN ('image', 'video_frame', 'audio_clip', 'tts_audio')",
                name="ck_multimodal_media_assets_kind",
            ),
            sa.CheckConstraint(
                "validation_status IN ('pending', 'quarantined', 'valid', 'invalid')",
                name="ck_multimodal_media_assets_validation",
            ),
            sa.CheckConstraint(
                "sensitivity IN ('normal', 'sensitive')",
                name="ck_multimodal_media_assets_sensitivity",
            ),
            sa.CheckConstraint(
                "retention_class IN ('process_then_delete_1h', "
                "'process_then_delete_24h', 'deleted')",
                name="ck_multimodal_media_assets_retention",
            ),
            sa.CheckConstraint(
                "sensitivity != 'sensitive' OR retention_class = 'process_then_delete_1h'",
                name="ck_multimodal_media_assets_sensitive_short_retention",
            ),
            sa.CheckConstraint(
                "purge_status != 'purged' OR (storage_key IS NULL AND content_available = 0)",
                name="ck_multimodal_media_assets_purge_state",
            ),
        ),
    )
    op.create_index(
        "ix_multimodal_media_assets_environment_received",
        "multimodal_media_assets",
        ["environment_id", "received_at"],
    )
    op.create_index(
        "ix_multimodal_media_assets_retention",
        "multimodal_media_assets",
        ["retention_until", "purge_status"],
    )
    op.create_index(
        "ix_multimodal_media_assets_session",
        "multimodal_media_assets",
        ["capture_session_id"],
    )

    _create_table(
        "multimodal_provider_invocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("media_asset_id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=36), nullable=False),
        sa.Column("capability", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("processing_location", sa.String(length=20), nullable=False),
        sa.Column("input_summary", sa.JSON(), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("response_digest", sa.String(length=64), nullable=True),
        sa.Column("sent_media_to_external", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.PrimaryKeyConstraint("id", name="pk_multimodal_provider_invocations"),
            sa.ForeignKeyConstraint(
                ["media_asset_id"],
                ["multimodal_media_assets.id"],
                name="fk_multimodal_invocations_asset",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["provider_id"],
                ["multimodal_providers.id"],
                name="fk_multimodal_invocations_provider",
            ),
            sa.CheckConstraint(
                "status IN ('queued', 'running', 'succeeded', 'failed', 'timeout', 'cancelled')",
                name="ck_multimodal_invocations_status",
            ),
        ),
    )
    op.create_index(
        "ix_multimodal_invocations_asset",
        "multimodal_provider_invocations",
        ["media_asset_id", "created_at"],
    )
    op.create_index(
        "ix_multimodal_invocations_correlation",
        "multimodal_provider_invocations",
        ["correlation_id"],
    )

    _create_table(
        "multimodal_extraction_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("media_asset_id", sa.String(length=36), nullable=False),
        sa.Column("invocation_id", sa.String(length=36), nullable=False),
        sa.Column("result_kind", sa.String(length=50), nullable=False),
        sa.Column("schema_version", sa.String(length=30), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("confidence_level", sa.String(length=20), nullable=False),
        sa.Column("quality_status", sa.String(length=30), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=True),
        sa.Column("alternatives", sa.JSON(), nullable=True),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.PrimaryKeyConstraint("id", name="pk_multimodal_extraction_results"),
            sa.ForeignKeyConstraint(
                ["media_asset_id"],
                ["multimodal_media_assets.id"],
                name="fk_multimodal_results_asset",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["invocation_id"],
                ["multimodal_provider_invocations.id"],
                name="fk_multimodal_results_invocation",
                ondelete="CASCADE",
            ),
            sa.CheckConstraint(
                "result_kind IN ('scene_labels', 'objects', 'ocr_text', 'transcript', "
                "'audio_events', 'structured_scene')",
                name="ck_multimodal_extraction_result_kind",
            ),
            sa.CheckConstraint(
                "confidence IS NULL OR confidence BETWEEN 0 AND 1",
                name="ck_multimodal_extraction_confidence",
            ),
            sa.CheckConstraint(
                "confidence_level IN ('unknown', 'low', 'medium', 'high')",
                name="ck_multimodal_extraction_confidence_level",
            ),
            sa.CheckConstraint(
                "quality_status IN ('candidate', 'valid_candidate', 'rejected', "
                "'superseded', 'expired')",
                name="ck_multimodal_extraction_quality",
            ),
        ),
    )
    op.create_index(
        "ix_multimodal_extraction_asset",
        "multimodal_extraction_results",
        ["media_asset_id", "created_at"],
    )
    op.create_index(
        "ix_multimodal_extraction_kind_status",
        "multimodal_extraction_results",
        ["result_kind", "quality_status"],
    )

    _create_table(
        "multimodal_artifact_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("artifact_type", sa.String(length=50), nullable=False),
        sa.Column("artifact_id", sa.String(length=36), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("relation", sa.String(length=50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.PrimaryKeyConstraint("id", name="pk_multimodal_artifact_links"),
            sa.CheckConstraint(
                "artifact_type IN ('media_asset', 'provider_invocation', 'extraction_result')",
                name="ck_multimodal_artifact_links_artifact",
            ),
            sa.CheckConstraint(
                "target_type IN ('observation', 'conversation_message', 'task', "
                "'reasoning_evidence', 'memory')",
                name="ck_multimodal_artifact_links_target",
            ),
            sa.CheckConstraint(
                "relation IN ('produced_observation', 'produced_message', 'evidence_for', "
                "'memory_evidence_for')",
                name="ck_multimodal_artifact_links_relation",
            ),
        ),
    )
    op.create_index(
        "ix_multimodal_artifact_links_artifact",
        "multimodal_artifact_links",
        ["artifact_type", "artifact_id"],
    )
    op.create_index(
        "ix_multimodal_artifact_links_target",
        "multimodal_artifact_links",
        ["target_type", "target_id"],
    )

    _seed_providers()
    _seed_attributes()


def downgrade() -> None:
    op.drop_table("multimodal_artifact_links")
    op.drop_table("multimodal_extraction_results")
    op.drop_table("multimodal_provider_invocations")
    op.drop_table("multimodal_media_assets")
    op.drop_table("multimodal_capture_sessions")
    op.drop_table("multimodal_providers")
    op.drop_table("multimodal_consents")
    op.execute(
        """
        DELETE FROM observation_attribute_policies
        WHERE attribute IN ('scene_label', 'object_presence', 'audio_event')
        """
    )
    op.execute(
        """
        DELETE FROM observation_attribute_definitions
        WHERE attribute IN ('scene_label', 'object_presence', 'audio_event')
        """
    )
