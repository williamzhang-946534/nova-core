import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from arvuno_core.errors import ArvunoError
from arvuno_core.events.bus import EventBus
from arvuno_core.events.models import (
    ArvunoEvent,
    ArvunoEventSource,
    ArvunoEventType,
    PrivacyErasureCompletedPayload,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.privacy.models import (
    PrivacyErasureRequest,
    PrivacyErasureResult,
    PrivacyImpact,
)


class PrivacyService:
    """Coordinates explicit user erasure across database, media, and audit boundaries."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork],
        media_root: Path,
        event_bus: EventBus,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._media_root = media_root.resolve()
        self._event_bus = event_bus

    async def impact(self, request: PrivacyErasureRequest) -> PrivacyImpact:
        self._validate(request)

        def execute() -> PrivacyImpact:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.privacy is not None
                impact = unit_of_work.privacy.impact(
                    owner_id=request.owner_id,
                    conversation_ids=request.conversation_ids,
                )
                return PrivacyImpact(owner_id=request.owner_id, **_int_fields(impact))

        return await asyncio.to_thread(execute)

    async def erase(self, request: PrivacyErasureRequest) -> PrivacyErasureResult:
        self._validate(request)
        request_id = str(uuid4())

        def execute() -> PrivacyErasureResult:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.privacy is not None
                media_keys = unit_of_work.privacy.media_keys(owner_id=request.owner_id)
                failed: list[str] = []
                for key in media_keys:
                    try:
                        path = (self._media_root / key).resolve()
                        if self._media_root in path.parents and path.is_file():
                            path.unlink()
                    except OSError:
                        failed.append(key)
                if failed:
                    raise ArvunoError(
                        code="PRIVACY_MEDIA_ERASURE_FAILED",
                        message=(
                            "Media files could not be deleted; database erasure was not committed."
                        ),
                        status_code=500,
                        details={
                            "request_id": request_id,
                            "media_files_failed": failed,
                        },
                    )
                impact = unit_of_work.privacy.impact(
                    owner_id=request.owner_id,
                    conversation_ids=request.conversation_ids,
                )
                result = unit_of_work.privacy.erase(
                    owner_id=request.owner_id,
                    conversation_ids=request.conversation_ids,
                )
                audit_preserved = impact["audit_records_preserved"]
                unit_of_work.commit()
            return PrivacyErasureResult(
                request_id=request_id,
                owner_id=request.owner_id,
                result=result,
                media_files_failed=failed,
                audit_records_preserved=audit_preserved,
                completed_at=datetime.now(UTC),
            )

        result = await asyncio.to_thread(execute)
        await self._event_bus.publish(
            ArvunoEvent(
                event_type=ArvunoEventType.PRIVACY_ERASURE_COMPLETED,
                source=ArvunoEventSource.API,
                subject_type="user",
                subject_id=request.owner_id,
                payload=PrivacyErasureCompletedPayload(
                    owner_id=request.owner_id,
                    memories_deleted=result.result["memories_deleted"],
                    preferences_deleted=result.result["preferences_deleted"],
                    media_assets_deleted=result.result["media_assets_deleted"],
                    conversations_deleted=result.result["conversations_deleted"],
                    messages_deleted=result.result["messages_deleted"],
                    provider_logs_deleted=result.result["provider_logs_deleted"],
                    audit_records_preserved=result.audit_records_preserved,
                ),
                correlation_id=result.request_id,
            )
        )
        return result

    @staticmethod
    def _validate(request: PrivacyErasureRequest) -> None:
        if request.owner_id == "local_user" and not request.confirm_local_user:
            raise ArvunoError(
                code="PRIVACY_LOCAL_USER_CONFIRMATION_REQUIRED",
                message="Erasing the default local user requires explicit confirmation.",
                status_code=409,
            )
        if len(set(request.conversation_ids)) != len(request.conversation_ids):
            raise ArvunoError(
                code="PRIVACY_REQUEST_INVALID",
                message="Conversation identifiers must be unique.",
                status_code=422,
            )


def _int_fields(values: dict[str, object]) -> dict[str, int]:
    return {
        key: int(value)
        for key, value in values.items()
        if key not in {"now"} and isinstance(value, int)
    }
