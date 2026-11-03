from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from arvuno_core.devices.errors import (
    ActionFailedError,
    AdapterTimeoutError,
    AdapterUnavailableError,
    DeviceError,
    DeviceNotFoundError,
    DeviceUnavailableError,
    StateVerificationFailedError,
)
from arvuno_core.devices.interface import DeviceAdapter
from arvuno_core.devices.models import DeviceAction, DeviceStateName
from arvuno_core.devices.registry import DeviceRegistry, RegisteredDevice
from arvuno_core.devices.verification import DeviceStateVerifier
from arvuno_core.observations.pipeline import ObservationPipeline


@dataclass(frozen=True)
class DeviceServiceResult:
    before_state: str
    actual_state: str
    attributes: dict[str, Any]
    verified: bool
    observed_at: datetime
    action_id: str


class DeviceApplicationService:
    """Application boundary used by tools; tools never touch adapter implementations."""

    def __init__(
        self,
        registry: DeviceRegistry,
        adapters: dict[str, DeviceAdapter],
        observation_pipeline: ObservationPipeline,
        *,
        verifier: DeviceStateVerifier | None = None,
    ) -> None:
        self._registry = registry
        self._adapters = dict(adapters)
        self._observation_pipeline = observation_pipeline
        self._verifier = verifier or DeviceStateVerifier()

    async def list_devices(
        self,
        *,
        area: str | None = None,
        device_type: str | None = None,
        online: bool | None = None,
    ) -> list[RegisteredDevice]:
        return await self._registry.list_devices(
            area=area,
            device_type=device_type,
            is_online=online,
            is_enabled=True,
        )

    async def get_registered_device(self, device_id: str) -> RegisteredDevice:
        device = await self._registry.get_by_id(device_id)
        if device is None or not device.is_enabled:
            raise DeviceNotFoundError("The device is not available to Arvuno.")
        return device

    async def find_device_for_policy(self, device_id: str) -> RegisteredDevice | None:
        """Return the projection without collapsing policy failure causes."""
        return await self._registry.get_by_id(device_id)

    async def get_state(self, device_id: str) -> DeviceServiceResult:
        device = await self.get_registered_device(device_id)
        state = await self._adapter(device.adapter_id).get_state(device.external_id)
        await self._record(device, state)
        return DeviceServiceResult(
            before_state=state.state.value,
            actual_state=state.state.value,
            attributes=state.attributes,
            verified=True,
            observed_at=state.observed_at,
            action_id=str(uuid4()),
        )

    async def control_device(
        self,
        device_id: str,
        *,
        action: str,
        parameters: dict[str, Any],
        expected_state: DeviceStateName | None = None,
    ) -> DeviceServiceResult:
        device = await self.get_registered_device(device_id)
        adapter = self._adapter(device.adapter_id)
        action_request = DeviceAction(action=action, parameters=parameters)  # type: ignore[arg-type]
        before = await adapter.get_state(device.external_id)
        await self._record(device, before)
        if before.state == DeviceStateName.UNAVAILABLE:
            raise DeviceUnavailableError("The device is unavailable.")

        try:
            result = await adapter.execute_action(device.external_id, action_request)
        except AdapterTimeoutError as exc:
            try:
                actual = await adapter.get_state(device.external_id)
                verification = self._verifier.verify(
                    action_request,
                    before,
                    actual,
                    required_state=expected_state,
                )
                await self._record(device, actual)
                verification_detail = (
                    f"verified={verification.verified};actual_state={actual.state.value}"
                )
            except DeviceError as verification_exc:
                verification_detail = f"post_timeout_verification_failed:{verification_exc.code}"
            raise AdapterTimeoutError(
                "The action timed out after the device state was read.",
                detail=verification_detail,
            ) from exc

        if not result.success:
            raise ActionFailedError(result.message or "The device action failed.")

        actual = await adapter.get_state(device.external_id)
        verification = self._verifier.verify(
            action_request,
            before,
            actual,
            required_state=expected_state,
        )
        if expected_state is not None and actual.state != expected_state:
            raise StateVerificationFailedError(
                "The device did not reach the requested state.",
                detail=f"expected={expected_state.value};actual={actual.state.value}",
            )
        await self._record(device, actual)
        return DeviceServiceResult(
            before_state=before.state.value,
            actual_state=actual.state.value,
            attributes=actual.attributes,
            verified=verification.verified,
            observed_at=actual.observed_at,
            action_id=result.action_id,
        )

    def _adapter(self, adapter_id: str) -> DeviceAdapter:
        adapter = self._adapters.get(adapter_id)
        if adapter is None:
            raise AdapterUnavailableError(f"The {adapter_id} adapter is unavailable.")
        return adapter

    async def _record(
        self,
        device: RegisteredDevice,
        state: Any,
    ) -> None:
        ingestion = await self._observation_pipeline.ingest_states(
            adapter_id=device.adapter_id,
            states=[state],
            batch_id=f"device:{uuid4()}",
            received_at=datetime.now(UTC),
        )
        if ingestion.status == "failed":
            raise AdapterUnavailableError(
                "The observed device state could not be persisted.",
                detail=f"batch_id={ingestion.batch_id};error={ingestion.error}",
            )


__all__ = ["DeviceApplicationService", "DeviceServiceResult"]
