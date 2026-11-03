from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import (
    CurrentStateEstimate,
    Device,
    Entity,
    EntitySpaceAssignment,
    Environment,
    EstimationTarget,
    Observation,
    ObservationSource,
    Space,
    SpacePath,
    StateEstimate,
    StateEstimateObservation,
)


def stored_as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class StateEstimateRepository:
    """Persistence boundary for estimation targets, history, and current projection."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def ensure_target(
        self,
        *,
        environment_id: str,
        target_type: str,
        attribute: str,
        strategy_id: str,
        strategy_version: str,
        validity_policy: dict[str, Any],
        conflict_policy: dict[str, Any],
        coverage_policy: dict[str, Any],
        entity_id: str | None = None,
        space_id: str | None = None,
    ) -> EstimationTarget:
        try:
            statement = select(EstimationTarget).where(
                EstimationTarget.environment_id == environment_id,
                EstimationTarget.target_type == target_type,
                EstimationTarget.entity_id == entity_id,
                EstimationTarget.space_id == space_id,
                EstimationTarget.attribute == attribute,
            )
            target = self._session.scalars(statement).first()
            if target is None:
                target = EstimationTarget(
                    environment_id=environment_id,
                    target_type=target_type,
                    entity_id=entity_id,
                    space_id=space_id,
                    attribute=attribute,
                    strategy_id=strategy_id,
                    strategy_version=strategy_version,
                    validity_policy=validity_policy,
                    conflict_policy=conflict_policy,
                    coverage_policy=coverage_policy,
                )
                self._session.add(target)
                self._session.flush()
            else:
                target.strategy_id = strategy_id
                target.strategy_version = strategy_version
                target.validity_policy = validity_policy
                target.conflict_policy = conflict_policy
                target.coverage_policy = coverage_policy
                target.enabled = True
            return target
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save an estimation target.") from exc

    def list_targets(self, *, environment_id: str | None = None) -> list[EstimationTarget]:
        try:
            statement = select(EstimationTarget)
            if environment_id is not None:
                statement = statement.where(EstimationTarget.environment_id == environment_id)
            return list(
                self._session.scalars(
                    statement.order_by(
                        EstimationTarget.target_type,
                        EstimationTarget.attribute,
                        EstimationTarget.id,
                    )
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list estimation targets.") from exc

    def get_estimate(self, estimate_id: str) -> StateEstimate | None:
        try:
            return self._session.get(StateEstimate, estimate_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a state estimate.") from exc

    def latest_estimate(self, target_id: str) -> StateEstimate | None:
        try:
            return self._session.scalars(
                select(StateEstimate)
                .where(
                    StateEstimate.target_id == target_id,
                    StateEstimate.superseded_at.is_(None),
                )
                .order_by(StateEstimate.generated_at.desc(), StateEstimate.id.desc())
                .limit(1)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read the latest state estimate.") from exc

    def add_estimate(self, estimate: StateEstimate) -> StateEstimate:
        self._session.add(estimate)
        try:
            self._session.flush()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to append a state estimate.") from exc
        return estimate

    def add_evidence(self, evidence: StateEstimateObservation) -> StateEstimateObservation:
        self._session.add(evidence)
        return evidence

    def evidence_for_estimate(self, estimate_id: str) -> list[StateEstimateObservation]:
        try:
            return list(
                self._session.scalars(
                    select(StateEstimateObservation)
                    .where(StateEstimateObservation.estimate_id == estimate_id)
                    .order_by(
                        StateEstimateObservation.contribution,
                        StateEstimateObservation.observation_id,
                    )
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read estimate evidence.") from exc

    def evidence_details_for_estimate(
        self,
        estimate_id: str,
    ) -> list[tuple[StateEstimateObservation, Observation, ObservationSource]]:
        try:
            rows = self._session.execute(
                select(StateEstimateObservation, Observation, ObservationSource)
                .join(
                    Observation,
                    StateEstimateObservation.observation_id == Observation.observation_id,
                )
                .join(ObservationSource, Observation.source_id == ObservationSource.id)
                .where(StateEstimateObservation.estimate_id == estimate_id)
                .order_by(
                    StateEstimateObservation.contribution,
                    StateEstimateObservation.observation_id,
                )
            ).all()
            return [(row[0], row[1], row[2]) for row in rows]
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read estimate evidence details.") from exc

    def list_estimates(
        self,
        *,
        environment_id: str | None = None,
        target_id: str | None = None,
        entity_id: str | None = None,
        space_id: str | None = None,
        attribute: str | None = None,
        status: str | None = None,
        include_history: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[StateEstimate], int]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("Page must be positive and page_size must be between 1 and 100")
        filters = []
        if environment_id is not None:
            filters.append(StateEstimate.environment_id == environment_id)
        if target_id is not None:
            filters.append(StateEstimate.target_id == target_id)
        if entity_id is not None:
            filters.append(EstimationTarget.entity_id == entity_id)
        if space_id is not None:
            filters.append(EstimationTarget.space_id == space_id)
        if attribute is not None:
            filters.append(EstimationTarget.attribute == attribute)
        if status is not None:
            filters.append(StateEstimate.status == status)
        if not include_history:
            filters.append(StateEstimate.superseded_at.is_(None))
        try:
            count = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(StateEstimate)
                    .join(EstimationTarget, StateEstimate.target_id == EstimationTarget.id)
                    .where(*filters)
                )
                or 0
            )
            rows = list(
                self._session.scalars(
                    select(StateEstimate)
                    .join(EstimationTarget, StateEstimate.target_id == EstimationTarget.id)
                    .where(*filters)
                    .order_by(StateEstimate.generated_at.desc(), StateEstimate.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            return rows, count
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list state estimates.") from exc

    def current_rows(
        self,
        *,
        environment_id: str,
        target_id: str | None = None,
        target_type: str | None = None,
        entity_id: str | None = None,
        space_id: str | None = None,
        attribute: str | None = None,
    ) -> list[tuple[CurrentStateEstimate, EstimationTarget, StateEstimate]]:
        try:
            statement = (
                select(CurrentStateEstimate, EstimationTarget, StateEstimate)
                .join(
                    EstimationTarget,
                    CurrentStateEstimate.target_id == EstimationTarget.id,
                )
                .join(
                    StateEstimate,
                    CurrentStateEstimate.latest_estimate_id == StateEstimate.id,
                )
                .where(CurrentStateEstimate.environment_id == environment_id)
            )
            if target_type is not None:
                statement = statement.where(EstimationTarget.target_type == target_type)
            if target_id is not None:
                statement = statement.where(EstimationTarget.id == target_id)
            if entity_id is not None:
                statement = statement.where(EstimationTarget.entity_id == entity_id)
            if space_id is not None:
                statement = statement.where(EstimationTarget.space_id == space_id)
            if attribute is not None:
                statement = statement.where(EstimationTarget.attribute == attribute)
            return [
                (row[0], row[1], row[2])
                for row in self._session.execute(
                    statement.order_by(EstimationTarget.target_type, EstimationTarget.attribute)
                ).all()
            ]
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read current state estimates.") from exc

    def current_for_target(self, target_id: str) -> CurrentStateEstimate | None:
        try:
            return self._session.get(CurrentStateEstimate, target_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a current state estimate.") from exc

    def upsert_current(
        self,
        *,
        estimate: StateEstimate,
        now: datetime,
    ) -> CurrentStateEstimate:
        try:
            current = self.current_for_target(estimate.target_id)
            if current is None:
                current = CurrentStateEstimate(
                    target_id=estimate.target_id,
                    projection_version=0,
                )
                self._session.add(current)
            current.latest_estimate_id = estimate.id
            current.environment_id = estimate.environment_id
            current.status = estimate.status
            current.value = estimate.value
            current.unit = estimate.unit
            current.confidence = estimate.confidence
            current.valid_until = estimate.valid_until
            current.refreshed_at = now
            current.projection_version += 1
            self._session.flush()
            return current
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save the current state estimate.") from exc

    def active_entity_ids(self, environment_id: str) -> list[str]:
        try:
            return list(
                self._session.scalars(
                    select(Entity.id)
                    .where(
                        Entity.environment_id == environment_id,
                        Entity.status == "active",
                    )
                    .order_by(Entity.normalized_name, Entity.id)
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list estimation entities.") from exc

    def observed_entity_attributes(self, environment_id: str) -> list[tuple[str, str]]:
        try:
            return [
                (row[0], row[1])
                for row in self._session.execute(
                    select(Observation.entity_id, Observation.attribute)
                    .join(Entity, Observation.entity_id == Entity.id)
                    .distinct()
                    .where(
                        Observation.entity_id.is_not(None),
                        Entity.environment_id == environment_id,
                    )
                    .order_by(Observation.entity_id, Observation.attribute)
                ).all()
            ]
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read observed entity attributes.") from exc

    def observed_space_attributes(self, environment_id: str) -> list[tuple[str, str]]:
        try:
            return [
                (row[0], row[1])
                for row in self._session.execute(
                    select(Observation.space_id, Observation.attribute)
                    .join(SpacePath, Observation.space_id == SpacePath.descendant_id)
                    .join(Environment, Environment.root_space_id == SpacePath.ancestor_id)
                    .distinct()
                    .where(
                        Observation.space_id.is_not(None),
                        Environment.id == environment_id,
                    )
                    .order_by(Observation.space_id, Observation.attribute)
                ).all()
            ]
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read observed space attributes.") from exc

    def descendant_space_ids(self, space_id: str) -> list[str]:
        try:
            return list(
                self._session.scalars(
                    select(SpacePath.descendant_id).where(SpacePath.ancestor_id == space_id)
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read descendant spaces.") from exc

    def candidate_observations(
        self,
        *,
        target_type: str,
        entity_id: str | None,
        space_id: str | None,
        attribute: str,
        received_after: datetime | None = None,
        limit: int = 1000,
    ) -> list[tuple[Observation, ObservationSource]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        try:
            statement = (
                select(Observation, ObservationSource)
                .join(ObservationSource, Observation.source_id == ObservationSource.id)
                .where(Observation.attribute == attribute)
            )
            if target_type == "entity":
                statement = statement.where(Observation.entity_id == entity_id)
            else:
                assert space_id is not None
                statement = statement.where(
                    Observation.space_id.in_(
                        select(SpacePath.descendant_id).where(SpacePath.ancestor_id == space_id)
                    )
                )
            if received_after is not None:
                statement = statement.where(Observation.received_at >= received_after)
            rows = self._session.execute(
                statement.order_by(
                    Observation.received_at.desc(), Observation.observation_id.desc()
                ).limit(limit)
            ).all()
            return [(row[0], row[1]) for row in rows]
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read estimation observations.") from exc

    def active_spaces_for_environment(self, environment_id: str) -> list[Space]:
        try:
            return list(
                self._session.scalars(
                    select(Space)
                    .join(SpacePath, Space.id == SpacePath.descendant_id)
                    .join(Environment, Environment.root_space_id == SpacePath.ancestor_id)
                    .where(Environment.id == environment_id)
                    .order_by(Space.path, Space.sort_order, Space.id)
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read estimation spaces.") from exc

    def entity_overviews(
        self,
        *,
        environment_id: str,
    ) -> list[tuple[Entity, Device | None, str | None]]:
        try:
            rows = self._session.execute(
                select(Entity, Device, EntitySpaceAssignment.space_id)
                .outerjoin(Device, Device.entity_id == Entity.id)
                .outerjoin(
                    EntitySpaceAssignment,
                    (EntitySpaceAssignment.entity_id == Entity.id)
                    & (EntitySpaceAssignment.valid_until.is_(None)),
                )
                .where(
                    Entity.environment_id == environment_id,
                    Entity.status == "active",
                )
                .order_by(Entity.normalized_name, Entity.id, Device.id)
            ).all()
            return [(row[0], row[1], row[2]) for row in rows]
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read estimation entity overviews.") from exc


__all__ = ["StateEstimateRepository", "stored_as_utc"]
