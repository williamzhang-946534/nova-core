from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from arvuno_core.devices.models import (
    DeviceRiskLevel,
)
from arvuno_core.devices.registry import RegisteredDevice
from arvuno_core.robots.models import RobotCapabilityName
from arvuno_core.tools.models import (
    ControlDeviceInput,
    PermissionResult,
    RobotActionInput,
    RobotCapabilitiesInput,
    RobotConsentsInput,
    RobotStatusInput,
    RobotTaskHistoryInput,
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


class RobotPolicyReader(Protocol):
    async def find_robot_for_policy(self, robot_id: str) -> Any | None: ...


ROBOT_ACTION_CAPABILITIES = {
    "robot_observe_scene": RobotCapabilityName.OBSERVE_SCENE,
    "robot_look_at": RobotCapabilityName.LOOK_AT,
    "robot_speak": RobotCapabilityName.SPEAK,
    "robot_listen": RobotCapabilityName.LISTEN,
    "robot_safe_stop": RobotCapabilityName.REQUEST_SAFE_STOP,
    "robot_idle": RobotCapabilityName.ENTER_IDLE_POSE,
}

ROBOT_REQUIRED_CONSENTS = {
    "robot_observe_scene": "camera",
    "robot_look_at": "motion",
    "robot_speak": "speaker",
    "robot_listen": "microphone",
    "robot_idle": "motion",
}


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
        robot_reader: RobotPolicyReader | None = None,
    ) -> None:
        self._device_reader = device_reader
        self._tool_permissions = dict(tool_permissions)
        self._robot_reader = robot_reader

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

        if definition.name.startswith("robot_"):
            return await self._evaluate_robot(definition, raw_input, permission)

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

    async def _evaluate_robot(
        self,
        definition: ToolDefinition[Any, Any],
        raw_input: Any,
        permission: ToolPermission,
    ) -> SafetyDecision:
        details: dict[str, Any] = {
            "tool_name": definition.name,
            "configured_permission": permission.value,
        }
        if self._robot_reader is None:
            return self._decision(
                PermissionResult.DENIED,
                definition.risk_level,
                False,
                {**details, "reason": "robot_policy_is_unavailable"},
            )

        is_action = definition.name in ROBOT_ACTION_CAPABILITIES
        if is_action:
            if not isinstance(raw_input, RobotActionInput):
                return self._decision(
                    PermissionResult.DENIED,
                    definition.risk_level,
                    False,
                    {**details, "reason": "robot_action_input_is_invalid"},
                )
            robot_id = raw_input.robot_id
            space_id = raw_input.space_id
            details["space_id"] = space_id
        else:
            if not isinstance(
                raw_input,
                RobotStatusInput
                | RobotCapabilitiesInput
                | RobotConsentsInput
                | RobotTaskHistoryInput,
            ):
                return self._decision(
                    PermissionResult.DENIED,
                    definition.risk_level,
                    False,
                    {**details, "reason": "robot_query_input_is_invalid"},
                )
            robot_id = raw_input.robot_id

        snapshot = await self._robot_reader.find_robot_for_policy(robot_id)
        if snapshot is None:
            return self._decision(
                PermissionResult.DEVICE_NOT_FOUND,
                definition.risk_level,
                False,
                {**details, "reason": "robot_not_found", "robot_id": robot_id},
            )
        robot = snapshot.robot
        details.update(
            {
                "robot_id": robot.id,
                "robot_profile": robot.profile,
                "robot_enabled": robot.is_enabled,
            }
        )

        if not is_action:
            return self._decision(
                PermissionResult.ALLOWED,
                definition.risk_level,
                False,
                details,
            )

        if robot.profile != "desktop_robot":
            return self._decision(
                PermissionResult.RISK_EXCEEDED,
                definition.risk_level,
                False,
                {
                    **details,
                    "reason": "robot_profile_is_not_approved_for_execution",
                },
            )
        if not robot.is_enabled:
            return self._decision(
                PermissionResult.DEVICE_DISABLED,
                definition.risk_level,
                False,
                {**details, "reason": "robot_disabled"},
            )
        if not robot.is_online:
            return self._decision(
                PermissionResult.DEVICE_UNAVAILABLE,
                definition.risk_level,
                False,
                {**details, "reason": "robot_offline"},
            )

        expected_capability = ROBOT_ACTION_CAPABILITIES[definition.name]
        capability = next(
            (item for item in snapshot.capabilities if item.capability is expected_capability),
            None,
        )
        if capability is None:
            return self._decision(
                PermissionResult.ACTION_NOT_ALLOWED,
                definition.risk_level,
                False,
                {
                    **details,
                    "reason": "robot_capability_not_discovered",
                    "capability": expected_capability.value,
                },
            )
        if not (
            capability.discovered
            and capability.supported
            and capability.enabled
            and capability.approved
            and capability.executable
            and capability.runtime_enabled
        ):
            return self._decision(
                PermissionResult.ACTION_NOT_ALLOWED,
                definition.risk_level,
                False,
                {
                    **details,
                    "reason": "robot_capability_is_not_executable",
                    "capability": expected_capability.value,
                },
            )
        if capability.risk_level == "high_risk":
            return self._decision(
                PermissionResult.RISK_EXCEEDED,
                ToolRiskLevel.HIGH,
                False,
                {
                    **details,
                    "reason": "high_risk_robot_capabilities_are_disabled",
                    "capability": expected_capability.value,
                },
            )

        required_categories = set(capability.requires_consents)
        required_by_tool = ROBOT_REQUIRED_CONSENTS.get(definition.name)
        if required_by_tool is not None:
            required_categories.add(required_by_tool)
        missing = sorted(
            category
            for category in required_categories
            if not self._consent_is_active(
                snapshot.consents, robot_id, expected_capability, category, space_id
            )
        )
        if missing:
            return self._decision(
                PermissionResult.CONSENT_REQUIRED,
                definition.risk_level,
                False,
                {
                    **details,
                    "reason": "robot_consent_required",
                    "capability": expected_capability.value,
                    "missing_consents": missing,
                },
            )

        requires_confirmation = definition.requires_confirmation or capability.requires_confirmation
        if requires_confirmation:
            return self._decision(
                PermissionResult.CONFIRMATION_REQUIRED,
                definition.risk_level,
                True,
                {
                    **details,
                    "capability": expected_capability.value,
                    "risk_level": capability.risk_level,
                },
            )
        return self._decision(
            PermissionResult.ALLOWED,
            definition.risk_level,
            False,
            {
                **details,
                "capability": expected_capability.value,
                "risk_level": capability.risk_level,
            },
        )

    @staticmethod
    def _consent_is_active(
        consents: tuple[Any, ...],
        robot_id: str,
        capability: RobotCapabilityName,
        data_category: str,
        space_id: str,
    ) -> bool:
        now = datetime.now(UTC)
        return any(
            consent.robot_id == robot_id
            and consent.capability is capability
            and consent.data_category == data_category
            and consent.space_id == space_id
            and consent.status == "granted"
            and consent.revoked_at is None
            and (consent.expires_at is None or consent.expires_at > now)
            for consent in consents
        )

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
