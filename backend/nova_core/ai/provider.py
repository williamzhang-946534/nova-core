from typing import Protocol

from nova_core.ai.models import ProviderRequest, ProviderResponse


class AIProvider(Protocol):
    async def generate(self, request: ProviderRequest) -> ProviderResponse: ...

    async def aclose(self) -> None: ...


__all__ = ["AIProvider"]
