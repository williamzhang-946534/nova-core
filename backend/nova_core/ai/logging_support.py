import asyncio
from datetime import UTC, datetime
from typing import Any

from nova_core.ai.errors import ProviderLogError
from nova_core.ai.models import ProviderRequest
from nova_core.ai.storage import ProviderLogFinish, ProviderLogStart, ProviderLogStoreProtocol
from nova_core.logging_config import redact_sensitive_value


def provider_log_input(request: ProviderRequest) -> dict[str, Any]:
    return redact_sensitive_value(
        {
            "correlation_id": request.correlation_id,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
            "response_schema_keys": sorted(request.response_schema),
        }
    )


async def start_provider_log(
    store: ProviderLogStoreProtocol,
    *,
    log_id: str,
    provider: str,
    model: str,
    request: ProviderRequest,
) -> None:
    try:
        await store.start(
            ProviderLogStart(
                id=log_id,
                provider=provider,
                model=model,
                request_kind=request.request_kind,
                input_summary=provider_log_input(request),
                created_at=datetime.now(UTC),
            )
        )
    except Exception as exc:
        raise ProviderLogError from exc


async def finish_provider_log(
    store: ProviderLogStoreProtocol,
    log_id: str,
    record: ProviderLogFinish,
) -> None:
    try:
        await store.finish(log_id, record)
    except Exception as exc:
        raise ProviderLogError from exc


def redacted_output(value: Any) -> dict[str, Any]:
    redacted = redact_sensitive_value(value)
    return redacted if isinstance(redacted, dict) else {}


async def retry_delay(seconds: float) -> None:
    if seconds > 0:
        await asyncio.sleep(seconds)
