import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from arvuno_core.ai.errors import ProviderLogError
from arvuno_core.ai.models import ProviderRequest
from arvuno_core.ai.storage import ProviderLogFinish, ProviderLogStart, ProviderLogStoreProtocol
from arvuno_core.logging_config import redact_sensitive_text, redact_sensitive_value

PROVIDER_LOG_SCHEMA_VERSION = 2


def provider_log_input(
    request: ProviderRequest,
    *,
    log_id: str,
    debug: bool = False,
    debug_ttl_seconds: int = 900,
    now: datetime | None = None,
) -> dict[str, Any]:
    roles = Counter(message.role.value for message in request.messages)
    summary: dict[str, Any] = {
        "schema_version": PROVIDER_LOG_SCHEMA_VERSION,
        "request_id": log_id,
        "correlation_id": request.correlation_id,
        "message_count": len(request.messages),
        "role_distribution": dict(sorted(roles.items())),
    }
    if debug:
        if debug_ttl_seconds <= 0:
            raise ValueError("Provider debug logging requires a positive TTL.")
        captured_at = now or datetime.now(UTC)
        summary["debug"] = {
            "purpose": "temporary_provider_request_debug",
            "captured_at": captured_at.isoformat(),
            "expires_at": (captured_at + timedelta(seconds=debug_ttl_seconds)).isoformat(),
            "messages": redact_sensitive_value(
                [
                    {"role": message.role.value, "content": message.content}
                    for message in request.messages
                ]
            ),
        }
    return summary


async def start_provider_log(
    store: ProviderLogStoreProtocol,
    *,
    log_id: str,
    provider: str,
    model: str,
    request: ProviderRequest,
    debug_logging: bool = False,
    debug_logging_ttl_seconds: int = 900,
) -> None:
    try:
        created_at = datetime.now(UTC)
        await store.start(
            ProviderLogStart(
                id=log_id,
                provider=provider,
                model=model,
                request_kind=request.request_kind,
                input_summary=provider_log_input(
                    request,
                    log_id=log_id,
                    debug=debug_logging,
                    debug_ttl_seconds=debug_logging_ttl_seconds,
                    now=created_at,
                ),
                created_at=created_at,
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


def redacted_provider_error(error: dict[str, Any]) -> dict[str, Any]:
    code = str(error.get("code", "PROVIDER_ERROR"))
    return {"code": redact_sensitive_text(code)}


async def retry_delay(seconds: float) -> None:
    if seconds > 0:
        await asyncio.sleep(seconds)
