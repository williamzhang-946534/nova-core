import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from arvuno_core.estimation.models import (
    ContextInputs,
    EntityContextV2,
    EntityLayout,
    EnvironmentContextV2,
    SpaceContextV2,
    SpaceLayout,
    StateEstimateView,
)
from arvuno_core.estimation.service import StateEstimationService
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.spatial.errors import SpaceNotFoundError

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
StateKey = tuple[str, str]


class EnvironmentContextV2Service:
    """Projects current state estimates into a read-only spatial context."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        estimation_service: StateEstimationService,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._estimation_service = estimation_service

    async def build(self, now: datetime | None = None) -> EnvironmentContextV2:
        generated_at = _utc(now or datetime.now(UTC))
        inputs = await self._estimation_service.context_inputs(generated_at)
        return _build_context(inputs, generated_at=generated_at)

    async def rebuild_snapshot(
        self,
        now: datetime | None = None,
    ) -> tuple[EnvironmentContextV2, int]:
        result = await self._estimation_service.rebuild(now)
        context = await self.build(result.generated_at)
        anomaly_count = _quality(context)
        anomaly_count_total = sum(
            anomaly_count[status]
            for status in ("conflict_count", "stale_count", "unavailable_count")
        )

        def persist() -> None:
            with self._unit_of_work_factory() as uow:
                assert uow.environments is not None
                uow.environments.add_snapshot(
                    context.environment_id,
                    context=context.model_dump(mode="json"),
                    active_task_ids=[],
                    anomaly_count=anomaly_count_total,
                    context_version=2,
                    state_generated_at=result.generated_at,
                )
                uow.commit()

        await asyncio.to_thread(persist)
        return context, anomaly_count_total

    async def space_state(self, space_id: str) -> SpaceContextV2:
        context = await self.build()
        node = _find_space(context.spaces, space_id)
        if node is None:
            raise SpaceNotFoundError()
        return node


def _build_context(
    inputs: ContextInputs,
    *,
    generated_at: datetime,
) -> EnvironmentContextV2:
    states_by_target = _states_by_target(inputs.states)
    entities_by_space = _entities_by_space(inputs.entities)
    nodes = {
        space.space_id: _space_node(
            space,
            states_by_target.get(("space", space.space_id), {}),
            entities_by_space.get(space.space_id, []),
            states_by_target,
        )
        for space in inputs.spaces
    }
    children: list[SpaceContextV2] = []
    for space in inputs.spaces:
        node = nodes[space.space_id]
        if space.parent_id is None:
            children.append(node)
        elif space.parent_id in nodes:
            nodes[space.parent_id].children.append(node)
    return EnvironmentContextV2(
        environment_id=inputs.environment_id,
        root_space_id=inputs.root_space_id,
        generated_at=generated_at,
        spaces=children,
        quality=_quality_from_states(inputs.states),
    )


def _space_node(
    space: SpaceLayout,
    states: dict[str, StateEstimateView],
    entities: list[EntityLayout],
    states_by_target: dict[StateKey, dict[str, StateEstimateView]],
) -> SpaceContextV2:
    entity_nodes = [
        EntityContextV2(
            entity_id=entity.entity_id,
            name=entity.name,
            entity_type=entity.entity_type,
            device_id=entity.device_id,
            space_id=entity.space_id,
            states=states_by_target.get(("entity", entity.entity_id), {}),
        )
        for entity in entities
    ]
    return SpaceContextV2(
        space_id=space.space_id,
        parent_id=space.parent_id,
        space_type=space.space_type,
        name=space.name,
        path=space.path,
        status=space.status,
        states=states,
        entities=entity_nodes,
    )


def _states_by_target(
    states: list[StateEstimateView],
) -> dict[StateKey, dict[str, StateEstimateView]]:
    result: dict[StateKey, dict[str, StateEstimateView]] = {}
    for state in states:
        if state.target_type == "entity":
            key = ("entity", state.entity_id or "")
        elif state.target_type == "space":
            key = ("space", state.space_id or "")
        else:
            key = ("environment", "")
        result.setdefault(key, {})[state.attribute] = state
    return result


def _entities_by_space(entities: list[EntityLayout]) -> dict[str, list[EntityLayout]]:
    result: dict[str, list[EntityLayout]] = {}
    for entity in entities:
        if entity.space_id is not None:
            result.setdefault(entity.space_id, []).append(entity)
    return result


def _quality(context: EnvironmentContextV2) -> dict[str, int]:
    return _quality_from_states(_context_states(context.spaces))


def _context_states(spaces: list[SpaceContextV2]) -> list[StateEstimateView]:
    result: list[StateEstimateView] = []
    for space in spaces:
        result.extend(space.states.values())
        for entity in space.entities:
            result.extend(entity.states.values())
        result.extend(_context_states(space.children))
    return result


def _quality_from_states(states: list[StateEstimateView]) -> dict[str, int]:
    return {
        "conflict_count": sum(state.status == "conflict" for state in states),
        "stale_count": sum(state.status == "stale" for state in states),
        "unavailable_count": sum(state.status == "unavailable" for state in states),
        "unknown_count": sum(state.status == "unknown" for state in states),
    }


def _find_space(spaces: list[SpaceContextV2], space_id: str) -> SpaceContextV2 | None:
    for space in spaces:
        if space.space_id == space_id:
            return space
        child = _find_space(space.children, space_id)
        if child is not None:
            return child
    return None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["EnvironmentContextV2Service"]
