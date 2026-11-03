from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import (
    Observation,
    ObservationAttributeDefinition,
    ObservationAttributePolicy,
    ObservationConsent,
    ObservationSource,
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
                .order_by(ObservationAttributePolicy.created_at.desc())
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

    def query(
        self,
        *,
        source_id: str | None = None,
        entity_id: str | None = None,
        space_id: str | None = None,
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


__all__ = [
    "ObservationAttributeRepository",
    "ObservationConsentRepository",
    "ObservationRepository",
    "ObservationSourceRepository",
]
