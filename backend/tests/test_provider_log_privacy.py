import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from arvuno_core.ai.mock import MockAIProvider
from arvuno_core.ai.models import ProviderMessage, ProviderMessageRole, ProviderRequest
from arvuno_core.config import Settings
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import ProviderLog
from arvuno_core.persistence.provider_logs import SqlProviderLogStore
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork


def isolated_settings(
    tmp_path: Path,
    *,
    environment: str = "test",
    debug_logging: bool = False,
) -> Settings:
    return Settings(
        _env_file=None,
        environment=environment,
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
        ai_provider_debug_logging=debug_logging,
    )


def private_request() -> ProviderRequest:
    return ProviderRequest(
        request_kind="agent_intent_plan",
        messages=[
            ProviderMessage(
                role=ProviderMessageRole.SYSTEM,
                content="System prompt must not be persisted.",
            ),
            ProviderMessage(
                role=ProviderMessageRole.USER,
                content="Private user request mentioning api_key=raw-provider-key",
            ),
        ],
        response_schema={"properties": {"reply_to_user": {"type": "string"}}},
        correlation_id="provider-privacy-correlation",
    )


def factory(manager: DatabaseManager):
    return lambda: SqlAlchemyUnitOfWork(manager.session_factory)


def test_provider_debug_logging_is_off_by_default_and_restricted_to_development() -> None:
    default_settings = isolated_settings(Path("unused-isolated-path"))
    assert default_settings.ai_provider_debug_logging is False
    assert default_settings.ai_provider_debug_logging_ttl_seconds == 900

    with pytest.raises(ValidationError, match="only be enabled in development"):
        isolated_settings(Path("unused-isolated-path"), debug_logging=True)

    development = Settings(
        _env_file=None,
        environment="development",
        ai_provider_debug_logging=True,
    )
    assert development.ai_provider_debug_logging is True


def test_provider_logs_store_metadata_without_conversation_or_response_content(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(isolated_settings(tmp_path))
    try:
        manager.initialize_database()
        provider = MockAIProvider(
            SqlProviderLogStore(factory(manager)),
            outputs=[{"reply_to_user": "private model response must not persist"}],
            log_id_factory=lambda: "provider-privacy-log",
        )

        asyncio.run(provider.generate(private_request()))

        with manager.session_factory() as session:
            record = session.get(ProviderLog, "provider-privacy-log")
            assert record is not None
            serialized_input = json.dumps(record.input_summary)
            serialized_output = json.dumps(record.output_summary)
            assert record.input_summary["schema_version"] == 2
            assert record.input_summary["message_count"] == 2
            assert record.input_summary["role_distribution"] == {"system": 1, "user": 1}
            assert "messages" not in record.input_summary
            assert "response_schema_keys" not in record.input_summary
            assert "System prompt must not be persisted" not in serialized_input
            assert "Private user request" not in serialized_input
            assert "raw-provider-key" not in serialized_input
            assert "private model response" not in serialized_output
            assert record.output_summary == {}
    finally:
        manager.dispose()


def test_debug_capture_is_redacted_temporary_and_hidden_from_metadata(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(isolated_settings(tmp_path, environment="development"))
    try:
        manager.initialize_database()
        store = SqlProviderLogStore(factory(manager))
        provider = MockAIProvider(
            store,
            log_id_factory=lambda: "provider-debug-log",
            debug_logging=True,
            debug_logging_ttl_seconds=60,
        )

        asyncio.run(provider.generate(private_request()))

        with manager.session_factory() as session:
            record = session.get(ProviderLog, "provider-debug-log")
            assert record is not None
            debug = record.input_summary["debug"]
            serialized_debug = json.dumps(debug)
            assert "System prompt must not be persisted" in serialized_debug
            assert "Private user request mentioning" in serialized_debug
            assert "raw-provider-key" not in serialized_debug
            assert "expires_at" in debug

        with factory(manager)() as unit_of_work:
            metadata = unit_of_work.provider_logs.metadata("provider-debug-log")
            assert set(metadata) == {
                "request_id",
                "provider",
                "model",
                "request_type",
                "schema_version",
                "correlation_id",
                "message_count",
                "role_distribution",
                "input_token_count",
                "output_token_count",
                "request_duration",
                "response_status",
                "error_code",
                "created_at",
            }
            assert "Private user request" not in json.dumps(metadata, default=str)

        expired_count = asyncio.run(
            store.cleanup_expired_debug(datetime.now(UTC) + timedelta(seconds=61))
        )
        assert expired_count == 1
        with manager.session_factory() as session:
            record = session.get(ProviderLog, "provider-debug-log")
            assert record is not None
            assert "debug" not in record.input_summary

        assert (
            asyncio.run(store.cleanup_expired_debug(datetime.now(UTC) + timedelta(seconds=61))) == 0
        )
    finally:
        manager.dispose()


def test_cleanup_removes_debug_without_a_valid_expiry(tmp_path: Path) -> None:
    manager = DatabaseManager(isolated_settings(tmp_path))
    try:
        manager.initialize_database()
        with manager.session_factory() as session:
            session.add(
                ProviderLog(
                    id="provider-invalid-debug-expiry",
                    provider="mock",
                    model="mock-agent",
                    request_kind="agent_intent_plan",
                    input_summary={
                        "schema_version": 2,
                        "message_count": 1,
                        "debug": {
                            "purpose": "temporary_provider_request_debug",
                            "expires_at": "not-a-timestamp",
                            "messages": [
                                {"role": "user", "content": "private malformed debug request"}
                            ],
                        },
                    },
                    output_summary={},
                    status="succeeded",
                    error=None,
                    latency_ms=1,
                    prompt_tokens=1,
                    completion_tokens=1,
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()

        expired_count = asyncio.run(
            SqlProviderLogStore(factory(manager)).cleanup_expired_debug(datetime.now(UTC))
        )

        assert expired_count == 1
        with manager.session_factory() as session:
            record = session.get(ProviderLog, "provider-invalid-debug-expiry")
            assert record is not None
            assert "debug" not in record.input_summary
            assert "private malformed debug request" not in json.dumps(record.input_summary)
    finally:
        manager.dispose()


def test_provider_log_migration_sanitizes_existing_full_text_in_place(tmp_path: Path) -> None:
    manager = DatabaseManager(isolated_settings(tmp_path))
    old_full_input = {
        "correlation_id": "old-correlation",
        "messages": [
            {"role": "system", "content": "old system prompt"},
            {"role": "user", "content": "old private user request"},
        ],
        "response_schema_keys": ["properties"],
    }
    old_full_output = {"structured_output": {"reply_to_user": "old private response"}}
    old_error = {"code": "PROVIDER_ERROR", "message": "password=old-secret"}
    try:
        manager.initialize_database()
        manager.downgrade("b8c3d4e5f6a7")
        with manager.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO provider_logs (
                        id, provider, model, request_kind, input_summary, output_summary,
                        status, error, latency_ms, prompt_tokens, completion_tokens, created_at
                    ) VALUES (
                        'old-full-provider-log', 'openai_compatible', 'old-model',
                        'agent_intent_plan', :input_summary, :output_summary,
                        'failed', :error, 12, 20, 30, '2026-11-10T00:00:00+00:00'
                    )
                    """
                ),
                {
                    "input_summary": json.dumps(old_full_input),
                    "output_summary": json.dumps(old_full_output),
                    "error": json.dumps(old_error),
                },
            )

        manager.upgrade()
        with manager.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT input_summary, output_summary, error FROM provider_logs "
                        "WHERE id = 'old-full-provider-log'"
                    )
                )
                .mappings()
                .one()
            )

        input_summary = json.loads(row["input_summary"])
        output_summary = json.loads(row["output_summary"])
        error = json.loads(row["error"])
        serialized_row = json.dumps({"input": input_summary, "output": output_summary})
        assert input_summary == {
            "schema_version": 2,
            "request_id": "old-full-provider-log",
            "correlation_id": "old-correlation",
            "message_count": 2,
            "role_distribution": {"system": 1, "user": 1},
        }
        assert output_summary == {}
        assert error == {"code": "PROVIDER_ERROR"}
        assert "old system prompt" not in serialized_row
        assert "old private user request" not in serialized_row
        assert "old private response" not in serialized_row

        manager.downgrade("b8c3d4e5f6a7")
        with manager.engine.connect() as connection:
            downgraded = json.loads(
                connection.execute(
                    text(
                        "SELECT input_summary FROM provider_logs WHERE id = 'old-full-provider-log'"
                    )
                ).scalar_one()
            )
        assert "messages" not in downgraded
        assert downgraded["schema_version"] == 1
    finally:
        manager.dispose()
