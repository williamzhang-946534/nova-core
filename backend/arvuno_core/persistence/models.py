from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime


def utc_now() -> datetime:
    return datetime.now(UTC)


def uuid_string() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    adapter_id: Mapped[str] = mapped_column(String(100))
    external_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255))
    device_type: Mapped[str] = mapped_column(String(100))
    area: Mapped[str | None] = mapped_column(String(255))
    entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("entities.id", ondelete="RESTRICT"), unique=True
    )
    manufacturer: Mapped[str | None] = mapped_column(String(255))
    model: Mapped[str | None] = mapped_column(String(255))
    is_online: Mapped[bool]
    is_enabled: Mapped[bool]
    risk_level: Mapped[str] = mapped_column(String(50))
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON)
    metadata_summary: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        UniqueConstraint("adapter_id", "external_id", name="uq_devices_adapter_external"),
        Index("ix_devices_adapter_external", "adapter_id", "external_id"),
        Index("ix_devices_device_type", "device_type"),
        Index("ix_devices_area", "area"),
        Index("ix_devices_entity", "entity_id"),
    )

    states: Mapped[list["DeviceState"]] = relationship(
        back_populates="device", cascade="all, delete-orphan", passive_deletes=True
    )
    capability_records: Mapped[list["DeviceCapability"]] = relationship(
        back_populates="device", cascade="all, delete-orphan", passive_deletes=True
    )


class DeviceState(Base):
    __tablename__ = "device_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(100))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON)
    raw_state: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(100))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))

    __table_args__ = (
        Index("ix_device_states_device_observed", "device_id", "observed_at"),
        Index(
            "uq_device_states_current",
            "device_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
        ),
    )

    device: Mapped[Device] = relationship(back_populates="states")


class DeviceCapability(Base):
    __tablename__ = "device_capabilities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    capability: Mapped[str] = mapped_column(String(100))
    supported_actions: Mapped[list[str]] = mapped_column(JSON)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    risk_level: Mapped[str] = mapped_column(String(50))
    requires_confirmation: Mapped[bool]
    enabled: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        UniqueConstraint("device_id", "capability", name="uq_device_capabilities_capability"),
        Index("ix_device_capabilities_capability", "capability"),
    )

    device: Mapped[Device] = relationship(back_populates="capability_records")


class Environment(Base):
    __tablename__ = "environments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool]
    root_space_id: Mapped[str | None] = mapped_column(
        ForeignKey("spaces.id", ondelete="RESTRICT"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("ix_environments_name", "name"),
        Index("ix_environments_root_space", "root_space_id"),
    )

    root_space: Mapped["Space | None"] = relationship(back_populates="environments")

    snapshots: Mapped[list["EnvironmentSnapshot"]] = relationship(
        back_populates="environment", cascade="all, delete-orphan", passive_deletes=True
    )


class EnvironmentSnapshot(Base):
    __tablename__ = "environment_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    context: Mapped[dict[str, Any]] = mapped_column(JSON)
    active_task_ids: Mapped[list[str]] = mapped_column(JSON)
    anomaly_count: Mapped[int]
    context_version: Mapped[int] = mapped_column(default=1, server_default=text("1"))
    state_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("ix_environment_snapshots_environment_created", "environment_id", "created_at"),
    )

    environment: Mapped[Environment] = relationship(back_populates="snapshots")


class EstimationTarget(Base):
    __tablename__ = "estimation_targets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    target_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    space_id: Mapped[str | None] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"))
    attribute: Mapped[str] = mapped_column(
        ForeignKey("observation_attribute_definitions.attribute", ondelete="RESTRICT")
    )
    strategy_id: Mapped[str] = mapped_column(String(100))
    strategy_version: Mapped[str] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    validity_policy: Mapped[dict[str, Any]] = mapped_column(JSON)
    conflict_policy: Mapped[dict[str, Any]] = mapped_column(JSON)
    coverage_policy: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "(target_type = 'entity' AND entity_id IS NOT NULL AND space_id IS NULL) "
            "OR (target_type = 'space' AND entity_id IS NULL AND space_id IS NOT NULL) "
            "OR (target_type = 'environment' AND entity_id IS NULL AND space_id IS NULL)",
            name="ck_estimation_targets_scope",
        ),
        Index(
            "uq_estimation_targets_entity",
            "environment_id",
            "entity_id",
            "attribute",
            unique=True,
            sqlite_where=text("target_type = 'entity' AND entity_id IS NOT NULL"),
        ),
        Index(
            "uq_estimation_targets_space",
            "environment_id",
            "space_id",
            "attribute",
            unique=True,
            sqlite_where=text("target_type = 'space' AND space_id IS NOT NULL"),
        ),
        Index(
            "uq_estimation_targets_environment",
            "environment_id",
            "attribute",
            unique=True,
            sqlite_where=text("target_type = 'environment'"),
        ),
        Index("ix_estimation_targets_environment_type", "environment_id", "target_type"),
        Index("ix_estimation_targets_attribute", "attribute"),
    )


class StateEstimate(Base):
    __tablename__ = "state_estimates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    target_id: Mapped[str] = mapped_column(ForeignKey("estimation_targets.id", ondelete="CASCADE"))
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20))
    value: Mapped[Any | None] = mapped_column(JSON)
    unit: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence_summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    conflict_details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    rule_id: Mapped[str] = mapped_column(String(100))
    rule_version: Mapped[str] = mapped_column(String(50))
    input_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "status IN ('observed', 'derived', 'inferred', 'unknown', 'stale', "
            "'unavailable', 'conflict')",
            name="ck_state_estimates_status",
        ),
        Index("ix_state_estimates_target_generated", "target_id", "generated_at"),
        Index(
            "ix_state_estimates_environment_status_generated",
            "environment_id",
            "status",
            "generated_at",
        ),
    )

    target: Mapped[EstimationTarget] = relationship()
    evidence: Mapped[list["StateEstimateObservation"]] = relationship(
        back_populates="estimate", cascade="all, delete-orphan", passive_deletes=True
    )


class StateEstimateObservation(Base):
    __tablename__ = "state_estimate_observations"

    estimate_id: Mapped[str] = mapped_column(
        ForeignKey("state_estimates.id", ondelete="CASCADE"), primary_key=True
    )
    observation_id: Mapped[str] = mapped_column(
        ForeignKey("observations.observation_id", ondelete="CASCADE"), primary_key=True
    )
    contribution: Mapped[str] = mapped_column(String(30))
    weight: Mapped[float | None] = mapped_column(Float)
    exclusion_reason: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "contribution IN ('direct', 'candidate', 'context', 'negative_evidence')",
            name="ck_state_estimate_observations_contribution",
        ),
        Index("ix_state_estimate_observations_observation", "observation_id"),
    )

    estimate: Mapped[StateEstimate] = relationship(back_populates="evidence")


class CurrentStateEstimate(Base):
    __tablename__ = "current_state_estimates"

    target_id: Mapped[str] = mapped_column(
        ForeignKey("estimation_targets.id", ondelete="CASCADE"), primary_key=True
    )
    latest_estimate_id: Mapped[str] = mapped_column(
        ForeignKey("state_estimates.id", ondelete="CASCADE")
    )
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20))
    value: Mapped[Any | None] = mapped_column(JSON)
    unit: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[float | None] = mapped_column(Float)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    projection_version: Mapped[str] = mapped_column(Integer, default=1)

    __table_args__ = (
        CheckConstraint(
            "status IN ('observed', 'derived', 'inferred', 'unknown', 'stale', "
            "'unavailable', 'conflict')",
            name="ck_current_state_estimates_status",
        ),
        Index("ix_current_state_estimates_environment_status", "environment_id", "status"),
        Index("ix_current_state_estimates_valid_until", "valid_until"),
    )

    target: Mapped[EstimationTarget] = relationship()
    latest_estimate: Mapped[StateEstimate] = relationship()


class Space(Base):
    __tablename__ = "spaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("spaces.id", ondelete="RESTRICT"))
    space_type: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(1024))
    sort_order: Mapped[int]
    external_space_id: Mapped[str | None] = mapped_column(String(255))
    external_source: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50))
    geometry: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    metadata_summary: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("parent_id", "slug", name="uq_spaces_parent_slug"),
        Index("ix_spaces_parent", "parent_id"),
        Index("ix_spaces_path", "path"),
        Index("ix_spaces_type", "space_type"),
        Index("ix_spaces_status", "status"),
        Index("ix_spaces_external", "external_source", "external_space_id"),
    )

    environments: Mapped[list[Environment]] = relationship(back_populates="root_space")


class SpacePath(Base):
    __tablename__ = "space_paths"

    ancestor_id: Mapped[str] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True
    )
    descendant_id: Mapped[str] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True
    )
    depth: Mapped[int]
    path_version: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (Index("ix_space_paths_descendant", "descendant_id"),)


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id", ondelete="RESTRICT"))
    entity_type: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50))
    semantic_tags: Mapped[list[str]] = mapped_column(JSON)
    capabilities_ref: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    metadata_summary: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_entities_environment_type", "environment_id", "entity_type"),
        Index("ix_entities_normalized_name", "normalized_name"),
    )


class EntitySpaceAssignment(Base):
    __tablename__ = "entity_space_assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="RESTRICT"))
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="RESTRICT"))
    assignment_type: Mapped[str] = mapped_column(String(50))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float | None] = mapped_column(Float)
    source_type: Mapped[str] = mapped_column(String(50))
    source_id: Mapped[str | None] = mapped_column(String(255))
    source_observation_id: Mapped[str | None] = mapped_column(String(36))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        Index("ix_entity_space_assignments_entity_from", "entity_id", "valid_from"),
        Index("ix_entity_space_assignments_space_from", "space_id", "valid_from"),
        Index("ix_entity_space_assignments_type", "assignment_type"),
    )


class ObservationSource(Base):
    __tablename__ = "observation_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    source_type: Mapped[str] = mapped_column(String(50))
    adapter_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50))
    trust_level: Mapped[float] = mapped_column(Float)
    time_trust: Mapped[str] = mapped_column(String(50))
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    privacy_scope: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        Index("ix_observation_sources_type_status", "source_type", "status"),
        Index("ix_observation_sources_adapter", "adapter_id"),
    )


class ObservationIngestionBatch(Base):
    __tablename__ = "observation_ingestion_batches"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("observation_sources.id", ondelete="RESTRICT")
    )
    source_type: Mapped[str] = mapped_column(String(50))
    adapter_id: Mapped[str] = mapped_column(String(100))
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    total: Mapped[int] = mapped_column(Integer, default=0)
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    deduplicated: Mapped[int] = mapped_column(Integer, default=0)
    sampled: Mapped[int] = mapped_column(Integer, default=0)
    invalid: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_observation_ingestion_batches_status",
        ),
        Index("ix_observation_ingestion_batches_source_received", "source_id", "received_at"),
        Index("ix_observation_ingestion_batches_status_received", "status", "received_at"),
    )


class ObservationSourceHeartbeat(Base):
    __tablename__ = "observation_source_heartbeats"

    source_id: Mapped[str] = mapped_column(
        ForeignKey("observation_sources.id", ondelete="CASCADE"), primary_key=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_batch_id: Mapped[str | None] = mapped_column(String(100))
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('healthy', 'degraded', 'failed')",
            name="ck_observation_source_heartbeats_status",
        ),
    )


class ObservationAttributeDefinition(Base):
    __tablename__ = "observation_attribute_definitions"

    attribute: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    value_type: Mapped[str] = mapped_column(String(20))
    canonical_unit: Mapped[str | None] = mapped_column(String(50))
    normalization_rule_version: Mapped[str] = mapped_column(String(50))
    valid_range: Mapped[dict[str, Any]] = mapped_column(JSON)
    quality_policy: Mapped[dict[str, Any]] = mapped_column(JSON)
    freshness_policy: Mapped[dict[str, Any]] = mapped_column(JSON)
    sampling_policy: Mapped[dict[str, Any]] = mapped_column(JSON)
    retention_policy: Mapped[dict[str, Any]] = mapped_column(JSON)
    sensitivity: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ObservationAttributePolicy(Base):
    __tablename__ = "observation_attribute_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    attribute: Mapped[str] = mapped_column(
        ForeignKey("observation_attribute_definitions.attribute", ondelete="CASCADE")
    )
    sensitivity: Mapped[str] = mapped_column(String(50))
    requires_consent: Mapped[bool]
    allowed_source_types: Mapped[list[str]] = mapped_column(JSON)
    allowed_spaces: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw_storage_allowed: Mapped[bool]
    record_retention_days: Mapped[int]
    normalized_only: Mapped[bool]
    redaction_rule: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    version: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        UniqueConstraint("attribute", "version", name="uq_observation_attribute_policies_version"),
        Index("ix_observation_attribute_policies_attribute", "attribute"),
    )


class ObservationConsent(Base):
    __tablename__ = "observation_consents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    subject_type: Mapped[str] = mapped_column(String(50))
    subject_id: Mapped[str] = mapped_column(String(255))
    attribute: Mapped[str] = mapped_column(
        ForeignKey("observation_attribute_definitions.attribute", ondelete="CASCADE")
    )
    policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("observation_attribute_policies.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(50))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scope: Mapped[dict[str, Any]] = mapped_column(JSON)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        UniqueConstraint(
            "subject_type",
            "subject_id",
            "attribute",
            "policy_id",
            name="uq_observation_consents_subject_attribute_policy",
        ),
        Index("ix_observation_consents_subject", "subject_type", "subject_id"),
        Index("ix_observation_consents_attribute_status", "attribute", "status"),
    )


class Observation(Base):
    __tablename__ = "observations"

    observation_id: Mapped[str] = mapped_column(
        "observation_id", String(36), primary_key=True, default=uuid_string
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("observation_sources.id", ondelete="RESTRICT")
    )
    source_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="RESTRICT"))
    subject_type: Mapped[str | None] = mapped_column(String(50))
    subject_id: Mapped[str | None] = mapped_column(String(255))
    space_id: Mapped[str | None] = mapped_column(ForeignKey("spaces.id", ondelete="RESTRICT"))
    attribute: Mapped[str] = mapped_column(
        ForeignKey("observation_attribute_definitions.attribute", ondelete="RESTRICT")
    )
    raw_value: Mapped[Any] = mapped_column(JSON)
    raw_unit: Mapped[str | None] = mapped_column(String(50))
    normalized_value: Mapped[Any | None] = mapped_column(JSON)
    normalized_unit: Mapped[str | None] = mapped_column(String(50))
    value_type: Mapped[str] = mapped_column(String(20))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at_source: Mapped[str | None] = mapped_column(String(50))
    observed_at_uncertainty_ms: Mapped[int | None] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality_status: Mapped[str] = mapped_column(String(20))
    quality_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    freshness_policy: Mapped[str | None] = mapped_column(String(50))
    freshness_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    external_id: Mapped[str | None] = mapped_column(String(255))
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    normalization_rule_version: Mapped[str | None] = mapped_column(String(50))
    retention_class: Mapped[str] = mapped_column(String(50))
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "(entity_id IS NOT NULL AND subject_type IS NULL AND subject_id IS NULL) "
            "OR (entity_id IS NULL AND subject_type IS NOT NULL AND subject_id IS NOT NULL)",
            name="ck_observations_one_subject",
        ),
        CheckConstraint("received_at IS NOT NULL", name="ck_observations_received_at"),
        Index("ix_observations_source_attribute_received", "source_id", "attribute", "received_at"),
        Index("ix_observations_entity_attribute_received", "entity_id", "attribute", "received_at"),
        Index("ix_observations_space_attribute_received", "space_id", "attribute", "received_at"),
        Index("ix_observations_retention_until", "retention_until"),
        Index("ix_observations_correlation", "correlation_id"),
        Index("ix_observations_external", "source_id", "external_id"),
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    event_type: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(100))
    subject_type: Mapped[str | None] = mapped_column(String(100))
    subject_id: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("ix_events_type_occurred", "event_type", "occurred_at"),
        Index("ix_events_subject_occurred", "subject_type", "subject_id", "occurred_at"),
        Index("ix_events_correlation", "correlation_id"),
    )

    automation_runs: Mapped[list["AutomationRun"]] = relationship(back_populates="trigger_event")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )
    tasks: Mapped[list["Task"]] = relationship(back_populates="conversation")


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(Text)
    structured_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    provider_log_id: Mapped[str | None] = mapped_column(String(36))
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (Index("ix_conversation_messages_created", "conversation_id", "created_at"),)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    task_type: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50))
    origin: Mapped[str] = mapped_column(String(50))
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    plan: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_tasks_status_created", "status", "created_at"),
        Index("ix_tasks_conversation", "conversation_id"),
        Index("ix_tasks_correlation", "correlation_id"),
    )

    conversation: Mapped[Conversation | None] = relationship(back_populates="tasks")
    steps: Mapped[list["TaskStep"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    executions: Mapped[list["ToolExecution"]] = relationship(back_populates="task")


class TaskStep(Base):
    __tablename__ = "task_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    step_index: Mapped[int]
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50))
    input: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("task_id", "step_index", name="uq_task_steps_index"),
        Index("ix_task_steps_index", "task_id", "step_index"),
    )

    task: Mapped[Task] = relationship(back_populates="steps")
    executions: Mapped[list["ToolExecution"]] = relationship(back_populates="task_step")


class Tool(Base):
    __tablename__ = "tools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    name: Mapped[str] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100))
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    risk_level: Mapped[str] = mapped_column(String(50))
    default_permission: Mapped[str] = mapped_column(String(50))
    requires_confirmation: Mapped[bool]
    enabled: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (UniqueConstraint("name", name="uq_tools_name"),)

    executions: Mapped[list["ToolExecution"]] = relationship(back_populates="tool")


class ToolExecution(Base):
    __tablename__ = "tool_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.id"))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    task_step_id: Mapped[str | None] = mapped_column(ForeignKey("task_steps.id"))
    status: Mapped[str] = mapped_column(String(50))
    input: Mapped[dict[str, Any]] = mapped_column(JSON)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    risk_level: Mapped[str] = mapped_column(String(50))
    permission_result: Mapped[str] = mapped_column(String(100))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None]

    __table_args__ = (
        Index("ix_tool_executions_tool_started", "tool_id", "started_at"),
        Index("ix_tool_executions_task", "task_id"),
        Index("ix_tool_executions_correlation", "correlation_id"),
    )

    tool: Mapped[Tool] = relationship(back_populates="executions")
    task: Mapped[Task | None] = relationship(back_populates="executions")
    task_step: Mapped[TaskStep | None] = relationship(back_populates="executions")


class ProviderLog(Base):
    __tablename__ = "provider_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    provider: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(255))
    request_kind: Mapped[str] = mapped_column(String(50))
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(50))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    latency_ms: Mapped[int | None]
    prompt_tokens: Mapped[int | None]
    completion_tokens: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (Index("ix_provider_logs_created", "created_at"),)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    key: Mapped[str] = mapped_column(String(255))
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    category: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100))
    source_type: Mapped[str] = mapped_column(String(50), default="user")
    source_record_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    consent_id: Mapped[str | None] = mapped_column(
        ForeignKey("memory_consents.id", ondelete="SET NULL")
    )
    confirmed: Mapped[bool]
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        UniqueConstraint("key", name="uq_user_preferences_key"),
        CheckConstraint(
            "status IN ('draft', 'active', 'revoked')",
            name="ck_user_preferences_status",
        ),
        CheckConstraint(
            "(confirmed = 0 AND confirmed_at IS NULL) "
            "OR (confirmed = 1 AND confirmed_at IS NOT NULL)",
            name="ck_user_preferences_confirmation",
        ),
        CheckConstraint(
            "source_type = 'user' AND source_record_id IS NOT NULL",
            name="ck_user_preferences_user_source",
        ),
        Index("ix_user_preferences_status_key", "status", "key"),
    )


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    memory_type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(JSON)
    importance: Mapped[int]
    source_type: Mapped[str] = mapped_column(String(100))
    source_id: Mapped[str | None] = mapped_column(String(255))
    user_confirmed: Mapped[bool]
    status: Mapped[str] = mapped_column(String(30), default="active")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified")
    owner_id: Mapped[str] = mapped_column(String(100), default="local_user")
    access_level: Mapped[str] = mapped_column(String(30), default="owner_only")
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    environment_id: Mapped[str | None] = mapped_column(
        ForeignKey("environments.id", ondelete="SET NULL")
    )
    space_id: Mapped[str | None] = mapped_column(ForeignKey("spaces.id", ondelete="SET NULL"))
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"))
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    subject_type: Mapped[str | None] = mapped_column(String(100))
    subject_id: Mapped[str | None] = mapped_column(String(255))
    predicate: Mapped[str | None] = mapped_column(String(255))
    object_value: Mapped[Any | None] = mapped_column(JSON)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL")
    )
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correction_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "memory_type IN ('episodic', 'semantic', 'procedural')",
            name="ck_memories_type",
        ),
        CheckConstraint(
            "status IN ('active', 'candidate', 'corrected', 'superseded', 'expired', 'archived')",
            name="ck_memories_status",
        ),
        CheckConstraint(
            "verification_status IN ('unverified', 'verified', 'rejected')",
            name="ck_memories_verification",
        ),
        CheckConstraint("importance BETWEEN 1 AND 5", name="ck_memories_importance"),
        CheckConstraint(
            "source_type != 'ai_inference' OR (status = 'candidate' AND user_confirmed = 0 "
            "AND verification_status = 'unverified' AND expires_at IS NOT NULL)",
            name="ck_memories_ai_inference_candidate",
        ),
        CheckConstraint(
            "memory_type != 'procedural' OR subject_id IS NOT NULL",
            name="ck_memories_procedure_subject",
        ),
        Index("ix_memories_type_created", "memory_type", "created_at"),
        Index("ix_memories_source", "source_type", "source_id"),
        Index("ix_memories_status_type", "status", "memory_type"),
        Index("ix_memories_scope", "environment_id", "space_id", "entity_id"),
        Index("ix_memories_subject_predicate", "subject_type", "subject_id", "predicate"),
        Index("ix_memories_valid_until", "expires_at"),
        Index("ix_memories_retention", "retention_until"),
    )

    evidence: Mapped[list["MemoryEvidence"]] = relationship(
        back_populates="memory",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    revisions: Mapped[list["MemoryRevision"]] = relationship(
        back_populates="memory",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MemoryEvidence(Base):
    __tablename__ = "memory_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"),
    )
    evidence_type: Mapped[str] = mapped_column(String(50))
    evidence_id: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(100))
    source_record_id: Mapped[str | None] = mapped_column(String(255))
    trust_level: Mapped[float] = mapped_column(Float, default=0.5)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "evidence_type IN ('observation', 'event', 'task', 'conversation', "
            "'procedure_execution', 'user_statement', 'environment_snapshot')",
            name="ck_memory_evidence_type",
        ),
        CheckConstraint(
            "evidence_type IN ('user_statement', 'ai_inference') OR evidence_id IS NOT NULL",
            name="ck_memory_evidence_record",
        ),
        UniqueConstraint(
            "memory_id",
            "evidence_type",
            "evidence_id",
            name="uq_memory_evidence_record",
        ),
        Index("ix_memory_evidence_memory", "memory_id"),
        Index("ix_memory_evidence_record", "evidence_type", "evidence_id"),
    )

    memory: Mapped[Memory] = relationship(back_populates="evidence")


class MemoryRevision(Base):
    __tablename__ = "memory_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"),
    )
    revision_type: Mapped[str] = mapped_column(String(30))
    previous_content: Mapped[str] = mapped_column(Text)
    previous_summary: Mapped[str | None] = mapped_column(Text)
    changed_fields: Mapped[dict[str, Any]] = mapped_column(JSON)
    actor_type: Mapped[str] = mapped_column(String(50), default="user")
    actor_id: Mapped[str] = mapped_column(String(100), default="local_user")
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "revision_type IN ('create', 'update', 'correct', 'confirm', "
            "'expire', 'archive', 'validate')",
            name="ck_memory_revisions_type",
        ),
        Index("ix_memory_revisions_memory_created", "memory_id", "created_at"),
    )

    memory: Mapped[Memory] = relationship(back_populates="revisions")


class MemoryConsent(Base):
    __tablename__ = "memory_consents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    subject_id: Mapped[str] = mapped_column(String(100), default="local_user")
    grant_type: Mapped[str] = mapped_column(String(50))
    statement: Mapped[str] = mapped_column(Text)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actor_type: Mapped[str] = mapped_column(String(50), default="user")

    __table_args__ = (
        CheckConstraint(
            "grant_type IN ('memory_store', 'preference_store', 'retrieval')",
            name="ck_memory_consents_grant_type",
        ),
        Index("ix_memory_consents_subject", "subject_id", "grant_type", "granted_at"),
    )


class MemoryProcedureVersion(Base):
    __tablename__ = "memory_procedure_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"),
    )
    version: Mapped[str] = mapped_column(String(50))
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    risk_level: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default="testing")
    required_successes: Mapped[int] = mapped_column(Integer, default=3)
    successful_validations: Mapped[int] = mapped_column(Integer, default=0)
    failed_validations: Mapped[int] = mapped_column(Integer, default=0)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        UniqueConstraint("memory_id", "version", name="uq_memory_procedure_versions_version"),
        CheckConstraint(
            "status IN ('testing', 'validated', 'retired')",
            name="ck_memory_procedure_versions_status",
        ),
        CheckConstraint("required_successes > 0", name="ck_memory_procedure_versions_required"),
        Index("ix_memory_procedure_versions_memory_status", "memory_id", "status"),
    )

    memory: Mapped[Memory] = relationship()


class MemoryProcedureValidation(Base):
    __tablename__ = "memory_procedure_validations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    procedure_version_id: Mapped[str] = mapped_column(
        ForeignKey("memory_procedure_versions.id", ondelete="CASCADE"),
    )
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    tool_execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("tool_executions.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(30))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    validator_type: Mapped[str] = mapped_column(String(50), default="user")
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "status IN ('passed', 'failed')",
            name="ck_memory_procedure_validations_status",
        ),
        Index("ix_memory_procedure_validations_version", "procedure_version_id", "validated_at"),
    )


class MemoryAccessLog(Base):
    __tablename__ = "memory_access_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    memory_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"),
    )
    preference_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_preferences.id", ondelete="SET NULL"),
    )
    access_type: Mapped[str] = mapped_column(String(30))
    actor_type: Mapped[str] = mapped_column(String(50), default="user")
    actor_id: Mapped[str] = mapped_column(String(100), default="local_user")
    authorized: Mapped[bool] = mapped_column(Boolean, default=True)
    query: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "access_type IN ('create', 'read', 'retrieve', 'update', 'confirm', "
            "'correct', 'delete', 'expire')",
            name="ck_memory_access_logs_type",
        ),
        CheckConstraint(
            "memory_id IS NOT NULL OR preference_id IS NOT NULL",
            name="ck_memory_access_logs_target",
        ),
        Index("ix_memory_access_logs_memory", "memory_id", "accessed_at"),
        Index("ix_memory_access_logs_preference", "preference_id", "accessed_at"),
    )


class ReasoningSession(Base):
    __tablename__ = "reasoning_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    trigger: Mapped[str] = mapped_column(String(50), default="user")
    status: Mapped[str] = mapped_column(String(20), default="running")
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    diagnosis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    analyzer_versions: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    actor_type: Mapped[str] = mapped_column(String(50), default="user")
    actor_id: Mapped[str] = mapped_column(String(100), default="local_user")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_reasoning_sessions_status",
        ),
        CheckConstraint(
            "trigger IN ('user', 'system', 'automation')",
            name="ck_reasoning_sessions_trigger",
        ),
        Index("ix_reasoning_sessions_environment_created", "environment_id", "created_at"),
        Index("ix_reasoning_sessions_status_created", "status", "created_at"),
    )

    evidence_bundles: Mapped[list["EvidenceBundle"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )
    hypotheses: Mapped[list["Hypothesis"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )


class EvidenceBundle(Base):
    __tablename__ = "evidence_bundles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(ForeignKey("reasoning_sessions.id", ondelete="CASCADE"))
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    selection_basis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    coverage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("ix_evidence_bundles_session", "session_id"),
        Index("ix_evidence_bundles_environment", "environment_id"),
    )

    session: Mapped[ReasoningSession] = relationship(back_populates="evidence_bundles")
    items: Mapped[list["EvidenceItem"]] = relationship(
        back_populates="bundle", cascade="all, delete-orphan", passive_deletes=True
    )


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    bundle_id: Mapped[str] = mapped_column(ForeignKey("evidence_bundles.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(50))
    source_record_id: Mapped[str] = mapped_column(String(255))
    classification: Mapped[str] = mapped_column(String(30))
    statement: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality_status: Mapped[str] = mapped_column(String(30), default="valid")
    quality_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    trust_level: Mapped[float] = mapped_column(Float, default=0.5)
    source_available: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "source_type IN ('observation', 'state_estimate', 'event', 'task', 'memory')",
            name="ck_evidence_items_source_type",
        ),
        CheckConstraint(
            "classification IN ('observed', 'derived', 'inferred_candidate', "
            "'verified_cause', 'unknown')",
            name="ck_evidence_items_classification",
        ),
        CheckConstraint(
            "quality_status IN ('valid', 'suspect', 'invalid', 'unavailable')",
            name="ck_evidence_items_quality",
        ),
        CheckConstraint("trust_level BETWEEN 0 AND 1", name="ck_evidence_items_trust"),
        UniqueConstraint(
            "bundle_id", "source_type", "source_record_id", name="uq_evidence_items_source"
        ),
        Index("ix_evidence_items_bundle_class", "bundle_id", "classification"),
        Index("ix_evidence_items_source", "source_type", "source_record_id"),
    )

    bundle: Mapped[EvidenceBundle] = relationship(back_populates="items")
    hypothesis_links: Mapped[list["HypothesisEvidence"]] = relationship(
        back_populates="evidence", cascade="all, delete-orphan", passive_deletes=True
    )


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(ForeignKey("reasoning_sessions.id", ondelete="CASCADE"))
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    statement: Mapped[str] = mapped_column(Text)
    hypothesis_type: Mapped[str] = mapped_column(String(50))
    origin_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="unsupported")
    confidence_level: Mapped[str] = mapped_column(String(20), default="unknown")
    causal_claim: Mapped[bool] = mapped_column(Boolean, default=False)
    explanation: Mapped[str] = mapped_column(Text)
    limitations: Mapped[list[str]] = mapped_column(JSON, default=list)
    unknowns: Mapped[list[str]] = mapped_column(JSON, default=list)
    rule_id: Mapped[str | None] = mapped_column(String(100))
    rule_version: Mapped[str | None] = mapped_column(String(50))
    superseded_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("hypotheses.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "hypothesis_type IN ('deterministic_rule', 'correlation', 'ai_candidate', "
            "'verified_cause', 'data_quality', 'unknown')",
            name="ck_hypotheses_type",
        ),
        CheckConstraint(
            "origin_type IN ('rule', 'model', 'user', 'system')",
            name="ck_hypotheses_origin",
        ),
        CheckConstraint(
            "status IN ('unsupported', 'plausible', 'supported', 'conflicted', "
            "'refuted', 'expired', 'superseded')",
            name="ck_hypotheses_status",
        ),
        CheckConstraint(
            "confidence_level IN ('unknown', 'low', 'medium', 'high')",
            name="ck_hypotheses_confidence",
        ),
        CheckConstraint(
            "origin_type != 'model' OR (status IN ('unsupported', 'plausible') "
            "AND causal_claim = 0)",
            name="ck_hypotheses_model_candidate",
        ),
        Index("ix_hypotheses_session_type", "session_id", "hypothesis_type"),
        Index("ix_hypotheses_environment_status", "environment_id", "status"),
    )

    session: Mapped[ReasoningSession] = relationship(back_populates="hypotheses")
    evidence_links: Mapped[list["HypothesisEvidence"]] = relationship(
        back_populates="parent_hypothesis", cascade="all, delete-orphan", passive_deletes=True
    )


class HypothesisEvidence(Base):
    __tablename__ = "hypothesis_evidence"

    parent_hypothesis: Mapped[Hypothesis] = relationship(back_populates="evidence_links")
    evidence: Mapped[EvidenceItem] = relationship(back_populates="hypothesis_links")

    hypothesis_id: Mapped[str] = mapped_column(
        ForeignKey("hypotheses.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_items.id", ondelete="CASCADE"), primary_key=True
    )
    relationship: Mapped[str] = mapped_column(String(30))
    weight: Mapped[float] = mapped_column(Float, default=0.5)
    rationale: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "relationship IN ('supports', 'contradicts', 'context')",
            name="ck_hypothesis_evidence_relationship",
        ),
        CheckConstraint("weight BETWEEN 0 AND 1", name="ck_hypothesis_evidence_weight"),
        Index("ix_hypothesis_evidence_evidence", "evidence_id"),
    )


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    objective: Mapped[str] = mapped_column(Text)
    origin_type: Mapped[str] = mapped_column(String(30), default="user")
    origin_record_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    goal_type: Mapped[str] = mapped_column(String(30), default="other")
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    desired_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prohibitions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    clarifications: Mapped[list[str]] = mapped_column(JSON, default=list)
    unknowns: Mapped[list[str]] = mapped_column(JSON, default=list)
    success_conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    failure_conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    authorization_scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    time_window: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reasoning_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("reasoning_sessions.id", ondelete="SET NULL")
    )
    parent_goal_id: Mapped[str | None] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"))
    confirmed_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "origin_type IN ('user', 'model', 'automation', 'system')",
            name="ck_goals_origin",
        ),
        CheckConstraint(
            "status IN ('candidate', 'active', 'paused', 'completed', 'failed', "
            "'cancelled', 'expired')",
            name="ck_goals_status",
        ),
        CheckConstraint(
            "goal_type IN ('comfort', 'energy', 'device_state', 'routine', "
            "'diagnosis', 'safety_check', 'other')",
            name="ck_goals_type",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'critical')",
            name="ck_goals_priority",
        ),
        Index("ix_goals_environment_status", "environment_id", "status"),
        Index("ix_goals_origin", "origin_type", "origin_record_id"),
    )

    environment: Mapped[Environment] = relationship()
    revisions: Mapped[list["GoalRevision"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan", passive_deletes=True
    )
    plans: Mapped[list["Plan"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan", passive_deletes=True
    )


class GoalRevision(Base):
    __tablename__ = "goal_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"))
    revision: Mapped[int]
    change_type: Mapped[str] = mapped_column(String(30))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(50))
    source_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        UniqueConstraint("goal_id", "revision", name="uq_goal_revisions_goal_revision"),
        CheckConstraint(
            "change_type IN ('create', 'clarify', 'rescope', 'confirm', 'pause', "
            "'resume', 'close')",
            name="ck_goal_revisions_change_type",
        ),
        Index("ix_goal_revisions_goal", "goal_id", "revision"),
    )

    goal: Mapped[Goal] = relationship(back_populates="revisions")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"))
    reasoning_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("reasoning_sessions.id", ondelete="SET NULL")
    )
    version: Mapped[int]
    status: Mapped[str] = mapped_column(String(30), default="draft")
    planner_type: Mapped[str] = mapped_column(String(20), default="rule")
    run_mode: Mapped[str] = mapped_column(String(30), default="awaiting_confirmation")
    strategy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    max_risk_level: Mapped[str] = mapped_column(String(20), default="read_only")
    estimated_duration: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    resource_requirements: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    success_criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    failure_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    submitted_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL")
    )
    superseded_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("plans.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("goal_id", "version", name="uq_plans_goal_version"),
        CheckConstraint(
            "status IN ('draft', 'validated', 'awaiting_confirmation', 'approved', "
            "'submitted', 'superseded', 'cancelled', 'rejected')",
            name="ck_plans_status",
        ),
        CheckConstraint(
            "planner_type IN ('rule', 'model', 'hybrid', 'template', 'user')",
            name="ck_plans_planner_type",
        ),
        CheckConstraint(
            "run_mode IN ('analyze_only', 'suggest_only', 'awaiting_confirmation', "
            "'confirm_then_execute', 'limited_auto_execute')",
            name="ck_plans_run_mode",
        ),
        CheckConstraint(
            "max_risk_level IN ('read_only', 'low_risk', 'medium_risk', 'high_risk')",
            name="ck_plans_max_risk",
        ),
        Index("ix_plans_goal_version", "goal_id", "version"),
        Index("ix_plans_environment_status", "environment_id", "status"),
        Index("ix_plans_submitted_task", "submitted_task_id"),
    )

    goal: Mapped[Goal] = relationship(back_populates="plans")
    steps: Mapped[list["PlanStep"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", passive_deletes=True
    )
    replanning_records: Mapped[list["PlanReplanningRecord"]] = relationship(
        back_populates="old_plan",
        foreign_keys="PlanReplanningRecord.old_plan_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PlanStep(Base):
    __tablename__ = "plan_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    step_index: Mapped[int]
    name: Mapped[str] = mapped_column(String(255))
    purpose: Mapped[str] = mapped_column(Text)
    tool_name: Mapped[str] = mapped_column(String(255))
    tool_version: Mapped[str | None] = mapped_column(String(50))
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    preconditions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    expected_effect: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    postconditions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verification: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_level: Mapped[str] = mapped_column(String(20))
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    retry_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    on_failure: Mapped[str] = mapped_column(String(40), default="stop")
    depends_on: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        UniqueConstraint("plan_id", "step_index", name="uq_plan_steps_plan_index"),
        CheckConstraint(
            "risk_level IN ('read_only', 'low_risk', 'medium_risk', 'high_risk')",
            name="ck_plan_steps_risk",
        ),
        CheckConstraint(
            "on_failure IN ('stop', 'request_user_confirmation', 'request_replan')",
            name="ck_plan_steps_on_failure",
        ),
        Index("ix_plan_steps_plan", "plan_id", "step_index"),
        Index("ix_plan_steps_tool", "tool_name"),
    )

    plan: Mapped[Plan] = relationship(back_populates="steps")


class PlanReplanningRecord(Base):
    __tablename__ = "plan_replanning_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    old_plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    new_plan_id: Mapped[str | None] = mapped_column(ForeignKey("plans.id", ondelete="SET NULL"))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    trigger_type: Mapped[str] = mapped_column(String(50))
    trigger_record_type: Mapped[str | None] = mapped_column(String(50))
    trigger_record_id: Mapped[str | None] = mapped_column(String(255))
    change_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_delta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    already_executed_steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    reversible_steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    decision: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('precondition_failed', 'tool_failed', 'verification_failed', "
            "'goal_changed', 'environment_changed', 'user_cancelled', "
            "'priority_preempted', 'timeout')",
            name="ck_plan_replanning_trigger",
        ),
        CheckConstraint(
            "decision IN ('replan', 'stop', 'wait_user_confirmation', 'reject')",
            name="ck_plan_replanning_decision",
        ),
        Index("ix_plan_replanning_old_plan", "old_plan_id", "created_at"),
        Index("ix_plan_replanning_task", "task_id"),
    )

    old_plan: Mapped[Plan] = relationship(
        back_populates="replanning_records",
        foreign_keys=[old_plan_id],
    )


class ProactiveSuggestion(Base):
    __tablename__ = "proactive_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    reasoning_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("reasoning_sessions.id", ondelete="SET NULL")
    )
    hypothesis_id: Mapped[str | None] = mapped_column(
        ForeignKey("hypotheses.id", ondelete="SET NULL")
    )
    goal_id: Mapped[str | None] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"))
    trigger_type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    importance: Mapped[str] = mapped_column(String(20), default="normal")
    autonomy_level: Mapped[int] = mapped_column(Integer, default=1)
    candidate_action: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    dedupe_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="evaluated")
    suppression_count: Mapped[int] = mapped_column(Integer, default=0)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_feedback: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('trend', 'anomaly', 'goal_deviation', 'task_failure', "
            "'coverage_gap', 'device_fault', 'cost_risk')",
            name="ck_proactive_suggestions_trigger_type",
        ),
        CheckConstraint(
            "importance IN ('low', 'normal', 'high')",
            name="ck_proactive_suggestions_importance",
        ),
        CheckConstraint(
            "autonomy_level BETWEEN 0 AND 4",
            name="ck_proactive_suggestions_autonomy_level",
        ),
        CheckConstraint(
            "status IN ('evaluated', 'suppressed', 'queued', 'delivered', 'opened', "
            "'accepted', 'dismissed', 'expired')",
            name="ck_proactive_suggestions_status",
        ),
        Index(
            "ix_proactive_suggestions_environment_dedupe",
            "environment_id",
            "dedupe_key",
        ),
        Index("ix_proactive_suggestions_status", "status"),
        Index("ix_proactive_suggestions_cooldown", "cooldown_until"),
        Index("ix_proactive_suggestions_delivered", "delivered_at"),
    )

    environment: Mapped[Environment] = relationship()
    reasoning_session: Mapped[ReasoningSession | None] = relationship()
    hypothesis: Mapped[Hypothesis | None] = relationship()
    goal: Mapped[Goal | None] = relationship()


class ActivePerceptionRequest(Base):
    __tablename__ = "active_perception_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    reasoning_session_id: Mapped[str] = mapped_column(
        ForeignKey("reasoning_sessions.id", ondelete="CASCADE")
    )
    hypothesis_id: Mapped[str | None] = mapped_column(
        ForeignKey("hypotheses.id", ondelete="SET NULL")
    )
    question: Mapped[str] = mapped_column(Text)
    gap_type: Mapped[str] = mapped_column(String(50))
    subject_type: Mapped[str] = mapped_column(String(50))
    subject_id: Mapped[str] = mapped_column(String(255))
    space_id: Mapped[str | None] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"))
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    attribute: Mapped[str | None] = mapped_column(String(50))
    needed_time_range: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    current_coverage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    expected_value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    would_resolve: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    proposed_capability: Mapped[str | None] = mapped_column(String(100))
    proposed_input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    privacy_level: Mapped[str] = mapped_column(String(20), default="normal")
    requires_user_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authorization_scope: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    cost_estimate: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="proposed")
    fulfilled_by_type: Mapped[str | None] = mapped_column(String(50))
    fulfilled_by_id: Mapped[str | None] = mapped_column(String(255))
    follow_up_reasoning_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("reasoning_sessions.id", ondelete="SET NULL")
    )
    unavailable_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "gap_type IN ('space_coverage', 'time_coverage', 'quality', "
            "'entity_identity', 'post_action_verification', 'procedure')",
            name="ck_active_perception_gap_type",
        ),
        CheckConstraint(
            "subject_type IN ('space', 'entity')",
            name="ck_active_perception_subject_type",
        ),
        CheckConstraint(
            "privacy_level IN ('normal', 'sensitive')",
            name="ck_active_perception_privacy",
        ),
        CheckConstraint(
            "privacy_level != 'sensitive' OR requires_user_consent = 1",
            name="ck_active_perception_sensitive_consent",
        ),
        CheckConstraint(
            "status IN ('proposed', 'awaiting_consent', 'rejected', 'queued', "
            "'executed', 'fulfilled', 'unavailable', 'expired')",
            name="ck_active_perception_status",
        ),
        CheckConstraint(
            "status != 'fulfilled' OR (fulfilled_by_type IS NOT NULL "
            "AND fulfilled_by_id IS NOT NULL)",
            name="ck_active_perception_fulfilled_source",
        ),
        Index(
            "ix_active_perception_environment_status",
            "environment_id",
            "status",
        ),
        Index(
            "ix_active_perception_subject",
            "subject_type",
            "subject_id",
            "attribute",
        ),
        Index("ix_active_perception_expires", "expires_at"),
    )

    environment: Mapped[Environment] = relationship()
    reasoning_session: Mapped[ReasoningSession] = relationship(foreign_keys=[reasoning_session_id])
    follow_up_reasoning_session: Mapped[ReasoningSession | None] = relationship(
        foreign_keys=[follow_up_reasoning_session_id]
    )
    hypothesis: Mapped[Hypothesis | None] = relationship()


class Automation(Base):
    __tablename__ = "automations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool]
    trigger: Mapped[dict[str, Any]] = mapped_column(JSON)
    condition: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    action: Mapped[dict[str, Any]] = mapped_column(JSON)
    cooldown_seconds: Mapped[int]
    risk_level: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    runs: Mapped[list["AutomationRun"]] = relationship(
        back_populates="automation", cascade="all, delete-orphan", passive_deletes=True
    )


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    automation_id: Mapped[str] = mapped_column(ForeignKey("automations.id", ondelete="CASCADE"))
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"))
    status: Mapped[str] = mapped_column(String(50))
    matched_context: Mapped[dict[str, Any]] = mapped_column(JSON)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_automation_runs_started", "automation_id", "started_at"),)

    automation: Mapped[Automation] = relationship(back_populates="runs")
    trigger_event: Mapped[Event | None] = relationship(back_populates="automation_runs")
    task: Mapped[Task | None] = relationship()


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    key: Mapped[str] = mapped_column(String(255))
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    value_type: Mapped[str] = mapped_column(String(50))
    is_secret: Mapped[bool]
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (UniqueConstraint("key", name="uq_system_settings_key"),)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    channel: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50))
    related_event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"))
    related_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_notifications_created", "created_at"),
        Index("ix_notifications_related_task", "related_task_id"),
    )

    related_event: Mapped[Event | None] = relationship()
    related_task: Mapped[Task | None] = relationship()
