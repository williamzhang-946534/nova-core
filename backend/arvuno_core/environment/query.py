import logging
from collections.abc import Callable
from datetime import UTC, datetime

from arvuno_core.environment.query_models import (
    EnvironmentQueryResult,
    EnvironmentStateQueryInput,
    QueriedEntitySummary,
    QueriedSpaceSummary,
    QueryExplanation,
    QuerySourceSummary,
    StateCoverage,
)
from arvuno_core.estimation.errors import StateEstimateNotFoundError
from arvuno_core.estimation.models import (
    ContextInputs,
    EntityLayout,
    SpaceLayout,
    StateEstimateEvidence,
    StateEstimateView,
)
from arvuno_core.estimation.service import StateEstimationService
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.spatial.errors import SpaceNotFoundError

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]

DEFAULT_COVERAGE_ATTRIBUTES = (
    "temperature",
    "humidity",
    "occupancy",
    "contact",
    "illumination",
)


logger = logging.getLogger(__name__)


class EnvironmentQueryService:
    """Read-only spatial aggregation over current state estimates."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        estimation_service: StateEstimationService,
        *,
        environment_name: str = "home",
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._estimation_service = estimation_service
        self._environment_name = environment_name

    async def query(
        self,
        request: EnvironmentStateQueryInput | None = None,
        *,
        now: datetime | None = None,
    ) -> EnvironmentQueryResult:
        request = request or EnvironmentStateQueryInput()
        generated_at = _utc(now or datetime.now(UTC))
        inputs = await self._estimation_service.context_inputs(generated_at)
        visible = self._visible_spaces(inputs, request)
        selected = self._selected_space(inputs, request)
        if selected is None:
            raise SpaceNotFoundError()

        visible_ids = {space.space_id for space in visible}
        visible_entities = [entity for entity in inputs.entities if entity.space_id in visible_ids]
        entity_ids = {entity.entity_id for entity in visible_entities}
        attributes = self._attributes(inputs, request)
        states = [
            state
            for state in inputs.states
            if state.attribute in attributes
            and (
                (state.target_type == "space" and state.space_id in visible_ids)
                or (state.target_type == "entity" and state.entity_id in entity_ids)
            )
        ]
        evidence = await self._evidence_for_states(states) if request.include_evidence else []
        return EnvironmentQueryResult(
            environment_id=inputs.environment_id,
            environment_name=self._environment_name,
            root_space_id=inputs.root_space_id,
            selected_space=self._space_summary(selected, states),
            spaces=[self._space_summary(space, states) for space in visible],
            entities=[self._entity_summary(entity, states) for entity in visible_entities],
            states=states,
            coverage=[
                self._coverage(space, attribute, states)
                for space in visible
                for attribute in attributes
                if attribute in DEFAULT_COVERAGE_ATTRIBUTES
                or any(
                    state.attribute == attribute
                    and state.target_type == "space"
                    and state.space_id == space.space_id
                    for state in states
                )
            ],
            sources=self._sources(states),
            explanations=self._explanations(states),
            evidence=evidence,
            attributes=sorted(attributes),
            include_descendants=request.include_descendants,
            generated_at=generated_at,
        )

    async def coverage(
        self,
        space_id: str,
        *,
        attributes: list[str] | None = None,
        include_descendants: bool = False,
    ) -> list[StateCoverage]:
        result = await self.query(
            EnvironmentStateQueryInput(
                space_id=space_id,
                attributes=attributes or [],
                include_descendants=include_descendants,
            )
        )
        return result.coverage

    async def _evidence_for_states(
        self,
        states: list[StateEstimateView],
    ) -> list[StateEstimateEvidence]:
        result: list[StateEstimateEvidence] = []
        for state in states:
            try:
                result.extend(await self._estimation_service.evidence(state.id))
            except StateEstimateNotFoundError:
                logger.debug(
                    "state_estimate_evidence_disappeared",
                    extra={"payload": {"estimate_id": state.id}},
                )
                continue
        return result

    @staticmethod
    def _visible_spaces(
        inputs: ContextInputs,
        request: EnvironmentStateQueryInput,
    ) -> list[SpaceLayout]:
        selected = EnvironmentQueryService._selected_space(inputs, request)
        if selected is None:
            raise SpaceNotFoundError()
        if not request.include_descendants:
            return [selected]
        prefix = selected.path
        return [
            space
            for space in inputs.spaces
            if len(space.path) >= len(prefix) and space.path[: len(prefix)] == prefix
        ]

    @staticmethod
    def _selected_space(
        inputs: ContextInputs,
        request: EnvironmentStateQueryInput,
    ) -> SpaceLayout | None:
        if request.space_id is not None:
            return next(
                (space for space in inputs.spaces if space.space_id == request.space_id),
                None,
            )
        if request.space_path is not None:
            normalized = request.space_path.strip().strip("/")
            by_path = next(
                (
                    space
                    for space in inputs.spaces
                    if "/".join(space.path).casefold() == normalized.casefold()
                ),
                None,
            )
            if by_path is not None:
                return by_path
            return next(
                (
                    space
                    for space in inputs.spaces
                    if space.name.casefold() == normalized.casefold()
                ),
                None,
            )
        return next(
            (space for space in inputs.spaces if space.space_id == inputs.root_space_id),
            None,
        )

    @staticmethod
    def _attributes(
        inputs: ContextInputs,
        request: EnvironmentStateQueryInput,
    ) -> set[str]:
        if request.attributes:
            return {
                attribute.strip()
                for attribute in request.attributes
                if any(state.attribute == attribute.strip() for state in inputs.states)
                or attribute.strip() in DEFAULT_COVERAGE_ATTRIBUTES
            }
        observed = {state.attribute for state in inputs.states}
        return observed | set(DEFAULT_COVERAGE_ATTRIBUTES)

    @staticmethod
    def _space_summary(
        space: SpaceLayout,
        states: list[StateEstimateView],
    ) -> QueriedSpaceSummary:
        return QueriedSpaceSummary(
            space_id=space.space_id,
            parent_id=space.parent_id,
            space_type=space.space_type,
            name=space.name,
            path=space.path,
            status=space.status,
            state_ids=[
                state.id
                for state in states
                if state.target_type == "space" and state.space_id == space.space_id
            ],
        )

    @staticmethod
    def _entity_summary(
        entity: EntityLayout,
        states: list[StateEstimateView],
    ) -> QueriedEntitySummary:
        return QueriedEntitySummary(
            entity_id=entity.entity_id,
            name=entity.name,
            entity_type=entity.entity_type,
            device_id=entity.device_id,
            space_id=entity.space_id,
            state_ids=[
                state.id
                for state in states
                if state.target_type == "entity" and state.entity_id == entity.entity_id
            ],
        )

    @staticmethod
    def _coverage(
        space: SpaceLayout,
        attribute: str,
        states: list[StateEstimateView],
    ) -> StateCoverage:
        state = next(
            (
                item
                for item in states
                if item.target_type == "space"
                and item.space_id == space.space_id
                and item.attribute == attribute
            ),
            None,
        )
        if state is None:
            coverage = "blind"
            explanation = "No state target exists for this attribute."
        elif state.status == "unknown":
            coverage = "blind"
            explanation = _state_reason(state)
        elif state.status in {"observed", "derived"}:
            coverage = "covered"
            explanation = "A current estimate is available from usable observations."
        elif state.status in {"inferred", "conflict"}:
            coverage = "partial"
            explanation = _state_reason(state)
        else:
            coverage = "lost"
            explanation = _state_reason(state)
        return StateCoverage(
            space_id=space.space_id,
            attribute=attribute,
            coverage=coverage,
            state_status=None if state is None else state.status,
            source_count=_source_ids(state).__len__(),
            explanation=explanation,
        )

    @staticmethod
    def _sources(states: list[StateEstimateView]) -> list[QuerySourceSummary]:
        grouped: dict[str, dict[str, set[str]]] = {}
        for state in states:
            observation_ids = _observation_ids(state)
            for source_id in _source_ids(state):
                item = grouped.setdefault(
                    source_id,
                    {
                        "observation_ids": set[str](),
                        "entity_ids": set[str](),
                    },
                )
                item["observation_ids"].update(observation_ids)
                if state.entity_id is not None:
                    item["entity_ids"].add(state.entity_id)
        return [
            QuerySourceSummary(
                source_id=source_id,
                observation_count=len(item["observation_ids"]),
                entity_ids=sorted(item["entity_ids"]),
                observation_ids=sorted(item["observation_ids"]),
            )
            for source_id, item in sorted(grouped.items())
        ]

    @staticmethod
    def _explanations(states: list[StateEstimateView]) -> list[QueryExplanation]:
        explanations: list[QueryExplanation] = []
        for state in states:
            if state.status not in {"unknown", "stale", "unavailable", "conflict"}:
                continue
            explanations.append(
                QueryExplanation(
                    status=state.status,
                    space_id=state.space_id,
                    entity_id=state.entity_id,
                    attribute=state.attribute,
                    message=_state_reason(state),
                    details=state.conflict_details or {},
                )
            )
        return explanations


def _source_ids(state: StateEstimateView | None) -> list[str]:
    if state is None:
        return []
    values = state.evidence_summary.get("source_ids", [])
    return [str(value) for value in values] if isinstance(values, list) else []


def _observation_ids(state: StateEstimateView | None) -> list[str]:
    if state is None:
        return []
    values = state.evidence_summary.get("observation_ids", [])
    return [str(value) for value in values] if isinstance(values, list) else []


def _state_reason(state: StateEstimateView) -> str:
    reason = state.evidence_summary.get("reason")
    if isinstance(reason, str) and reason:
        return reason
    labels = {
        "unknown": "There is not enough usable evidence to confirm this state.",
        "stale": "Previously valid evidence has expired.",
        "unavailable": "The source or entity is currently unavailable.",
        "conflict": "Credible sources report conflicting values.",
    }
    return labels.get(state.status, state.status)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["EnvironmentQueryService"]
