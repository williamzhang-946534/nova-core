from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from arvuno_core.config import Settings
from arvuno_core.persistence import database as database_module
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.exceptions import DatabaseConnectionError, MigrationError

EXPECTED_TABLES = {
    "automation_runs",
    "automations",
    "conversation_messages",
    "conversations",
    "device_capabilities",
    "device_states",
    "devices",
    "entities",
    "entity_space_assignments",
    "current_state_estimates",
    "environment_snapshots",
    "environments",
    "events",
    "memory_access_logs",
    "memory_consents",
    "memory_evidence",
    "memories",
    "memory_procedure_validations",
    "memory_procedure_versions",
    "memory_revisions",
    "notifications",
    "observation_attribute_definitions",
    "observation_attribute_policies",
    "observation_consents",
    "observation_ingestion_batches",
    "observation_sources",
    "observation_source_heartbeats",
    "observations",
    "provider_logs",
    "space_paths",
    "spaces",
    "state_estimate_observations",
    "state_estimates",
    "estimation_targets",
    "system_settings",
    "task_steps",
    "tasks",
    "tool_executions",
    "tools",
    "user_preferences",
}

EXPECTED_COLUMNS = {
    "automation_runs": {
        "id",
        "automation_id",
        "event_id",
        "status",
        "matched_context",
        "task_id",
        "error",
        "started_at",
        "completed_at",
    },
    "automations": {
        "id",
        "name",
        "description",
        "enabled",
        "trigger",
        "condition",
        "action",
        "cooldown_seconds",
        "risk_level",
        "created_at",
        "updated_at",
    },
    "conversation_messages": {
        "id",
        "conversation_id",
        "role",
        "content",
        "structured_data",
        "provider_log_id",
        "correlation_id",
        "created_at",
    },
    "conversations": {"id", "title", "status", "created_at", "updated_at"},
    "device_capabilities": {
        "id",
        "device_id",
        "capability",
        "supported_actions",
        "parameters",
        "risk_level",
        "requires_confirmation",
        "enabled",
        "created_at",
    },
    "device_states": {
        "id",
        "device_id",
        "state",
        "attributes",
        "raw_state",
        "source",
        "observed_at",
        "created_at",
        "is_current",
    },
    "devices": {
        "id",
        "adapter_id",
        "external_id",
        "name",
        "normalized_name",
        "device_type",
        "area",
        "entity_id",
        "manufacturer",
        "model",
        "is_online",
        "is_enabled",
        "risk_level",
        "capabilities",
        "metadata",
        "last_seen_at",
        "created_at",
        "updated_at",
    },
    "entities": {
        "id",
        "environment_id",
        "entity_type",
        "name",
        "normalized_name",
        "description",
        "status",
        "semantic_tags",
        "capabilities_ref",
        "metadata",
        "created_at",
        "updated_at",
        "retired_at",
    },
    "entity_space_assignments": {
        "id",
        "entity_id",
        "space_id",
        "assignment_type",
        "valid_from",
        "valid_until",
        "confidence",
        "source_type",
        "source_id",
        "source_observation_id",
        "reason",
        "created_at",
        "updated_at",
    },
    "environment_snapshots": {
        "id",
        "environment_id",
        "context",
        "active_task_ids",
        "anomaly_count",
        "context_version",
        "state_generated_at",
        "created_at",
    },
    "estimation_targets": {
        "id",
        "environment_id",
        "target_type",
        "entity_id",
        "space_id",
        "attribute",
        "strategy_id",
        "strategy_version",
        "enabled",
        "validity_policy",
        "conflict_policy",
        "coverage_policy",
        "created_at",
        "updated_at",
    },
    "environments": {
        "id",
        "name",
        "description",
        "is_default",
        "root_space_id",
        "created_at",
    },
    "events": {
        "id",
        "event_type",
        "source",
        "subject_type",
        "subject_id",
        "payload",
        "correlation_id",
        "occurred_at",
        "created_at",
    },
    "state_estimates": {
        "id",
        "target_id",
        "environment_id",
        "status",
        "value",
        "unit",
        "confidence",
        "evidence_summary",
        "conflict_details",
        "rule_id",
        "rule_version",
        "input_cutoff_at",
        "effective_from",
        "generated_at",
        "valid_until",
        "superseded_at",
        "created_at",
    },
    "state_estimate_observations": {
        "estimate_id",
        "observation_id",
        "contribution",
        "weight",
        "exclusion_reason",
        "created_at",
    },
    "current_state_estimates": {
        "target_id",
        "latest_estimate_id",
        "environment_id",
        "status",
        "value",
        "unit",
        "confidence",
        "valid_until",
        "refreshed_at",
        "projection_version",
    },
    "memories": {
        "id",
        "memory_type",
        "title",
        "content",
        "summary",
        "keywords",
        "importance",
        "source_type",
        "source_id",
        "user_confirmed",
        "status",
        "confidence",
        "verification_status",
        "owner_id",
        "access_level",
        "scope",
        "environment_id",
        "space_id",
        "entity_id",
        "conversation_id",
        "task_id",
        "subject_type",
        "subject_id",
        "predicate",
        "object_value",
        "valid_from",
        "retention_until",
        "superseded_by_id",
        "last_reviewed_at",
        "correction_count",
        "expires_at",
        "created_at",
        "updated_at",
    },
    "memory_access_logs": {
        "id",
        "memory_id",
        "preference_id",
        "access_type",
        "actor_type",
        "actor_id",
        "authorized",
        "query",
        "accessed_at",
    },
    "memory_consents": {
        "id",
        "subject_id",
        "grant_type",
        "statement",
        "scope",
        "granted_at",
        "revoked_at",
        "expires_at",
        "actor_type",
    },
    "memory_evidence": {
        "id",
        "memory_id",
        "evidence_type",
        "evidence_id",
        "source_type",
        "source_record_id",
        "trust_level",
        "snapshot",
        "occurred_at",
        "created_at",
    },
    "memory_procedure_validations": {
        "id",
        "procedure_version_id",
        "task_id",
        "tool_execution_id",
        "status",
        "result",
        "validator_type",
        "validated_at",
    },
    "memory_procedure_versions": {
        "id",
        "memory_id",
        "version",
        "steps",
        "input_schema",
        "output_schema",
        "risk_level",
        "status",
        "required_successes",
        "successful_validations",
        "failed_validations",
        "validated_at",
        "retired_at",
        "created_at",
        "updated_at",
    },
    "memory_revisions": {
        "id",
        "memory_id",
        "revision_type",
        "previous_content",
        "previous_summary",
        "changed_fields",
        "actor_type",
        "actor_id",
        "reason",
        "created_at",
    },
    "notifications": {
        "id",
        "channel",
        "title",
        "content",
        "level",
        "status",
        "related_event_id",
        "related_task_id",
        "created_at",
        "sent_at",
    },
    "observation_attribute_definitions": {
        "attribute",
        "display_name",
        "value_type",
        "canonical_unit",
        "normalization_rule_version",
        "valid_range",
        "quality_policy",
        "freshness_policy",
        "sampling_policy",
        "retention_policy",
        "sensitivity",
        "created_at",
        "updated_at",
    },
    "observation_attribute_policies": {
        "id",
        "attribute",
        "sensitivity",
        "requires_consent",
        "allowed_source_types",
        "allowed_spaces",
        "raw_storage_allowed",
        "record_retention_days",
        "normalized_only",
        "redaction_rule",
        "version",
        "created_at",
        "updated_at",
    },
    "observation_consents": {
        "id",
        "subject_type",
        "subject_id",
        "attribute",
        "policy_id",
        "status",
        "granted_at",
        "revoked_at",
        "expires_at",
        "scope",
        "evidence",
        "created_at",
        "updated_at",
    },
    "observation_sources": {
        "id",
        "source_type",
        "adapter_id",
        "name",
        "status",
        "trust_level",
        "time_trust",
        "config",
        "privacy_scope",
        "created_at",
        "updated_at",
    },
    "observation_ingestion_batches": {
        "id",
        "source_id",
        "source_type",
        "adapter_id",
        "correlation_id",
        "received_at",
        "status",
        "total",
        "accepted",
        "deduplicated",
        "sampled",
        "invalid",
        "errors",
        "error",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    },
    "observation_source_heartbeats": {
        "source_id",
        "last_seen_at",
        "last_success_at",
        "last_failure_at",
        "status",
        "consecutive_failures",
        "last_batch_id",
        "last_error",
        "updated_at",
    },
    "observations": {
        "observation_id",
        "source_id",
        "source_type",
        "entity_id",
        "subject_type",
        "subject_id",
        "space_id",
        "attribute",
        "raw_value",
        "raw_unit",
        "normalized_value",
        "normalized_unit",
        "value_type",
        "observed_at",
        "observed_at_source",
        "observed_at_uncertainty_ms",
        "received_at",
        "processed_at",
        "quality_status",
        "quality_issues",
        "valid_from",
        "valid_until",
        "freshness_policy",
        "freshness_evaluated_at",
        "correlation_id",
        "external_id",
        "dedupe_key",
        "payload_hash",
        "normalization_rule_version",
        "retention_class",
        "retention_until",
        "created_at",
    },
    "provider_logs": {
        "id",
        "provider",
        "model",
        "request_kind",
        "input_summary",
        "output_summary",
        "status",
        "error",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "created_at",
    },
    "space_paths": {
        "ancestor_id",
        "descendant_id",
        "depth",
        "path_version",
        "created_at",
    },
    "spaces": {
        "id",
        "parent_id",
        "space_type",
        "name",
        "normalized_name",
        "slug",
        "path",
        "sort_order",
        "external_space_id",
        "external_source",
        "status",
        "geometry",
        "metadata",
        "created_at",
        "updated_at",
        "archived_at",
    },
    "system_settings": {
        "id",
        "key",
        "value",
        "value_type",
        "is_secret",
        "description",
        "updated_at",
    },
    "task_steps": {
        "id",
        "task_id",
        "step_index",
        "name",
        "description",
        "tool_name",
        "status",
        "input",
        "output",
        "error",
        "started_at",
        "completed_at",
    },
    "tasks": {
        "id",
        "task_type",
        "title",
        "description",
        "status",
        "origin",
        "conversation_id",
        "plan",
        "result",
        "error",
        "correlation_id",
        "created_at",
        "started_at",
        "completed_at",
    },
    "tool_executions": {
        "id",
        "tool_id",
        "task_id",
        "task_step_id",
        "status",
        "input",
        "output",
        "validation",
        "risk_level",
        "permission_result",
        "error",
        "correlation_id",
        "started_at",
        "completed_at",
        "duration_ms",
    },
    "tools": {
        "id",
        "name",
        "version",
        "description",
        "category",
        "input_schema",
        "output_schema",
        "risk_level",
        "default_permission",
        "requires_confirmation",
        "enabled",
        "created_at",
        "updated_at",
    },
    "user_preferences": {
        "id",
        "key",
        "value",
        "category",
        "description",
        "source",
        "source_type",
        "source_record_id",
        "status",
        "scope",
        "conversation_id",
        "consent_id",
        "confirmed",
        "confirmed_at",
        "valid_from",
        "expires_at",
        "retention_until",
        "superseded_at",
        "created_at",
        "updated_at",
    },
}


def test_observation_pipeline_migration_preserves_device_history(tmp_path: Path) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))
    observed_at = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)

    try:
        manager.initialize_database()
        manager.downgrade("f3d2c8a67b01")

        with manager.engine.begin() as connection:
            for device_id in ("device-a", "device-b"):
                connection.execute(
                    text(
                        """
                        INSERT INTO devices (
                            id, adapter_id, external_id, name, normalized_name,
                            device_type, area, manufacturer, model, is_online,
                            is_enabled, risk_level, capabilities, metadata,
                            last_seen_at, created_at, updated_at
                        ) VALUES (
                            :id, 'mock', :id, :id, :id, 'sensor_temperature', NULL,
                            NULL, NULL, 1, 1, 'low', '{}', '{}',
                            :timestamp, :timestamp, :timestamp
                        )
                        """
                    ),
                    {"id": device_id, "timestamp": observed_at.isoformat()},
                )

            state_rows = [
                ("state-a-old", "device-a", observed_at - timedelta(minutes=20)),
                ("state-a-middle", "device-a", observed_at - timedelta(minutes=10)),
                ("state-a-new", "device-a", observed_at),
                ("state-b-only", "device-b", observed_at - timedelta(minutes=5)),
            ]
            for state_id, device_id, timestamp in state_rows:
                connection.execute(
                    text(
                        """
                        INSERT INTO device_states (
                            id, device_id, state, attributes, raw_state, source,
                            observed_at, created_at
                        ) VALUES (
                            :id, :device_id, 'on', '{}', 'on', 'mock',
                            :observed_at, :created_at
                        )
                        """
                    ),
                    {
                        "id": state_id,
                        "device_id": device_id,
                        "observed_at": timestamp.isoformat(),
                        "created_at": (timestamp + timedelta(seconds=1)).isoformat(),
                    },
                )

        manager.upgrade()
        with manager.engine.connect() as connection:
            current_states = dict(
                connection.execute(
                    text("SELECT id, is_current FROM device_states ORDER BY id")
                ).all()
            )

        assert current_states == {
            "state-a-old": False,
            "state-a-middle": False,
            "state-a-new": True,
            "state-b-only": True,
        }

        manager.downgrade("f3d2c8a67b01")
        with manager.engine.connect() as connection:
            history_count = connection.scalar(text("SELECT COUNT(*) FROM device_states"))

        assert history_count == 4
        assert "is_current" not in {
            column["name"] for column in inspect(manager.engine).get_columns("device_states")
        }
    finally:
        manager.dispose()


def phase_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "data_dir": tmp_path / "data",
        "log_dir": tmp_path / "logs",
        "backup_dir": tmp_path / "backups",
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_initial_migration_repeats_and_downgrade_upgrade_cycle(tmp_path: Path) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))

    try:
        first = manager.initialize_database()
        assert first.migration_pending is False
        assert first.current_revision == first.head_revision

        inspector = inspect(manager.engine)
        tables = set(inspector.get_table_names()) - {"alembic_version"}
        assert tables == EXPECTED_TABLES
        for table in EXPECTED_TABLES:
            columns = {column["name"] for column in inspector.get_columns(table)}
            assert columns == EXPECTED_COLUMNS[table]

        repeated = manager.initialize_database()
        assert repeated.current_revision == repeated.head_revision

        manager.downgrade("base")
        inspector = inspect(manager.engine)
        assert not EXPECTED_TABLES & set(inspector.get_table_names())

        upgraded = manager.initialize_database()
        assert upgraded.migration_pending is False
    finally:
        manager.dispose()


def test_migration_creates_documented_constraints_and_indexes(tmp_path: Path) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))

    try:
        manager.initialize_database()
        inspector = inspect(manager.engine)

        def unique_tuples(table: str) -> set[tuple[str, ...]]:
            return {
                tuple(constraint["column_names"])
                for constraint in inspector.get_unique_constraints(table)
            }

        assert unique_tuples("devices") == {("adapter_id", "external_id"), ("entity_id",)}
        assert unique_tuples("device_capabilities") == {("device_id", "capability")}
        assert unique_tuples("environments") == {("root_space_id",)}
        assert unique_tuples("task_steps") == {("task_id", "step_index")}
        assert unique_tuples("tools") == {("name",)}
        assert unique_tuples("user_preferences") == {("key",)}
        assert unique_tuples("system_settings") == {("key",)}
        assert unique_tuples("spaces") == {("parent_id", "slug")}
        assert unique_tuples("observation_attribute_policies") == {("attribute", "version")}
        assert unique_tuples("observations") == {("dedupe_key",)}

        event_indexes = {
            index["name"]: tuple(index["column_names"]) for index in inspector.get_indexes("events")
        }

        device_state_indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspector.get_indexes("device_states")
        }
        assert device_state_indexes == {
            "ix_device_states_device_observed": ("device_id", "observed_at"),
            "uq_device_states_current": ("device_id",),
        }

        batch_indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspector.get_indexes("observation_ingestion_batches")
        }
        assert batch_indexes == {
            "ix_observation_ingestion_batches_source_received": ("source_id", "received_at"),
            "ix_observation_ingestion_batches_status_received": ("status", "received_at"),
        }
        assert event_indexes == {
            "ix_events_correlation": ("correlation_id",),
            "ix_events_subject_occurred": ("subject_type", "subject_id", "occurred_at"),
            "ix_events_type_occurred": ("event_type", "occurred_at"),
        }

        foreign_keys = {
            (key["referred_table"], key["constrained_columns"][0])
            for key in inspector.get_foreign_keys("device_states")
        }
        assert foreign_keys == {("devices", "device_id")}

        assignment_keys = {
            (key["referred_table"], tuple(key["constrained_columns"]))
            for key in inspector.get_foreign_keys("entity_space_assignments")
        }
        assert assignment_keys == {
            ("entities", ("entity_id",)),
            ("spaces", ("space_id",)),
        }

        observation_indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspector.get_indexes("observations")
        }
        assert observation_indexes == {
            "ix_observations_source_attribute_received": (
                "source_id",
                "attribute",
                "received_at",
            ),
            "ix_observations_entity_attribute_received": (
                "entity_id",
                "attribute",
                "received_at",
            ),
            "ix_observations_space_attribute_received": (
                "space_id",
                "attribute",
                "received_at",
            ),
            "ix_observations_retention_until": ("retention_until",),
            "ix_observations_correlation": ("correlation_id",),
            "ix_observations_external": ("source_id", "external_id"),
        }

        observation_keys = {
            (key["referred_table"], tuple(key["constrained_columns"]))
            for key in inspector.get_foreign_keys("observations")
        }
        assert observation_keys == {
            ("entities", ("entity_id",)),
            ("spaces", ("space_id",)),
            ("observation_attribute_definitions", ("attribute",)),
            ("observation_sources", ("source_id",)),
        }
    finally:
        manager.dispose()


def test_database_connection_failure_is_wrapped(tmp_path: Path) -> None:
    database_directory = tmp_path / "not-a-file"
    database_directory.mkdir()
    settings = phase_settings(tmp_path, database_path=database_directory)
    manager = DatabaseManager(settings)

    try:
        with pytest.raises(DatabaseConnectionError):
            manager.verify_connection()
    finally:
        manager.dispose()


def test_migration_failure_is_wrapped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_upgrade(*args: object, **kwargs: object) -> None:
        raise RuntimeError("migration script failed")

    monkeypatch.setattr(database_module.command, "upgrade", fail_upgrade)
    manager = DatabaseManager(phase_settings(tmp_path))

    try:
        with pytest.raises(MigrationError, match="Database upgrade failed.") as error:
            manager.initialize_database()
        assert isinstance(error.value.__cause__, RuntimeError)
    finally:
        manager.dispose()
