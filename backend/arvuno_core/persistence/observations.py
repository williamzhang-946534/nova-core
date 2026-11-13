from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import (
    Observation,
    ObservationAttributeDefinition,
    ObservationAttributePolicy,
    ObservationConsent,
    ObservationIngestionBatch,
    ObservationSource,
    ObservationSourceHeartbeat,
    SpacePath,
)


class ObservationSourceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, source_id: str) -> ObservationSource | None:
        try:
            return self._session.get(ObservationSource, source_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read an observation source.") from exc

    def get_by_adapter(self, adapter_id: str) -> ObservationSource | None:
        try:
            return self._session.scalars(
                select(ObservationSource).where(ObservationSource.adapter_id == adapter_id)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read an observation source.") from exc

    def list_sources(self, *, source_type: str | None = None) -> list[ObservationSource]:
        statement = select(ObservationSource).order_by(ObservationSource.name, ObservationSource.id)
        if source_type is not None:
            statement = statement.where(ObservationSource.source_type == source_type)
        try:
            return list(self._session.scalars(statement))
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list observation sources.") from exc

    def add(self, source: ObservationSource) -> ObservationSource:
        self._session.add(source)
        return source

    def flush(self) -> None:
        try:
            self._session.flush()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save an observation source.") from exc


class ObservationAttributeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, attribute: str) -> ObservationAttributeDefinition | None:
        try:
            return self._session.get(ObservationAttributeDefinition, attribute)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read an observation attribute.") from exc

    def list_attributes(self) -> list[ObservationAttributeDefinition]:
        try:
            return list(
                self._session.scalars(
                    select(ObservationAttributeDefinition).order_by(
                        ObservationAttributeDefinition.attribute
                    )
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list observation attributes.") from exc

    def latest_policy(self, attribute: str) -> ObservationAttributePolicy | None:
        try:
            return self._session.scalars(
                select(ObservationAttributePolicy)
                .where(ObservationAttributePolicy.attribute == attribute)
                .order_by(func.julianday(ObservationAttributePolicy.created_at).desc())
                .limit(1)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read an observation policy.") from exc

    def add(self, definition: ObservationAttributeDefinition) -> ObservationAttributeDefinition:
        self._session.add(definition)
        return definition


class ObservationConsentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def effective(
        self,
        *,
        subject_type: str,
        subject_id: str,
        attribute: str,
        now: datetime,
    ) -> ObservationConsent | None:
        try:
            return self._session.scalars(
                select(ObservationConsent)
                .where(
                    ObservationConsent.subject_type == subject_type,
                    ObservationConsent.subject_id == subject_id,
                    ObservationConsent.attribute == attribute,
                    ObservationConsent.status == "granted",
                    ObservationConsent.granted_at <= now,
                    (ObservationConsent.expires_at.is_(None))
                    | (ObservationConsent.expires_at > now),
                )
                .order_by(ObservationConsent.granted_at.desc())
                .limit(1)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read an observation consent.") from exc

    def add(self, consent: ObservationConsent) -> ObservationConsent:
        self._session.add(consent)
        self._session.flush()
        return consent


class ObservationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, observation_id: str) -> Observation | None:
        try:
            return self._session.get(Observation, observation_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read an observation.") from exc

    def get_by_dedupe_key(self, dedupe_key: str) -> Observation | None:
        try:
            return self._session.scalars(
                select(Observation).where(Observation.dedupe_key == dedupe_key)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read an observation dedupe key.") from exc

    def latest_for_series(
        self,
        *,
        source_id: str,
        entity_id: str | None,
        subject_type: str | None,
        subject_id: str | None,
        attribute: str,
    ) -> Observation | None:
        try:
            statement = (
                select(Observation)
                .where(
                    Observation.source_id == source_id,
                    Observation.entity_id == entity_id,
                    Observation.subject_type == subject_type,
                    Observation.subject_id == subject_id,
                    Observation.attribute == attribute,
                )
                .order_by(Observation.received_at.desc(), Observation.observation_id.desc())
                .limit(1)
            )
            return self._session.scalars(statement).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read the latest observation.") from exc

    def source_ids_for_attribute(self, attribute: str) -> set[str]:
        try:
            rows = self._session.scalars(
                select(Observation.source_id).where(Observation.attribute == attribute).distinct()
            )
            return set(rows)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read observation source usage.") from exc

    def append(self, observation: Observation) -> tuple[Observation, bool]:
        existing = self.get_by_dedupe_key(observation.dedupe_key)
        if existing is not None:
            return existing, True
        try:
            self._session.add(observation)
            self._session.flush()
            return observation, False
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to append an observation.") from exc

    def cleanup_expired(self, *, now: datetime, limit: int = 1000) -> int:
        if limit < 1:
            raise ValueError("limit must be positive")
        try:
            ids = list(
                self._session.scalars(
                    select(Observation.observation_id)
                    .where(
                        Observation.retention_until.is_not(None),
                        Observation.retention_until <= now,
                    )
                    .order_by(Observation.retention_until)
                    .limit(limit)
                )
            )
            if not ids:
                return 0
            result = self._session.execute(
                delete(Observation).where(Observation.observation_id.in_(ids))
            )
            return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to clean up observations.") from exc

    def query(
        self,
        *,
        source_id: str | None = None,
        entity_id: str | None = None,
        space_id: str | None = None,
        include_descendants: bool = False,
        attribute: str | None = None,
        quality_status: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        correlation_id: str | None = None,
        external_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Observation], int]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("Page must be positive and page_size must be between 1 and 100")
        filters = []
        if source_id is not None:
            filters.append(Observation.source_id == source_id)
        if entity_id is not None:
            filters.append(Observation.entity_id == entity_id)
        if space_id is not None:
            if include_descendants:
                filters.append(
                    Observation.space_id.in_(
                        select(SpacePath.descendant_id).where(SpacePath.ancestor_id == space_id)
                    )
                )
            else:
                filters.append(Observation.space_id == space_id)
        if attribute is not None:
            filters.append(Observation.attribute == attribute)
        if quality_status is not None:
            filters.append(Observation.quality_status == quality_status)
        if correlation_id is not None:
            filters.append(Observation.correlation_id == correlation_id)
        if external_id is not None:
            filters.append(Observation.external_id == external_id)
        if start_time is not None:
            filters.append(Observation.received_at >= start_time)
        if end_time is not None:
            filters.append(Observation.received_at <= end_time)
        try:
            count = (
                self._session.scalar(select(func.count()).select_from(Observation).where(*filters))
                or 0
            )
            rows = list(
                self._session.scalars(
                    select(Observation)
                    .where(*filters)
                    .order_by(Observation.received_at.desc(), Observation.observation_id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            return rows, int(count)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to query observations.") from exc


class ObservationIngestionBatchRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, batch_id: str) -> ObservationIngestionBatch | None:
        try:
            return self._session.get(ObservationIngestionBatch, batch_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read an observation batch.") from exc

    def start(
        self,
        *,
        batch_id: str,
        source_id: str | None,
        adapter_id: str,
        correlation_id: str | None,
        received_at: datetime,
        total: int,
    ) -> ObservationIngestionBatch:
        try:
            batch = self.get(batch_id)
            if batch is None:
                batch = ObservationIngestionBatch(
                    id=batch_id,
                    source_id=source_id,
                    source_type="adapter",
                    adapter_id=adapter_id,
                    correlation_id=correlation_id,
                    received_at=received_at,
                    status="processing",
                    total=total,
                    started_at=datetime.now(UTC),
                )
                self._session.add(batch)
            else:
                batch.source_id = source_id
                batch.adapter_id = adapter_id
                batch.correlation_id = correlation_id
                batch.received_at = received_at
                batch.status = "processing"
                batch.total = total
                batch.accepted = 0
                batch.deduplicated = 0
                batch.sampled = 0
                batch.invalid = 0
                batch.errors = []
                batch.error = None
                batch.completed_at = None
                batch.started_at = datetime.now(UTC)
            self._session.flush()
            return batch
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save an observation batch.") from exc

    def complete(
        self,
        batch: ObservationIngestionBatch,
        *,
        accepted: int,
        deduplicated: int,
        sampled: int,
        invalid: int,
        errors: list[dict[str, object]],
    ) -> ObservationIngestionBatch:
        batch.status = "completed"
        batch.accepted = accepted
        batch.deduplicated = deduplicated
        batch.sampled = sampled
        batch.invalid = invalid
        batch.errors = errors  # type: ignore[assignment]
        batch.completed_at = datetime.now(UTC)
        return batch

    def fail(
        self,
        batch: ObservationIngestionBatch,
        *,
        error: str,
    ) -> ObservationIngestionBatch:
        try:
            batch.status = "failed"
            batch.error = error
            batch.completed_at = datetime.now(UTC)
            return batch
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to mark an observation batch failed.") from exc

    def cleanup_expired(
        self,
        *,
        now: datetime,
        retention_days: int = 30,
        limit: int | None = None,
    ) -> int:
        if retention_days < 1 or (limit is not None and limit < 1):
            raise ValueError("Retention period and limit must be positive")
        cutoff = now - timedelta(days=retention_days)
        try:
            statement = (
                select(ObservationIngestionBatch.id)
                .where(ObservationIngestionBatch.received_at < cutoff)
                .order_by(ObservationIngestionBatch.received_at, ObservationIngestionBatch.id)
            )
            if limit is not None:
                statement = statement.limit(limit)
            ids = list(self._session.scalars(statement))
            if not ids:
                return 0
            result = self._session.execute(
                delete(ObservationIngestionBatch).where(ObservationIngestionBatch.id.in_(ids))
            )
            return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to clean up observation batches.") from exc


class ObservationSourceHeartbeatRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record_success(
        self,
        *,
        source_id: str,
        seen_at: datetime,
        batch_id: str,
    ) -> ObservationSourceHeartbeat:
        try:
            heartbeat = self._session.get(ObservationSourceHeartbeat, source_id)
            if heartbeat is None:
                heartbeat = ObservationSourceHeartbeat(source_id=source_id, status="healthy")
                self._session.add(heartbeat)
            heartbeat.last_seen_at = seen_at
            heartbeat.last_success_at = seen_at
            heartbeat.status = "healthy"
            heartbeat.consecutive_failures = 0
            heartbeat.last_batch_id = batch_id
            heartbeat.last_error = None
            return heartbeat
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save an observation source heartbeat.") from exc

    def record_failure(
        self,
        *,
        source_id: str,
        seen_at: datetime,
        batch_id: str,
        error: str,
    ) -> ObservationSourceHeartbeat:
        try:
            heartbeat = self._session.get(ObservationSourceHeartbeat, source_id)
            if heartbeat is None:
                heartbeat = ObservationSourceHeartbeat(source_id=source_id, status="failed")
                self._session.add(heartbeat)
            heartbeat.last_seen_at = seen_at
            heartbeat.last_failure_at = seen_at
            heartbeat.status = "failed"
            if heartbeat.consecutive_failures is None:
                heartbeat.consecutive_failures = 0
            heartbeat.consecutive_failures += 1
            heartbeat.last_batch_id = batch_id
            heartbeat.last_error = error
            return heartbeat
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save an observation source heartbeat.") from exc


__all__ = [
    "ObservationIngestionBatchRepository",
    "ObservationAttributeRepository",
    "ObservationConsentRepository",
    "ObservationRepository",
    "ObservationSourceRepository",
    "ObservationSourceHeartbeatRepository",
]
