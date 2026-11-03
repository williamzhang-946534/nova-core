from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from arvuno_core.estimation.errors import (
    StateEstimateNotFoundError,
    StateEstimationEnvironmentError,
)
from arvuno_core.estimation.models import (
    ContextInputs,
    EntityLayout,
    RuleInfo,
    SpaceLayout,
    StateEstimateEvidence,
    StateEstimateView,
    StateRebuildResult,
)
from arvuno_core.estimation.rules import estimate, rule_for
from arvuno_core.persistence.models import (
    Entity,
    Environment,
    EstimationTarget,
    Observation,
    ObservationSource,
    Space,
    StateEstimate,
    StateEstimateObservation,
)
from arvuno_core.persistence.state_estimates import stored_as_utc
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]


class StateEstimationService:
    """Builds explainable state estimates from retained observations."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        environment_name: str = "home",
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._environment_name = environment_name

    async def rebuild(self, now: datetime | None = None) -> StateRebuildResult:
        return await asyncio.to_thread(self._rebuild, _now(now))

    async def list(
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
    ) -> tuple[list[StateEstimateView], int]:
        return await asyncio.to_thread(
            self._list,
            environment_id=environment_id,
            target_id=target_id,
            entity_id=entity_id,
            space_id=space_id,
            attribute=attribute,
            status=status,
            include_history=include_history,
            page=page,
            page_size=page_size,
        )

    async def get(self, estimate_id: str) -> StateEstimateView:
        return await asyncio.to_thread(self._get, estimate_id)

    async def evidence(self, estimate_id: str) -> list[StateEstimateEvidence]:
        return await asyncio.to_thread(self._evidence, estimate_id)

    async def context_inputs(self, now: datetime | None = None) -> ContextInputs:
        return await asyncio.to_thread(self._context_inputs, _now(now))

    def _rebuild(self, now: datetime) -> StateRebuildResult:
        appended = 0
        unchanged = 0
        generated_at = now
        with self._unit_of_work_factory() as uow:
            assert uow.environments is not None
            assert uow.state_estimates is not None
            repository = uow.state_estimates
            environment = self._environment(uow)
            targets = self._ensure_targets(uow, environment.id)

            for target in targets:
                attribute = target.attribute
                candidates = repository.candidate_observations(
                    target_type=target.target_type,
                    entity_id=target.entity_id,
                    space_id=target.space_id,
                    attribute=attribute,
                    received_after=now - timedelta(days=370),
                )
                availability_candidates = None
                motion_candidates = None
                if target.target_type == "entity" and attribute != "device_availability":
                    availability_candidates = repository.candidate_observations(
                        target_type="entity",
                        entity_id=target.entity_id,
                        space_id=None,
                        attribute="device_availability",
                        received_after=now - timedelta(days=370),
                    )
                if target.target_type == "space" and attribute == "occupancy":
                    motion_candidates = repository.candidate_observations(
                        target_type="space",
                        entity_id=None,
                        space_id=target.space_id,
                        attribute="motion",
                        received_after=now - timedelta(days=370),
                    )

                result = estimate(
                    attribute=attribute,
                    target_type=target.target_type,
                    candidates=candidates,
                    availability_candidates=availability_candidates,
                    motion_candidates=motion_candidates,
                    now=now,
                )
                all_pairs = [
                    *(availability_candidates or []),
                    *candidates,
                    *(motion_candidates or []),
                ]
                latest = repository.latest_estimate(target.id)
                evidence_ids = [link.observation.observation_id for link in result.links]
                if latest is not None and self._same_semantics(
                    latest=latest,
                    status=result.status,
                    value=result.value,
                    unit=result.unit,
                    rule_id=result.rule_id,
                    rule_version=result.rule_version,
                    evidence_ids=evidence_ids,
                ):
                    current = repository.current_for_target(target.id)
                    if current is None or current.latest_estimate_id != latest.id:
                        repository.upsert_current(estimate=latest, now=now)
                    unchanged += 1
                    continue

                if latest is not None:
                    latest.superseded_at = now
                row = StateEstimate(
                    target_id=target.id,
                    environment_id=environment.id,
                    status=result.status,
                    value=result.value,
                    unit=result.unit,
                    confidence=result.confidence,
                    evidence_summary=result.evidence_summary,
                    conflict_details=result.conflict_details,
                    rule_id=result.rule_id,
                    rule_version=result.rule_version,
                    input_cutoff_at=self._input_cutoff(all_pairs, now),
                    effective_from=result.effective_from,
                    generated_at=now,
                    valid_until=result.valid_until,
                )
                saved = repository.add_estimate(row)
                for link in result.links:
                    repository.add_evidence(
                        StateEstimateObservation(
                            estimate_id=saved.id,
                            observation_id=link.observation.observation_id,
                            contribution=link.contribution,
                            weight=link.weight,
                            exclusion_reason=link.exclusion_reason,
                        )
                    )
                repository.upsert_current(estimate=saved, now=now)
                appended += 1

            uow.commit()
            return StateRebuildResult(
                environment_id=environment.id,
                targets=len(targets),
                appended=appended,
                unchanged=unchanged,
                generated_at=generated_at,
            )

    def _ensure_targets(
        self,
        uow: SqlAlchemyUnitOfWork,
        environment_id: str,
    ) -> list[EstimationTarget]:
        assert uow.state_estimates is not None
        repository = uow.state_estimates
        planned: list[tuple[str, str | None, str | None, str]] = []
        for entity_id in repository.active_entity_ids(environment_id):
            planned.append(("entity", entity_id, None, "device_availability"))
        for entity_id, attribute in repository.observed_entity_attributes(environment_id):
            planned.append(("entity", entity_id, None, attribute))

        spaces = repository.active_spaces_for_environment(environment_id)
        for space in spaces:
            for attribute in ("temperature", "humidity", "occupancy"):
                planned.append(("space", None, space.id, attribute))
        for space_id, attribute in repository.observed_space_attributes(environment_id):
            planned.append(("space", None, space_id, attribute))

        targets: list[EstimationTarget] = []
        seen: set[tuple[str, str | None, str | None, str]] = set()
        for target_type, entity_id, space_id, attribute in planned:
            key = (target_type, entity_id, space_id, attribute)
            if key in seen:
                continue
            seen.add(key)
            spec = rule_for(attribute)
            targets.append(
                repository.ensure_target(
                    environment_id=environment_id,
                    target_type=target_type,
                    entity_id=entity_id,
                    space_id=space_id,
                    attribute=attribute,
                    strategy_id=spec.strategy_id,
                    strategy_version=spec.strategy_version,
                    validity_policy={"valid_seconds": spec.valid_seconds},
                    conflict_policy=spec.conflict_policy,
                    coverage_policy=spec.coverage_policy,
                )
            )
        return sorted(
            targets,
            key=lambda item: (
                item.target_type,
                item.attribute,
                item.entity_id or "",
                item.space_id or "",
            ),
        )

    def _environment(self, uow: SqlAlchemyUnitOfWork) -> Environment:
        assert uow.environments is not None
        environment = uow.environments.ensure_default(self._environment_name)
        if environment.root_space_id is None:
            raise StateEstimationEnvironmentError()
        return environment

    @staticmethod
    def _same_semantics(
        *,
        latest: StateEstimate,
        status: str,
        value: Any,
        unit: str | None,
        rule_id: str,
        rule_version: str,
        evidence_ids: list[str],
    ) -> bool:
        return (
            latest.status,
            latest.value,
            latest.unit,
            latest.rule_id,
            latest.rule_version,
            sorted(latest.evidence_summary.get("observation_ids", [])),
        ) == (
            status,
            value,
            unit,
            rule_id,
            rule_version,
            sorted(evidence_ids),
        )

    @staticmethod
    def _input_cutoff(
        rows: list[tuple[Observation, ObservationSource]],
        now: datetime,
    ) -> datetime:
        return max(
            (stored_as_utc(observation.received_at) for observation, _ in rows),
            default=now,
        )

    def _list(
        self,
        *,
        environment_id: str | None,
        target_id: str | None,
        entity_id: str | None,
        space_id: str | None,
        attribute: str | None,
        status: str | None,
        include_history: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[StateEstimateView], int]:
        now = datetime.now(UTC)
        with self._unit_of_work_factory() as uow:
            assert uow.state_estimates is not None
            repository = uow.state_estimates
            selected_environment = environment_id or self._environment(uow).id
            if include_history:
                rows, total = repository.list_estimates(
                    environment_id=selected_environment,
                    target_id=target_id,
                    entity_id=entity_id,
                    space_id=space_id,
                    attribute=attribute,
                    status=status,
                    include_history=True,
                    page=page,
                    page_size=page_size,
                )
                return [self._view(row, row.target, now) for row in rows], total

            rows = repository.current_rows(
                environment_id=selected_environment,
                target_id=target_id,
                entity_id=entity_id,
                space_id=space_id,
                attribute=attribute,
            )
            filtered = [
                self._view(row[2], row[1], now)
                for row in rows
                if status is None or self._effective_status(row[2], now) == status
            ]
            start = (page - 1) * page_size
            return filtered[start : start + page_size], len(filtered)

    def _get(self, estimate_id: str) -> StateEstimateView:
        now = datetime.now(UTC)
        with self._unit_of_work_factory() as uow:
            assert uow.state_estimates is not None
            row = uow.state_estimates.get_estimate(estimate_id)
            if row is None:
                raise StateEstimateNotFoundError()
            return self._view(row, row.target, now)

    def _evidence(self, estimate_id: str) -> list[StateEstimateEvidence]:
        with self._unit_of_work_factory() as uow:
            assert uow.state_estimates is not None
            row = uow.state_estimates.get_estimate(estimate_id)
            if row is None:
                raise StateEstimateNotFoundError()
            details = uow.state_estimates.evidence_details_for_estimate(estimate_id)
            return [
                self._evidence_item(link, observation, source)
                for link, observation, source in details
            ]

    def _context_inputs(self, now: datetime) -> ContextInputs:
        with self._unit_of_work_factory() as uow:
            assert uow.state_estimates is not None
            environment = self._environment(uow)
            repository = uow.state_estimates
            spaces = repository.active_spaces_for_environment(environment.id)
            entity_rows = repository.entity_overviews(environment_id=environment.id)
            current_rows = repository.current_rows(environment_id=environment.id)
            return ContextInputs(
                environment_id=environment.id,
                root_space_id=environment.root_space_id or "",
                spaces=[self._space_layout(space) for space in spaces],
                entities=[self._entity_layout(row[0], row[1], row[2]) for row in entity_rows],
                states=[self._view(row[2], row[1], now) for row in current_rows],
            )

    @staticmethod
    def _view(row: StateEstimate, target: EstimationTarget, now: datetime) -> StateEstimateView:
        return StateEstimateView(
            id=row.id,
            target_id=row.target_id,
            environment_id=row.environment_id,
            target_type=target.target_type,
            entity_id=target.entity_id,
            space_id=target.space_id,
            attribute=target.attribute,
            status=StateEstimationService._effective_status(row, now),
            value=row.value,
            unit=row.unit,
            confidence=row.confidence,
            evidence_summary=row.evidence_summary,
            conflict_details=row.conflict_details,
            rule=RuleInfo(id=row.rule_id, version=row.rule_version),
            input_cutoff_at=stored_as_utc(row.input_cutoff_at),
            effective_from=stored_as_utc(row.effective_from),
            generated_at=stored_as_utc(row.generated_at),
            valid_until=(stored_as_utc(row.valid_until) if row.valid_until is not None else None),
            superseded_at=(
                stored_as_utc(row.superseded_at) if row.superseded_at is not None else None
            ),
            created_at=stored_as_utc(row.created_at),
        )

    @staticmethod
    def _effective_status(row: StateEstimate, now: datetime) -> str:
        if row.valid_until is None:
            return row.status
        if (
            row.status in {"observed", "derived", "inferred"}
            and stored_as_utc(row.valid_until) <= now
        ):
            return "stale"
        return row.status

    @staticmethod
    def _evidence_item(
        link: StateEstimateObservation,
        observation: Observation,
        source: ObservationSource,
    ) -> StateEstimateEvidence:
        return StateEstimateEvidence(
            observation_id=observation.observation_id,
            source_id=source.id,
            source_type=source.source_type,
            entity_id=observation.entity_id,
            space_id=observation.space_id,
            attribute=observation.attribute,
            normalized_value=observation.normalized_value,
            normalized_unit=observation.normalized_unit,
            observed_at=observation.observed_at,
            observed_at_source=observation.observed_at_source,
            received_at=observation.received_at,
            quality_status=observation.quality_status,
            contribution=link.contribution,
            weight=link.weight,
            exclusion_reason=link.exclusion_reason,
        )

    @staticmethod
    def _space_layout(space: Space) -> SpaceLayout:
        return SpaceLayout(
            space_id=space.id,
            parent_id=space.parent_id,
            space_type=space.space_type,
            name=space.name,
            path=space.path.split("/"),
            status=space.status,
        )

    @staticmethod
    def _entity_layout(
        entity: Entity,
        device: Any | None,
        space_id: str | None,
    ) -> EntityLayout:
        return EntityLayout(
            entity_id=entity.id,
            name=entity.name,
            entity_type=entity.entity_type,
            device_id=getattr(device, "id", None),
            space_id=space_id,
        )


def _now(value: datetime | None) -> datetime:
    return stored_as_utc(value or datetime.now(UTC))


__all__ = ["StateEstimationService"]
