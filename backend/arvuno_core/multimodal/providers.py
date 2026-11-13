import asyncio
import hashlib
import time
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
        partial: bool = False,
    ) -> None:
        self.result_kind = result_kind
        self.result = result
        self.confidence = confidence
        self.model_version = model_version
        self.language = language
        self.alternatives = alternatives
        self.output_path = output_path
        self.output_mime = output_mime
        self.partial = partial


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


class GovernedProviderAdapter:
    """Wrap a replaceable provider with local timeout, retry, and quota policy."""

    capability = "governed"
    provider_name = "governed"
    model_id = "governed"
    model_version = "1.0.0"
    processing_location = "external"

    def __init__(
        self,
        delegate: MultimodalProviderAdapter,
        *,
        timeout_seconds: float,
        max_attempts: int = 1,
        max_requests: int | None = None,
        quota_window_seconds: float | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self._delegate = delegate
        self.capability = delegate.capability
        self.provider_name = delegate.provider_name
        self.model_id = delegate.model_id
        self.model_version = delegate.model_version
        self.processing_location = delegate.processing_location
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.max_requests = max_requests
        self.quota_window_seconds = quota_window_seconds
        self._clock = clock
        self._window_started_at = clock()
        self._request_count = 0

    async def process(
        self,
        *,
        capability: str,
        content: bytes,
        mime_type: str,
        text: str | None = None,
        output_path: Path | None = None,
    ) -> ProviderResult:
        if capability != self.capability:
            raise MultimodalError(code="MULTIMODAL_PROVIDER_CAPABILITY_INVALID")
        request_started_at = self._check_quota(reserve=False)
        deadline = request_started_at + self.timeout_seconds
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._check_quota(now=request_started_at)
            remaining = max(0.0, deadline - self._clock())
            try:
                return await asyncio.wait_for(
                    self._delegate.process(
                        capability=capability,
                        content=content,
                        mime_type=mime_type,
                        text=text,
                        output_path=output_path,
                    ),
                    timeout=remaining,
                )
            except TimeoutError as exc:
                raise MultimodalError(
                    code="MULTIMODAL_PROVIDER_TIMEOUT",
                    message="The governed provider deadline elapsed.",
                    status_code=504,
                ) from exc
            except MultimodalError as exc:
                last_error = exc
                if (
                    exc.status_code not in {408, 429, 500, 502, 503, 504}
                    or attempt == self.max_attempts
                ):
                    raise
            except (ConnectionError, OSError) as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    raise
        raise MultimodalError(
            code="MULTIMODAL_PROVIDER_FAILED",
            message=f"The governed provider failed after {attempt} attempts.",
            status_code=502,
        ) from last_error

    def _check_quota(self, *, now: float | None = None, reserve: bool = True) -> float:
        if self.max_requests is None:
            return self._clock()
        if now is None:
            now = self._clock()
        if (
            self.quota_window_seconds is not None
            and now - self._window_started_at >= self.quota_window_seconds
        ):
            self._window_started_at = now
            self._request_count = 0
        if self._request_count >= self.max_requests:
            raise MultimodalError(
                code="MULTIMODAL_PROVIDER_QUOTA_EXCEEDED",
                message="The governed provider request quota has been reached.",
                status_code=429,
            )
        if reserve:
            self._request_count += 1
        return now
