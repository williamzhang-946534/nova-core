from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class RobotConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"


class RobotRuntimeState(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    STALE = "stale"
    BUSY = "busy"
    IDLE = "idle"
    ERROR = "error"
    EMERGENCY_STOPPED = "emergency_stopped"
    UNKNOWN = "unknown"


class RobotMotionSafetyState(StrEnum):
    NORMAL = "normal"
    STOPPED = "stopped"
    MANUAL_TAKEOVER = "manual_takeover"
    LIMIT_REACHED = "limit_reached"
    STALLED = "stalled"
    OVER_CURRENT = "over_current"
    TILT_DETECTED = "tilt_detected"
    UNKNOWN = "unknown"


class RobotCapabilityName(StrEnum):
    NAVIGATE_TO = "navigate_to"
    OBSERVE = "observe"
    INSPECT = "inspect"
    SPEAK = "speak"
    LISTEN = "listen"
    RETURN_TO_DOCK = "return_to_dock"
    CHARGE = "charge"
    REPORT_STATUS = "report_status"
    LOOK_AT = "look_at"
    OBSERVE_SCENE = "observe_scene"
    REQUEST_SAFE_STOP = "request_safe_stop"
    ENTER_IDLE_POSE = "enter_idle_pose"


CapabilityVerification = Literal[
    "concept",
    "specified",
    "bench_verified",
    "integration_verified",
    "safety_approved",
]

RobotRiskLevel = Literal["read_only", "low_risk", "medium_risk", "high_risk"]
RobotDataCategory = Literal["camera", "microphone", "speaker", "motion"]


class RobotTaskStatus(StrEnum):
    CREATED = "created"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    REJECTED = "rejected"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    RUNNING = "running"
    WAITING_RESULT = "waiting_result"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    CANCEL_REQUESTED = "cancel_requested"
    STOPPING = "stopping"
    CANCEL_FAILED = "cancel_failed"
    EXECUTION_UNKNOWN = "execution_state_unknown"
    SAFE_STOPPED = "safe_stopped"
    UNAVAILABLE = "unavailable"


ACTIVE_ROBOT_TASK_STATUSES = {
    RobotTaskStatus.CREATED,
    RobotTaskStatus.AWAITING_CONFIRMATION,
    RobotTaskStatus.SUBMITTED,
    RobotTaskStatus.ACCEPTED,
    RobotTaskStatus.RUNNING,
    RobotTaskStatus.WAITING_RESULT,
    RobotTaskStatus.CANCEL_REQUESTED,
    RobotTaskStatus.STOPPING,
    RobotTaskStatus.CANCEL_FAILED,
    RobotTaskStatus.EXECUTION_UNKNOWN,
}


class RobotLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = None
    reference_frame: Literal["desktop", "room", "dock", "unknown"] = "unknown"
    x: float | None = None
    y: float | None = None
    z: float | None = None
    yaw: float | None = Field(default=None, ge=-360, le=360)
    pitch: float | None = Field(default=None, ge=-180, le=180)
    roll: float | None = Field(default=None, ge=-180, le=180)
    position_confidence: float | None = Field(default=None, ge=0, le=1)
    localization_state: Literal["known", "degraded", "lost", "unknown"] = "unknown"


class RobotDeviceStates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera: Literal["disabled", "idle", "capturing", "unavailable", "unauthorized"] = "disabled"
    microphone: Literal[
        "disabled",
        "idle",
        "recording",
        "unavailable",
        "unauthorized",
    ] = "disabled"
    speaker: Literal["idle", "speaking", "muted", "unavailable"] = "idle"


class RobotDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_id: str = Field(min_length=1, max_length=100)
    external_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    vendor: str = Field(default="custom", max_length=100)
    model: str = Field(default="custom_desktop_robot", max_length=100)
    profile: str | None = Field(default=None, max_length=50)
    hardware_version: str | None = Field(default=None, max_length=100)
    firmware_version: str | None = Field(default=None, max_length=100)
    edge_runtime_version: str | None = Field(default=None, max_length=100)
    is_enabled: bool = False
    space_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RegisteredRobot(RobotDefinition):
    id: str = Field(min_length=1)
    connection_state: RobotConnectionState = RobotConnectionState.DISCONNECTED
    is_online: bool = False
    motion_safety_state: RobotMotionSafetyState = RobotMotionSafetyState.UNKNOWN
    emergency_stop: bool = True
    manual_takeover: bool = False
    battery_percent: float | None = Field(default=None, ge=0, le=100)
    low_battery_percent: float = 15
    device_states: RobotDeviceStates = Field(default_factory=RobotDeviceStates)
    location: RobotLocation = Field(default_factory=RobotLocation)
    last_seen_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RobotCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    robot_id: str | None = None
    capability: RobotCapabilityName
    schema_version: str = "1.0"
    verification_status: CapabilityVerification = "concept"
    discovered: bool = True
    supported: bool = False
    enabled: bool = False
    approved: bool = False
    consent_granted: bool = False
    executable: bool = False
    runtime_enabled: bool = False
    risk_level: RobotRiskLevel = "medium_risk"
    requires_confirmation: bool = True
    requires_consents: list[Literal["camera", "microphone", "speaker", "motion"]] = Field(
        default_factory=list
    )
    min_battery_percent: float = Field(default=0, ge=0, le=100)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    safety_envelope: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)


class RobotStateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    robot_id: str = Field(min_length=1)
    connection_state: RobotConnectionState
    is_online: bool
    motion_safety_state: RobotMotionSafetyState
    emergency_stop: bool
    manual_takeover: bool
    battery_percent: float | None = None
    device_states: RobotDeviceStates
    location: RobotLocation
    source: Literal["firmware_reported", "edge_observed", "adapter_derived", "mock"]
    observed_at: datetime
    received_at: datetime = Field(default_factory=utc_now)
    schema_version: str = "1.0"


class RobotEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    robot_id: str = Field(min_length=1)
    task_request_id: str | None = None
    event_type: Literal[
        "connection_changed",
        "state_changed",
        "safety_changed",
        "task_accepted",
        "task_running",
        "task_succeeded",
        "task_failed",
        "task_cancelled",
        "task_cancel_requested",
        "task_stopping",
        "task_cancel_failed",
        "task_execution_unknown",
        "task_safe_stopped",
        "task_unavailable",
    ]
    severity: Literal["info", "warning", "critical"] = "info"
    source: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime
    received_at: datetime = Field(default_factory=utc_now)
    processed_at: datetime = Field(default_factory=utc_now)
    late_arrival: bool = False
    correlation_id: str | None = Field(default=None, max_length=100)


class RobotTaskRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: RobotCapabilityName
    parameters: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = Field(min_length=1, max_length=255)
    origin_type: Literal["user", "task_system", "active_perception", "system"] = "user"
    task_id: str | None = Field(default=None, max_length=36)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)
    confirmed: bool = False
    timeout_seconds: float = Field(default=10, gt=0, le=120)
    correlation_id: str | None = Field(default=None, max_length=100)


class RegisteredRobotTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    capability: RobotCapabilityName
    status: RobotTaskStatus
    parameters: dict[str, Any]
    requested_by: str
    origin_type: str
    task_id: str | None = None
    task_step_id: str | None = None
    tool_execution_id: str | None = None
    idempotency_key: str | None = None
    confirmed_by_user: bool = False
    requires_confirmation: bool = True
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    timeout_seconds: float
    correlation_id: str | None = None
    created_at: datetime
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class RobotRuntimeStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    robot_id: str = Field(min_length=1)
    state: RobotRuntimeState
    connection_state: RobotConnectionState
    motion_safety_state: RobotMotionSafetyState
    is_fresh: bool
    last_seen_at: datetime | None = None
    last_evaluated_at: datetime
    heartbeat_timeout_seconds: float = Field(gt=0)
    active_task_count: int = Field(ge=0)
    error_code: str | None = Field(default=None, max_length=100)


class RobotHeartbeatReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    motion_safety_state: RobotMotionSafetyState | None = None
    emergency_stop: bool | None = None
    manual_takeover: bool | None = None
    battery_percent: float | None = Field(default=None, ge=0, le=100)
    device_states: RobotDeviceStates | None = None
    location: RobotLocation | None = None
    source: Literal["firmware_reported", "edge_observed", "mock"] = "firmware_reported"


class RobotHeartbeatResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    reason: str = Field(min_length=1, max_length=100)
    robot: RegisteredRobot
    runtime_state: RobotRuntimeStatus


class RobotExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    request_id: str = Field(min_length=1)
    message: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    state: RobotStateSnapshot
    events: list[RobotEvent] = Field(default_factory=list)


class RobotConsent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    robot_id: str = Field(min_length=1)
    capability: RobotCapabilityName
    data_category: RobotDataCategory
    space_id: str | None = None
    status: Literal["granted", "revoked", "expired"] = "granted"
    granted_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    grant_source: str
    granted_by: str


class RobotConsentGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: RobotCapabilityName
    data_category: RobotDataCategory
    space_id: str | None = Field(default=None, max_length=36)
    expires_at: datetime | None = None
    grant_source: str = Field(default="user", max_length=50)
    granted_by: str = Field(min_length=1, max_length=255)


class RobotConsentRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent_id: str = Field(min_length=1, max_length=36)
    revoked_by: str = Field(min_length=1, max_length=255)


class RobotRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_id: str = Field(min_length=1, max_length=100)
    external_id: str = Field(min_length=1, max_length=255)


@dataclass(frozen=True)
class RobotPolicySnapshot:
    robot: RegisteredRobot
    capabilities: tuple[RobotCapability, ...]
    consents: tuple[RobotConsent, ...]


def robot_task_is_final(status: RobotTaskStatus) -> bool:
    return status not in ACTIVE_ROBOT_TASK_STATUSES
