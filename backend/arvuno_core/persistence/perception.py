from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import (
    ActivePerceptionRequest,
    Environment,
    Hypothesis,
    ObservationConsent,
    ReasoningSession,
)


def stored_datetime(value: datetime) -> datetime:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).replace(tzinfo=None)


class PerceptionRepository:
    """Persistence boundary for active perception decisions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def environment(self, environment_id: str | None, name: str) -> Environment | None:
        try:
            statement = select(Environment)
            if environment_id is not None:
                statement = statement.where(Environment.id == environment_id)
            else:
                statement = statement.where(
                    Environment.name == name,
                    Environment.is_default.is_(True),
                )
            return self._session.scalars(
                statement.order_by(Environment.created_at).limit(1)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read the active perception environment.") from exc

    def reasoning_session(self, session_id: str) -> ReasoningSession | None:
        try:
            return self._session.get(ReasoningSession, session_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read the reasoning session.") from exc

    def hypothesis(self, hypothesis_id: str) -> Hypothesis | None:
        try:
            return self._session.get(Hypothesis, hypothesis_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read the hypothesis.") from exc

    def get_consent(self, consent_id: str) -> ObservationConsent | None:
        try:
            return self._session.get(ObservationConsent, consent_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read the observation consent.") from exc

    def add(self, request: ActivePerceptionRequest) -> ActivePerceptionRequest:
        try:
            self._session.add(request)
            self._session.flush()
            return request
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save an active perception request.") from exc

    def get(self, request_id: str) -> ActivePerceptionRequest | None:
        try:
            return self._session.get(ActivePerceptionRequest, request_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read an active perception request.") from exc

    def list(
        self,
        *,
        environment_id: str | None = None,
        status: str | None = None,
        gap_type: str | None = None,
        privacy_level: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ActivePerceptionRequest], int]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("Page must be positive and page_size must be between 1 and 100")
        filters: list[Any] = []
        if environment_id is not None:
            filters.append(ActivePerceptionRequest.environment_id == environment_id)
        if status is not None:
            filters.append(ActivePerceptionRequest.status == status)
        if gap_type is not None:
            filters.append(ActivePerceptionRequest.gap_type == gap_type)
        if privacy_level is not None:
            filters.append(ActivePerceptionRequest.privacy_level == privacy_level)
        try:
            count = int(
                self._session.scalar(
                    select(func.count()).select_from(ActivePerceptionRequest).where(*filters)
                )
                or 0
            )
            rows = list(
                self._session.scalars(
                    select(ActivePerceptionRequest)
                    .where(*filters)
                    .order_by(
                        ActivePerceptionRequest.created_at.desc(),
                        ActivePerceptionRequest.id.desc(),
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            return rows, count
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list active perception requests.") from exc

    def active_for_gap(
        self,
        *,
        environment_id: str,
        gap_type: str,
        subject_type: str,
        subject_id: str,
        attribute: str,
    ) -> ActivePerceptionRequest | None:
        # Rejected and fulfilled requests remain de-duplicated until they expire.
        # Unavailable and expired requests can be retried when capability changes.
        active_statuses = (
            "proposed",
            "awaiting_consent",
            "rejected",
            "queued",
            "executed",
            "fulfilled",
        )
        try:
            return self._session.scalars(
                select(ActivePerceptionRequest)
                .where(
                    ActivePerceptionRequest.environment_id == environment_id,
                    ActivePerceptionRequest.gap_type == gap_type,
                    ActivePerceptionRequest.subject_type == subject_type,
                    ActivePerceptionRequest.subject_id == subject_id,
                    ActivePerceptionRequest.attribute == attribute,
                    ActivePerceptionRequest.status.in_(active_statuses),
                )
                .order_by(ActivePerceptionRequest.created_at.desc())
                .limit(1)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to find an active perception request.") from exc

    def mark(self, request: ActivePerceptionRequest) -> ActivePerceptionRequest:
        try:
            self._session.flush()
            return request
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to update an active perception request.") from exc

    def delete(self, request: ActivePerceptionRequest) -> None:
        try:
            self._session.delete(request)
            self._session.flush()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to delete an active perception request.") from exc

    def expire_stale(self, *, now: datetime) -> int:
        stale_statuses = ("proposed", "awaiting_consent", "queued", "unavailable")
        try:
            rows = list(
                self._session.scalars(
                    select(ActivePerceptionRequest).where(
                        ActivePerceptionRequest.status.in_(stale_statuses),
                        ActivePerceptionRequest.expires_at.is_not(None),
                        ActivePerceptionRequest.expires_at <= stored_datetime(now),
                    )
                )
            )
            for row in rows:
                row.status = "expired"
            self._session.flush()
            return len(rows)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to expire active perception requests.") from exc


__all__ = ["PerceptionRepository", "stored_datetime"]
