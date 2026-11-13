"""Versioned contract between Arvuno and a future desktop robot firmware.

The protocol intentionally contains high-level capability commands only.  It is
used by the local firmware simulator; real firmware must implement the same
schema and go through independent hardware safety review before integration.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from arvuno_core.robots.models import RegisteredRobotTaskRequest, RobotExecutionResult


class RobotProtocolError(Exception):
    """The firmware message does not match the approved protocol contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class FirmwareEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["1.0"]
    message_id: str = Field(min_length=8, max_length=64)
    message_type: Literal["command", "result", "heartbeat"]
    robot_id: str = Field(min_length=1, max_length=255)
    task_request_id: str | None = Field(default=None, min_length=1, max_length=64)
    capability: str | None = Field(default=None, min_length=1, max_length=50)
    payload: dict[str, Any] = Field(default_factory=dict)
    issued_at: datetime


def encode_firmware_command(
    request: RegisteredRobotTaskRequest,
    *,
    issued_at: datetime,
) -> FirmwareEnvelope:
    return FirmwareEnvelope(
        protocol_version="1.0",
        message_id=f"cmd-{uuid4()}",
        message_type="command",
        robot_id=request.robot_id,
        task_request_id=request.id,
        capability=request.capability.value,
        payload={"parameters": request.parameters, "timeout_seconds": request.timeout_seconds},
        issued_at=issued_at,
    )


def decode_firmware_command(value: object) -> FirmwareEnvelope:
    try:
        envelope = FirmwareEnvelope.model_validate(value)
    except ValidationError as exc:
        raise RobotProtocolError(
            "ROBOT_PROTOCOL_INVALID", "The firmware command is invalid."
        ) from exc
    if envelope.message_type != "command":
        raise RobotProtocolError("ROBOT_PROTOCOL_WRONG_TYPE", "Expected a firmware command.")
    if envelope.task_request_id is None or envelope.capability is None:
        raise RobotProtocolError(
            "ROBOT_PROTOCOL_INCOMPLETE",
            "Firmware commands require task request and capability identifiers.",
        )
    return envelope


def encode_firmware_result(
    result: RobotExecutionResult, *, issued_at: datetime
) -> FirmwareEnvelope:
    return FirmwareEnvelope(
        protocol_version="1.0",
        message_id=f"result-{uuid4()}",
        message_type="result",
        robot_id=result.state.robot_id,
        task_request_id=result.request_id,
        capability=None,
        payload=result.model_dump(mode="json"),
        issued_at=issued_at,
    )


def decode_firmware_result(value: object) -> RobotExecutionResult:
    try:
        envelope = FirmwareEnvelope.model_validate(value)
    except ValidationError as exc:
        raise RobotProtocolError(
            "ROBOT_PROTOCOL_INVALID", "The firmware result is invalid."
        ) from exc
    if envelope.message_type != "result":
        raise RobotProtocolError("ROBOT_PROTOCOL_WRONG_TYPE", "Expected a firmware result.")
    result_request_id = envelope.payload.get("request_id")
    result_robot_id = envelope.payload.get("state", {}).get("robot_id")
    if envelope.task_request_id != result_request_id or envelope.robot_id != result_robot_id:
        raise RobotProtocolError(
            "ROBOT_PROTOCOL_RESULT_INVALID",
            "The firmware result envelope and payload identities do not match.",
        )
    try:
        return RobotExecutionResult.model_validate(envelope.payload)
    except ValidationError as exc:
        raise RobotProtocolError(
            "ROBOT_PROTOCOL_RESULT_INVALID",
            "The firmware result payload is invalid.",
        ) from exc


class FirmwareHeartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["1.0"]
    message_id: str = Field(min_length=8, max_length=64)
    robot_id: str = Field(min_length=1, max_length=255)
    observed_at: datetime
    emergency_stop: bool
    source: Literal["firmware_reported"] = "firmware_reported"


def encode_firmware_heartbeat(
    *,
    robot_id: str,
    observed_at: datetime,
    emergency_stop: bool,
) -> FirmwareHeartbeat:
    return FirmwareHeartbeat(
        protocol_version="1.0",
        message_id=f"hb-{uuid4()}",
        robot_id=robot_id,
        observed_at=observed_at,
        emergency_stop=emergency_stop,
    )


def decode_firmware_heartbeat(value: object) -> FirmwareHeartbeat:
    try:
        return FirmwareHeartbeat.model_validate(value)
    except ValidationError as exc:
        raise RobotProtocolError(
            "ROBOT_PROTOCOL_HEARTBEAT_INVALID",
            "The firmware heartbeat is invalid.",
        ) from exc


__all__ = [
    "FirmwareEnvelope",
    "FirmwareHeartbeat",
    "RobotProtocolError",
    "decode_firmware_command",
    "decode_firmware_heartbeat",
    "decode_firmware_result",
    "encode_firmware_command",
    "encode_firmware_heartbeat",
    "encode_firmware_result",
]
