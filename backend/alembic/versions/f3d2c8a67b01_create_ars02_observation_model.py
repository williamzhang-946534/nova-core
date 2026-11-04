"""create the ARS-02 observation model

Revision ID: f3d2c8a67b01
Revises: 7c2a9f10d48d
Create Date: 2026-11-03
"""

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "f3d2c8a67b01"
down_revision: str | None = "7c2a9f10d48d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


HOME_ASSISTANT_SOURCE_ID = "5b6dc6ac-79e3-4c47-a5e3-2f32db4a6d01"
MOCK_SOURCE_ID = "5b6dc6ac-79e3-4c47-a5e3-2f32db4a6d02"

ATTRIBUTE_DEFINITIONS: dict[str, dict[str, object]] = {
    "temperature": {
        "display_name": "Temperature",
        "value_type": "number",
        "canonical_unit": "°C",
        "valid_range": {"min": -50, "max": 100},
        "quality_policy": {"delay_warning_seconds": 300, "future_warning_seconds": 300},
        "freshness_policy": {"valid_seconds": 300},
        "sampling_policy": {"minimum_interval_seconds": 60, "change_threshold": 0.2},
        "retention_policy": {"retention_days": 30, "class": "standard_30d"},
        "sensitivity": "normal",
    },
    "humidity": {
        "display_name": "Relative humidity",
        "value_type": "number",
        "canonical_unit": "%RH",
        "valid_range": {"min": 0, "max": 100},
        "quality_policy": {"delay_warning_seconds": 600, "future_warning_seconds": 300},
        "freshness_policy": {"valid_seconds": 600},
        "sampling_policy": {"minimum_interval_seconds": 60, "change_threshold": 1},
        "retention_policy": {"retention_days": 30, "class": "standard_30d"},
        "sensitivity": "normal",
    },
    "motion": {
        "display_name": "Motion",
        "value_type": "boolean",
        "canonical_unit": None,
        "valid_range": {"values": [True, False, None]},
        "quality_policy": {"delay_warning_seconds": 60, "future_warning_seconds": 60},
        "freshness_policy": {"valid_seconds": 60},
        "sampling_policy": {"minimum_interval_seconds": 5, "on_change_only": True},
        "retention_policy": {"retention_days": 7, "class": "sensitive_7d"},
        "sensitivity": "sensitive",
    },
    "contact": {
        "display_name": "Contact",
        "value_type": "enum",
        "canonical_unit": None,
        "valid_range": {"values": ["open", "closed", "unknown"]},
        "quality_policy": {"delay_warning_seconds": 300, "future_warning_seconds": 60},
        "freshness_policy": {"valid_seconds": 300},
        "sampling_policy": {"minimum_interval_seconds": 5, "on_change_only": True},
        "retention_policy": {"retention_days": 30, "class": "standard_30d"},
        "sensitivity": "normal",
    },
    "occupancy": {
        "display_name": "Occupancy",
        "value_type": "enum",
        "canonical_unit": None,
        "valid_range": {"values": ["occupied", "unoccupied", "unknown"]},
        "quality_policy": {"delay_warning_seconds": 60, "future_warning_seconds": 60},
        "freshness_policy": {"valid_seconds": 120},
        "sampling_policy": {"minimum_interval_seconds": 5, "on_change_only": True},
        "retention_policy": {"retention_days": 7, "class": "sensitive_7d"},
        "sensitivity": "sensitive",
    },
    "illumination": {
        "display_name": "Illumination",
        "value_type": "number",
        "canonical_unit": "lux",
        "valid_range": {"min": 0, "max": 200000},
        "quality_policy": {"delay_warning_seconds": 600, "future_warning_seconds": 300},
        "freshness_policy": {"valid_seconds": 600},
        "sampling_policy": {"minimum_interval_seconds": 60, "change_threshold": 5},
        "retention_policy": {"retention_days": 30, "class": "standard_30d"},
        "sensitivity": "normal",
    },
    "co2": {
        "display_name": "Carbon dioxide",
        "value_type": "number",
        "canonical_unit": "ppm",
        "valid_range": {"min": 0, "max": 10000},
        "quality_policy": {"delay_warning_seconds": 600, "future_warning_seconds": 300},
        "freshness_policy": {"valid_seconds": 600},
        "sampling_policy": {"minimum_interval_seconds": 60, "change_threshold": 25},
        "retention_policy": {"retention_days": 30, "class": "standard_30d"},
        "sensitivity": "normal",
    },
    "device_availability": {
        "display_name": "Device availability",
        "value_type": "enum",
        "canonical_unit": None,
        "valid_range": {"values": ["online", "offline", "unknown"]},
        "quality_policy": {"delay_warning_seconds": 300, "future_warning_seconds": 60},
        "freshness_policy": {"valid_seconds": 300},
        "sampling_policy": {"minimum_interval_seconds": 30, "on_change_only": True},
        "retention_policy": {"retention_days": 30, "class": "standard_30d"},
        "sensitivity": "normal",
    },
    "actuator_state": {
        "display_name": "Actuator state",
        "value_type": "json",
        "canonical_unit": None,
        "valid_range": {},
        "quality_policy": {"delay_warning_seconds": 300, "future_warning_seconds": 60},
        "freshness_policy": {"valid_seconds": 300},
        "sampling_policy": {"minimum_interval_seconds": 5, "on_change_only": True},
        "retention_policy": {"retention_days": 30, "class": "standard_30d"},
        "sensitivity": "normal",
    },
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _seed_sources() -> None:
    rows = [
        (
            HOME_ASSISTANT_SOURCE_ID,
            "adapter",
            "home_assistant",
            "Home Assistant",
            "active",
            0.9,
            "gateway_clock",
        ),
        (
            MOCK_SOURCE_ID,
            "adapter",
            "mock",
            "Mock Adapter",
            "active",
            0.5,
            "poll_clock",
        ),
    ]
    for source_id, source_type, adapter_id, name, status, trust, time_trust in rows:
        op.execute(
            sa.text(
                """
                INSERT INTO observation_sources (
                    id, source_type, adapter_id, name, status, trust_level,
                    time_trust, config, privacy_scope, created_at, updated_at
                ) VALUES (
                    :id, :source_type, :adapter_id, :name, :status, :trust_level,
                    :time_trust, :config, :privacy_scope, :created_at, :updated_at
                )
                """
            ).bindparams(
                id=source_id,
                source_type=source_type,
                adapter_id=adapter_id,
                name=name,
                status=status,
                trust_level=trust,
                time_trust=time_trust,
                config=_json({"kind": adapter_id}),
                privacy_scope=_json({"allowed_environment": "home"}),
                created_at=_now(),
                updated_at=_now(),
            )
        )


def _seed_attributes() -> None:
    timestamp = _now()
    for attribute, values in ATTRIBUTE_DEFINITIONS.items():
        op.execute(
            sa.text(
                """
                INSERT INTO observation_attribute_definitions (
                    attribute, display_name, value_type, canonical_unit,
                    normalization_rule_version, valid_range, quality_policy,
                    freshness_policy, sampling_policy, retention_policy,
                    sensitivity, created_at, updated_at
                ) VALUES (
                    :attribute, :display_name, :value_type, :canonical_unit,
                    :normalization_rule_version, :valid_range, :quality_policy,
                    :freshness_policy, :sampling_policy, :retention_policy,
                    :sensitivity, :created_at, :updated_at
                )
                """
            ).bindparams(
                attribute=attribute,
                display_name=values["display_name"],
                value_type=values["value_type"],
                canonical_unit=values["canonical_unit"],
                normalization_rule_version="1.0.0",
                valid_range=_json(values["valid_range"]),
                quality_policy=_json(values["quality_policy"]),
                freshness_policy=_json(values["freshness_policy"]),
                sampling_policy=_json(values["sampling_policy"]),
                retention_policy=_json(values["retention_policy"]),
                sensitivity=values["sensitivity"],
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        policy_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"arvuno:policy:{attribute}:1.0.0"))
        retention_days = int(
            dict(values["retention_policy"])["retention_days"]  # type: ignore[arg-type]
        )
        op.execute(
            sa.text(
                """
                INSERT INTO observation_attribute_policies (
                    id, attribute, sensitivity, requires_consent,
                    allowed_source_types, allowed_spaces, raw_storage_allowed,
                    record_retention_days, normalized_only, redaction_rule,
                    version, created_at, updated_at
                ) VALUES (
                    :id, :attribute, :sensitivity, 0,
                    :allowed_source_types, NULL, 1, :record_retention_days, 0,
                    :redaction_rule, :version, :created_at, :updated_at
                )
                """
            ).bindparams(
                id=policy_id,
                attribute=attribute,
                sensitivity=values["sensitivity"],
                allowed_source_types=_json(
                    ["adapter", "user_report", "derived_job", "future_external"]
                ),
                record_retention_days=retention_days,
                redaction_rule=None,
                version="1.0.0",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )


def upgrade() -> None:
    op.create_table(
        "observation_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("adapter_id", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("trust_level", sa.Float(), nullable=False),
        sa.Column("time_trust", sa.String(length=50), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("privacy_scope", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_observation_sources")),
        sa.UniqueConstraint("adapter_id", name="uq_observation_sources_adapter_id"),
    )
    with op.batch_alter_table("observation_sources", schema=None) as batch_op:
        batch_op.create_index(
            "ix_observation_sources_type_status", ["source_type", "status"], unique=False
        )
        batch_op.create_index("ix_observation_sources_adapter", ["adapter_id"], unique=False)

    op.create_table(
        "observation_attribute_definitions",
        sa.Column("attribute", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("value_type", sa.String(length=20), nullable=False),
        sa.Column("canonical_unit", sa.String(length=50), nullable=True),
        sa.Column("normalization_rule_version", sa.String(length=50), nullable=False),
        sa.Column("valid_range", sa.JSON(), nullable=False),
        sa.Column("quality_policy", sa.JSON(), nullable=False),
        sa.Column("freshness_policy", sa.JSON(), nullable=False),
        sa.Column("sampling_policy", sa.JSON(), nullable=False),
        sa.Column("retention_policy", sa.JSON(), nullable=False),
        sa.Column("sensitivity", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("attribute", name=op.f("pk_observation_attribute_definitions")),
    )

    op.create_table(
        "observation_attribute_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("attribute", sa.String(length=50), nullable=False),
        sa.Column("sensitivity", sa.String(length=50), nullable=False),
        sa.Column("requires_consent", sa.Boolean(), nullable=False),
        sa.Column("allowed_source_types", sa.JSON(), nullable=False),
        sa.Column("allowed_spaces", sa.JSON(), nullable=True),
        sa.Column("raw_storage_allowed", sa.Boolean(), nullable=False),
        sa.Column("record_retention_days", sa.Integer(), nullable=False),
        sa.Column("normalized_only", sa.Boolean(), nullable=False),
        sa.Column("redaction_rule", sa.JSON(), nullable=True),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["attribute"],
            ["observation_attribute_definitions.attribute"],
            name="fk_observation_attribute_policies_attribute",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_observation_attribute_policies")),
        sa.UniqueConstraint(
            "attribute", "version", name="uq_observation_attribute_policies_version"
        ),
    )
    with op.batch_alter_table("observation_attribute_policies", schema=None) as batch_op:
        batch_op.create_index(
            "ix_observation_attribute_policies_attribute", ["attribute"], unique=False
        )

    op.create_table(
        "observation_consents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject_type", sa.String(length=50), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("attribute", sa.String(length=50), nullable=False),
        sa.Column("policy_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["attribute"],
            ["observation_attribute_definitions.attribute"],
            name="fk_observation_consents_attribute",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["observation_attribute_policies.id"],
            name="fk_observation_consents_policy_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_observation_consents")),
        sa.UniqueConstraint(
            "subject_type",
            "subject_id",
            "attribute",
            "policy_id",
            name="uq_observation_consents_subject_attribute_policy",
        ),
    )
    with op.batch_alter_table("observation_consents", schema=None) as batch_op:
        batch_op.create_index(
            "ix_observation_consents_subject", ["subject_type", "subject_id"], unique=False
        )
        batch_op.create_index(
            "ix_observation_consents_attribute_status", ["attribute", "status"], unique=False
        )

    op.create_table(
        "observations",
        sa.Column("observation_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.Column("subject_type", sa.String(length=50), nullable=True),
        sa.Column("subject_id", sa.String(length=255), nullable=True),
        sa.Column("space_id", sa.String(length=36), nullable=True),
        sa.Column("attribute", sa.String(length=50), nullable=False),
        sa.Column("raw_value", sa.JSON(), nullable=False),
        sa.Column("raw_unit", sa.String(length=50), nullable=True),
        sa.Column("normalized_value", sa.JSON(), nullable=True),
        sa.Column("normalized_unit", sa.String(length=50), nullable=True),
        sa.Column("value_type", sa.String(length=20), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at_source", sa.String(length=50), nullable=True),
        sa.Column("observed_at_uncertainty_ms", sa.Integer(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quality_status", sa.String(length=20), nullable=False),
        sa.Column("quality_issues", sa.JSON(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("freshness_policy", sa.String(length=50), nullable=True),
        sa.Column("freshness_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("normalization_rule_version", sa.String(length=50), nullable=True),
        sa.Column("retention_class", sa.String(length=50), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["observation_sources.id"],
            name="fk_observations_source_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entities.id"], name="fk_observations_entity_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["space_id"], ["spaces.id"], name="fk_observations_space_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["attribute"],
            ["observation_attribute_definitions.attribute"],
            name="fk_observations_attribute",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("observation_id", name=op.f("pk_observations")),
        sa.UniqueConstraint("dedupe_key", name="uq_observations_dedupe_key"),
        sa.CheckConstraint(
            "(entity_id IS NOT NULL AND subject_type IS NULL AND subject_id IS NULL) "
            "OR (entity_id IS NULL AND subject_type IS NOT NULL AND subject_id IS NOT NULL)",
            name="ck_observations_one_subject",
        ),
    )
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.create_index(
            "ix_observations_source_attribute_received",
            ["source_id", "attribute", "received_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_observations_entity_attribute_received",
            ["entity_id", "attribute", "received_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_observations_space_attribute_received",
            ["space_id", "attribute", "received_at"],
            unique=False,
        )
        batch_op.create_index("ix_observations_retention_until", ["retention_until"], unique=False)
        batch_op.create_index("ix_observations_correlation", ["correlation_id"], unique=False)
        batch_op.create_index(
            "ix_observations_external", ["source_id", "external_id"], unique=False
        )

    _seed_sources()
    _seed_attributes()


def downgrade() -> None:
    # ARS-02.1 spatial and entity structures are intentionally preserved.
    op.drop_table("observations")
    op.drop_table("observation_consents")
    op.drop_table("observation_attribute_policies")
    op.drop_table("observation_attribute_definitions")
    with op.batch_alter_table("observation_sources", schema=None) as batch_op:
        batch_op.drop_index("ix_observation_sources_adapter")
        batch_op.drop_index("ix_observation_sources_type_status")
    op.drop_table("observation_sources")
