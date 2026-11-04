import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from arvuno_core.devices.service import DeviceApplicationService
from arvuno_core.environment.context import EnvironmentStateSink
from arvuno_core.environment.query_models import (
    EnvironmentQueryResult,
    EnvironmentStateQueryInput,
)
from arvuno_core.memory.models import MemoryRetrievalResult
from arvuno_core.tools.models import (
    ControlDeviceInput,
    ControlDeviceOutput,
    GetDeviceStateInput,
    GetDeviceStateOutput,
    HistoryQueryInput,
    HistoryQueryOutput,
    ListDevicesInput,
    ListDevicesOutput,
    MemoryRetrievalInput,
    MemoryRetrievalOutput,
    ToolExecutionContext,
    ToolPermission,
    ToolRiskLevel,
)

ToolInputT = TypeVar("ToolInputT", bound=BaseModel)
ToolOutputT = TypeVar("ToolOutputT", bound=BaseModel)
ToolHandler = Callable[[ToolExecutionContext, Any], Awaitable[BaseModel]]

logger = logging.getLogger(__name__)


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
    environment_query_provider: Callable[
        [EnvironmentStateQueryInput], Awaitable[EnvironmentQueryResult]
    ]
    | None = None,
    environment_state_sink: EnvironmentStateSink | None = None,
    memory_retrieval_provider: Callable[[MemoryRetrievalInput], Awaitable[MemoryRetrievalResult]]
    | None = None,
    history_query_provider: Callable[[HistoryQueryInput], Awaitable[HistoryQueryOutput]]
    | None = None,
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
        raw_input: EnvironmentStateQueryInput,
    ) -> EnvironmentQueryResult:
        if environment_query_provider is None:
            return EnvironmentQueryResult(
                service_available=False,
                environment_name="unavailable",
                generated_at=datetime.now(UTC),
            )
        return await environment_query_provider(raw_input)

    async def retrieve_memory(
        _context: ToolExecutionContext,
        raw_input: MemoryRetrievalInput,
    ) -> MemoryRetrievalOutput:
        if memory_retrieval_provider is None:
            return MemoryRetrievalOutput(
                service_available=False,
                question_type=raw_input.question_type,
                query=raw_input.query,
            )
        result = await memory_retrieval_provider(raw_input)
        return MemoryRetrievalOutput(
            service_available=True,
            question_type=result.question_type,
            query=result.query,
            memories=result.memories,
            preferences=result.preferences,
            source_references=[
                evidence.model_dump(mode="json") for evidence in result.source_references
            ],
            retrieved_at=result.retrieved_at,
        )

    async def query_history(
        _context: ToolExecutionContext,
        raw_input: HistoryQueryInput,
    ) -> HistoryQueryOutput:
        if history_query_provider is None:
            return HistoryQueryOutput(
                service_available=False,
                operation=raw_input.operation,
            )
        return await history_query_provider(raw_input)

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
        if result.verified and environment_state_sink is not None:
            try:
                await environment_state_sink.apply_verified_state(
                    raw_input.device_id,
                    state=result.actual_state,
                    attributes=result.attributes,
                    observed_at=result.observed_at,
                )
            except Exception:
                logger.exception(
                    "environment_state_sync_failed",
                    extra={"payload": {"device_id": raw_input.device_id}},
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
            description="List devices enabled for Arvuno.",
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
            version="2.0.0",
            description="Read current spatial state estimates, sources, coverage, and evidence.",
            category="environment_query",
            risk_level=ToolRiskLevel.READ_ONLY,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=False,
            enabled=True,
            input_type=EnvironmentStateQueryInput,
            output_type=EnvironmentQueryResult,
            handler=get_environment_state,
        )
    )
    registry.register(
        ToolDefinition(
            name="retrieve_memory",
            version="1.0.0",
            description="Retrieve preferences, stable facts, memories, and validated procedures.",
            category="memory_query",
            risk_level=ToolRiskLevel.READ_ONLY,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=False,
            enabled=True,
            input_type=MemoryRetrievalInput,
            output_type=MemoryRetrievalOutput,
            handler=retrieve_memory,
        )
    )
    registry.register(
        ToolDefinition(
            name="query_history",
            version="1.0.0",
            description="Read observations, events, tasks, trends, snapshots, diffs, correlations.",
            category="history_query",
            risk_level=ToolRiskLevel.READ_ONLY,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=False,
            enabled=True,
            input_type=HistoryQueryInput,
            output_type=HistoryQueryOutput,
            handler=query_history,
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
