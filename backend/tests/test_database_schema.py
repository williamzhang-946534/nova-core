from pathlib import Path

import pytest
from sqlalchemy import inspect

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
    "environment_snapshots",
    "environments",
    "events",
    "memories",
    "notifications",
    "provider_logs",
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
    },
    "devices": {
        "id",
        "adapter_id",
        "external_id",
        "name",
        "normalized_name",
        "device_type",
        "area",
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
    "environment_snapshots": {
        "id",
        "environment_id",
        "context",
        "active_task_ids",
        "anomaly_count",
        "created_at",
    },
    "environments": {"id", "name", "description", "is_default", "created_at"},
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
        "expires_at",
        "created_at",
        "updated_at",
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
        "confirmed",
        "created_at",
        "updated_at",
    },
}


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

        assert unique_tuples("devices") == {("adapter_id", "external_id")}
        assert unique_tuples("device_capabilities") == {("device_id", "capability")}
        assert unique_tuples("task_steps") == {("task_id", "step_index")}
        assert unique_tuples("tools") == {("name",)}
        assert unique_tuples("user_preferences") == {("key",)}
        assert unique_tuples("system_settings") == {("key",)}

        event_indexes = {
            index["name"]: tuple(index["column_names"]) for index in inspector.get_indexes("events")
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
