from typing import Any

from arvuno_core.robots.mock import MockRobotAdapter
from arvuno_core.robots.models import (
    RegisteredRobotTaskRequest,
    RobotExecutionResult,
    utc_now,
)
from arvuno_core.robots.protocol import (
    RobotProtocolError,
    decode_firmware_command,
    decode_firmware_result,
    encode_firmware_command,
    encode_firmware_result,
)


class DesktopRobotFirmwareSimulatorAdapter(MockRobotAdapter):
    """Runs the same high-level state machine through the firmware contract.

    This adapter remains local and deterministic.  It does not make the desktop
    robot hardware-verified, and the default verification status stays `concept`.
    """

    adapter_id = "desktop_firmware_simulator"
    version = "1.0.0"

    async def execute_task(
        self,
        request: RegisteredRobotTaskRequest,
    ) -> RobotExecutionResult:
        issued_at = utc_now()
        firmware_request = request.model_copy(update={"robot_id": self.external_id})
        encoded = encode_firmware_command(firmware_request, issued_at=issued_at)
        decoded = decode_firmware_command(encoded.model_dump(mode="json"))
        if decoded.robot_id != self.external_id or decoded.task_request_id != request.id:
            raise RobotProtocolError(
                "ROBOT_PROTOCOL_IDENTITY_MISMATCH",
                "The firmware transport changed the command identity.",
            )

        adapter_request = request.model_copy(update={"robot_id": decoded.robot_id})
        adapter_result = await super().execute_task(adapter_request)
        result_envelope = encode_firmware_result(
            adapter_result,
            issued_at=utc_now(),
        )
        result = decode_firmware_result(result_envelope.model_dump(mode="json"))
        if result.request_id != request.id or result.state.robot_id != decoded.robot_id:
            raise RobotProtocolError(
                "ROBOT_PROTOCOL_IDENTITY_MISMATCH",
                "The firmware transport changed the result identity "
                f"(request_id={result.request_id!r}/{request.id!r}, "
                f"robot_id={result.state.robot_id!r}/{decoded.robot_id!r}).",
            )
        normalized_result = result.model_copy(
            update={
                "result": {
                    **result.result,
                    "mock_only": True,
                    "protocol_version": "1.0",
                    "simulator_only": True,
                }
            }
        )
        # The simulator speaks firmware identity externally; the governed
        # application service stores projections under Arvuno's internal ID.
        return normalized_result.model_copy(
            update={
                "state": normalized_result.state.model_copy(update={"robot_id": request.robot_id})
            }
        )

    def _state_snapshot(self) -> Any:
        snapshot = super()._state_snapshot()
        return snapshot.model_copy(update={"source": "adapter_derived"})


__all__ = ["DesktopRobotFirmwareSimulatorAdapter"]
