import asyncio
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.events.bus import EventBus
from arvuno_core.events.models import ArvunoEvent
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import RobotTaskRequestRecord
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.robots.mock import MockRobotAdapter
from arvuno_core.robots.models import (
    RegisteredRobot,
    RegisteredRobotTaskRequest,
    RobotCapabilityName,
    RobotConnectionState,
    RobotExecutionResult,
    RobotHeartbeatReport,
    RobotMotionSafetyState,
    RobotRuntimeState,
    RobotTaskRequestCreate,
    RobotTaskStatus,
)
from arvuno_core.robots.registry import RobotRegistry
from arvuno_core.robots.service import RobotApplicationService

HEADERS = {"Authorization": "Bearer test-api-token"}


@dataclass
class MutableClock:
    now: datetime = field(default_factory=lambda: datetime(2026, 1, 1, tzinfo=UTC))

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.now


class RecordingEventBus(EventBus):
    def __init__(self, unit_of_work_factory: Any) -> None:
        super().__init__(unit_of_work_factory)
        self.published: list[ArvunoEvent] = []

    async def publish(self, event: ArvunoEvent) -> None:
        await super().publish(event)
        self.published.append(event)


class FailingEventPublisher:
    def __init__(self, inner: EventBus) -> None:
        self._inner = inner

    async def publish(self, event: ArvunoEvent) -> None:
        await self._inner.publish(event)
        raise RuntimeError("event subscriber transport failed")


class CancelingRobotAdapter(MockRobotAdapter):
    def __init__(self, clock: MutableClock) -> None:
        super().__init__(clock=clock)
        self.mode = "success"

    async def cancel_task(self, request: RegisteredRobotTaskRequest) -> Any:
        if self.mode == "timeout":
            await asyncio.sleep(2)
        if self.mode == "connection":
            raise self.connection_error()
        result = await super().cancel_task(request)
        if self.mode == "rejected":
            result.success = False
            result.message = "The mock robot rejected cancellation."
        return result

    def connection_error(self) -> Exception:
        from arvuno_core.robots.errors import RobotConnectionError

        return RobotConnectionError()


class RejectCancelAdapter(MockRobotAdapter):
    async def cancel_task(self, request: RegisteredRobotTaskRequest) -> RobotExecutionResult:
        return RobotExecutionResult(
            success=False,
            request_id=request.id,
            message="The mock robot rejected cancellation.",
            result={"cancelled": False},
        )


class UnverifiableSafeStopAdapter(MockRobotAdapter):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.safe_stop_requested = False

    async def get_state(self, external_id: str) -> Any:
        state = await super().get_state(external_id)
        if self.safe_stop_requested:
            return state.model_copy(
                update={
                    "motion_safety_state": RobotMotionSafetyState.NORMAL,
                    "emergency_stop": False,
                }
            )
        return state

    async def execute_task(self, request: RegisteredRobotTaskRequest) -> Any:
        if request.capability is RobotCapabilityName.REQUEST_SAFE_STOP:
            self.safe_stop_requested = True
            state = await self.get_state(self.external_id)
            return RobotExecutionResult(
                success=True,
                request_id=request.id,
                message="Unverified safe-stop acknowledgement.",
                result={"requested": True, "verified": True},
                state=state,
            )
        return await super().execute_task(request)


@dataclass
class FailsafeEnvironment:
    manager: DatabaseManager
    adapter: MockRobotAdapter
    service: RobotApplicationService
    bus: RecordingEventBus
    clock: MutableClock
    robot: RegisteredRobot


@contextmanager
def failsafe_environment(
    *,
    heartbeat_timeout_seconds: float = 30,
) -> Iterator[FailsafeEnvironment]:
    with tempfile.TemporaryDirectory(prefix="robot-failsafe-") as directory:
        root = Path(directory)
        clock = MutableClock()
        settings = Settings(
            _env_file=None,
            environment="test",
            api_token="test-api-token",
            data_dir=root / "data",
            log_dir=root / "logs",
            backup_dir=root / "backups",
            database_path=root / "robot.sqlite3",
        )
        manager = DatabaseManager(settings)
        manager.initialize_database()
        adapter = MockRobotAdapter(clock=clock)

        def unit_of_work_factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(manager.session_factory)

        bus = RecordingEventBus(unit_of_work_factory)
        service = RobotApplicationService(
            RobotRegistry(unit_of_work_factory),
            {adapter.adapter_id: adapter},
            unit_of_work_factory=unit_of_work_factory,
            event_publisher=bus,
            clock=clock,
            heartbeat_timeout_seconds=heartbeat_timeout_seconds,
        )
        try:
            asyncio.run(service.sync_robot(adapter, adapter.external_id))
            robot = asyncio.run(service.list_robots())[0]
            yield FailsafeEnvironment(manager, adapter, service, bus, clock, robot)
        finally:
            manager.dispose()


def make_ready(environment: FailsafeEnvironment) -> None:
    environment.adapter.set_emergency_stop(active=False)
    asyncio.run(environment.service.enable_robot(environment.robot.id, enabled=True))
    asyncio.run(environment.service.state(environment.robot.id))


def mark_task_running(environment: FailsafeEnvironment) -> RegisteredRobotTaskRequest:
    governance_request(environment, RobotCapabilityName.REPORT_STATUS)
    request = asyncio.run(
        environment.service.create_task_request(
            environment.robot.id,
            RobotTaskRequestCreate(
                capability=RobotCapabilityName.REPORT_STATUS,
                parameters={},
                requested_by="test-user",
                confirmed=True,
            ),
        )
    )
    with environment.manager.session_factory() as session:
        record = session.get(RobotTaskRequestRecord, request.id)
        assert record is not None
        record.status = RobotTaskStatus.RUNNING.value
        session.commit()
    return asyncio.run(environment.service.task_request(environment.robot.id, request.id))


def governance_request(
    environment: FailsafeEnvironment,
    capability: RobotCapabilityName,
) -> None:
    environment.adapter.set_capability(
        capability,
        runtime_enabled=True,
        verification_status="bench_verified",
        requires_confirmation=False,
    )
    asyncio.run(environment.service.enable_robot(environment.robot.id, enabled=True))
    asyncio.run(
        environment.service.sync_robot(environment.adapter, environment.adapter.external_id)
    )
    asyncio.run(
        environment.service.set_capability_governance(
            environment.robot.id,
            capability,
            enabled=True,
            approved=True,
            consent_granted=True,
            approved_by="test-admin",
        )
    )


def execute_request(
    environment: FailsafeEnvironment,
    capability: RobotCapabilityName,
) -> RegisteredRobotTaskRequest:
    request = RobotTaskRequestCreate(
        capability=capability,
        parameters={},
        requested_by="task_system",
        origin_type="task_system",
        task_id=str(uuid4()),
        idempotency_key=f"failsafe-{uuid4()}",
        timeout_seconds=0.05,
    )
    return asyncio.run(
        environment.service.execute_preauthorized_task_request(
            environment.robot.id,
            request,
            task_id=str(uuid4()),
            task_step_id=str(uuid4()),
            tool_execution_id=str(uuid4()),
        )
    )


def test_heartbeat_refreshes_state_and_timeout_becomes_stale() -> None:
    with failsafe_environment() as environment:
        make_ready(environment)
        environment.clock.advance(10)
        accepted = asyncio.run(
            environment.service.heartbeat(
                environment.robot.id,
                RobotHeartbeatReport(observed_at=environment.clock.now),
            )
        )
        assert accepted.accepted is True
        assert accepted.runtime_state.state is RobotRuntimeState.IDLE
        assert accepted.runtime_state.is_fresh is True

        environment.clock.advance(31)
        stale = asyncio.run(environment.service.runtime_status(environment.robot.id))
        assert stale.state is RobotRuntimeState.STALE
        assert stale.is_fresh is False
        assert stale.error_code == "ROBOT_STATE_STALE"


def test_late_heartbeat_is_rejected_and_future_is_rejected() -> None:
    with failsafe_environment() as environment:
        make_ready(environment)
        environment.clock.advance(10)
        late = asyncio.run(
            environment.service.heartbeat(
                environment.robot.id,
                RobotHeartbeatReport(observed_at=environment.clock.now - timedelta(seconds=10)),
            )
        )
        assert late.accepted is False
        assert late.reason == "late_heartbeat"

        future = asyncio.run(
            environment.service.heartbeat(
                environment.robot.id,
                RobotHeartbeatReport(
                    observed_at=environment.clock.now + timedelta(seconds=30),
                    motion_safety_state=RobotMotionSafetyState.NORMAL,
                ),
            )
        )
        assert future.accepted is False
        assert future.reason == "future_heartbeat"


def test_adapter_failure_is_offline_and_reconnect_resynchronizes() -> None:
    with failsafe_environment() as environment:
        make_ready(environment)
        environment.adapter.set_offline()
        failed = asyncio.run(environment.service.resynchronize(environment.robot.id))
        assert failed.state is RobotRuntimeState.OFFLINE
        assert failed.connection_state is RobotConnectionState.DISCONNECTED
        assert failed.is_fresh is False

        preserved = asyncio.run(environment.service.get_robot(environment.robot.id))
        assert preserved.last_seen_at is not None

        environment.adapter.set_offline(offline=False)
        environment.clock.advance(1)
        restored = asyncio.run(environment.service.resynchronize(environment.robot.id))
        assert restored.state is RobotRuntimeState.IDLE
        assert restored.connection_state is RobotConnectionState.CONNECTED
        assert restored.is_fresh is True


def test_runtime_distinguishes_busy_emergency_and_active_task_state() -> None:
    with failsafe_environment() as environment:
        make_ready(environment)
        running = mark_task_running(environment)
        busy = asyncio.run(environment.service.runtime_status(environment.robot.id))
        assert busy.state is RobotRuntimeState.BUSY
        assert busy.active_task_count == 1

        cancelled = asyncio.run(
            environment.service.cancel_task_request(
                environment.robot.id,
                running.id,
                cancelled_by="test-user",
            )
        )
        assert cancelled.status is RobotTaskStatus.CANCELLED
        idle = asyncio.run(environment.service.runtime_status(environment.robot.id))
        assert idle.state is RobotRuntimeState.IDLE
        assert idle.active_task_count == 0

        environment.adapter.set_emergency_stop()
        emergency = asyncio.run(environment.service.state(environment.robot.id))
        assert emergency.emergency_stop is True
        runtime = asyncio.run(environment.service.runtime_status(environment.robot.id))
        assert runtime.state is RobotRuntimeState.EMERGENCY_STOPPED


def test_cancel_timeout_and_connection_are_execution_unknown() -> None:
    for mode in {"timeout", "connection"}:
        with tempfile.TemporaryDirectory(prefix=f"robot-cancel-{mode}-") as directory:
            clock = MutableClock()
            settings = database_settings(Path(directory) / "robot.sqlite3")
            manager = DatabaseManager(settings)
            manager.initialize_database()
            adapter = CancelingRobotAdapter(clock)
            adapter.mode = mode

            def unit_of_work_factory(manager: DatabaseManager = manager) -> SqlAlchemyUnitOfWork:
                return SqlAlchemyUnitOfWork(manager.session_factory)

            service = RobotApplicationService(
                RobotRegistry(unit_of_work_factory),
                {adapter.adapter_id: adapter},
                unit_of_work_factory=unit_of_work_factory,
                clock=clock,
            )
            try:
                asyncio.run(service.sync_robot(adapter, adapter.external_id))
                robot = asyncio.run(service.list_robots())[0]
                adapter.set_capability(
                    RobotCapabilityName.REPORT_STATUS,
                    runtime_enabled=True,
                    verification_status="bench_verified",
                    requires_confirmation=False,
                )
                asyncio.run(service.enable_robot(robot.id, enabled=True))
                asyncio.run(service.sync_robot(adapter, adapter.external_id))
                asyncio.run(
                    service.set_capability_governance(
                        robot.id,
                        RobotCapabilityName.REPORT_STATUS,
                        enabled=True,
                        approved=True,
                        consent_granted=True,
                        approved_by="test-admin",
                    )
                )
                adapter.set_emergency_stop(active=False)
                asyncio.run(service.state(robot.id))
                request = asyncio.run(
                    service.create_task_request(
                        robot.id,
                        RobotTaskRequestCreate(
                            capability=RobotCapabilityName.REPORT_STATUS,
                            parameters={},
                            requested_by="test-user",
                            confirmed=True,
                            timeout_seconds=0.05,
                        ),
                    ),
                )
                with manager.session_factory() as session:
                    record = session.get(RobotTaskRequestRecord, request.id)
                    assert record is not None
                    record.status = RobotTaskStatus.RUNNING.value
                    session.commit()

                result = asyncio.run(
                    service.cancel_task_request(robot.id, request.id, cancelled_by="test-user")
                )
                assert result.status is RobotTaskStatus.EXECUTION_UNKNOWN
                events = asyncio.run(service.events(robot.id, task_request_id=result.id))
                assert "task_execution_unknown" in {event.event_type for event in events}
            finally:
                manager.dispose()


def test_cancel_rejection_is_not_success() -> None:
    with failsafe_environment() as environment:
        make_ready(environment)
        adapter = environment.adapter
        assert isinstance(adapter, MockRobotAdapter)
        running = mark_task_running(environment)
        environment.service._adapters[adapter.adapter_id] = RejectCancelAdapter(
            clock=environment.clock
        )  # type: ignore[assignment]
        result = asyncio.run(
            environment.service.cancel_task_request(
                environment.robot.id,
                running.id,
                cancelled_by="test-user",
            )
        )
        assert result.status is RobotTaskStatus.CANCEL_FAILED


def test_safe_stop_requires_verified_stopped_state() -> None:
    with failsafe_environment() as environment:
        make_ready(environment)
        governance_request(environment, RobotCapabilityName.REQUEST_SAFE_STOP)
        completed = execute_request(environment, RobotCapabilityName.REQUEST_SAFE_STOP)
        assert completed.status is RobotTaskStatus.SUCCEEDED
        assert completed.result["verified"] is True
        robot = asyncio.run(environment.service.get_robot(environment.robot.id))
        assert robot.emergency_stop is True
        assert robot.motion_safety_state is RobotMotionSafetyState.STOPPED


def test_unverified_safe_stop_is_failed_not_succeeded() -> None:
    with failsafe_environment() as environment:
        make_ready(environment)
        adapter = UnverifiableSafeStopAdapter(clock=environment.clock)
        environment.service._adapters[adapter.adapter_id] = adapter  # type: ignore[assignment]
        governance_request(environment, RobotCapabilityName.REQUEST_SAFE_STOP)
        completed = execute_request(environment, RobotCapabilityName.REQUEST_SAFE_STOP)
        assert completed.status is RobotTaskStatus.FAILED
        assert completed.error is not None
        assert completed.error["code"] == "ROBOT_STATE_VERIFICATION_FAILED"


def test_robot_state_and_safety_events_persist_and_bridge_to_event_bus() -> None:
    with failsafe_environment() as environment:
        environment.adapter.set_emergency_stop(active=False)
        updated = asyncio.run(environment.service.state(environment.robot.id))
        assert updated.emergency_stop is False

        robot_events = asyncio.run(environment.service.events(environment.robot.id))
        assert "state_changed" in {event.event_type for event in robot_events}
        assert "safety_changed" in {event.event_type for event in robot_events}
        assert {event.event_type for event in environment.bus.published} >= {
            "robot_state_changed",
            "robot_safety_changed",
        }

        def unit_of_work_factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(environment.manager.session_factory)

        with unit_of_work_factory() as unit_of_work:
            assert unit_of_work.events is not None
            persisted, total = unit_of_work.events.query(
                event_type="robot_safety_changed",
                subject_id=environment.robot.id,
                page_size=10,
            )
        assert total >= 1
        assert persisted


def test_event_bus_failure_does_not_hide_persisted_robot_event() -> None:
    with failsafe_environment() as environment:
        environment.adapter.set_emergency_stop(active=False)
        inner = RecordingEventBus(lambda: SqlAlchemyUnitOfWork(environment.manager.session_factory))
        environment.service._event_publisher = FailingEventPublisher(inner)
        asyncio.run(environment.service.state(environment.robot.id))

        robot_events = asyncio.run(environment.service.events(environment.robot.id))
        assert "safety_changed" in {event.event_type for event in robot_events}
        assert inner.published


def test_runtime_state_and_reconnect_api_only_manage_projection(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        robot_heartbeat_timeout_seconds=30,
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )
    manager = DatabaseManager(settings)
    manager.initialize_database()
    app = create_app(
        settings,
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
        initialize_tool_runtime=True,
    )
    try:
        with TestClient(app) as client:
            service = app.state.robot_service
            adapter = app.state.mock_robot_adapter
            asyncio.run(service.sync_robot(adapter, adapter.external_id))
            robot_id = asyncio.run(service.list_robots())[0].id

            runtime = client.get(f"/api/robots/{robot_id}/runtime-state", headers=HEADERS)
            assert runtime.status_code == 200
            assert runtime.json()["data"]["state"] == "emergency_stopped"

            heartbeat = client.post(
                f"/api/robots/{robot_id}/heartbeat",
                headers=HEADERS,
                json={
                    "report": {
                        "observed_at": datetime.now(UTC).isoformat(),
                        "motion_safety_state": "normal",
                        "emergency_stop": False,
                    }
                },
            )
            assert heartbeat.status_code == 200
            assert heartbeat.json()["data"]["runtime_state"]["state"] == "idle"

            adapter.set_offline()
            reconnected = client.post(f"/api/robots/{robot_id}/reconnect", headers=HEADERS)
            assert reconnected.status_code == 200
            assert reconnected.json()["data"]["state"] == "offline"
    finally:
        manager.dispose()


def database_settings(path: Path) -> Settings:
    settings = Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=path.parent / "data",
        log_dir=path.parent / "logs",
        backup_dir=path.parent / "backups",
        database_path=path,
    )
    return settings
