from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from nova_core.devices.errors import (
    ActionFailedError,
    AdapterTimeoutError,
    AdapterUnavailableError,
    DeviceError,
    DeviceNotFoundError,
    DeviceUnavailableError,
    StateVerificationFailedError,
)
from nova_core.devices.interface import DeviceAdapter
from nova_core.devices.models import DeviceAction, DeviceStateName
from nova_core.devices.registry import DeviceRegistry, RegisteredDevice
from nova_core.devices.verification import DeviceStateVerifier


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
        *,
        verifier: DeviceStateVerifier | None = None,
    ) -> None:
        self._registry = registry
        self._adapters = dict(adapters)
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
            raise DeviceNotFoundError("The device is not available to Nova.")
        return device

    async def find_device_for_policy(self, device_id: str) -> RegisteredDevice | None:
        """Return the projection without collapsing policy failure causes."""
        return await self._registry.get_by_id(device_id)

    async def get_state(self, device_id: str) -> DeviceServiceResult:
        device = await self.get_registered_device(device_id)
        state = await self._adapter(device.adapter_id).get_state(device.external_id)
        await self._registry.record_observed_state(
            device_id,
            state=state.state.value,
            attributes=state.attributes,
            source=device.adapter_id,
            observed_at=state.observed_at,
        )
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
        await self._record(device, before.state.value, before.attributes, before.observed_at)
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
                await self._record(
                    device,
                    actual.state.value,
                    actual.attributes,
                    actual.observed_at,
                )
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
        await self._record(device, actual.state.value, actual.attributes, actual.observed_at)
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
        state: str,
        attributes: dict[str, Any],
        observed_at: datetime,
    ) -> None:
        await self._registry.record_observed_state(
            device.id,
            state=state,
            attributes=attributes,
            source=device.adapter_id,
            observed_at=observed_at,
        )


__all__ = ["DeviceApplicationService", "DeviceServiceResult"]
