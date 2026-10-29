import logging
from dataclasses import dataclass
from typing import Any

from arvuno_core.devices.errors import (
    AdapterTimeoutError,
    AdapterUnavailableError,
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

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciliationResult:
    checked: int
    reconciled: int
    events_published: int
    failures: int


class EnvironmentReconciler:
    """Compares current allowlisted states with Arvuno's latest stored observations."""

    def __init__(self, registry: DeviceRegistry, publisher: DeviceEventService) -> None:
        self._registry = registry
        self._publisher = publisher

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
            try:
                current = await adapter.get_state(external_id)
            except (AdapterUnavailableError, AdapterTimeoutError, DeviceUnavailableError):
                failures += 1
                if previous is not None and previous.state != DeviceStateName.UNAVAILABLE:
                    event = self._unavailable_event(adapter, registered.id, external_id, previous)
                    await self._publisher.publish(event)
                    published += 1
                    reconciled += 1
                continue

            await self._registry.record_observed_state(
                registered.id,
                state=current.state.value,
                attributes=current.attributes,
                source=adapter.adapter_id,
                observed_at=current.observed_at,
            )
            if previous is None:
                continue

            event = self._difference_event(
                adapter,
                registered.id,
                external_id,
                registered.device_type,
                previous,
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
    ) -> DeviceEvent:
        return DeviceEvent(
            event_type=DeviceEventType.DEVICE_UNAVAILABLE,
            source=adapter.adapter_id,
            subject_id=device_id,
            external_id=external_id,
            payload={
                "previous_state": previous.state.value,
                "current_state": DeviceStateName.UNAVAILABLE.value,
                "previous_attributes": previous.attributes,
                "attributes": {},
            },
            occurred_at=utc_now(),
        )
