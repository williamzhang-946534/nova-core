import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from arvuno_core.devices.models import DeviceState
from arvuno_core.observations.adapter_mapping import map_device_state_to_observations
from arvuno_core.observations.errors import ObservationError
from arvuno_core.observations.models import (
    AdapterObservationBatch,
    ObservationBatchResult,
    ObservationInput,
    ObservationItemResult,
)
from arvuno_core.observations.normalization import normalize
from arvuno_core.observations.service import ObservationService
from arvuno_core.persistence.models import Observation
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork

logger = logging.getLogger(__name__)


class ObservationPipeline:
    """Validates, samples, deduplicates, and persists adapter observations."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork],
        observation_service: ObservationService | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._observation_service = observation_service or ObservationService(unit_of_work_factory)

    async def ingest(self, batch: AdapterObservationBatch) -> ObservationBatchResult:
        received_at = self._utc(batch.received_at)
        normalized_batch = batch.model_copy(update={"received_at": received_at})
        prepared = await asyncio.to_thread(self._prepare_batch, normalized_batch)
        if prepared["already_completed"]:
            return await asyncio.to_thread(self._completed_result, batch.batch_id)

        items: list[ObservationItemResult] = list(prepared["items"])
        accepted = 0
        deduplicated = 0
        sampled = 0
        invalid = 0
        try:
            for item in items:
                if item.status == "sampled":
                    sampled += 1
                    continue
                if item.status == "invalid":
                    invalid += 1
                    continue
                request = prepared["requests"].get((item.external_id, item.attribute))
                if request is None:
                    item.status = "invalid"
                    item.error = {"code": "OBSERVATION_INPUT_MISSING"}
                    invalid += 1
                    continue
                try:
                    result = await self._observation_service.record(request)
                except ObservationError as exc:
                    item.status = "invalid"
                    item.error = {
                        "code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                    }
                    invalid += 1
                    continue
                item.observation = result.data
                if result.duplicate:
                    item.status = "deduplicated"
                    deduplicated += 1
                else:
                    item.status = "accepted"
                    accepted += 1

            return await asyncio.to_thread(
                self._finish_batch,
                normalized_batch,
                items,
                accepted=accepted,
                deduplicated=deduplicated,
                sampled=sampled,
                invalid=invalid,
            )
        except Exception as exc:
            logger.exception("observation_pipeline_failed", extra={"batch_id": batch.batch_id})
            return await asyncio.to_thread(
                self._fail_batch,
                batch.batch_id,
                str(exc),
                items=items,
                accepted=accepted,
                deduplicated=deduplicated,
                sampled=sampled,
                invalid=invalid,
            )

    async def ingest_states(
        self,
        *,
        adapter_id: str,
        states: list[DeviceState],
        batch_id: str | None = None,
        received_at: datetime | None = None,
        correlation_id: str | None = None,
    ) -> ObservationBatchResult:
        return await self.ingest(
            AdapterObservationBatch(
                adapter_id=adapter_id,
                batch_id=batch_id or str(uuid4()),
                received_at=received_at or datetime.now(UTC),
                correlation_id=correlation_id,
                states=states,
            )
        )

    async def cleanup_expired(self, *, now: datetime, limit: int = 1000) -> int:
        def execute() -> int:
            deleted_observations = 0
            deleted_batches = 0
            while True:
                with self._unit_of_work_factory() as uow:
                    assert uow.observation_batches is not None
                    assert uow.observations is not None
                    deleted_observations += uow.observations.cleanup_expired(
                        now=now,
                        limit=limit,
                    )
                    deleted_batches = uow.observation_batches.cleanup_expired(now=now)
                    uow.commit()
                if limit < 1 or deleted_observations < limit:
                    return deleted_observations + deleted_batches

        return await asyncio.to_thread(execute)

    def _prepare_batch(self, batch: AdapterObservationBatch) -> dict[str, Any]:
        items: list[ObservationItemResult] = []
        requests: dict[tuple[str, str], ObservationInput] = {}
        errors: list[dict[str, Any]] = []
        with self._unit_of_work_factory() as uow:
            assert uow.devices is not None
            assert uow.entities is not None
            assert uow.environments is not None
            assert uow.observation_attributes is not None
            assert uow.observation_batches is not None
            assert uow.observation_sources is not None
            assert uow.observations is not None

            source = uow.observation_sources.get_by_adapter(batch.adapter_id)
            existing_batch = uow.observation_batches.get(batch.batch_id)
            if existing_batch is not None and existing_batch.status == "completed":
                return {"already_completed": True, "items": [], "requests": {}}
            uow.observation_batches.start(
                batch_id=batch.batch_id,
                source_id=source.id if source is not None else None,
                adapter_id=batch.adapter_id,
                correlation_id=batch.correlation_id,
                received_at=batch.received_at,
                total=0,
            )
            if source is None:
                error = {
                    "code": "OBSERVATION_SOURCE_NOT_FOUND",
                    "message": "No observation source is registered for the adapter.",
                    "external_id": "*",
                    "attribute": "*",
                }
                errors.append(error)
                items.append(
                    ObservationItemResult(
                        external_id="*",
                        attribute="*",
                        status="invalid",
                        error=error,
                    )
                )
            elif source.status != "active":
                error = {
                    "code": "OBSERVATION_SOURCE_INACTIVE",
                    "message": "Observations cannot be accepted from an inactive source.",
                    "external_id": "*",
                    "attribute": "*",
                }
                errors.append(error)
                items.append(
                    ObservationItemResult(
                        external_id="*",
                        attribute="*",
                        status="invalid",
                        error=error,
                    )
                )

            environment = uow.environments.ensure_default()
            for state in batch.states:
                device = uow.devices.get_by_external_id(batch.adapter_id, state.external_id)
                if device is None:
                    error = {
                        "code": "OBSERVATION_SUBJECT_NOT_FOUND",
                        "message": (
                            "The device subject could not be resolved through Device Registry."
                        ),
                        "external_id": state.external_id,
                        "attribute": "*",
                    }
                    errors.append(error)
                    items.append(
                        ObservationItemResult(
                            external_id=state.external_id,
                            attribute="*",
                            status="invalid",
                            error=error,
                        )
                    )
                    continue
                entity = uow.entities.ensure_device_entity(device, environment)
                try:
                    candidates = map_device_state_to_observations(
                        adapter_id=batch.adapter_id,
                        state=state,
                        entity_id=entity.id,
                        device_type=device.device_type,
                        batch_id=batch.batch_id,
                        received_at=batch.received_at,
                        correlation_id=batch.correlation_id,
                    )
                except (ObservationError, ValidationError) as exc:
                    error = {
                        "code": "OBSERVATION_INPUT_INVALID",
                        "message": str(exc),
                        "external_id": state.external_id,
                        "attribute": "*",
                    }
                    errors.append(error)
                    items.append(
                        ObservationItemResult(
                            external_id=state.external_id,
                            attribute="*",
                            status="invalid",
                            error=error,
                        )
                    )
                    continue

                for request in candidates:
                    latest = (
                        uow.observations.latest_for_series(
                            source_id=source.id,
                            entity_id=entity.id,
                            subject_type=None,
                            subject_id=None,
                            attribute=request.attribute,
                        )
                        if source is not None and source.status == "active"
                        else None
                    )
                    definition = uow.observation_attributes.get(request.attribute)
                    sampled = (
                        definition is not None
                        and latest is not None
                        and self._should_sample(
                            sampling_policy=definition.sampling_policy,
                            value_type=definition.value_type,
                            latest=latest,
                            request=request,
                        )
                    )
                    status = "sampled" if sampled else "accepted"
                    requests[(state.external_id, request.attribute)] = request
                    items.append(
                        ObservationItemResult(
                            external_id=state.external_id,
                            attribute=request.attribute,
                            status=status,
                        )
                    )

            batch_row = uow.observation_batches.get(batch.batch_id)
            assert batch_row is not None
            batch_row.total = len(items)
            batch_row.errors = errors  # type: ignore[assignment]
            uow.commit()
        return {"already_completed": False, "items": items, "requests": requests}

    def _finish_batch(
        self,
        batch: AdapterObservationBatch,
        items: list[ObservationItemResult],
        *,
        accepted: int,
        deduplicated: int,
        sampled: int,
        invalid: int,
    ) -> ObservationBatchResult:
        errors = [item.error for item in items if item.error is not None]
        with self._unit_of_work_factory() as uow:
            assert uow.devices is not None
            assert uow.observation_batches is not None
            assert uow.observation_heartbeats is not None
            assert uow.observation_sources is not None
            batch_row = uow.observation_batches.get(batch.batch_id)
            assert batch_row is not None
            uow.observation_batches.complete(
                batch_row,
                accepted=accepted,
                deduplicated=deduplicated,
                sampled=sampled,
                invalid=invalid,
                errors=errors,  # type: ignore[arg-type]
            )
            source = uow.observation_sources.get_by_adapter(batch.adapter_id)
            if source is not None:
                if source.status == "active":
                    uow.observation_heartbeats.record_success(
                        source_id=source.id,
                        seen_at=batch.received_at,
                        batch_id=batch.batch_id,
                    )
                else:
                    uow.observation_heartbeats.record_failure(
                        source_id=source.id,
                        seen_at=batch.received_at,
                        batch_id=batch.batch_id,
                        error="Observation source is inactive.",
                    )

            states_by_external_id = {state.external_id: state for state in batch.states}
            projected_external_ids = {
                item.external_id for item in items if item.status in {"accepted", "deduplicated"}
            }
            for external_id in projected_external_ids:
                state = states_by_external_id.get(external_id)
                device = uow.devices.get_by_external_id(batch.adapter_id, external_id)
                if state is None or device is None:
                    continue
                uow.devices.record_observed_state(
                    device.id,
                    state=state.state.value,
                    attributes=state.attributes,
                    raw_state=state.raw_state,
                    source=batch.adapter_id,
                    observed_at=state.observed_at,
                )
            uow.commit()

        return ObservationBatchResult(
            batch_id=batch.batch_id,
            source_id=batch_row.source_id,
            status="completed",
            total=len(items),
            accepted=accepted,
            deduplicated=deduplicated,
            sampled=sampled,
            invalid=invalid,
            items=items,
        )

    def _fail_batch(
        self,
        batch_id: str,
        error: str,
        *,
        items: list[ObservationItemResult],
        accepted: int,
        deduplicated: int,
        sampled: int,
        invalid: int,
    ) -> ObservationBatchResult:
        source_id: str | None = None
        total = len(items)
        with self._unit_of_work_factory() as uow:
            assert uow.observation_batches is not None
            assert uow.observation_heartbeats is not None
            batch = uow.observation_batches.get(batch_id)
            if batch is not None:
                source_id = batch.source_id
                uow.observation_batches.fail(batch, error=error)
                if source_id is not None:
                    uow.observation_heartbeats.record_failure(
                        source_id=source_id,
                        seen_at=batch.received_at,
                        batch_id=batch_id,
                        error=error,
                    )
                total = batch.total
                uow.commit()
        return ObservationBatchResult(
            batch_id=batch_id,
            source_id=source_id,
            status="failed",
            total=total,
            accepted=accepted,
            deduplicated=deduplicated,
            sampled=sampled,
            invalid=invalid,
            items=items,
            error=error,
        )

    def _completed_result(self, batch_id: str) -> ObservationBatchResult:
        with self._unit_of_work_factory() as uow:
            assert uow.observation_batches is not None
            batch = uow.observation_batches.get(batch_id)
            assert batch is not None
            return ObservationBatchResult(
                batch_id=batch.id,
                source_id=batch.source_id,
                status="completed",
                total=batch.total,
                accepted=batch.accepted,
                deduplicated=batch.deduplicated,
                sampled=batch.sampled,
                invalid=batch.invalid,
                items=[],
            )

    @staticmethod
    def _should_sample(
        *,
        sampling_policy: dict[str, Any],
        value_type: str,
        latest: Observation,
        request: ObservationInput,
    ) -> bool:
        normalized = normalize(
            attribute=request.attribute,
            value_type=value_type,
            raw_value=request.raw_value,
            raw_unit=request.raw_unit,
        ).normalized_value
        if bool(sampling_policy.get("on_change_only", False)):
            return latest.normalized_value == normalized
        minimum_seconds = float(sampling_policy.get("minimum_interval_seconds", 0))
        latest_received = (
            latest.received_at.replace(tzinfo=UTC)
            if latest.received_at.tzinfo is None
            else latest.received_at.astimezone(UTC)
        )
        elapsed = (request.received_at - latest_received).total_seconds()
        if elapsed < 0:
            return False
        if elapsed >= minimum_seconds:
            return False
        threshold = sampling_policy.get("change_threshold")
        if threshold is not None:
            if normalized is None:
                return latest.normalized_value is None
            try:
                return abs(float(normalized) - float(latest.normalized_value)) < float(threshold)
            except (TypeError, ValueError):
                return False
        return latest.normalized_value == normalized

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ObservationError(
                code="OBSERVATION_TIME_NOT_UTC",
                message="The received_at timestamp must include a timezone.",
            )
        return value.astimezone(UTC)


__all__ = ["ObservationPipeline"]
