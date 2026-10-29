from dataclasses import dataclass
from typing import Any, Protocol

from arvuno_core.devices.models import (
    DeviceRiskLevel,
)
from arvuno_core.devices.registry import RegisteredDevice
from arvuno_core.tools.models import (
    ControlDeviceInput,
    PermissionResult,
    ToolPermission,
    ToolRiskLevel,
)
from arvuno_core.tools.registry import ToolDefinition

_RISK_ORDER = {
    ToolRiskLevel.READ_ONLY: 0,
    ToolRiskLevel.LOW: 1,
    ToolRiskLevel.MEDIUM: 2,
    ToolRiskLevel.HIGH: 3,
}


class DevicePolicyReader(Protocol):
    async def find_device_for_policy(self, device_id: str) -> RegisteredDevice | None: ...


@dataclass(frozen=True)
class SafetyDecision:
    permission_result: PermissionResult
    risk_level: ToolRiskLevel
    requires_confirmation: bool
    details: dict[str, Any]


class SafetyPolicy:
    """Independent risk and permission checks for validated tool input."""

    def __init__(
        self,
        device_reader: DevicePolicyReader,
        *,
        tool_permissions: dict[str, str],
    ) -> None:
        self._device_reader = device_reader
        self._tool_permissions = dict(tool_permissions)

    async def evaluate(
        self,
        definition: ToolDefinition[Any, Any],
        raw_input: Any,
    ) -> SafetyDecision:
        if not definition.enabled:
            return self._decision(
                PermissionResult.TOOL_DISABLED,
                definition.risk_level,
                False,
                {"reason": "tool_disabled"},
            )

        configured = self._tool_permissions.get(
            definition.name,
            definition.default_permission.value,
        )
        permission = ToolPermission(configured)
        if permission is ToolPermission.DENY:
            return self._decision(
                PermissionResult.DENIED,
                definition.risk_level,
                False,
                {"reason": "tool_denied"},
            )
        if (
            permission is ToolPermission.ALLOW_READ_ONLY
            and definition.risk_level is not ToolRiskLevel.READ_ONLY
        ):
            return self._decision(
                PermissionResult.DENIED,
                definition.risk_level,
                False,
                {"reason": "write_tools_are_not_allowed"},
            )

        risk_level = definition.risk_level
        requires_confirmation = definition.requires_confirmation
        details: dict[str, Any] = {"configured_permission": permission.value}

        if definition.name == "control_device" and isinstance(raw_input, ControlDeviceInput):
            device = await self._device_reader.find_device_for_policy(raw_input.device_id)
            if device is None:
                return self._decision(
                    PermissionResult.DEVICE_NOT_FOUND,
                    definition.risk_level,
                    False,
                    {**details, "device_id": raw_input.device_id},
                )
            if not device.is_enabled:
                return self._decision(
                    PermissionResult.DEVICE_DISABLED,
                    definition.risk_level,
                    False,
                    {**details, "device_id": device.id},
                )
            if raw_input.action not in device.permissions.allowed_actions:
                return self._decision(
                    PermissionResult.ACTION_NOT_ALLOWED,
                    definition.risk_level,
                    False,
                    {**details, "device_id": device.id, "action": raw_input.action.value},
                )

            capability = next(
                (item for item in device.capabilities if raw_input.action in item.actions),
                None,
            )
            if capability is None:
                return self._decision(
                    PermissionResult.ACTION_NOT_ALLOWED,
                    definition.risk_level,
                    False,
                    {**details, "device_id": device.id, "action": raw_input.action.value},
                )

            if device.risk_level is not None:
                risk_level = self._max_tool_risk(
                    risk_level,
                    _device_risk(device.risk_level),
                )
            risk_level = self._max_tool_risk(
                risk_level,
                _device_risk(capability.risk_level),
            )
            requires_confirmation = (
                requires_confirmation
                or device.permissions.requires_confirmation
                or capability.requires_confirmation
            )
            max_device_risk = _device_risk(device.permissions.max_risk_level)
            if _RISK_ORDER[risk_level] > _RISK_ORDER[max_device_risk]:
                return self._decision(
                    PermissionResult.RISK_EXCEEDED,
                    risk_level,
                    False,
                    {
                        **details,
                        "device_id": device.id,
                        "max_risk_level": device.permissions.max_risk_level.value,
                    },
                )
            if not device.is_online:
                return self._decision(
                    PermissionResult.DEVICE_UNAVAILABLE,
                    risk_level,
                    False,
                    {**details, "device_id": device.id, "reason": "device_offline"},
                )
            details.update(
                {
                    "device_id": device.id,
                    "device_risk_level": device.risk_level.value,
                    "capability_risk_level": capability.risk_level.value,
                    "max_risk_level": device.permissions.max_risk_level.value,
                }
            )

        if permission is ToolPermission.ALLOW_LOW_RISK and _RISK_ORDER[risk_level] > 1:
            return self._decision(
                PermissionResult.RISK_EXCEEDED,
                risk_level,
                False,
                {**details, "reason": "risk_exceeds_allow_low_risk"},
            )
        if (
            permission is ToolPermission.ALLOW_READ_ONLY
            and _RISK_ORDER[risk_level] > _RISK_ORDER[ToolRiskLevel.READ_ONLY]
        ):
            return self._decision(
                PermissionResult.DENIED,
                risk_level,
                False,
                {**details, "reason": "write_tools_are_not_allowed"},
            )
        if risk_level is ToolRiskLevel.HIGH:
            return self._decision(
                PermissionResult.RISK_EXCEEDED,
                risk_level,
                False,
                {**details, "reason": "high_risk_tools_are_disabled"},
            )
        if permission is ToolPermission.REQUIRE_CONFIRMATION:
            requires_confirmation = True
        if risk_level is ToolRiskLevel.MEDIUM:
            requires_confirmation = True
        if requires_confirmation and risk_level is ToolRiskLevel.MEDIUM:
            return self._decision(
                PermissionResult.CONFIRMATION_REQUIRED,
                risk_level,
                True,
                details,
            )
        if requires_confirmation:
            return self._decision(
                PermissionResult.CONFIRMATION_REQUIRED,
                risk_level,
                True,
                details,
            )
        return self._decision(PermissionResult.ALLOWED, risk_level, False, details)

    @staticmethod
    def _decision(
        result: PermissionResult,
        risk_level: ToolRiskLevel,
        requires_confirmation: bool,
        details: dict[str, Any],
    ) -> SafetyDecision:
        return SafetyDecision(
            permission_result=result,
            risk_level=risk_level,
            requires_confirmation=requires_confirmation,
            details=details,
        )

    @staticmethod
    def _max_tool_risk(left: ToolRiskLevel, right: ToolRiskLevel) -> ToolRiskLevel:
        return left if _RISK_ORDER[left] >= _RISK_ORDER[right] else right


def _device_risk(value: DeviceRiskLevel) -> ToolRiskLevel:
    if value is DeviceRiskLevel.MEDIUM:
        return ToolRiskLevel.MEDIUM
    if value is DeviceRiskLevel.HIGH:
        return ToolRiskLevel.HIGH
    return ToolRiskLevel.LOW


__all__ = ["DevicePolicyReader", "SafetyDecision", "SafetyPolicy"]
