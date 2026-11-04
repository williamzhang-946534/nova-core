from typing import Protocol

from arvuno_core.persistence.history import HistoryRepository
from arvuno_core.persistence.models import (
    Entity,
    EntitySpaceAssignment,
    Environment,
    EnvironmentSnapshot,
    Event,
    Observation,
    Space,
    Task,
)


class HistoryStore(Protocol):
    """Read-only history boundary; callers never receive a SQLAlchemy session."""

    def space(self, space_id: str) -> Space | None: ...

    def spaces(self) -> list[Space]: ...

    def entity(self, entity_id: str) -> Entity | None: ...

    def entities(self) -> list[Entity]: ...

    def observation(self, observation_id: str) -> Observation | None: ...

    def event(self, event_id: str) -> Event | None: ...

    def task(self, task_id: str) -> Task | None: ...

    def default_environment(self, environment_name: str) -> Environment | None: ...

    def find_space_by_name(self, name: str) -> Space | None: ...

    def find_entity_by_name(self, name: str) -> Entity | None: ...

    def descendant_space_ids(self, space_id: str) -> list[str]: ...

    def observations(self, **filters: object) -> list[Observation]: ...

    def events(self, **filters: object) -> list[Event]: ...

    def tasks(self, **filters: object) -> list[Task]: ...

    def entity_assignments(self, **filters: object) -> list[EntitySpaceAssignment]: ...

    def snapshot(self, snapshot_id: str) -> EnvironmentSnapshot | None: ...

    def snapshot_at_or_before(self, **filters: object) -> EnvironmentSnapshot | None: ...

    def nearest_snapshot(self, **filters: object) -> tuple[EnvironmentSnapshot | None, int]: ...

    def snapshots_around(self, **filters: object) -> list[EnvironmentSnapshot]: ...


class SqlAlchemyHistoryStore:
    """Expose the read-only repository through the HistoryStore contract."""

    def __init__(self, repository: HistoryRepository) -> None:
        self._repository = repository

    def space(self, space_id: str) -> Space | None:
        return self._repository.space(space_id)

    def spaces(self) -> list[Space]:
        return self._repository.spaces()

    def entity(self, entity_id: str) -> Entity | None:
        return self._repository.entity(entity_id)

    def entities(self) -> list[Entity]:
        return self._repository.entities()

    def observation(self, observation_id: str) -> Observation | None:
        return self._repository.observation(observation_id)

    def event(self, event_id: str) -> Event | None:
        return self._repository.event(event_id)

    def task(self, task_id: str) -> Task | None:
        return self._repository.task(task_id)

    def default_environment(self, environment_name: str) -> Environment | None:
        return self._repository.default_environment(environment_name)

    def find_space_by_name(self, name: str) -> Space | None:
        return self._repository.find_space_by_name(name)

    def find_entity_by_name(self, name: str) -> Entity | None:
        return self._repository.find_entity_by_name(name)

    def descendant_space_ids(self, space_id: str) -> list[str]:
        return self._repository.descendant_space_ids(space_id)

    def observations(self, **filters: object) -> list[Observation]:
        return self._repository.observations(**filters)  # type: ignore[arg-type]

    def events(self, **filters: object) -> list[Event]:
        return self._repository.events(**filters)  # type: ignore[arg-type]

    def tasks(self, **filters: object) -> list[Task]:
        return self._repository.tasks(**filters)  # type: ignore[arg-type]

    def entity_assignments(self, **filters: object) -> list[EntitySpaceAssignment]:
        return self._repository.entity_assignments(**filters)  # type: ignore[arg-type]

    def snapshot(self, snapshot_id: str) -> EnvironmentSnapshot | None:
        return self._repository.snapshot(snapshot_id)

    def snapshot_at_or_before(self, **filters: object) -> EnvironmentSnapshot | None:
        return self._repository.snapshot_at_or_before(**filters)  # type: ignore[arg-type]

    def nearest_snapshot(self, **filters: object) -> tuple[EnvironmentSnapshot | None, int]:
        return self._repository.nearest_snapshot(**filters)  # type: ignore[arg-type]

    def snapshots_around(self, **filters: object) -> list[EnvironmentSnapshot]:
        return self._repository.snapshots_around(**filters)  # type: ignore[arg-type]


__all__ = ["HistoryStore", "SqlAlchemyHistoryStore"]
