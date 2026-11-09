import hashlib
import wave
from pathlib import Path
from typing import Any, Protocol

from arvuno_core.multimodal.errors import MultimodalError


class ProviderResult:
    def __init__(
        self,
        *,
        result_kind: str,
        result: dict[str, Any],
        confidence: float,
        model_version: str,
        language: str | None = None,
        alternatives: list[Any] | None = None,
        output_path: Path | None = None,
        output_mime: str | None = None,
    ) -> None:
        self.result_kind = result_kind
        self.result = result
        self.confidence = confidence
        self.model_version = model_version
        self.language = language
        self.alternatives = alternatives
        self.output_path = output_path
        self.output_mime = output_mime


class MultimodalProviderAdapter(Protocol):
    capability: str
    provider_name: str
    model_id: str
    model_version: str
    processing_location: str

    async def process(
        self,
        *,
        capability: str,
        content: bytes,
        mime_type: str,
        text: str | None = None,
        output_path: Path | None = None,
    ) -> ProviderResult: ...


class MockVisionProvider:
    provider_name = "mock"
    model_id = "mock"
    model_version = "1.0.0"
    processing_location = "local"

    def __init__(self, capability: str = "vision_scene") -> None:
        if capability not in {"vision_scene", "vision_object", "ocr"}:
            raise MultimodalError(code="MULTIMODAL_PROVIDER_CAPABILITY_INVALID")
        self.capability = capability

    async def process(
        self,
        *,
        capability: str,
        content: bytes,
        mime_type: str,
        text: str | None = None,
        output_path: Path | None = None,
    ) -> ProviderResult:
        if capability not in {"vision_scene", "vision_object", "ocr"}:
            raise MultimodalError(code="MULTIMODAL_PROVIDER_CAPABILITY_INVALID")
        digest = hashlib.sha256(content).hexdigest()
        labels = ["indoor", "room"]
        objects: list[dict[str, Any]] = []
        if int(digest[:2], 16) % 2 == 0:
            objects.append({"label": "chair", "confidence": 0.72})
        if int(digest[2:4], 16) % 3 == 0:
            objects.append({"label": "plant", "confidence": 0.65})
        if capability == "vision_scene":
            return ProviderResult(
                result_kind="scene_labels",
                result={"labels": labels},
                confidence=0.8,
                model_version=self.model_version,
            )
        if capability == "vision_object":
            return ProviderResult(
                result_kind="objects",
                result={"objects": objects, "identity_state": "candidate"},
                confidence=0.7,
                model_version=self.model_version,
            )
        return ProviderResult(
            result_kind="ocr_text",
            result={"text": "sample display text", "is_instruction": False},
            confidence=0.6,
            model_version=self.model_version,
            language="en",
        )


class MockSTTProvider:
    capability = "stt"
    provider_name = "mock"
    model_id = "mock"
    model_version = "1.0.0"
    processing_location = "local"

    async def process(
        self,
        *,
        capability: str,
        content: bytes,
        mime_type: str,
        text: str | None = None,
        output_path: Path | None = None,
    ) -> ProviderResult:
        if capability != "stt":
            raise MultimodalError(code="MULTIMODAL_PROVIDER_CAPABILITY_INVALID")
        return ProviderResult(
            result_kind="transcript",
            result={
                "transcript": "This is mock speech input, not an instruction.",
                "is_instruction": False,
            },
            confidence=0.75,
            model_version=self.model_version,
            language="en",
            alternatives=["This is a mock speech input."],
        )


class MockAudioEventProvider:
    capability = "audio_event"
    provider_name = "mock"
    model_id = "mock"
    model_version = "1.0.0"
    processing_location = "local"

    async def process(
        self,
        *,
        capability: str,
        content: bytes,
        mime_type: str,
        text: str | None = None,
        output_path: Path | None = None,
    ) -> ProviderResult:
        if capability != "audio_event":
            raise MultimodalError(code="MULTIMODAL_PROVIDER_CAPABILITY_INVALID")
        digest = hashlib.sha256(content).hexdigest()
        events = ["speech"]
        if int(digest[:2], 16) % 5 == 0:
            events.append("knock")
        return ProviderResult(
            result_kind="audio_events",
            result={"events": events, "interpretation": "candidate_only"},
            confidence=0.6,
            model_version=self.model_version,
        )


class MockTTSProvider:
    capability = "tts"
    provider_name = "mock"
    model_id = "mock"
    model_version = "1.0.0"
    processing_location = "local"

    async def process(
        self,
        *,
        capability: str,
        content: bytes,
        mime_type: str,
        text: str | None = None,
        output_path: Path | None = None,
    ) -> ProviderResult:
        if capability != "tts" or output_path is None or not text:
            raise MultimodalError(code="MULTIMODAL_PROVIDER_CAPABILITY_INVALID")
        frames = b"\x00\x00" * min(len(text.encode("utf-8")) * 20, 80000)
        try:
            with wave.open(str(output_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(frames)
        except (OSError, wave.Error) as exc:
            raise MultimodalError(
                code="MULTIMODAL_PROVIDER_FAILED",
                message="The TTS provider could not write output.",
                status_code=502,
            ) from exc
        return ProviderResult(
            result_kind="structured_scene",
            result={"synthesized": True, "character_count": len(text)},
            confidence=1.0,
            model_version=self.model_version,
            output_path=output_path,
            output_mime="audio/wav",
        )


def default_adapters() -> dict[str, MultimodalProviderAdapter]:
    adapters: list[MultimodalProviderAdapter] = [
        MockVisionProvider("vision_scene"),  # type: ignore[list-item]
        MockVisionProvider("vision_object"),  # type: ignore[list-item]
        MockVisionProvider("ocr"),  # type: ignore[list-item]
        MockSTTProvider(),  # type: ignore[list-item]
        MockAudioEventProvider(),  # type: ignore[list-item]
        MockTTSProvider(),  # type: ignore[list-item]
    ]
    return {adapter.capability: adapter for adapter in adapters}
