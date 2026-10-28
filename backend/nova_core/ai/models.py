from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProviderMessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ProviderMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ProviderMessageRole
    content: str = Field(min_length=1, max_length=100_000)


class ProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_kind: str = Field(min_length=1, max_length=100)
    messages: list[ProviderMessage] = Field(min_length=1, max_length=50)
    response_schema: dict[str, Any]
    correlation_id: str = Field(min_length=1, max_length=100)


class ProviderUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)


class ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    request_kind: str
    output: dict[str, Any]
    latency_ms: int = Field(ge=0)
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    provider_log_id: str
