import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from nova_core.ai.errors import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderInvalidOutputError,
    ProviderTimeoutError,
)
from nova_core.ai.mock import MockAIProvider
from nova_core.ai.models import (
    ProviderMessage,
    ProviderMessageRole,
    ProviderRequest,
    ProviderResponse,
)
from nova_core.ai.openai_compatible import (
    OpenAICompatibleProvider,
    OpenAICompatibleProviderConfig,
)
from nova_core.ai.storage import ProviderLogFinish, ProviderLogStart
from nova_core.config import Settings
from nova_core.persistence.database import DatabaseManager
from nova_core.persistence.models import ProviderLog
from nova_core.persistence.provider_logs import SqlProviderLogStore
from nova_core.persistence.unit_of_work import SqlAlchemyUnitOfWork


@dataclass
class MemoryProviderLogStore:
    starts: list[ProviderLogStart] = field(default_factory=list)
    finishes: dict[str, ProviderLogFinish] = field(default_factory=dict)

    async def start(self, record: ProviderLogStart) -> None:
        self.starts.append(record)

    async def finish(self, log_id: str, record: ProviderLogFinish) -> None:
        self.finishes[log_id] = record


def request() -> ProviderRequest:
    return ProviderRequest(
        request_kind="agent_intent_plan",
        messages=[
            ProviderMessage(
                role=ProviderMessageRole.USER,
                content="Return JSON only. api_key must not be echoed.",
            )
        ],
        response_schema={"type": "object"},
        correlation_id="correlation-provider",
    )


def provider_config() -> OpenAICompatibleProviderConfig:
    return OpenAICompatibleProviderConfig(
        base_url="https://provider.example/v1",
        model="test-model",
        api_key=SecretStr("provider-secret"),
        timeout_seconds=5,
        max_retries=2,
        retry_backoff_seconds=0,
    )


def completion(content: object, *, usage: dict[str, int] | None = None) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content if isinstance(content, str) else json.dumps(content),
                }
            }
        ],
        "usage": usage or {"prompt_tokens": 11, "completion_tokens": 7},
    }


def mock_client(
    responses: list[httpx.Response | Exception],
    requests: list[httpx.Request],
) -> httpx.AsyncClient:
    def handler(next_request: httpx.Request) -> httpx.Response:
        requests.append(next_request)
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://provider.example/v1",
    )


def test_openai_provider_parses_structured_output_and_redacts_logs() -> None:
    store = MemoryProviderLogStore()
    requests: list[httpx.Request] = []
    client = mock_client(
        [httpx.Response(200, json=completion({"intent": {"type": "smalltalk"}}))],
        requests,
    )
    provider = OpenAICompatibleProvider(
        provider_config(),
        store,
        client=client,
        log_id_factory=lambda: "provider-log-success",
    )

    async def scenario() -> ProviderResponse:
        async with client:
            return await provider.generate(request())

    response = asyncio.run(scenario())

    assert response.output == {"intent": {"type": "smalltalk"}}
    assert response.usage.prompt_tokens == 11
    assert response.provider_log_id == "provider-log-success"
    assert requests[0].headers["Authorization"] == "Bearer provider-secret"
    assert requests[0].url.path.endswith("/chat/completions")
    assert store.starts[0].input_summary["correlation_id"] == "correlation-provider"
    assert "provider-secret" not in json.dumps(store.starts[0].input_summary)
    assert store.finishes["provider-log-success"].status == "succeeded"


def test_openai_provider_falls_back_when_json_schema_is_unsupported() -> None:
    store = MemoryProviderLogStore()
    requests: list[httpx.Request] = []
    client = mock_client(
        [
            httpx.Response(400, json={"error": "response_format is unsupported"}),
            httpx.Response(200, json=completion({"intent": {"type": "smalltalk"}})),
        ],
        requests,
    )
    provider = OpenAICompatibleProvider(
        provider_config(),
        store,
        client=client,
        log_id_factory=lambda: "provider-log-fallback",
    )

    async def scenario() -> ProviderResponse:
        async with client:
            return await provider.generate(request())

    response = asyncio.run(scenario())

    first_payload = json.loads(requests[0].read())
    second_payload = json.loads(requests[1].read())
    assert first_payload["response_format"]["type"] == "json_schema"
    assert second_payload["response_format"] == {"type": "json_object"}
    assert response.provider_log_id == "provider-log-fallback"
    assert store.finishes["provider-log-fallback"].output_summary["attempts"] == 2


def test_openai_provider_retries_transient_errors_a_bounded_number_of_times() -> None:
    store = MemoryProviderLogStore()
    requests: list[httpx.Request] = []
    client = mock_client(
        [
            httpx.Response(429, json={"error": "rate limited"}),
            httpx.Response(503, json={"error": "unavailable"}),
            httpx.Response(200, json=completion({"ok": True})),
        ],
        requests,
    )
    provider = OpenAICompatibleProvider(
        provider_config(),
        store,
        client=client,
        log_id_factory=lambda: "provider-log-retry",
    )

    async def scenario() -> ProviderResponse:
        async with client:
            return await provider.generate(request())

    response = asyncio.run(scenario())

    assert len(requests) == 3
    assert response.output == {"ok": True}
    assert store.finishes["provider-log-retry"].output_summary["attempts"] == 3


def test_openai_provider_does_not_retry_authentication_errors() -> None:
    store = MemoryProviderLogStore()
    requests: list[httpx.Request] = []
    client = mock_client([httpx.Response(401, json={"error": "invalid key"})], requests)
    provider = OpenAICompatibleProvider(
        provider_config(),
        store,
        client=client,
        log_id_factory=lambda: "provider-log-auth",
    )

    async def scenario() -> None:
        async with client:
            with pytest.raises(ProviderAuthenticationError):
                await provider.generate(request())

    asyncio.run(scenario())

    assert len(requests) == 1
    assert store.finishes["provider-log-auth"].status == "failed"
    assert store.finishes["provider-log-auth"].error is not None
    assert store.finishes["provider-log-auth"].error["code"] == "PROVIDER_AUTHENTICATION_ERROR"


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (200, {"choices": [{"message": {"content": "{not-json"}}]}),
        (200, {"choices": [{"message": {"refusal": "safety refusal"}}]}),
        (200, {"choices": []}),
        (200, {"choices": ["not-a-message"]}),
    ],
)
def test_openai_provider_rejects_invalid_model_output(status: int, body: dict[str, Any]) -> None:
    store = MemoryProviderLogStore()
    client = mock_client([httpx.Response(status, json=body)], [])
    provider = OpenAICompatibleProvider(
        provider_config(),
        store,
        client=client,
        log_id_factory=lambda: "provider-log-invalid",
    )

    async def scenario() -> None:
        async with client:
            with pytest.raises(ProviderInvalidOutputError):
                await provider.generate(request())

    asyncio.run(scenario())
    assert store.finishes["provider-log-invalid"].status == "failed"


def test_openai_provider_timeout_is_bounded_and_logged() -> None:
    store = MemoryProviderLogStore()
    requests: list[httpx.Request] = []
    client = mock_client([httpx.ConnectTimeout("timed out")], requests)
    provider = OpenAICompatibleProvider(
        OpenAICompatibleProviderConfig(
            base_url="https://provider.example/v1",
            model="test-model",
            api_key=SecretStr("provider-secret"),
            timeout_seconds=1,
            max_retries=0,
            retry_backoff_seconds=0,
        ),
        store,
        client=client,
        log_id_factory=lambda: "provider-log-timeout",
    )

    async def scenario() -> None:
        async with client:
            with pytest.raises(ProviderTimeoutError):
                await provider.generate(request())

    asyncio.run(scenario())
    assert len(requests) == 1
    assert store.finishes["provider-log-timeout"].error is not None
    assert store.finishes["provider-log-timeout"].error["code"] == "PROVIDER_TIMEOUT"


def test_openai_provider_requires_protected_configuration() -> None:
    config = OpenAICompatibleProviderConfig(
        base_url="",
        model="",
        api_key=SecretStr(" "),
        timeout_seconds=1,
        max_retries=0,
    )

    with pytest.raises(ProviderConfigurationError, match="NOVA_AI_BASE_URL"):
        config.validate()

    with pytest.raises(ValueError, match="Missing OpenAI-compatible AI settings"):
        Settings(_env_file=None, ai_provider="openai_compatible")


def test_mock_provider_and_sql_store_persist_redacted_logs(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )
    manager = DatabaseManager(settings)
    try:
        manager.initialize_database()

        def factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(manager.session_factory)

        provider = MockAIProvider(
            SqlProviderLogStore(factory),
            outputs=[
                {
                    "intent": {"type": "smalltalk"},
                    "api_key": "model-should-not-persist-this",
                }
            ],
            log_id_factory=lambda: "mock-provider-log",
        )

        asyncio.run(provider.generate(request()))

        with manager.session_factory() as session:
            record = session.get(ProviderLog, "mock-provider-log")

        assert record is not None
        assert record.provider == "mock"
        assert record.status == "succeeded"
        assert record.input_summary["correlation_id"] == "correlation-provider"
        assert "model-should-not-persist-this" not in json.dumps(record.output_summary)
        assert record.output_summary["structured_output"]["api_key"] == "[REDACTED]"
        assert record.prompt_tokens == 1
        assert record.completion_tokens == 1
    finally:
        manager.dispose()
