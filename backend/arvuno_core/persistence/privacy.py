from typing import Any

from sqlalchemy import delete, false, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import (
    Conversation,
    ConversationMessage,
    Event,
    Memory,
    MemoryConsent,
    MultimodalCaptureSession,
    MultimodalConsent,
    MultimodalDataAccessGrant,
    MultimodalMediaAsset,
    ProviderLog,
    UserPreference,
)


class PrivacyRepository:
    """Transactional boundary for explicit user-level data erasure."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def impact(self, *, owner_id: str, conversation_ids: list[str]) -> dict[str, Any]:
        conversation_filter = Conversation.id.in_(conversation_ids) if conversation_ids else false()
        message_filter = (
            ConversationMessage.conversation_id.in_(conversation_ids)
            if conversation_ids
            else false()
        )
        provider_filter = (
            ProviderLog.input_summary["correlation_id"].as_string().in_(conversation_ids)
            if conversation_ids
            else false()
        )
        media_statement = (
            select(func.count())
            .select_from(MultimodalMediaAsset)
            .join(MultimodalConsent, MultimodalConsent.id == MultimodalMediaAsset.consent_id)
            .where(MultimodalConsent.user_id == owner_id)
        )
        try:
            return {
                "memories": self._count(Memory, Memory.owner_id == owner_id),
                "memory_consents": self._count(MemoryConsent, MemoryConsent.subject_id == owner_id),
                "preferences": self._count(
                    UserPreference, UserPreference.scope["owner_id"].as_string() == owner_id
                ),
                "multimodal_consents": self._count(
                    MultimodalConsent, MultimodalConsent.user_id == owner_id
                ),
                "data_access_grants": self._count(
                    MultimodalDataAccessGrant, MultimodalDataAccessGrant.user_id == owner_id
                ),
                "media_assets": int(self._session.scalar(media_statement) or 0),
                "capture_sessions": self._count(
                    MultimodalCaptureSession,
                    MultimodalCaptureSession.requested_by == owner_id,
                ),
                "conversations": self._count(Conversation, conversation_filter),
                "messages": self._count(ConversationMessage, message_filter),
                "provider_logs": self._count(ProviderLog, provider_filter),
                "audit_records_preserved": self._count(Event, Event.subject_id == owner_id),
            }
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to assess privacy erasure impact.") from exc

    def media_keys(self, *, owner_id: str) -> list[str]:
        try:
            return list(
                self._session.scalars(
                    select(MultimodalMediaAsset.storage_key)
                    .join(
                        MultimodalConsent,
                        MultimodalConsent.id == MultimodalMediaAsset.consent_id,
                    )
                    .where(
                        MultimodalConsent.user_id == owner_id,
                        MultimodalMediaAsset.storage_key.is_not(None),
                    )
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list privacy erasure media.") from exc

    def erase(self, *, owner_id: str, conversation_ids: list[str]) -> dict[str, int]:
        try:
            deleted_provider_logs = 0
            deleted_messages = 0
            deleted_conversations = 0
            if conversation_ids:
                deleted_provider_logs = self._delete(
                    ProviderLog,
                    ProviderLog.input_summary["correlation_id"].as_string().in_(conversation_ids),
                )
                deleted_messages = self._delete(
                    ConversationMessage,
                    ConversationMessage.conversation_id.in_(conversation_ids),
                )
                deleted_conversations = self._delete(
                    Conversation,
                    Conversation.id.in_(conversation_ids),
                )
            return {
                "memories_deleted": self._delete(Memory, Memory.owner_id == owner_id),
                "memory_consents_deleted": self._delete(
                    MemoryConsent,
                    MemoryConsent.subject_id == owner_id,
                ),
                "preferences_deleted": self._delete(
                    UserPreference,
                    UserPreference.scope["owner_id"].as_string() == owner_id,
                ),
                "media_assets_deleted": self._delete(
                    MultimodalMediaAsset,
                    MultimodalMediaAsset.consent_id.in_(
                        select(MultimodalConsent.id).where(MultimodalConsent.user_id == owner_id)
                    ),
                ),
                "data_access_grants_deleted": self._delete(
                    MultimodalDataAccessGrant,
                    MultimodalDataAccessGrant.user_id == owner_id,
                ),
                "capture_sessions_deleted": self._delete(
                    MultimodalCaptureSession,
                    MultimodalCaptureSession.requested_by == owner_id,
                ),
                "multimodal_consents_deleted": self._delete(
                    MultimodalConsent,
                    MultimodalConsent.user_id == owner_id,
                ),
                "provider_logs_deleted": deleted_provider_logs,
                "messages_deleted": deleted_messages,
                "conversations_deleted": deleted_conversations,
            }
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to execute privacy erasure.") from exc

    def _count(self, model: type, *filters: object) -> int:
        try:
            return int(
                self._session.scalar(select(func.count()).select_from(model).where(*filters)) or 0
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to count privacy erasure records.") from exc

    def _delete(self, model: type, *filters: object) -> int:
        result = self._session.execute(delete(model).where(*filters))
        return result.rowcount or 0
