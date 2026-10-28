from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from nova_core.devices.service import DeviceApplicationService
from nova_core.environment.context import EnvironmentContextState, area_summary
from nova_core.tools.models import (
    ControlDeviceInput,
    ControlDeviceOutput,
    GetDeviceStateInput,
    GetDeviceStateOutput,
    GetEnvironmentStateInput,
    GetEnvironmentStateOutput,
    ListDevicesInput,
    ListDevicesOutput,
    ToolExecutionContext,
    ToolPermission,
    ToolRiskLevel,
)

ToolInputT = TypeVar("ToolInputT", bound=BaseModel)
ToolOutputT = TypeVar("ToolOutputT", bound=BaseModel)
ToolHandler = Callable[[ToolExecutionContext, Any], Awaitable[BaseModel]]


@dataclass(frozen=True)
class ToolDefinition(Generic[ToolInputT, ToolOutputT]):
    name: str
    version: str
    description: str
    category: str
    risk_level: ToolRiskLevel
    default_permission: ToolPermission
    requires_confirmation: bool
    enabled: bool
    input_type: type[ToolInputT]
    output_type: type[ToolOutputT]
    handler: ToolHandler


class ToolRegistry:
    """Registers internal handlers and exposes only schema projections to callers."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition[Any, Any]] = {}

    def register(self, definition: ToolDefinition[Any, Any]) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Tool is already registered: {definition.name}")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition[Any, Any] | None:
        return self._tools.get(name)

    def catalog(self, *, enabled_only: bool = True) -> list[dict[str, Any]]:
        return [
            _catalog_item(definition)
            for definition in self._tools.values()
            if not (enabled_only and not definition.enabled)
        ]


def _catalog_item(definition: ToolDefinition[Any, Any]) -> dict[str, Any]:
    return {
        "name": definition.name,
        "version": definition.version,
        "description": definition.description,
        "category": definition.category,
        "input_schema": definition.input_type.model_json_schema(),
        "output_schema": definition.output_type.model_json_schema(),
        "risk_level": definition.risk_level.value,
        "default_permission": definition.default_permission.value,
        "requires_confirmation": definition.requires_confirmation,
        "enabled": definition.enabled,
    }


def build_default_tool_registry(
    device_service: DeviceApplicationService,
    *,
    environment_state_provider: Callable[[], EnvironmentContextState] | None = None,
) -> ToolRegistry:
    async def list_devices(
        _context: ToolExecutionContext,
        raw_input: ListDevicesInput,
    ) -> ListDevicesOutput:
        devices = await device_service.list_devices(
            area=raw_input.area,
            device_type=raw_input.device_type,
            online=raw_input.online,
        )
        return ListDevicesOutput(
            devices=[
                {
                    "id": device.id,
                    "name": device.name,
                    "device_type": device.device_type.value,
                    "area": device.area,
                    "is_online": device.is_online,
                    "state": None,
                }
                for device in devices
            ]
        )

    async def get_device_state(
        _context: ToolExecutionContext,
        raw_input: GetDeviceStateInput,
    ) -> GetDeviceStateOutput:
        state = await device_service.get_state(raw_input.device_id)
        return GetDeviceStateOutput(
            device_id=raw_input.device_id,
            state=state.actual_state,
            attributes=state.attributes,
            observed_at=state.observed_at,
        )

    async def get_environment_state(
        _context: ToolExecutionContext,
        raw_input: GetEnvironmentStateInput,
    ) -> GetEnvironmentStateOutput:
        state = (
            environment_state_provider()
            if environment_state_provider is not None
            else EnvironmentContextState()
        )
        devices = [
            device.model_dump(mode="json")
            for device in state.devices.values()
            if raw_input.area is None or device.area == raw_input.area
        ]
        sensors = [
            sensor.model_dump(mode="json")
            for sensor in state.sensors.values()
            if raw_input.area is None
            or next(
                (
                    device.area
                    for device in state.devices.values()
                    if device.device_id == sensor.device_id
                ),
                None,
            )
            == raw_input.area
        ]
        return GetEnvironmentStateOutput(
            environment_id=state.environment_id,
            environment_name=state.environment_name,
            updated_at=state.updated_at,
            devices=devices if raw_input.include_devices else [],
            sensors=sensors if raw_input.include_devices else [],
            areas=area_summary(state),
            recent_events=[],
        )

    async def control_device(
        _context: ToolExecutionContext,
        raw_input: ControlDeviceInput,
    ) -> ControlDeviceOutput:
        result = await device_service.control_device(
            raw_input.device_id,
            action=raw_input.action.value,
            parameters=raw_input.parameters,
            expected_state=raw_input.expected_state,
        )
        return ControlDeviceOutput(
            device_id=raw_input.device_id,
            action=raw_input.action,
            executed=True,
            verified=result.verified,
            actual_state=result.actual_state,
            attributes=result.attributes,
            observed_at=result.observed_at,
        )

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="list_devices",
            version="1.0.0",
            description="List devices enabled for Nova.",
            category="device_query",
            risk_level=ToolRiskLevel.READ_ONLY,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=False,
            enabled=True,
            input_type=ListDevicesInput,
            output_type=ListDevicesOutput,
            handler=list_devices,
        )
    )
    registry.register(
        ToolDefinition(
            name="get_environment_state",
            version="1.0.0",
            description="Read the current Nova environment context.",
            category="environment_query",
            risk_level=ToolRiskLevel.READ_ONLY,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=False,
            enabled=True,
            input_type=GetEnvironmentStateInput,
            output_type=GetEnvironmentStateOutput,
            handler=get_environment_state,
        )
    )
    registry.register(
        ToolDefinition(
            name="get_device_state",
            version="1.0.0",
            description="Read the current normalized state of one device.",
            category="device_query",
            risk_level=ToolRiskLevel.READ_ONLY,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=False,
            enabled=True,
            input_type=GetDeviceStateInput,
            output_type=GetDeviceStateOutput,
            handler=get_device_state,
        )
    )
    registry.register(
        ToolDefinition(
            name="control_device",
            version="1.0.0",
            description="Execute an enabled low-risk device action and verify its state.",
            category="device_control",
            risk_level=ToolRiskLevel.LOW,
            default_permission=ToolPermission.ALLOW_LOW_RISK,
            requires_confirmation=False,
            enabled=True,
            input_type=ControlDeviceInput,
            output_type=ControlDeviceOutput,
            handler=control_device,
        )
    )
    return registry
