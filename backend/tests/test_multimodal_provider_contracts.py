import asyncio
from pathlib import Path

import pytest

from arvuno_core.multimodal.errors import MultimodalError
from arvuno_core.multimodal.providers import (
    GovernedProviderAdapter,
    ProviderResult,
    default_adapters,
)

PNG = bytes.fromhex("89504e470d0a1a0a00000000")
EXPECTED_RESULT_KINDS = {
    "vision_scene": "scene_labels",
    "vision_object": "objects",
    "ocr": "ocr_text",
    "stt": "transcript",
    "audio_event": "audio_events",
    "tts": "structured_scene",
}


class ContractProvider:
    def __init__(self, capability: str, handler=None) -> None:
        self.capability = capability
        self.provider_name = "contract"
        self.model_id = "contract-model"
        self.model_version = "2.0"
        self.processing_location = "cloud"
        self._handler = handler

    async def process(self, **kwargs: object) -> ProviderResult:
        if self._handler is None:
            return ProviderResult(
                result_kind=EXPECTED_RESULT_KINDS[self.capability],
                result={"capability": self.capability},
                confidence=0.7,
                model_version=self.model_version,
            )
        return await self._handler(**kwargs)


@pytest.mark.parametrize("capability", sorted(EXPECTED_RESULT_KINDS))
def test_default_provider_contract_for_all_six_capabilities(
    capability: str, tmp_path: Path
) -> None:
    adapter = default_adapters()[capability]
    output_path = tmp_path / "output.wav"
    result = asyncio.run(
        adapter.process(
            capability=capability,
            content=PNG,
            mime_type="image/png"
            if capability.startswith("vision") or capability == "ocr"
            else "audio/wav",
            text="hello" if capability == "tts" else None,
            output_path=output_path if capability == "tts" else None,
        )
    )

    assert adapter.capability == capability
    assert result.result_kind == EXPECTED_RESULT_KINDS[capability]
    assert isinstance(result.result, dict)
    assert 0 <= result.confidence <= 1
    if capability == "stt":
        assert result.result["is_instruction"] is False
    if capability == "ocr":
        assert result.result["is_instruction"] is False
    if capability == "tts":
        assert result.output_mime == "audio/wav"
        assert result.output_path == output_path
        assert output_path.stat().st_size > 44


def test_governed_adapter_retries_transient_provider_failure() -> None:
    calls = 0

    async def handler(**_: object) -> ProviderResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise MultimodalError(code="PROVIDER_UNAVAILABLE", status_code=503)
        return ProviderResult(
            result_kind="scene_labels",
            result={"labels": ["kitchen"]},
            confidence=0.8,
            model_version="2.0",
        )

    adapter = GovernedProviderAdapter(
        ContractProvider("vision_scene", handler),
        timeout_seconds=1,
        max_attempts=3,
    )
    result = asyncio.run(
        adapter.process(capability="vision_scene", content=PNG, mime_type="image/png")
    )

    assert calls == 2
    assert result.result == {"labels": ["kitchen"]}


def test_governed_adapter_enforces_total_deadline_and_cancellation() -> None:
    async def handler(**_: object) -> ProviderResult:
        await asyncio.sleep(0.1)
        return ProviderResult(
            result_kind="scene_labels",
            result={"labels": []},
            confidence=0.8,
            model_version="2.0",
        )

    adapter = GovernedProviderAdapter(
        ContractProvider("vision_scene", handler),
        timeout_seconds=0.01,
    )
    with pytest.raises(MultimodalError) as raised:
        asyncio.run(adapter.process(capability="vision_scene", content=PNG, mime_type="image/png"))

    assert raised.value.code == "MULTIMODAL_PROVIDER_TIMEOUT"
    assert raised.value.status_code == 504


def test_governed_adapter_quota_blocks_retry_after_budget_is_spent() -> None:
    calls = 0

    async def handler(**_: object) -> ProviderResult:
        nonlocal calls
        calls += 1
        raise MultimodalError(code="PROVIDER_BUSY", status_code=503)

    adapter = GovernedProviderAdapter(
        ContractProvider("stt", handler),
        timeout_seconds=1,
        max_attempts=2,
        max_requests=1,
    )
    with pytest.raises(MultimodalError) as raised:
        asyncio.run(adapter.process(capability="stt", content=b"wave", mime_type="audio/wav"))

    assert calls == 1
    assert raised.value.code == "MULTIMODAL_PROVIDER_QUOTA_EXCEEDED"


def test_governed_adapter_quota_window_resets_and_preserves_partial_results() -> None:
    times = [0.0, 0.01, 0.01, 12.0, 12.01, 12.02]
    calls = 0

    async def handler(**_: object) -> ProviderResult:
        nonlocal calls
        calls += 1
        return ProviderResult(
            result_kind="transcript",
            result={"transcript": "partial speech", "is_instruction": False},
            confidence=0.5,
            model_version="2.0",
            alternatives=["partial speech"],
            partial=True,
        )

    adapter = GovernedProviderAdapter(
        ContractProvider("stt", handler),
        timeout_seconds=1,
        max_requests=1,
        quota_window_seconds=10,
        clock=lambda: times.pop(0) if len(times) > 1 else times[0],
    )
    first = asyncio.run(adapter.process(capability="stt", content=b"wave", mime_type="audio/wav"))
    second = asyncio.run(adapter.process(capability="stt", content=b"wave", mime_type="audio/wav"))

    assert calls == 2
    assert first.partial is True
    assert second.partial is True
    assert second.alternatives == ["partial speech"]


def test_governed_adapter_rejects_capability_mismatch() -> None:
    adapter = GovernedProviderAdapter(
        ContractProvider("ocr"),
        timeout_seconds=1,
    )
    with pytest.raises(MultimodalError) as raised:
        asyncio.run(adapter.process(capability="vision_scene", content=PNG, mime_type="image/png"))

    assert raised.value.code == "MULTIMODAL_PROVIDER_CAPABILITY_INVALID"
