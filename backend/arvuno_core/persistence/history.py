from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import (
    Entity,
    EntitySpaceAssignment,
    Environment,
    EnvironmentSnapshot,
    Event,
    Observation,
    Space,
    SpacePath,
    Task,
)


class HistoryRepository:
    """Read-only query boundary for observations, events, tasks, and snapshots."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _utc_naive(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    def space(self, space_id: str) -> Space | None:
        try:
            return self._session.get(Space, space_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a history space.") from exc

    def spaces(self) -> list[Space]:
        try:
            return list(self._session.scalars(select(Space).order_by(Space.path)))
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list history spaces.") from exc

    def entity(self, entity_id: str) -> Entity | None:
        try:
            return self._session.get(Entity, entity_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a history entity.") from exc

    def entities(self) -> list[Entity]:
        try:
            return list(
                self._session.scalars(select(Entity).order_by(Entity.normalized_name, Entity.id))
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list history entities.") from exc

    def observation(self, observation_id: str) -> Observation | None:
        try:
            return self._session.get(Observation, observation_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a history observation.") from exc

    def event(self, event_id: str) -> Event | None:
        try:
            return self._session.get(Event, event_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a history event.") from exc

    def task(self, task_id: str) -> Task | None:
        try:
            return self._session.get(Task, task_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a history task.") from exc

    def default_environment(self, environment_name: str) -> Environment | None:
        try:
            return self._session.scalars(
                select(Environment)
                .where(Environment.name == environment_name, Environment.is_default.is_(True))
                .limit(1)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read the default history environment.") from exc

    def find_space_by_name(self, name: str) -> Space | None:
        normalized = name.strip().casefold()
        try:
            return self._session.scalars(
                select(Space)
                .where(
                    or_(
                        Space.normalized_name == normalized,
                        Space.name.ilike(f"%{name}%"),
                    )
                )
                .order_by(Space.status.desc(), Space.path)
                .limit(1)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to resolve a history space name.") from exc

    def find_entity_by_name(self, name: str) -> Entity | None:
        normalized = name.strip().casefold()
        try:
            return self._session.scalars(
                select(Entity)
                .where(
                    or_(
                        Entity.normalized_name == normalized,
                        Entity.name.ilike(f"%{name}%"),
                    )
                )
                .order_by(Entity.status.desc(), Entity.normalized_name)
                .limit(1)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to resolve a history entity name.") from exc

    def descendant_space_ids(self, space_id: str) -> list[str]:
        try:
            return list(
                self._session.scalars(
                    select(SpacePath.descendant_id).where(
                        SpacePath.ancestor_id == space_id,
                        SpacePath.descendant_id != space_id,
                    )
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read history space descendants.") from exc

    def observations(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        space_id: str | None = None,
        include_descendants: bool = False,
        entity_id: str | None = None,
        attribute: str | None = None,
        quality_status: str | None = None,
        correlation_id: str | None = None,
        limit: int = 1000,
    ) -> list[Observation]:
        if limit < 1:
            raise ValueError("limit must be positive")
        filters = [
            Observation.received_at >= self._utc_naive(start_time),
            Observation.received_at <= self._utc_naive(end_time),
        ]
        if space_id is not None:
            if include_descendants:
                filters.append(
                    Observation.space_id.in_(
                        select(SpacePath.descendant_id).where(
                            SpacePath.ancestor_id == space_id,
                            SpacePath.descendant_id != space_id,
                        )
                    )
                )
            else:
                filters.append(Observation.space_id == space_id)
        if entity_id is not None:
            filters.append(Observation.entity_id == entity_id)
        if attribute is not None:
            filters.append(Observation.attribute == attribute)
        if quality_status is not None:
            filters.append(Observation.quality_status == quality_status)
        if correlation_id is not None:
            filters.append(Observation.correlation_id == correlation_id)
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
            raise RepositoryError("Failed to query history observations.") from exc

    def events(
        self,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        correlation_id: str | None = None,
        limit: int = 1000,
    ) -> list[Event]:
        if limit < 1:
            raise ValueError("limit must be positive")
        filters = []
        if start_time is not None:
            filters.append(Event.occurred_at >= self._utc_naive(start_time))
        if end_time is not None:
            filters.append(Event.occurred_at <= self._utc_naive(end_time))
        if subject_type is not None:
            filters.append(Event.subject_type == subject_type)
        if subject_id is not None:
            filters.append(Event.subject_id == subject_id)
        if correlation_id is not None:
            filters.append(Event.correlation_id == correlation_id)
        try:
            return list(
                self._session.scalars(
                    select(Event)
                    .where(*filters)
                    .order_by(Event.occurred_at.asc(), Event.id.asc())
                    .limit(limit)
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to query history events.") from exc

    def tasks(
        self,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        correlation_id: str | None = None,
        limit: int = 100,
    ) -> list[Task]:
        if limit < 1:
            raise ValueError("limit must be positive")
        filters = []
        if start_time is not None:
            filters.append(Task.created_at >= self._utc_naive(start_time))
        if end_time is not None:
            filters.append(Task.created_at <= self._utc_naive(end_time))
        if correlation_id is not None:
            filters.append(Task.correlation_id == correlation_id)
        try:
            return list(
                self._session.scalars(
                    select(Task)
                    .where(*filters)
                    .order_by(Task.created_at.asc(), Task.id.asc())
                    .limit(limit)
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to query history tasks.") from exc

    def entity_assignments(
        self,
        *,
        entity_id: str | None = None,
        space_id: str | None = None,
        at_time: datetime | None = None,
    ) -> list[EntitySpaceAssignment]:
        try:
            statement = select(EntitySpaceAssignment).order_by(
                EntitySpaceAssignment.valid_from.asc(), EntitySpaceAssignment.id.asc()
            )
            if entity_id is not None:
                statement = statement.where(EntitySpaceAssignment.entity_id == entity_id)
            if space_id is not None:
                statement = statement.where(
                    EntitySpaceAssignment.space_id.in_(
                        select(SpacePath.descendant_id).where(SpacePath.ancestor_id == space_id)
                    )
                )
            if at_time is not None:
                at_time = self._utc_naive(at_time)
                statement = statement.where(
                    EntitySpaceAssignment.valid_from <= at_time,
                    or_(
                        EntitySpaceAssignment.valid_until.is_(None),
                        EntitySpaceAssignment.valid_until > at_time,
                    ),
                )
            return list(self._session.scalars(statement))
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to query historical space assignments.") from exc

    def snapshot(self, snapshot_id: str) -> EnvironmentSnapshot | None:
        try:
            return self._session.get(EnvironmentSnapshot, snapshot_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read an environment snapshot.") from exc

    def snapshot_at_or_before(
        self,
        *,
        environment_id: str,
        at_time: datetime,
    ) -> EnvironmentSnapshot | None:
        try:
            at_time = self._utc_naive(at_time)
            return self._session.scalars(
                select(EnvironmentSnapshot)
                .where(
                    EnvironmentSnapshot.environment_id == environment_id,
                    EnvironmentSnapshot.created_at <= at_time,
                )
                .order_by(
                    EnvironmentSnapshot.created_at.desc(),
                    EnvironmentSnapshot.id.desc(),
                )
                .limit(1)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to locate an environment snapshot.") from exc

    def nearest_snapshot(
        self,
        *,
        environment_id: str,
        at_time: datetime,
    ) -> tuple[EnvironmentSnapshot | None, int]:
        try:
            at_time = self._utc_naive(at_time)
            snapshot = self.snapshot_at_or_before(
                environment_id=environment_id,
                at_time=at_time,
            )
            if snapshot is not None:
                distance = int(abs((at_time - snapshot.created_at).total_seconds()))
                return snapshot, distance
            snapshot = self._session.scalars(
                select(EnvironmentSnapshot)
                .where(EnvironmentSnapshot.environment_id == environment_id)
                .order_by(EnvironmentSnapshot.created_at.asc(), EnvironmentSnapshot.id.asc())
                .limit(1)
            ).first()
            distance = (
                int(abs((snapshot.created_at - at_time).total_seconds()))
                if snapshot is not None
                else None
            )
            return snapshot, distance or 0
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to locate the nearest environment snapshot.") from exc

    def snapshots_around(
        self,
        *,
        environment_id: str,
        at_time: datetime,
        limit: int = 2,
    ) -> list[EnvironmentSnapshot]:
        if limit < 1:
            raise ValueError("limit must be positive")
        try:
            at_time = self._utc_naive(at_time)
            before = list(
                self._session.scalars(
                    select(EnvironmentSnapshot)
                    .where(
                        EnvironmentSnapshot.environment_id == environment_id,
                        EnvironmentSnapshot.created_at <= at_time,
                    )
                    .order_by(EnvironmentSnapshot.created_at.desc())
                    .limit(limit)
                )
            )
            after = list(
                self._session.scalars(
                    select(EnvironmentSnapshot)
                    .where(
                        EnvironmentSnapshot.environment_id == environment_id,
                        EnvironmentSnapshot.created_at > at_time,
                    )
                    .order_by(EnvironmentSnapshot.created_at.asc())
                    .limit(limit)
                )
            )
            return sorted([*before, *after], key=lambda item: (item.created_at, item.id))
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to locate snapshots around a time.") from exc


__all__ = ["HistoryRepository"]
