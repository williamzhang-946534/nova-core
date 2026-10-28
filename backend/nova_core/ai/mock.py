import json
from collections.abc import Callable
from copy import deepcopy
from time import monotonic
from typing import Any
from uuid import uuid4

from nova_core.ai.errors import ProviderInvalidOutputError
from nova_core.ai.logging_support import (
    finish_provider_log,
    redacted_output,
    start_provider_log,
)
from nova_core.ai.models import ProviderRequest, ProviderResponse, ProviderUsage
from nova_core.ai.storage import ProviderLogFinish, ProviderLogStoreProtocol


class MockAIProvider:
    """Deterministic provider used by tests and local offline development."""

    def __init__(
        self,
        log_store: ProviderLogStoreProtocol,
        *,
        outputs: list[dict[str, Any] | str] | None = None,
        errors: list[Exception] | None = None,
        log_id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._log_store = log_store
        self._outputs = list(outputs or [])
        self._errors = list(errors or [])
        self._log_id_factory = log_id_factory
        self.requests: list[ProviderRequest] = []

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request.model_copy(deep=True))
        log_id = self._log_id_factory()
        await start_provider_log(
            self._log_store,
            log_id=log_id,
            provider="mock",
            model="mock-agent",
            request=request,
        )
        started_at = monotonic()
        output_count = len(self.requests) - 1
        raw_output = (
            self._outputs[output_count] if output_count < len(self._outputs) else _default_output()
        )

        if isinstance(raw_output, str):
            try:
                parsed = json.loads(raw_output)
            except ValueError as exc:
                failure = ProviderInvalidOutputError("The mock content was not valid JSON.")
                await self._finish_failure(log_id, started_at, failure)
                raise failure from exc
            if not isinstance(parsed, dict):
                failure = ProviderInvalidOutputError("The mock JSON was not an object.")
                await self._finish_failure(log_id, started_at, failure)
                raise failure
            output = parsed
        else:
            output = deepcopy(raw_output)

        if self._errors and output_count < len(self._errors):
            error = self._errors[output_count]
            await self._finish_failure(log_id, started_at, error)
            raise error

        await finish_provider_log(
            self._log_store,
            log_id,
            ProviderLogFinish(
                status="succeeded",
                output_summary=redacted_output({"structured_output": output}),
                latency_ms=0,
                prompt_tokens=1,
                completion_tokens=1,
            ),
        )
        return ProviderResponse(
            provider="mock",
            model="mock-agent",
            request_kind=request.request_kind,
            output=output,
            latency_ms=0,
            usage=ProviderUsage(prompt_tokens=1, completion_tokens=1),
            provider_log_id=log_id,
        )

    async def aclose(self) -> None:
        return None

    async def _finish_failure(
        self,
        log_id: str,
        started_at: float,
        error: Exception,
    ) -> None:
        await finish_provider_log(
            self._log_store,
            log_id,
            ProviderLogFinish(
                status="failed",
                error={
                    "code": getattr(error, "code", "PROVIDER_ERROR"),
                    "message": getattr(error, "message", "The mock provider failed."),
                },
                latency_ms=max(0, int((monotonic() - started_at) * 1000)),
            ),
        )


def _default_output() -> dict[str, Any]:
    return {
        "intent": {
            "type": "unsupported",
            "confidence": 1.0,
            "target": None,
            "action": None,
        },
        "requires_tool": False,
        "plan": [],
        "reply_to_user": "The offline mock provider is not configured for this request.",
    }


__all__ = ["MockAIProvider"]
