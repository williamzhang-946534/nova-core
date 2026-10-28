import json
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import uuid4

import httpx
from pydantic import SecretStr

from nova_core.ai.errors import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderHTTPError,
    ProviderInvalidOutputError,
    ProviderLogError,
    ProviderTimeoutError,
)
from nova_core.ai.logging_support import (
    finish_provider_log,
    redacted_output,
    retry_delay,
    start_provider_log,
)
from nova_core.ai.models import (
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
)
from nova_core.ai.storage import ProviderLogFinish, ProviderLogStoreProtocol

STRUCTURED_OUTPUT_MODES = ("json_schema", "json_object", "prompt_only")
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
FALLBACK_STATUS_CODES = {400, 422}


@dataclass(frozen=True)
class OpenAICompatibleProviderConfig:
    base_url: str
    model: str
    api_key: SecretStr
    timeout_seconds: float
    max_retries: int
    structured_output_mode: str = "json_schema"
    retry_backoff_seconds: float = 0.2

    def validate(self) -> None:
        missing = [
            name
            for name, value in (
                ("NOVA_AI_BASE_URL", self.base_url),
                ("NOVA_AI_MODEL", self.model),
            )
            if not str(value).strip()
        ]
        if not self.api_key.get_secret_value().strip():
            missing.append("NOVA_AI_API_KEY")
        if missing:
            raise ProviderConfigurationError(
                "Required AI provider settings are missing: " + ", ".join(missing)
            )
        if not self.base_url.rstrip("/").startswith(("http://", "https://")):
            raise ProviderConfigurationError("NOVA_AI_BASE_URL must be an HTTP URL.")
        if self.structured_output_mode not in STRUCTURED_OUTPUT_MODES:
            raise ProviderConfigurationError("Unsupported AI structured output mode.")


class OpenAICompatibleProvider:
    """Calls an OpenAI-compatible chat completion endpoint with strict JSON parsing."""

    def __init__(
        self,
        config: OpenAICompatibleProviderConfig,
        log_store: ProviderLogStoreProtocol,
        *,
        client: httpx.AsyncClient | None = None,
        log_id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        config.validate()
        self._config = config
        self._log_store = log_store
        self._external_client = client
        self._client = client
        self._log_id_factory = log_id_factory

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        config = self._config
        config.validate()
        log_id = self._log_id_factory()
        await start_provider_log(
            self._log_store,
            log_id=log_id,
            provider="openai_compatible",
            model=config.model,
            request=request,
        )
        started_at = monotonic()
        try:
            output, usage, mode, attempts = await self._generate_with_fallback(request)
        except Exception as exc:
            latency_ms = _duration_ms(started_at)
            try:
                await finish_provider_log(
                    self._log_store,
                    log_id,
                    ProviderLogFinish(
                        status="failed",
                        error={
                            "code": getattr(exc, "code", "PROVIDER_ERROR"),
                            "message": getattr(exc, "message", "The AI provider call failed."),
                        },
                        latency_ms=latency_ms,
                    ),
                )
            except Exception:
                raise ProviderLogError from exc
            raise

        latency_ms = _duration_ms(started_at)
        try:
            await finish_provider_log(
                self._log_store,
                log_id,
                ProviderLogFinish(
                    status="succeeded",
                    output_summary=redacted_output(
                        {
                            "structured_output": output,
                            "structured_output_mode": mode,
                            "attempts": attempts,
                        }
                    ),
                    latency_ms=latency_ms,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                ),
            )
        except Exception:
            raise
        return ProviderResponse(
            provider="openai_compatible",
            model=config.model,
            request_kind=request.request_kind,
            output=output,
            latency_ms=latency_ms,
            usage=usage,
            provider_log_id=log_id,
        )

    async def aclose(self) -> None:
        if self._external_client is None and self._client is not None:
            await self._client.aclose()

    async def _generate_with_fallback(
        self,
        request: ProviderRequest,
    ) -> tuple[dict[str, Any], ProviderUsage, str, int]:
        mode_index = STRUCTURED_OUTPUT_MODES.index(self._config.structured_output_mode)
        retries = 0
        attempts = 0

        while True:
            attempts += 1
            try:
                result = await self._request_once(request, STRUCTURED_OUTPUT_MODES[mode_index])
                return (*result, attempts)
            except httpx.TimeoutException as exc:
                await self._maybe_retry(retries, "timeout")
                retries += 1
                if retries > self._config.max_retries:
                    raise ProviderTimeoutError from exc
            except httpx.TransportError as exc:
                await self._maybe_retry(retries, "network")
                retries += 1
                if retries > self._config.max_retries:
                    raise ProviderHTTPError(0) from exc
            except ProviderHTTPError as exc:
                status_code = int(exc.details.get("provider_status_code", 0))
                if (
                    status_code in FALLBACK_STATUS_CODES
                    and mode_index < len(STRUCTURED_OUTPUT_MODES) - 1
                ):
                    mode_index += 1
                    continue
                if status_code in TRANSIENT_STATUS_CODES:
                    await self._maybe_retry(retries, "http")
                    retries += 1
                    if retries > self._config.max_retries:
                        raise
                else:
                    raise

    async def _request_once(
        self,
        request: ProviderRequest,
        mode: str,
    ) -> tuple[dict[str, Any], ProviderUsage, str]:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._config.base_url.rstrip("/"),
                timeout=self._config.timeout_seconds,
            )

        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [message.model_dump(mode="json") for message in request.messages],
        }
        if mode == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.request_kind,
                    "schema": request.response_schema,
                    "strict": True,
                },
            }
        elif mode == "json_object":
            payload["response_format"] = {"type": "json_object"}

        try:
            response = await self._client.post(
                "/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._config.api_key.get_secret_value()}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException:
            raise
        except httpx.TransportError:
            raise
        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError
        if response.status_code >= 400:
            raise ProviderHTTPError(response.status_code)
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderInvalidOutputError("The provider response was not JSON.") from exc

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderInvalidOutputError("The provider response has no choice.")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ProviderInvalidOutputError("The provider choice is invalid.")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ProviderInvalidOutputError("The provider message is invalid.")
        if message.get("refusal"):
            raise ProviderInvalidOutputError("The model refused the request.")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderInvalidOutputError("The model returned empty content.")
        try:
            output = json.loads(content, parse_constant=_reject_json_constant)
        except (TypeError, ValueError) as exc:
            raise ProviderInvalidOutputError("The model content was not valid JSON.") from exc
        if not isinstance(output, dict):
            raise ProviderInvalidOutputError("The model JSON was not an object.")
        return output, _usage(body), mode

    async def _maybe_retry(self, retries: int, reason: str) -> None:
        if retries >= self._config.max_retries:
            return
        await retry_delay(self._config.retry_backoff_seconds * (2**retries))


def _usage(body: dict[str, Any]) -> ProviderUsage:
    raw_usage = body.get("usage")
    if not isinstance(raw_usage, dict):
        return ProviderUsage()
    return ProviderUsage(
        prompt_tokens=_optional_int(raw_usage.get("prompt_tokens")),
        completion_tokens=_optional_int(raw_usage.get("completion_tokens")),
    )


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Unsupported JSON constant: {value}")


def _duration_ms(started_at: float) -> int:
    return max(0, int((monotonic() - started_at) * 1000))


__all__ = ["OpenAICompatibleProvider", "OpenAICompatibleProviderConfig"]
