from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import (
    Entity,
    Environment,
    EstimationTarget,
    Event,
    EvidenceBundle,
    EvidenceItem,
    Hypothesis,
    HypothesisEvidence,
    Memory,
    Observation,
    ReasoningSession,
    SpacePath,
    StateEstimate,
    Task,
)


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return (utc(value) or value).isoformat()
    return value


class ReasoningRepository:
    """Persistence boundary for reasoning work products and source resolution."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_session(self, session: ReasoningSession) -> ReasoningSession:
        try:
            session.scope = _json_safe(session.scope)
            session.diagnosis = _json_safe(session.diagnosis)
            session.analyzer_versions = _json_safe(session.analyzer_versions)
            self._session.add(session)
            self._session.flush()
            return session
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a reasoning session.") from exc

    def get_session(self, session_id: str) -> ReasoningSession | None:
        try:
            return self._session.scalars(
                select(ReasoningSession)
                .where(ReasoningSession.id == session_id)
                .options(
                    selectinload(ReasoningSession.evidence_bundles).selectinload(
                        EvidenceBundle.items
                    ),
                    selectinload(ReasoningSession.hypotheses)
                    .selectinload(Hypothesis.evidence_links)
                    .selectinload(HypothesisEvidence.evidence),
                )
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a reasoning session.") from exc

    def list_sessions(
        self,
        *,
        environment_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ReasoningSession], int]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("Page must be positive and page_size must be between 1 and 100")
        filters = []
        if environment_id is not None:
            filters.append(ReasoningSession.environment_id == environment_id)
        if status is not None:
            filters.append(ReasoningSession.status == status)
        try:
            count = int(
                self._session.scalar(
                    select(func.count()).select_from(ReasoningSession).where(*filters)
                )
                or 0
            )
            rows = list(
                self._session.scalars(
                    select(ReasoningSession)
                    .where(*filters)
                    .order_by(ReasoningSession.created_at.desc(), ReasoningSession.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            return rows, count
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list reasoning sessions.") from exc

    def add_bundle(self, bundle: EvidenceBundle) -> EvidenceBundle:
        try:
            bundle.selection_basis = _json_safe(bundle.selection_basis)
            bundle.coverage = _json_safe(bundle.coverage)
            self._session.add(bundle)
            self._session.flush()
            return bundle
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save an evidence bundle.") from exc

    def bundle(self, session_id: str) -> EvidenceBundle | None:
        try:
            return self._session.scalars(
                select(EvidenceBundle)
                .where(EvidenceBundle.session_id == session_id)
                .options(selectinload(EvidenceBundle.items))
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read an evidence bundle.") from exc

    def add_evidence(self, evidence: EvidenceItem) -> EvidenceItem:
        try:
            evidence.snapshot = _json_safe(evidence.snapshot)
            evidence.scope = _json_safe(evidence.scope)
            evidence.quality_issues = _json_safe(evidence.quality_issues)
            self._session.add(evidence)
            self._session.flush()
            return evidence
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save reasoning evidence.") from exc

    def get_evidence(self, evidence_id: str) -> EvidenceItem | None:
        try:
            return self._session.get(EvidenceItem, evidence_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read reasoning evidence.") from exc

    def list_evidence(
        self,
        bundle_id: str,
        *,
        classification: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[EvidenceItem], int]:
        if page < 1 or page_size < 1 or page_size > 200:
            raise ValueError("Page must be positive and page_size must be between 1 and 200")
        filters = [EvidenceItem.bundle_id == bundle_id]
        if classification is not None:
            filters.append(EvidenceItem.classification == classification)
        try:
            count = int(
                self._session.scalar(select(func.count()).select_from(EvidenceItem).where(*filters))
                or 0
            )
            rows = list(
                self._session.scalars(
                    select(EvidenceItem)
                    .where(*filters)
                    .order_by(EvidenceItem.created_at, EvidenceItem.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            return rows, count
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list reasoning evidence.") from exc

    def add_hypothesis(self, hypothesis: Hypothesis) -> Hypothesis:
        try:
            hypothesis.limitations = _json_safe(hypothesis.limitations or [])
            hypothesis.unknowns = _json_safe(hypothesis.unknowns or [])
            self._session.add(hypothesis)
            self._session.flush()
            return hypothesis
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a hypothesis.") from exc

    def add_hypothesis_evidence(self, link: HypothesisEvidence) -> HypothesisEvidence:
        try:
            self._session.add(link)
            self._session.flush()
            return link
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to link hypothesis evidence.") from exc

    def get_hypothesis(self, hypothesis_id: str) -> Hypothesis | None:
        try:
            return self._session.scalars(
                select(Hypothesis)
                .where(Hypothesis.id == hypothesis_id)
                .options(
                    selectinload(Hypothesis.evidence_links).selectinload(
                        HypothesisEvidence.evidence
                    )
                )
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a hypothesis.") from exc

    def list_hypotheses(
        self,
        *,
        session_id: str | None = None,
        environment_id: str | None = None,
        status: str | None = None,
        hypothesis_type: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Hypothesis], int]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("Page must be positive and page_size must be between 1 and 100")
        filters = []
        if session_id is not None:
            filters.append(Hypothesis.session_id == session_id)
        if environment_id is not None:
            filters.append(Hypothesis.environment_id == environment_id)
        if status is not None:
            filters.append(Hypothesis.status == status)
        if hypothesis_type is not None:
            filters.append(Hypothesis.hypothesis_type == hypothesis_type)
        try:
            count = int(
                self._session.scalar(select(func.count()).select_from(Hypothesis).where(*filters))
                or 0
            )
            rows = list(
                self._session.scalars(
                    select(Hypothesis)
                    .where(*filters)
                    .order_by(Hypothesis.created_at.desc(), Hypothesis.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            return rows, count
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list hypotheses.") from exc

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
            raise RepositoryError("Failed to read a reasoning environment.") from exc

    def observations(
        self,
        *,
        environment_id: str,
        start_time: datetime,
        end_time: datetime,
        space_id: str | None = None,
        entity_id: str | None = None,
        attribute: str | None = None,
        limit: int = 1000,
    ) -> list[Observation]:
        space_ids = (
            select(SpacePath.descendant_id)
            .join(Environment, Environment.root_space_id == SpacePath.ancestor_id)
            .where(Environment.id == environment_id)
        )
        filters = [
            Observation.received_at >= _stored_datetime(start_time),
            Observation.received_at <= _stored_datetime(end_time),
            or_(
                Observation.entity_id.in_(
                    select(Entity.id).where(Entity.environment_id == environment_id)
                ),
                Observation.space_id.in_(space_ids),
            ),
        ]
        if space_id is not None:
            filters.append(Observation.space_id == space_id)
        if entity_id is not None:
            filters.append(Observation.entity_id == entity_id)
        if attribute is not None:
            filters.append(Observation.attribute == attribute)
        try:
            return list(
                self._session.scalars(
                    select(Observation)
                    .where(*filters)
                    .order_by(Observation.received_at.asc(), Observation.observation_id.asc())
                    .limit(limit)
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to query reasoning observations.") from exc

    def source_record(self, source_type: str, source_record_id: str) -> tuple[str, Any] | None:
        try:
            if source_type == "observation":
                row = self._session.get(Observation, source_record_id)
            elif source_type == "state_estimate":
                row = self._session.scalars(
                    select(StateEstimate)
                    .join(EstimationTarget, StateEstimate.target_id == EstimationTarget.id)
                    .where(StateEstimate.id == source_record_id)
                ).first()
            elif source_type == "event":
                row = self._session.get(Event, source_record_id)
            elif source_type == "task":
                row = self._session.get(Task, source_record_id)
            elif source_type == "memory":
                row = self._session.get(Memory, source_record_id)
            else:
                return None
            if row is None:
                return None
            return source_type, row
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to resolve reasoning evidence source.") from exc

    def delete_session(self, session: ReasoningSession) -> None:
        try:
            self._session.delete(session)
            self._session.flush()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to delete a reasoning session.") from exc

    @staticmethod
    def keyword_matches(rows: list[Memory], keyword: str) -> list[Memory]:
        needle = keyword.casefold()
        return [
            row
            for row in rows
            if needle in row.title.casefold()
            or needle in row.content.casefold()
            or needle in (row.summary or "").casefold()
            or needle in str(row.keywords).casefold()
        ]


def _stored_datetime(value: datetime) -> datetime:
    normalized = utc(value) or datetime.now(UTC)
    return normalized.replace(tzinfo=None)


__all__ = ["ReasoningRepository", "utc"]
