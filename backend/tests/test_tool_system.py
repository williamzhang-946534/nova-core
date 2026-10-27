import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nova_core.devices.models import (
    DeviceCapability,
    DevicePermissions,
    DeviceRiskLevel,
    DeviceType,
)
from nova_core.devices.registry import RegisteredDevice
from nova_core.tools.confirmation import ConfirmationService, ConfirmationSubject
from nova_core.tools.errors import (
    ToolConfirmationRequiredError,
    ToolNotFoundError,
    ToolPersistenceError,
    ToolStateConflictError,
    ToolValidationError,
)
from nova_core.tools.executor import ToolEventPublisherProtocol, ToolExecutor
from nova_core.tools.models import (
    ControlDeviceInput,
    ControlDeviceOutput,
    PermissionResult,
    ToolExecutionContext,
    ToolPermission,
    ToolRiskLevel,
)
from nova_core.tools.registry import ToolDefinition, ToolRegistry
from nova_core.tools.safety import SafetyPolicy
from nova_core.tools.storage import (
    ToolDefinitionRecord,
    ToolExecutionCreate,
    ToolExecutionUpdate,
)


class FixedReader:
    def __init__(self, device: RegisteredDevice | None = None) -> None:
        self.device = device

    async def find_device_for_policy(self, device_id: str) -> RegisteredDevice | None:
        return self.device if self.device is not None and self.device.id == device_id else None


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=32)


class EchoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str


@dataclass
class MemoryToolStore:
    definitions: dict[str, ToolDefinitionRecord] = field(default_factory=dict)
    executions: dict[str, ToolExecutionCreate | ToolExecutionUpdate] = field(default_factory=dict)
    fail_create: bool = False
    fail_update: bool = False

    def register_definition(self, record: ToolDefinitionRecord) -> None:
        self.definitions[record.name] = record

    def create_execution(self, record: ToolExecutionCreate) -> None:
        if self.fail_create:
            raise RuntimeError("execution persistence failed")
        self.executions[record.id] = record

    def update_execution(self, execution_id: str, record: ToolExecutionUpdate) -> None:
        if self.fail_update:
            raise RuntimeError("update persistence failed")
        self.executions[execution_id] = record

    def get_execution(self, execution_id: str) -> Any:
        return self.executions.get(execution_id)


@dataclass
class EventPublisher:
    events: list[Any] = field(default_factory=list)
    fail: bool = False

    async def publish(self, event: Any) -> None:
        if self.fail:
            raise RuntimeError("event publisher failed")
        self.events.append(event)


class FixedClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def device(
    *,
    risk_level: DeviceRiskLevel = DeviceRiskLevel.LOW,
    capability_risk: DeviceRiskLevel = DeviceRiskLevel.LOW,
    max_risk: DeviceRiskLevel = DeviceRiskLevel.LOW,
    enabled: bool = True,
    online: bool = True,
) -> RegisteredDevice:
    return RegisteredDevice(
        id="018f3a1b-8b68-7d67-a204-4dbd5ebd5a91",
        adapter_id="mock",
        external_id="mock.light.living_room",
        name="Virtual Light",
        device_type=DeviceType.LIGHT,
        capabilities=[
            DeviceCapability(
                capability="control",
                actions=["turn_on"],
                risk_level=capability_risk,
            )
        ],
        risk_level=risk_level,
        is_online=online,
        is_enabled=enabled,
        permissions=DevicePermissions(
            allowed_actions=["turn_on"],
            max_risk_level=max_risk,
        ),
    )


def definition(
    *,
    name: str = "test_tool",
    input_type: type[BaseModel] = EchoInput,
    output_type: type[BaseModel] = EchoOutput,
    risk_level: ToolRiskLevel = ToolRiskLevel.READ_ONLY,
    permission: ToolPermission = ToolPermission.ALLOW,
    requires_confirmation: bool = False,
    enabled: bool = True,
    handler: Any | None = None,
) -> ToolDefinition[Any, Any]:
    async def default_handler(_context: ToolExecutionContext, raw_input: Any) -> BaseModel:
        return EchoOutput(value=raw_input.value)

    return ToolDefinition(
        name=name,
        version="1.0.0",
        description="test tool",
        category="test",
        risk_level=risk_level,
        default_permission=permission,
        requires_confirmation=requires_confirmation,
        enabled=enabled,
        input_type=input_type,
        output_type=output_type,
        handler=handler or default_handler,
    )


def control_definition() -> ToolDefinition[Any, Any]:
    return definition(
        name="control_device",
        input_type=ControlDeviceInput,
        output_type=ControlDeviceOutput,
        risk_level=ToolRiskLevel.LOW,
        permission=ToolPermission.ALLOW_LOW_RISK,
    )


def execution_context() -> ToolExecutionContext:
    return ToolExecutionContext(correlation_id="correlation-1")


def make_executor(
    tool_definition: ToolDefinition[Any, Any],
    store: MemoryToolStore,
    *,
    device: RegisteredDevice | None = None,
    permissions: dict[str, str] | None = None,
    confirmation_service: ConfirmationService | None = None,
    publisher: ToolEventPublisherProtocol | None = None,
) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(tool_definition)
    return ToolExecutor(
        registry=registry,
        safety_policy=SafetyPolicy(
            FixedReader(device),
            tool_permissions=permissions or {tool_definition.name: "allow"},
        ),
        confirmation_service=confirmation_service or ConfirmationService(ttl_seconds=300),
        execution_store=store,
        event_publisher=publisher,
    )


def test_control_input_schema_accepts_only_defined_parameters() -> None:
    ControlDeviceInput.model_validate(
        {"device_id": "device-id", "action": "turn_on", "parameters": {}}
    )
    ControlDeviceInput.model_validate(
        {
            "device_id": "device-id",
            "action": "set_brightness",
            "parameters": {"brightness_pct": 80},
        }
    )
    ControlDeviceInput.model_validate(
        {
            "device_id": "device-id",
            "action": "set_temperature",
            "parameters": {"temperature": 24.5},
        }
    )

    invalid = [
        {"device_id": "device-id", "action": "turn_on", "parameters": {"extra": 1}},
        {"device_id": "device-id", "action": "set_brightness", "parameters": {"x": 1}},
        {
            "device_id": "device-id",
            "action": "set_brightness",
            "parameters": {"brightness_pct": 0},
        },
        {
            "device_id": "device-id",
            "action": "set_temperature",
            "parameters": {"temperature": 36},
        },
        {"device_id": "device-id", "action": "unknown"},
    ]
    for raw_input in invalid:
        with pytest.raises(ValidationError):
            ControlDeviceInput.model_validate(raw_input)


@pytest.mark.parametrize(
    ("item", "permission", "expected"),
    [
        (device(), "allow_low_risk", PermissionResult.ALLOWED),
        (device(enabled=False), "allow_low_risk", PermissionResult.DEVICE_DISABLED),
        (device(online=False), "allow_low_risk", PermissionResult.DEVICE_UNAVAILABLE),
        (
            device(capability_risk=DeviceRiskLevel.MEDIUM),
            "allow_low_risk",
            PermissionResult.RISK_EXCEEDED,
        ),
        (
            device(
                capability_risk=DeviceRiskLevel.MEDIUM,
                max_risk=DeviceRiskLevel.MEDIUM,
            ),
            "require_confirmation",
            PermissionResult.CONFIRMATION_REQUIRED,
        ),
        (
            device(
                capability_risk=DeviceRiskLevel.HIGH,
                max_risk=DeviceRiskLevel.HIGH,
            ),
            "allow",
            PermissionResult.RISK_EXCEEDED,
        ),
    ],
)
def test_safety_policy_checks_device_risk_and_availability(
    item: RegisteredDevice,
    permission: str,
    expected: PermissionResult,
) -> None:
    policy = SafetyPolicy(FixedReader(item), tool_permissions={"control_device": permission})
    raw_input = ControlDeviceInput(device_id=item.id, action="turn_on")

    decision = asyncio.run(policy.evaluate(control_definition(), raw_input))

    assert decision.permission_result is expected


def test_safety_policy_rejects_missing_disabled_and_unauthorized_paths() -> None:
    raw_input = ControlDeviceInput(device_id=device().id, action="turn_on")
    missing = SafetyPolicy(FixedReader(), tool_permissions={"control_device": "allow"})
    denied = SafetyPolicy(FixedReader(device()), tool_permissions={"control_device": "deny"})
    read_only = SafetyPolicy(
        FixedReader(device()),
        tool_permissions={"control_device": "allow_read_only"},
    )
    unauthorized_device = device().model_copy(
        update={
            "permissions": DevicePermissions(
                allowed_actions=["turn_off"],
                max_risk_level=DeviceRiskLevel.LOW,
            )
        }
    )
    unauthorized = SafetyPolicy(
        FixedReader(unauthorized_device),
        tool_permissions={"control_device": "allow_low_risk"},
    )

    decisions = [
        asyncio.run(missing.evaluate(control_definition(), raw_input)),
        asyncio.run(denied.evaluate(control_definition(), raw_input)),
        asyncio.run(read_only.evaluate(control_definition(), raw_input)),
        asyncio.run(unauthorized.evaluate(control_definition(), raw_input)),
        asyncio.run(
            SafetyPolicy(
                FixedReader(),
                tool_permissions={"test_tool": "allow"},
            ).evaluate(definition(enabled=False), EchoInput(value="x"))
        ),
    ]

    assert [item.permission_result for item in decisions] == [
        PermissionResult.DEVICE_NOT_FOUND,
        PermissionResult.DENIED,
        PermissionResult.DENIED,
        PermissionResult.ACTION_NOT_ALLOWED,
        PermissionResult.TOOL_DISABLED,
    ]


def test_confirmation_tokens_expire_are_single_use_and_bound() -> None:
    clock = FixedClock()
    service = ConfirmationService(ttl_seconds=60, clock=clock)
    subject = ConfirmationSubject(
        tool_name="test_tool",
        input_fingerprint="input-hash",
        task_id="018f3a1b-8b68-7d67-a204-4dbd5ebd5a92",
    )

    token = service.issue(subject)
    assert service.consume(token, subject)
    assert not service.consume(token, subject)

    expired = service.issue(subject)
    clock.now += timedelta(seconds=61)
    assert not service.consume(expired, subject)

    valid = service.issue(subject)
    input_bound = service.issue(subject)
    task_bound = service.issue(subject)
    different_input = replace(subject, input_fingerprint="other-hash")
    different_task = replace(subject, task_id=None)
    assert not service.consume(input_bound, different_input)
    assert not service.consume(task_bound, different_task)
    assert service.consume(valid, subject)


def test_executor_success_persists_validation_risk_and_event() -> None:
    store = MemoryToolStore()
    publisher = EventPublisher()
    test_executor = make_executor(definition(), store, publisher=publisher)

    result = asyncio.run(
        test_executor.execute("test_tool", {"value": "hello"}, context=execution_context())
    )

    record = store.get_execution(result.execution_id)
    assert isinstance(record, ToolExecutionUpdate)
    assert record.status == "completed"
    assert record.output == {"value": "hello"}
    assert record.validation == {"schema_valid": True, "verified": True}
    assert record.risk_level == ToolRiskLevel.READ_ONLY.value
    assert record.permission_result == PermissionResult.ALLOWED.value
    assert record.completed_at is not None
    assert record.duration_ms is not None
    assert len(publisher.events) == 1


def test_executor_records_invalid_input_and_rejects_unknown_tool() -> None:
    store = MemoryToolStore()
    test_executor = make_executor(definition(), store)

    with pytest.raises(ToolValidationError):
        asyncio.run(
            test_executor.execute(
                "test_tool",
                {"value": "", "extra": 1},
                context=execution_context(),
            )
        )
    with pytest.raises(ToolNotFoundError):
        asyncio.run(test_executor.execute("missing", {"value": "x"}, context=execution_context()))

    assert len(store.executions) == 1
    record = next(iter(store.executions.values()))
    assert isinstance(record, ToolExecutionUpdate)
    assert record.status == "rejected"
    assert record.permission_result == PermissionResult.DENIED.value
    assert record.error is not None
    assert record.error["code"] == ToolValidationError("").code


def test_medium_risk_requires_confirmation_and_rejects_expired_or_replayed_tokens() -> None:
    clock = FixedClock()
    confirmation = ConfirmationService(ttl_seconds=60, clock=clock)
    store = MemoryToolStore()
    test_executor = make_executor(
        definition(risk_level=ToolRiskLevel.MEDIUM),
        store,
        permissions={"test_tool": "allow"},
        confirmation_service=confirmation,
    )
    raw_input = {"value": "medium"}

    with pytest.raises(ToolConfirmationRequiredError) as required:
        asyncio.run(test_executor.execute("test_tool", raw_input, context=execution_context()))
    token = required.value.details["confirmation_token"]
    confirmed = asyncio.run(
        test_executor.execute(
            "test_tool",
            raw_input,
            context=execution_context(),
            confirmation_token=token,
        )
    )
    assert confirmed.status == "completed"

    with pytest.raises(Exception, match="invalid, expired"):
        asyncio.run(
            test_executor.execute(
                "test_tool",
                raw_input,
                context=execution_context(),
                confirmation_token=token,
            )
        )

    with pytest.raises(ToolConfirmationRequiredError) as expired_required:
        asyncio.run(test_executor.execute("test_tool", raw_input, context=execution_context()))
    expired_token = expired_required.value.details["confirmation_token"]
    clock.now += timedelta(seconds=61)
    with pytest.raises(Exception, match="invalid, expired"):
        asyncio.run(
            test_executor.execute(
                "test_tool",
                raw_input,
                context=execution_context(),
                confirmation_token=expired_token,
            )
        )


def test_executor_rejects_high_risk_and_persists_rejection() -> None:
    store = MemoryToolStore()
    test_executor = make_executor(
        definition(risk_level=ToolRiskLevel.HIGH),
        store,
        permissions={"test_tool": "require_confirmation"},
    )

    with pytest.raises(Exception) as error:
        asyncio.run(
            test_executor.execute("test_tool", {"value": "high"}, context=execution_context())
        )

    assert error.value.details["risk_level"] == ToolRiskLevel.HIGH.value
    record = next(iter(store.executions.values()))
    assert isinstance(record, ToolExecutionUpdate)
    assert record.status == "rejected"
    assert record.permission_result == PermissionResult.RISK_EXCEEDED.value


def test_persistence_failures_prevent_execution_or_success_response() -> None:
    create_failure = MemoryToolStore(fail_create=True)
    create_executor = make_executor(definition(), create_failure)
    with pytest.raises(ToolPersistenceError):
        asyncio.run(
            create_executor.execute("test_tool", {"value": "x"}, context=execution_context())
        )

    update_failure = MemoryToolStore(fail_update=True)
    update_executor = make_executor(definition(), update_failure)
    with pytest.raises(ToolPersistenceError):
        asyncio.run(
            update_executor.execute("test_tool", {"value": "x"}, context=execution_context())
        )


def test_event_publisher_failure_does_not_invalidate_verified_result() -> None:
    store = MemoryToolStore()
    test_executor = make_executor(
        definition(),
        store,
        publisher=EventPublisher(fail=True),
    )

    result = asyncio.run(
        test_executor.execute("test_tool", {"value": "x"}, context=execution_context())
    )

    assert result.status == "completed"
    assert result.verified is True


def test_unverified_control_output_is_persisted_as_failed() -> None:
    store = MemoryToolStore()
    observed_at = FixedClock().now

    async def handler(
        _context: ToolExecutionContext,
        raw_input: ControlDeviceInput,
    ) -> ControlDeviceOutput:
        return ControlDeviceOutput(
            device_id=raw_input.device_id,
            action=raw_input.action,
            executed=True,
            verified=False,
            actual_state="off",
            observed_at=observed_at,
        )

    test_executor = make_executor(
        definition(
            name="control_device",
            input_type=ControlDeviceInput,
            output_type=ControlDeviceOutput,
            risk_level=ToolRiskLevel.LOW,
            permission=ToolPermission.ALLOW_LOW_RISK,
            handler=handler,
        ),
        store,
        device=device(),
        permissions={"control_device": "allow_low_risk"},
    )

    with pytest.raises(ToolStateConflictError):
        asyncio.run(
            test_executor.execute(
                "control_device",
                {"device_id": device().id, "action": "turn_on"},
                context=execution_context(),
            )
        )

    record = next(iter(store.executions.values()))
    assert isinstance(record, ToolExecutionUpdate)
    assert record.status == "failed"
    assert record.validation == {"schema_valid": True, "verified": False}
    assert record.output is not None
    assert record.output["verified"] is False
