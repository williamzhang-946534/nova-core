from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import (
    Environment,
    MultimodalArtifactLink,
    MultimodalAuditEvent,
    MultimodalCaptureSession,
    MultimodalConsent,
    MultimodalDataAccessGrant,
    MultimodalExtractionResult,
    MultimodalMediaAsset,
    MultimodalProvider,
    MultimodalProviderInvocation,
    Observation,
    SpacePath,
)


class MultimodalRepository:
    """Transaction-bound persistence adapter for perception metadata."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_providers(self, *, enabled_only: bool = False) -> list[MultimodalProvider]:
        statement = select(MultimodalProvider).order_by(
            MultimodalProvider.capability,
            MultimodalProvider.priority,
            MultimodalProvider.provider_name,
        )
        if enabled_only:
            statement = statement.where(MultimodalProvider.enabled.is_(True))
        try:
            return list(self._session.scalars(statement))
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list multimodal providers.") from exc

    def get_provider(self, provider_id: str) -> MultimodalProvider | None:
        try:
            return self._session.get(MultimodalProvider, provider_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a multimodal provider.") from exc

    def add_consent(self, consent: MultimodalConsent) -> MultimodalConsent:
        try:
            self._session.add(consent)
            self._session.flush()
            return consent
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save multimodal consent.") from exc

    def get_consent(self, consent_id: str) -> MultimodalConsent | None:
        try:
            return self._session.get(MultimodalConsent, consent_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read multimodal consent.") from exc

    def list_consents(self, environment_id: str | None = None) -> list[MultimodalConsent]:
        statement = select(MultimodalConsent).order_by(
            MultimodalConsent.granted_at.desc(),
            MultimodalConsent.id,
        )
        if environment_id is not None:
            statement = statement.where(MultimodalConsent.environment_id == environment_id)
        try:
            return list(self._session.scalars(statement))
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list multimodal consents.") from exc

    def add_data_access_grant(
        self,
        grant: MultimodalDataAccessGrant,
    ) -> MultimodalDataAccessGrant:
        try:
            self._session.add(grant)
            self._session.flush()
            return grant
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a multimodal data access grant.") from exc

    def get_data_access_grant(self, grant_id: str) -> MultimodalDataAccessGrant | None:
        try:
            return self._session.get(MultimodalDataAccessGrant, grant_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a multimodal data access grant.") from exc

    def list_data_access_grants(
        self,
        environment_id: str | None = None,
    ) -> list[MultimodalDataAccessGrant]:
        statement = select(MultimodalDataAccessGrant).order_by(
            MultimodalDataAccessGrant.granted_at.desc(),
            MultimodalDataAccessGrant.id,
        )
        if environment_id is not None:
            statement = statement.where(MultimodalDataAccessGrant.environment_id == environment_id)
        try:
            return list(self._session.scalars(statement))
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list multimodal data access grants.") from exc

    def add_capture_session(
        self,
        capture_session: MultimodalCaptureSession,
    ) -> MultimodalCaptureSession:
        try:
            self._session.add(capture_session)
            self._session.flush()
            return capture_session
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a capture session.") from exc

    def get_capture_session(self, session_id: str) -> MultimodalCaptureSession | None:
        try:
            return self._session.get(MultimodalCaptureSession, session_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a capture session.") from exc

    def count_session_assets(self, session_id: str) -> int:
        try:
            return len(
                list(
                    self._session.scalars(
                        select(MultimodalMediaAsset.id).where(
                            MultimodalMediaAsset.capture_session_id == session_id
                        )
                    )
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to count capture session assets.") from exc

    def add_asset(self, asset: MultimodalMediaAsset) -> MultimodalMediaAsset:
        try:
            self._session.add(asset)
            self._session.flush()
            return asset
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a multimodal media asset.") from exc

    def get_asset(self, asset_id: str) -> MultimodalMediaAsset | None:
        try:
            return self._session.get(MultimodalMediaAsset, asset_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a multimodal media asset.") from exc

    def add_invocation(
        self,
        invocation: MultimodalProviderInvocation,
    ) -> MultimodalProviderInvocation:
        try:
            self._session.add(invocation)
            self._session.flush()
            return invocation
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a provider invocation.") from exc

    def get_invocation(self, invocation_id: str) -> MultimodalProviderInvocation | None:
        try:
            return self._session.get(MultimodalProviderInvocation, invocation_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a provider invocation.") from exc

    def list_assets_pending_purge(self, *, limit: int | None = None) -> list[MultimodalMediaAsset]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        statement = (
            select(MultimodalMediaAsset)
            .where(MultimodalMediaAsset.purge_status == "pending")
            .order_by(MultimodalMediaAsset.retention_until, MultimodalMediaAsset.id)
        )
        if limit is not None:
            statement = statement.limit(limit)
        try:
            return list(self._session.scalars(statement))
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list assets pending purge.") from exc

    def list_assets_by_consent(self, consent_id: str) -> list[MultimodalMediaAsset]:
        statement = (
            select(MultimodalMediaAsset)
            .where(MultimodalMediaAsset.consent_id == consent_id)
            .order_by(MultimodalMediaAsset.received_at, MultimodalMediaAsset.id)
        )
        try:
            return list(self._session.scalars(statement))
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list multimodal assets for a consent.") from exc

    def add_extraction(
        self,
        extraction: MultimodalExtractionResult,
    ) -> MultimodalExtractionResult:
        try:
            self._session.add(extraction)
            self._session.flush()
            return extraction
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save an extraction result.") from exc

    def add_artifact_link(self, link: MultimodalArtifactLink) -> MultimodalArtifactLink:
        try:
            self._session.add(link)
            self._session.flush()
            return link
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save an artifact link.") from exc

    def list_extractions(self) -> list[MultimodalExtractionResult]:
        statement = select(MultimodalExtractionResult).order_by(
            MultimodalExtractionResult.created_at.desc(),
            MultimodalExtractionResult.id,
        )
        try:
            return list(self._session.scalars(statement))
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list extraction results.") from exc

    def delete_sensitive_extractions(self, asset_id: str) -> int:
        """Physically remove text derived from media before its retention ends."""
        try:
            extraction_ids = list(
                self._session.scalars(
                    select(MultimodalExtractionResult.id).where(
                        MultimodalExtractionResult.media_asset_id == asset_id,
                        MultimodalExtractionResult.result_kind.in_(("ocr_text", "transcript")),
                    )
                )
            )
            if not extraction_ids:
                return 0
            self._session.execute(
                delete(MultimodalArtifactLink).where(
                    MultimodalArtifactLink.artifact_type == "extraction_result",
                    MultimodalArtifactLink.artifact_id.in_(extraction_ids),
                )
            )
            result = self._session.execute(
                delete(MultimodalExtractionResult).where(
                    MultimodalExtractionResult.id.in_(extraction_ids)
                )
            )
            return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to delete sensitive multimodal extractions.") from exc

    def add_audit_event(self, event: MultimodalAuditEvent) -> MultimodalAuditEvent:
        try:
            self._session.add(event)
            self._session.flush()
            return event
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a multimodal audit event.") from exc

    def list_audit_events(
        self,
        environment_id: str,
        *,
        action: str | None = None,
        limit: int = 100,
    ) -> list[MultimodalAuditEvent]:
        statement = (
            select(MultimodalAuditEvent)
            .where(MultimodalAuditEvent.environment_id == environment_id)
            .order_by(MultimodalAuditEvent.occurred_at.desc(), MultimodalAuditEvent.id.desc())
            .limit(limit)
        )
        if action is not None:
            statement = statement.where(MultimodalAuditEvent.action == action)
        try:
            return list(self._session.scalars(statement))
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list multimodal audit events.") from exc

    def list_fusion_observations(
        self,
        *,
        environment_id: str,
        from_at: datetime,
        to_at: datetime,
        space_id: str | None,
        entity_id: str | None,
        correlation_id: str | None,
    ) -> list[Observation]:
        statement = (
            select(Observation)
            .join(SpacePath, SpacePath.descendant_id == Observation.space_id)
            .join(Environment, Environment.root_space_id == SpacePath.ancestor_id)
            .where(
                Environment.id == environment_id,
                func.coalesce(Observation.observed_at, Observation.received_at).between(
                    from_at,
                    to_at,
                ),
            )
            .order_by(
                func.coalesce(Observation.observed_at, Observation.received_at),
                Observation.observation_id,
            )
        )
        if space_id is not None:
            statement = statement.where(Observation.space_id == space_id)
        if entity_id is not None:
            statement = statement.where(Observation.entity_id == entity_id)
        if correlation_id is not None:
            statement = statement.where(Observation.correlation_id == correlation_id)
        try:
            return list(self._session.scalars(statement))
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to query fusion observations.") from exc

    def list_fusion_extractions(
        self,
        *,
        environment_id: str,
        from_at: datetime,
        to_at: datetime,
        space_id: str | None,
        entity_id: str | None,
        correlation_id: str | None,
    ) -> list[tuple[MultimodalExtractionResult, MultimodalMediaAsset]]:
        statement = (
            select(MultimodalExtractionResult, MultimodalMediaAsset)
            .join(
                MultimodalMediaAsset,
                MultimodalExtractionResult.media_asset_id == MultimodalMediaAsset.id,
            )
            .where(
                MultimodalMediaAsset.environment_id == environment_id,
                MultimodalMediaAsset.media_kind != "tts_audio",
                func.coalesce(
                    MultimodalMediaAsset.client_captured_at,
                    MultimodalMediaAsset.received_at,
                ).between(from_at, to_at),
            )
            .order_by(
                func.coalesce(
                    MultimodalMediaAsset.client_captured_at,
                    MultimodalMediaAsset.received_at,
                ),
                MultimodalExtractionResult.id,
            )
        )
        if space_id is not None:
            statement = statement.where(MultimodalMediaAsset.space_id == space_id)
        if entity_id is not None:
            statement = statement.where(MultimodalMediaAsset.entity_id == entity_id)
        if correlation_id is not None:
            statement = statement.join(
                MultimodalCaptureSession,
                MultimodalMediaAsset.capture_session_id == MultimodalCaptureSession.id,
            ).where(MultimodalCaptureSession.correlation_id == correlation_id)
        try:
            return list(self._session.execute(statement).all())
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to query fusion extractions.") from exc


__all__ = ["MultimodalRepository"]
