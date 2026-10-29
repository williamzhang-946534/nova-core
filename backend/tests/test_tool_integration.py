import asyncio
import itertools
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.devices.mock import MockDeviceAdapter
from arvuno_core.devices.models import ActionResult
from arvuno_core.devices.registry import DeviceRegistry
from arvuno_core.devices.service import DeviceApplicationService
from arvuno_core.events.bus import EventBus
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.tools import SqlToolExecutionStore
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.tools.confirmation import ConfirmationService
from arvuno_core.tools.executor import ToolExecutor
from arvuno_core.tools.models import PermissionResult, ToolExecutionContext, ToolRiskLevel
from arvuno_core.tools.registry import build_default_tool_registry
from arvuno_core.tools.safety import SafetyPolicy


def phase_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


def integration_parts(
    manager: DatabaseManager,
) -> tuple[MockDeviceAdapter, ToolExecutor, DeviceRegistry, EventBus]:
    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(manager.session_factory)

    counter = itertools.count(1)
    adapter = MockDeviceAdapter()
    registry = DeviceRegistry(factory)
    service = DeviceApplicationService(registry, {"mock": adapter})
    event_bus = EventBus(factory)
    executor = ToolExecutor(
        registry=build_default_tool_registry(service),
        safety_policy=SafetyPolicy(service, tool_permissions={}),
        confirmation_service=ConfirmationService(ttl_seconds=300),
        execution_store=SqlToolExecutionStore(factory),
        event_publisher=event_bus,
        execution_id_factory=lambda: f"execution-{next(counter)}",
    )
    return adapter, executor, registry, event_bus


def execution_store(manager: DatabaseManager) -> SqlToolExecutionStore:
    return SqlToolExecutionStore(lambda: SqlAlchemyUnitOfWork(manager.session_factory))


class PostActionVerificationFailureAdapter(MockDeviceAdapter):
    async def execute_action(self, external_id: str, action: Any) -> Any:
        item = self._require(external_id)
        self._validate_action(item.definition, action)
        return ActionResult(
            success=True,
            action_id=action.action_id,
            external_id=external_id,
            message="The adapter reported success without applying the action.",
        )


def test_mock_control_success_chain_persists_state_audit_and_event(tmp_path: Path) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))
    try:
        manager.initialize_database()

        async def scenario() -> str:
            adapter, executor, registry, _ = integration_parts(manager)
            await registry.sync_devices(adapter)
            device = await registry.get_by_external_id("mock", "mock.light.living_room")
            assert device is not None
            result = await executor.execute(
                "control_device",
                {"device_id": device.id, "action": "turn_on", "parameters": {}},
                context=ToolExecutionContext(correlation_id="correlation-success"),
            )
            return result.execution_id

        execution_id = asyncio.run(scenario())
        record = execution_store(manager).get_execution(execution_id)
        assert record is not None
        assert record.status == "completed"
        assert record.permission_result == PermissionResult.ALLOWED.value
        assert record.risk_level == ToolRiskLevel.LOW.value
        assert record.correlation_id == "correlation-success"
        assert record.output is not None
        assert record.output["verified"] is True
        assert record.output["actual_state"] == "on"

        with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
            assert uow.events is not None
            events, total = uow.events.query(event_type="tool_executed")
            assert total == 1
            assert events[0].subject_id == execution_id
            assert events[0].correlation_id == "correlation-success"
    finally:
        manager.dispose()


def test_mock_offline_timeout_and_action_failure_are_rejected(tmp_path: Path) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))
    try:
        manager.initialize_database()

        async def scenario() -> None:
            adapter, executor, registry, _ = integration_parts(manager)
            await registry.sync_devices(adapter)
            device = await registry.get_by_external_id("mock", "mock.light.living_room")
            assert device is not None
            raw_input = {"device_id": device.id, "action": "turn_on", "parameters": {}}

            adapter.set_offline("mock.light.living_room")
            with pytest.raises(Exception, match="unavailable"):
                await executor.execute(
                    "control_device", raw_input, context=ToolExecutionContext("correlation")
                )
            adapter.set_offline("mock.light.living_room", offline=False)

            adapter.set_timeout("mock.light.living_room")
            with pytest.raises(Exception, match="timed out"):
                await executor.execute(
                    "control_device", raw_input, context=ToolExecutionContext("correlation")
                )
            adapter.set_timeout("mock.light.living_room", timeout=False)

            adapter.set_action_failure("mock.light.living_room")
            with pytest.raises(Exception, match="action failed"):
                await executor.execute(
                    "control_device", raw_input, context=ToolExecutionContext("correlation")
                )

        asyncio.run(scenario())
        records = [
            execution_store(manager).get_execution(f"execution-{index}") for index in range(1, 4)
        ]
        assert all(record is not None for record in records)
        assert [record.status for record in records if record is not None] == [
            "failed",
            "failed",
            "failed",
        ]
        assert [record.error["code"] for record in records if record is not None] == [
            "DEVICE_UNAVAILABLE",
            "ADAPTER_TIMEOUT",
            "TOOL_EXECUTION_FAILED",
        ]
    finally:
        manager.dispose()


def test_successful_adapter_call_with_wrong_actual_state_is_not_success(tmp_path: Path) -> None:
    manager = DatabaseManager(phase_settings(tmp_path))
    try:
        manager.initialize_database()

        async def scenario() -> None:
            adapter = PostActionVerificationFailureAdapter()
            registry = DeviceRegistry(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
            service = DeviceApplicationService(registry, {"mock": adapter})
            executor = ToolExecutor(
                registry=build_default_tool_registry(service),
                safety_policy=SafetyPolicy(service, tool_permissions={}),
                confirmation_service=ConfirmationService(ttl_seconds=300),
                execution_store=execution_store(manager),
                execution_id_factory=lambda: "execution-verification",
            )
            await registry.sync_devices(adapter)
            device = await registry.get_by_external_id("mock", "mock.light.living_room")
            assert device is not None
            with pytest.raises(Exception, match="did not reach its expected state"):
                await executor.execute(
                    "control_device",
                    {"device_id": device.id, "action": "turn_on", "parameters": {}},
                    context=ToolExecutionContext(correlation_id="correlation-verify"),
                )

        asyncio.run(scenario())
        record = execution_store(manager).get_execution("execution-verification")
        assert record is not None
        assert record.status == "failed"
        assert record.error is not None
        assert record.error["code"] == "STATE_CONFLICT"
        assert record.output is None
    finally:
        manager.dispose()


def test_tools_api_requires_auth_and_executes_mock_tool(tmp_path: Path) -> None:
    settings = phase_settings(tmp_path)
    manager = DatabaseManager(settings)
    try:
        manager.initialize_database()
        app = create_app(
            settings,
            unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
            initialize_tool_runtime=True,
        )
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer test-api-token"}

            no_token = client.get("/api/tools")
            invalid_token = client.get("/api/tools", headers={"Authorization": "Bearer wrong"})
            catalog = client.get("/api/tools", headers=headers)
            devices = client.post(
                "/api/tools/list_devices/execute",
                headers=headers,
                json={"input": {}},
            )
            openapi = client.get("/openapi.json")

        assert no_token.status_code == 401
        assert invalid_token.status_code == 401
        assert catalog.status_code == 200
        assert [item["name"] for item in catalog.json()["data"]] == [
            "list_devices",
            "get_environment_state",
            "get_device_state",
            "control_device",
        ]
        assert devices.status_code == 200
        assert len(devices.json()["data"]["output"]["devices"]) == 6
        assert devices.json()["data"]["status"] == "completed"
        assert openapi.status_code == 200
        assert "/api/tools" in openapi.json()["paths"]
        assert "/api/tools/{tool_name}/execute" in openapi.json()["paths"]
    finally:
        manager.dispose()
