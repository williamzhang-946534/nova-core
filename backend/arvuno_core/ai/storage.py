from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ProviderLogStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    provider: str
    model: str
    request_kind: str
    input_summary: dict[str, Any]
    status: str = "running"
    created_at: datetime


class ProviderLogFinish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern="^(succeeded|failed)$")
    output_summary: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    latency_ms: int = Field(ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)


class ProviderLogStoreProtocol(Protocol):
    async def start(self, record: ProviderLogStart) -> None: ...

    async def finish(self, log_id: str, record: ProviderLogFinish) -> None: ...


__all__ = ["ProviderLogFinish", "ProviderLogStart", "ProviderLogStoreProtocol"]
