import asyncio
from collections.abc import Callable
from datetime import timedelta

import pytest

from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.robots.errors import (
    RobotInvalidParameterError,
    RobotNotFoundError,
)
from arvuno_core.robots.models import (
    RegisteredRobotTaskRequest,
    RobotCapabilityName,
    RobotExecutionResult,
    RobotStateSnapshot,
    RobotTaskStatus,
    utc_now,
)
from arvuno_core.robots.protocol import (
    RobotProtocolError,
    decode_firmware_command,
    decode_firmware_heartbeat,
    decode_firmware_result,
    encode_firmware_command,
    encode_firmware_heartbeat,
    encode_firmware_result,
)
from arvuno_core.robots.registry import RobotRegistry
from arvuno_core.robots.service import RobotApplicationService
from arvuno_core.robots.simulator import DesktopRobotFirmwareSimulatorAdapter


def adapter_request(robot_id: str = "sim.desktop.robot") -> RegisteredRobotTaskRequest:
    now = utc_now()
    return RegisteredRobotTaskRequest(
        id="sim-request-0001",
        robot_id=robot_id,
        capability=RobotCapabilityName.SPEAK,
        status=RobotTaskStatus.SUBMITTED,
        parameters={"text": "hello"},
        requested_by="test-user",
        origin_type="task_system",
        confirmed_by_user=True,
        requires_confirmation=True,
        timeout_seconds=5,
        created_at=now,
        updated_at=now,
    )


def protocol_service(tmp_path):
    manager = DatabaseManager(
        _settings(tmp_path),
    )
    manager.initialize_database()
    adapter = DesktopRobotFirmwareSimulatorAdapter(external_id="sim.desktop.robot")
    registry = RobotRegistry(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
    service = RobotApplicationService(
        registry,
        {adapter.adapter_id: adapter},
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
    )
    return manager, adapter, service


def assert_protocol_error(action: Callable[[], object], expected_code: str) -> None:
    with pytest.raises(RobotProtocolError) as error_info:
        action()
    assert error_info.value.code == expected_code


def _settings(tmp_path):
    from arvuno_core.config import Settings

    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        robot_profile="desktop_robot",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


def test_firmware_command_and_result_contract_preserves_identity() -> None:
    request = adapter_request()
    command = decode_firmware_command(
        encode_firmware_command(request, issued_at=utc_now()).model_dump(mode="json")
    )
    assert command.protocol_version == "1.0"
    assert command.message_type == "command"
    assert command.robot_id == request.robot_id
    assert command.task_request_id == request.id
    assert command.capability == "speak"
    assert command.payload["parameters"] == {"text": "hello"}

    result = RobotExecutionResult(
        success=True,
        request_id=request.id,
        result={"spoken": "hello"},
        state=RobotStateSnapshot(
            robot_id=request.robot_id,
            connection_state="connected",
            is_online=True,
            motion_safety_state="stopped",
            emergency_stop=True,
            manual_takeover=False,
            device_states={},
            location={},
            source="firmware_reported",
            observed_at=utc_now(),
        ),
    )
    decoded = decode_firmware_result(
        encode_firmware_result(result, issued_at=utc_now()).model_dump(mode="json")
    )
    assert decoded.success is True
    assert decoded.request_id == request.id
    assert decoded.state.robot_id == request.robot_id


def test_firmware_contract_rejects_version_and_payload_drift() -> None:
    command = encode_firmware_command(adapter_request(), issued_at=utc_now())
    assert_protocol_error(
        lambda: decode_firmware_command(
            {**command.model_dump(mode="json"), "protocol_version": "2.0"}
        ),
        "ROBOT_PROTOCOL_INVALID",
    )

    result = encode_firmware_result(
        RobotExecutionResult(
            success=False,
            request_id="another-request",
            state=RobotStateSnapshot(
                robot_id="sim.desktop.robot",
                connection_state="connected",
                is_online=True,
                motion_safety_state="stopped",
                emergency_stop=True,
                manual_takeover=False,
                device_states={},
                location={},
                source="firmware_reported",
                observed_at=utc_now(),
            ),
        ),
        issued_at=utc_now(),
    )
    payload = result.model_dump(mode="json")
    payload["task_request_id"] = "sim-request-0001"
    assert_protocol_error(
        lambda: decode_firmware_result(payload),
        "ROBOT_PROTOCOL_RESULT_INVALID",
    )


def test_firmware_heartbeat_contract_round_trip() -> None:
    now = utc_now()
    heartbeat = encode_firmware_heartbeat(
        robot_id="sim.desktop.robot",
        observed_at=now,
        emergency_stop=False,
    )
    decoded = decode_firmware_heartbeat(heartbeat.model_dump(mode="json"))
    assert decoded.robot_id == "sim.desktop.robot"
    assert decoded.observed_at - now < timedelta(seconds=1)
    assert decoded.emergency_stop is False


def test_simulator_adapter_executes_through_protocol(tmp_path) -> None:
    manager, adapter, service = protocol_service(tmp_path)
    try:
        asyncio.run(service.sync_robot(adapter, adapter.external_id))
        robot = asyncio.run(service.list_robots())[0]
        assert robot.profile == "desktop_robot"
        assert adapter.profile == "desktop_robot"
        capabilities = asyncio.run(adapter.get_capabilities(adapter.external_id))
        assert {item.capability for item in capabilities} == {
            RobotCapabilityName.REPORT_STATUS,
            RobotCapabilityName.LOOK_AT,
            RobotCapabilityName.OBSERVE_SCENE,
            RobotCapabilityName.REQUEST_SAFE_STOP,
            RobotCapabilityName.ENTER_IDLE_POSE,
            RobotCapabilityName.SPEAK,
            RobotCapabilityName.LISTEN,
        }
        assert all(item.verification_status == "concept" for item in capabilities)
        assert all(not item.runtime_enabled for item in capabilities)

        adapter.set_capability(
            RobotCapabilityName.SPEAK,
            runtime_enabled=True,
            verification_status="bench_verified",
        )
        adapter.set_emergency_stop(active=False)
        request = adapter_request(adapter.external_id)
        result = asyncio.run(adapter.execute_task(request))
        assert result.success is True
        assert result.result["spoken"] == "hello"
        assert result.result["protocol_version"] == "1.0"
        assert result.result["simulator_only"] is True
        assert result.state.source == "adapter_derived"
    finally:
        manager.dispose()


def test_simulator_adapter_rejects_low_level_and_foreign_robot(tmp_path) -> None:
    manager, adapter, _ = protocol_service(tmp_path)
    try:
        request = adapter_request(adapter.external_id)
        request.parameters["motor"] = 1
        with pytest.raises(RobotInvalidParameterError):
            asyncio.run(adapter.execute_task(request))
        with pytest.raises(RobotNotFoundError):
            asyncio.run(adapter.get_robot("other.desktop.robot"))
    finally:
        manager.dispose()
