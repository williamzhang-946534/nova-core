import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from arvuno_core.devices.errors import (
    AdapterTimeoutError,
    AdapterUnavailableError,
    AuthorizationError,
    DeviceError,
    DeviceNotFoundError,
    DeviceUnavailableError,
)
from arvuno_core.devices.interface import DeviceAdapter
from arvuno_core.devices.models import (
    DeviceEvent,
    DeviceEventType,
    DeviceState,
    DeviceStateName,
    DeviceType,
)
from arvuno_core.devices.registry import DeviceRegistry
from arvuno_core.events.models import utc_now
from arvuno_core.events.service import DeviceEventService
from arvuno_core.observations.pipeline import ObservationPipeline

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciliationResult:
    checked: int
    reconciled: int
    events_published: int
    failures: int


class EnvironmentReconciler:
    """Compares current allowlisted states with Arvuno's latest stored observations."""

    def __init__(
        self,
        registry: DeviceRegistry,
        publisher: DeviceEventService,
        observation_pipeline: ObservationPipeline,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._registry = registry
        self._publisher = publisher
        self._observation_pipeline = observation_pipeline
        self._clock = clock

    async def reconcile(
        self,
        adapter: DeviceAdapter,
        external_ids: list[str],
    ) -> ReconciliationResult:
        checked = 0
        reconciled = 0
        published = 0
        failures = 0

        for external_id in dict.fromkeys(external_ids):
            registered = await self._registry.get_by_external_id(adapter.adapter_id, external_id)
            if registered is None:
                failures += 1
                logger.warning(
                    "reconciliation_skipped_unregistered_device",
                    extra={"adapter_id": adapter.adapter_id, "external_id": external_id},
                )
                continue
            checked += 1
            previous = await self._registry.latest_state(registered.id)
            availability_before = await self._registry.availability(registered.id)
            try:
                current = await adapter.get_state(external_id)
            except DeviceError as exc:
                failures += 1
                failure = _failure_classification(exc)
                failed_at = self._clock()
                transition = await self._registry.mark_availability(
                    registered.id,
                    unavailable=True,
                    error_code=failure[0],
                    failure_scope=failure[1],
                    read_at=failed_at,
                )
                if transition.transitioned:
                    event = self._unavailable_event(
                        adapter,
                        registered.id,
                        external_id,
                        previous,
                        error_code=failure[0],
                        failure_scope=failure[1],
                        occurred_at=failed_at,
                    )
                    await self._publisher.publish(event)
                    published += 1
                    reconciled += 1
                continue

            if previous is not None and _is_late(current.observed_at, previous.observed_at):
                failures += 1
                logger.warning(
                    "reconciliation_skipped_late_state",
                    extra={
                        "adapter_id": adapter.adapter_id,
                        "external_id": external_id,
                        "observed_at": current.observed_at,
                        "latest_observed_at": previous.observed_at,
                    },
                )
                continue

            read_at = self._clock()
            transition = await self._registry.mark_availability(
                registered.id,
                unavailable=current.state == DeviceStateName.UNAVAILABLE,
                error_code="device_unavailable"
                if current.state == DeviceStateName.UNAVAILABLE
                else None,
                failure_scope="entity" if current.state == DeviceStateName.UNAVAILABLE else "none",
                read_at=read_at,
            )

            ingestion = await self._observation_pipeline.ingest_states(
                adapter_id=adapter.adapter_id,
                states=[current],
                batch_id=f"poll:{uuid4()}",
                received_at=datetime.now(UTC),
            )
            if ingestion.status == "failed":
                failures += 1
                continue
            if previous is None:
                continue

            comparison_previous = previous
            if (
                availability_before.availability == "unavailable"
                and previous.state != DeviceStateName.UNAVAILABLE
            ):
                comparison_previous = previous.model_copy(
                    update={"state": DeviceStateName.UNAVAILABLE}
                )
            event = self._difference_event(
                adapter,
                registered.id,
                external_id,
                registered.device_type,
                comparison_previous,
                current,
            )
            if event is None:
                continue
            await self._publisher.publish(event)
            published += 1
            reconciled += 1

        return ReconciliationResult(
            checked=checked,
            reconciled=reconciled,
            events_published=published,
            failures=failures,
        )

    def _difference_event(
        self,
        adapter: DeviceAdapter,
        device_id: str,
        external_id: str,
        device_type: DeviceType,
        previous: Any,
        current: DeviceState,
    ) -> DeviceEvent | None:
        previous_attributes = previous.attributes if isinstance(previous.attributes, dict) else {}
        if current.state == DeviceStateName.UNAVAILABLE:
            if previous.state == DeviceStateName.UNAVAILABLE:
                return None
            event_type = DeviceEventType.DEVICE_UNAVAILABLE
        elif current.state != previous.state:
            event_type = DeviceEventType.STATE_CHANGED
        elif current.attributes != previous_attributes and device_type in {
            DeviceType.SENSOR_TEMPERATURE,
            DeviceType.SENSOR_HUMIDITY,
            DeviceType.SENSOR_MOTION,
            DeviceType.SENSOR_CONTACT,
        }:
            event_type = DeviceEventType.SENSOR_UPDATED
        else:
            return None

        return DeviceEvent(
            event_type=event_type,
            source=adapter.adapter_id,
            subject_id=device_id,
            external_id=external_id,
            payload={
                "previous_state": previous.state.value,
                "current_state": current.state.value,
                "previous_attributes": previous_attributes,
                "attributes": current.attributes,
            },
            occurred_at=current.observed_at,
        )

    def _unavailable_event(
        self,
        adapter: DeviceAdapter,
        device_id: str,
        external_id: str,
        previous: Any,
        *,
        error_code: str,
        failure_scope: str,
        occurred_at: datetime,
    ) -> DeviceEvent:
        previous_attributes = previous.attributes if previous is not None else {}
        previous_state = (
            previous.state.value if previous is not None else DeviceStateName.UNKNOWN.value
        )
        return DeviceEvent(
            event_type=DeviceEventType.DEVICE_UNAVAILABLE,
            source=adapter.adapter_id,
            subject_id=device_id,
            external_id=external_id,
            payload={
                "previous_state": previous_state,
                "current_state": DeviceStateName.UNAVAILABLE.value,
                "previous_attributes": previous_attributes,
                "attributes": {},
                "error_code": error_code,
                "failure_scope": failure_scope,
                "reason": _failure_reason(error_code),
            },
            occurred_at=occurred_at,
        )


def _failure_classification(exc: DeviceError) -> tuple[str, str]:
    if isinstance(exc, AdapterUnavailableError):
        return exc.code, "adapter"
    if isinstance(exc, AdapterTimeoutError):
        return exc.code, "adapter"
    if isinstance(exc, AuthorizationError):
        return exc.code, "adapter"
    if isinstance(exc, DeviceUnavailableError):
        return exc.code, "device"
    if isinstance(exc, DeviceNotFoundError):
        return exc.code, "device"
    return exc.code, "adapter"


def _failure_reason(error_code: str) -> str:
    reasons = {
        "adapter_unavailable": "The adapter or its network connection is unavailable.",
        "adapter_timeout": "The adapter read timed out.",
        "authorization_failed": "Adapter authorization failed.",
        "device_unavailable": "The device reported an unavailable state.",
        "device_not_found": "The adapter no longer recognizes the device.",
    }
    return reasons.get(error_code, "The device read failed.")


def _is_late(current: datetime, latest: datetime) -> bool:
    return _utc(current) < _utc(latest)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
