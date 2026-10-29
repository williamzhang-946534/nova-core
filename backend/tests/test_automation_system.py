import asyncio
import itertools
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from arvuno_core.app import create_app
from arvuno_core.automation.evaluator import evaluate_condition
from arvuno_core.automation.models import (
    AutomationCondition,
    AutomationCreate,
    AutomationRunStatus,
    AutomationToolAction,
    AutomationTrigger,
)
from arvuno_core.automation.notifications import NotificationService
from arvuno_core.automation.service import AutomationService
from arvuno_core.config import Settings
from arvuno_core.devices.mock import MockDeviceAdapter
from arvuno_core.devices.registry import DeviceRegistry
from arvuno_core.devices.service import DeviceApplicationService
from arvuno_core.events.bus import EventBus
from arvuno_core.events.models import (
    ArvunoEvent,
    ArvunoEventSource,
    ArvunoEventType,
    DeviceStateChangedPayload,
    SensorUpdatedPayload,
)
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.tools import SqlToolExecutionStore
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.tasks.models import TaskStatus
from arvuno_core.tasks.service import TaskService
from arvuno_core.tools.confirmation import ConfirmationService
from arvuno_core.tools.executor import ToolExecutor
from arvuno_core.tools.registry import build_default_tool_registry
from arvuno_core.tools.safety import SafetyPolicy


def automation_settings(tmp_path: Path, *, token: str | None = None) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token=token or "test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


@dataclass
class FixedClock:
    now: datetime = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@dataclass
class AutomationEnvironment:
    manager: DatabaseManager
    adapter: MockDeviceAdapter
    event_bus: EventBus
    task_service: TaskService
    automation_service: AutomationService
    notification_service: NotificationService
    clock: FixedClock


def registered_temperature_sensor(
    environment: AutomationEnvironment,
) -> str:
    registry = DeviceRegistry(lambda: SqlAlchemyUnitOfWork(environment.manager.session_factory))
    asyncio.run(registry.sync_devices(environment.adapter))
    sensor = asyncio.run(registry.get_by_external_id("mock", "mock.sensor.temperature"))
    assert sensor is not None
    return sensor.id


def automation_environment(
    manager: DatabaseManager,
    *,
    tool_permissions: dict[str, str] | None = None,
) -> AutomationEnvironment:
    clock = FixedClock()

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(manager.session_factory)

    adapter = MockDeviceAdapter(clock=clock)
    registry = DeviceRegistry(factory)
    event_bus = EventBus(factory)
    device_service = DeviceApplicationService(registry, {"mock": adapter})
    execution_counter = itertools.count(1)
    tool_executor = ToolExecutor(
        registry=build_default_tool_registry(device_service),
        safety_policy=SafetyPolicy(
            device_service,
            tool_permissions=tool_permissions
            or {
                "list_devices": "allow",
                "get_device_state": "allow",
                "get_environment_state": "allow",
                "control_device": "allow_low_risk",
            },
        ),
        confirmation_service=ConfirmationService(clock=clock, ttl_seconds=300),
        execution_store=SqlToolExecutionStore(factory),
        event_publisher=event_bus,
        execution_id_factory=lambda: f"execution-{next(execution_counter)}",
    )
    task_service = TaskService(factory, tool_executor, event_bus, clock=clock)
    notification_service = NotificationService(factory, clock=clock)
    automation_service = AutomationService(
        factory,
        task_service,
        event_bus,
        clock=clock,
        automation_id_factory=lambda: str(uuid4()),
        run_id_factory=lambda: str(uuid4()),
        event_id_factory=lambda: str(uuid4()),
    )
    event_bus.subscribe(
        automation_service.handle_event,
        event_types={
            ArvunoEventType.DEVICE_STATE_CHANGED.value,
            ArvunoEventType.SENSOR_UPDATED.value,
            ArvunoEventType.DEVICE_UNAVAILABLE.value,
        },
    )
    event_bus.subscribe(
        notification_service.handle_task_failed,
        event_types={ArvunoEventType.TASK_FAILED.value},
    )
    return AutomationEnvironment(
        manager,
        adapter,
        event_bus,
        task_service,
        automation_service,
        notification_service,
        clock,
    )


def temperature_event(
    device_id: str,
    value: float,
    *,
    correlation_id: str = "automation-correlation",
) -> ArvunoEvent:
    return ArvunoEvent(
        id=str(uuid4()),
        event_type=ArvunoEventType.SENSOR_UPDATED,
        source=ArvunoEventSource.MOCK_ADAPTER,
        subject_type="device",
        subject_id=device_id,
        payload=SensorUpdatedPayload(
            device_id=device_id,
            sensor_type="temperature",
            value=value,
            unit="C",
            previous_value=value - 1,
        ),
        correlation_id=correlation_id,
        occurred_at=datetime.now(UTC),
    )


def state_event(
    device_id: str,
    *,
    correlation_id: str = "automation-tool-correlation",
) -> ArvunoEvent:
    return ArvunoEvent(
        id=str(uuid4()),
        event_type=ArvunoEventType.DEVICE_STATE_CHANGED,
        source=ArvunoEventSource.MOCK_ADAPTER,
        subject_type="device",
        subject_id=device_id,
        payload=DeviceStateChangedPayload(
            device_id=device_id,
            previous_state="off",
            current_state="on",
            attributes={"brightness": 80},
        ),
        correlation_id=correlation_id,
        occurred_at=datetime.now(UTC),
    )


def query_events(manager: DatabaseManager, correlation_id: str) -> list[str]:
    with SqlAlchemyUnitOfWork(manager.session_factory) as unit_of_work:
        assert unit_of_work.events is not None
        events, _ = unit_of_work.events.query(
            correlation_id=correlation_id,
            order="asc",
            page_size=100,
        )
        return [event.event_type for event in events]


def query_task_count(manager: DatabaseManager) -> int:
    with SqlAlchemyUnitOfWork(manager.session_factory) as unit_of_work:
        assert unit_of_work.tasks is not None
        page = unit_of_work.tasks.list(page_size=100)
        return page.total


def notification_rule(
    *,
    enabled: bool = True,
    cooldown_seconds: int = 600,
    subject_id: str | None = None,
    operator: str = "gt",
    value: float = 28,
) -> AutomationCreate:
    return AutomationCreate(
        name="High temperature notification",
        enabled=enabled,
        trigger=AutomationTrigger(
            event_type="sensor_updated",
            subject_id=subject_id,
        ),
        conditions=[
            AutomationCondition(
                field="payload.value",
                operator=operator,  # type: ignore[arg-type]
                value=value,
            )
        ],
        action={
            "type": "notification",
            "title": "温度过高",
            "message": "当前温度超过阈值。",
            "level": "warning",
        },
        cooldown_seconds=cooldown_seconds,
    )


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        (AutomationCondition(field="payload.value", operator="eq", value=30), True),
        (AutomationCondition(field="payload.value", operator="ne", value=30), False),
        (AutomationCondition(field="payload.value", operator="gt", value=29), True),
        (AutomationCondition(field="payload.value", operator="gte", value=30), True),
        (AutomationCondition(field="payload.value", operator="lt", value=30), False),
        (AutomationCondition(field="payload.value", operator="lte", value=30), True),
        (
            AutomationCondition(field="payload.tags", operator="contains", value="living"),
            True,
        ),
        (
            AutomationCondition(field="payload.value", operator="in", value=[29, 30]),
            True,
        ),
        (AutomationCondition(field="payload.missing", operator="eq", value=1), False),
    ],
)
def test_condition_operators_are_explicit(
    condition: AutomationCondition,
    expected: bool,
) -> None:
    source = {"payload": {"value": 30, "tags": ["living"]}}

    assert evaluate_condition(condition, source) is expected


def test_notification_rule_records_runs_notifications_and_cooldown(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(automation_settings(tmp_path))
    try:
        manager.initialize_database()
        environment = automation_environment(manager)
        sensor_id = registered_temperature_sensor(environment)
        rule = asyncio.run(
            environment.automation_service.create(notification_rule(subject_id=sensor_id))
        )

        async def scenario() -> None:
            await environment.event_bus.publish(
                temperature_event(sensor_id, 30, correlation_id="automation-correlation")
            )
            environment.clock.now += timedelta(seconds=1)
            await environment.event_bus.publish(
                temperature_event(sensor_id, 31, correlation_id="automation-correlation")
            )
            environment.clock.now += timedelta(seconds=601)
            await environment.event_bus.publish(
                temperature_event(sensor_id, 32, correlation_id="automation-correlation")
            )

        asyncio.run(scenario())
        runs = asyncio.run(environment.automation_service.list_runs(rule.id))
        notifications = asyncio.run(environment.notification_service.list())

        assert [run.status for run in runs.items] == [
            AutomationRunStatus.COMPLETED,
            AutomationRunStatus.COOLDOWN_SKIPPED,
            AutomationRunStatus.COMPLETED,
        ]
        assert runs.items[0].matched_context["correlation_id"] == "automation-correlation"
        assert runs.items[0].notification_id is not None
        assert notifications.total == 2
        assert notifications.items[0].title == "温度过高"
        assert query_events(manager, "automation-correlation").count("automation_triggered") == 2
    finally:
        manager.dispose()


def test_disabled_and_unmatched_rules_do_not_execute_actions(tmp_path: Path) -> None:
    manager = DatabaseManager(automation_settings(tmp_path))
    try:
        manager.initialize_database()
        environment = automation_environment(manager)
        sensor_id = registered_temperature_sensor(environment)
        disabled = asyncio.run(
            environment.automation_service.create(
                notification_rule(enabled=False, subject_id=sensor_id)
            )
        )
        unmatched = asyncio.run(
            environment.automation_service.create(notification_rule(subject_id=sensor_id, value=40))
        )

        asyncio.run(
            environment.event_bus.publish(
                temperature_event(sensor_id, 30, correlation_id="automation-not-matched")
            )
        )

        disabled_runs = asyncio.run(environment.automation_service.list_runs(disabled.id))
        unmatched_runs = asyncio.run(environment.automation_service.list_runs(unmatched.id))
        notifications = asyncio.run(environment.notification_service.list())
        assert disabled_runs.total == 0
        assert [run.status for run in unmatched_runs.items] == [
            AutomationRunStatus.CONDITION_NOT_MET
        ]
        assert notifications.total == 0
        assert "automation_triggered" not in query_events(manager, "automation-not-matched")
    finally:
        manager.dispose()


def test_high_risk_automation_is_rejected_before_task_creation(tmp_path: Path) -> None:
    manager = DatabaseManager(automation_settings(tmp_path))
    try:
        manager.initialize_database()
        environment = automation_environment(manager)
        sensor_id = registered_temperature_sensor(environment)
        rule = asyncio.run(
            environment.automation_service.create(
                AutomationCreate(
                    name="High-risk action",
                    trigger=AutomationTrigger(
                        event_type="sensor_updated",
                        subject_id=sensor_id,
                    ),
                    conditions=[],
                    action=AutomationToolAction(
                        tool_name="control_device",
                        input={},
                        title="Control automatically",
                        risk_level="high_risk",
                    ),
                    cooldown_seconds=0,
                )
            )
        )

        asyncio.run(
            environment.event_bus.publish(
                temperature_event(sensor_id, 30, correlation_id="automation-risk")
            )
        )

        runs = asyncio.run(environment.automation_service.list_runs(rule.id))
        assert [run.status for run in runs.items] == [AutomationRunStatus.RISK_REJECTED]
        assert runs.items[0].error is not None
        assert runs.items[0].error["code"] == "AUTOMATION_RISK_REJECTED"
        assert runs.items[0].task_id is None
        assert query_task_count(manager) == 0
        assert "automation_triggered" not in query_events(manager, "automation-risk")
    finally:
        manager.dispose()


def test_low_risk_tool_rule_executes_through_task_and_tool_executor(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(automation_settings(tmp_path))
    try:
        manager.initialize_database()
        environment = automation_environment(manager)
        registry = DeviceRegistry(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
        asyncio.run(registry.sync_devices(environment.adapter))
        light = asyncio.run(registry.get_by_external_id("mock", "mock.light.living_room"))
        assert light is not None
        rule = asyncio.run(
            environment.automation_service.create(
                AutomationCreate(
                    name="Turn on light when requested by context",
                    trigger=AutomationTrigger(
                        event_type="device_state_changed",
                        subject_id=light.id,
                    ),
                    conditions=[
                        AutomationCondition(
                            field="payload.current_state",
                            operator="eq",
                            value="on",
                        )
                    ],
                    action=AutomationToolAction(
                        tool_name="control_device",
                        input={"device_id": light.id, "action": "turn_on"},
                        title="Turn on light",
                        risk_level="low_risk",
                    ),
                    cooldown_seconds=0,
                )
            )
        )

        asyncio.run(
            environment.event_bus.publish(
                state_event(light.id, correlation_id="automation-tool-correlation")
            )
        )

        runs = asyncio.run(environment.automation_service.list_runs(rule.id))
        assert [run.status for run in runs.items] == [AutomationRunStatus.COMPLETED]
        task_id = runs.items[0].task_id
        assert task_id is not None
        task = asyncio.run(environment.task_service.get_task_detail(task_id))
        assert task.status is TaskStatus.COMPLETED
        assert task.origin == "automation"
        assert task.steps[0].tool_name == "control_device"
        assert task.executions[0].correlation_id == "automation-tool-correlation"
        assert task.executions[0].validation == {"schema_valid": True, "verified": True}
        assert set(query_events(manager, "automation-tool-correlation")) >= {
            "device_state_changed",
            "automation_triggered",
            "task_started",
            "tool_executed",
            "task_completed",
        }
    finally:
        manager.dispose()


def test_tool_failure_is_recorded_and_creates_task_failure_notification(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(automation_settings(tmp_path))
    try:
        manager.initialize_database()
        environment = automation_environment(manager)
        sensor_id = registered_temperature_sensor(environment)
        rule = asyncio.run(
            environment.automation_service.create(
                AutomationCreate(
                    name="Failing tool rule",
                    trigger=AutomationTrigger(
                        event_type="sensor_updated",
                        subject_id=sensor_id,
                    ),
                    action=AutomationToolAction(
                        tool_name="missing_tool",
                        input={},
                        title="Missing tool",
                        risk_level="read_only",
                    ),
                    cooldown_seconds=0,
                )
            )
        )

        asyncio.run(
            environment.event_bus.publish(
                temperature_event(sensor_id, 30, correlation_id="automation-failure")
            )
        )

        runs = asyncio.run(environment.automation_service.list_runs(rule.id))
        notifications = asyncio.run(environment.notification_service.list())
        assert [run.status for run in runs.items] == [AutomationRunStatus.FAILED]
        task_id = runs.items[0].task_id
        assert task_id is not None
        task = asyncio.run(environment.task_service.get_task_detail(task_id))
        assert task.status is TaskStatus.FAILED
        assert task.error is not None
        assert task.error["code"] == "TOOL_NOT_FOUND"
        assert runs.items[0].matched_context["event_id"]
        assert notifications.total == 1
        assert notifications.items[0].related_task_id == task_id
        assert notifications.items[0].related_event_id is not None
        assert "task_failed" in query_events(manager, "automation-failure")
    finally:
        manager.dispose()


def test_duplicate_concurrent_events_are_serialized_and_cooldown_skips_once(
    tmp_path: Path,
) -> None:
    manager = DatabaseManager(automation_settings(tmp_path))
    try:
        manager.initialize_database()
        environment = automation_environment(manager)
        sensor_id = registered_temperature_sensor(environment)
        rule = asyncio.run(
            environment.automation_service.create(notification_rule(subject_id=sensor_id))
        )
        first_event = temperature_event(sensor_id, 30, correlation_id="automation-repeat")
        second_event = temperature_event(sensor_id, 31, correlation_id="automation-repeat")

        async def scenario() -> None:
            await asyncio.gather(
                environment.event_bus.publish(first_event),
                environment.event_bus.publish(second_event),
            )

        asyncio.run(scenario())
        runs = asyncio.run(environment.automation_service.list_runs(rule.id))
        assert sorted(run.status for run in runs.items) == [
            AutomationRunStatus.COMPLETED,
            AutomationRunStatus.COOLDOWN_SKIPPED,
        ]
    finally:
        manager.dispose()


def test_automation_and_notification_api_requires_auth_and_exposes_history(
    tmp_path: Path,
) -> None:
    settings = automation_settings(tmp_path)
    manager = DatabaseManager(settings)
    try:
        manager.initialize_database()
        app = create_app(
            settings,
            unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
        )
        headers = {"Authorization": "Bearer test-api-token"}
        body = {
            "name": "API notification rule",
            "trigger": {"event_type": "sensor_updated"},
            "conditions": [{"field": "payload.value", "operator": "gt", "value": 28}],
            "action": {
                "type": "notification",
                "title": "温度过高",
                "message": "请查看环境状态。",
                "level": "warning",
            },
            "cooldown_seconds": 600,
        }
        with TestClient(app) as client:
            unauthorized = client.get("/api/automations")
            created = client.post("/api/automations", headers=headers, json=body)
            automation = created.json()["data"]
            detail = client.get(f"/api/automations/{automation['id']}", headers=headers)
            updated = client.patch(
                f"/api/automations/{automation['id']}",
                headers=headers,
                json={"cooldown_seconds": 300},
            )
            disabled = client.post(f"/api/automations/{automation['id']}/disable", headers=headers)
            enabled = client.post(f"/api/automations/{automation['id']}/enable", headers=headers)

            async def trigger() -> None:
                await app.state.event_bus.publish(temperature_event("sensor-api-device", 30))

            asyncio.run(trigger())
            history = client.get(f"/api/automations/{automation['id']}/runs", headers=headers)
            notifications = client.get("/api/notifications", headers=headers)
            notification_id = notifications.json()["data"][0]["id"]
            read = client.post(f"/api/notifications/{notification_id}/read", headers=headers)
            openapi = client.get("/openapi.json")

        assert unauthorized.status_code == 401
        assert created.status_code == 200
        assert automation["risk_level"] == "read_only"
        assert detail.status_code == 200
        assert updated.json()["data"]["cooldown_seconds"] == 300
        assert disabled.json()["data"]["enabled"] is False
        assert enabled.json()["data"]["enabled"] is True
        assert history.status_code == 200
        assert [item["status"] for item in history.json()["data"]] == ["completed"]
        assert history.json()["data"][0]["notification_id"] == notification_id
        assert notifications.status_code == 200
        assert notifications.json()["total"] == 1
        assert read.json()["data"]["status"] == "read"
        for path in (
            "/api/automations",
            "/api/automations/{automation_id}",
            "/api/automations/{automation_id}/enable",
            "/api/automations/{automation_id}/disable",
            "/api/automations/{automation_id}/runs",
            "/api/notifications",
            "/api/notifications/{notification_id}/read",
        ):
            assert path in openapi.json()["paths"]
    finally:
        manager.dispose()
