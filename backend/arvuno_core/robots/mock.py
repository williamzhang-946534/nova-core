import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from arvuno_core.robots.errors import (
    RobotCapabilityDisabledError,
    RobotCapabilityUnsupportedError,
    RobotConnectionError,
    RobotInvalidParameterError,
    RobotLocalizationLostError,
    RobotLowBatteryError,
    RobotNavigationError,
    RobotNotFoundError,
    RobotSafetyStateError,
)
from arvuno_core.robots.interface import RobotEventSubscriber
from arvuno_core.robots.models import (
    CapabilityVerification,
    RegisteredRobot,
    RegisteredRobotTaskRequest,
    RobotCapability,
    RobotCapabilityName,
    RobotConnectionState,
    RobotDeviceStates,
    RobotEvent,
    RobotExecutionResult,
    RobotLocation,
    RobotMotionSafetyState,
    RobotStateSnapshot,
    utc_now,
)


class MockRobotAdapter:
    """Deterministic high-level adapter for local tests and development."""

    adapter_id = "mock_robot"
    version = "1.0.0"

    @property
    def external_id(self) -> str:
        return self._external_id

    def __init__(
        self,
        *,
        external_id: str = "mock.desktop.robot",
        name: str = "Mock Desktop Robot",
        clock: Callable[[], Any] = utc_now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._external_id = external_id
        self._name = name
        self._clock = clock
        self._sleep = sleep
        self._offline = False
        self._timeout = False
        self._emergency_stop = True
        self._manual_takeover = False
        self._battery_percent = 100.0
        self._navigation_failure = False
        self._localization_lost = False
        self._location = RobotLocation(
            reference_frame="desktop",
            x=0,
            y=0,
            z=0,
            yaw=0,
            position_confidence=0.9,
            localization_state="known",
        )
        self._device_states = RobotDeviceStates()
        self._capabilities = _default_capabilities()
        self._subscribers: dict[int, RobotEventSubscriber] = {}

    async def get_robot(self, external_id: str) -> RegisteredRobot:
        self._require_external_id(external_id)
        return self._robot()

    async def get_capabilities(self, external_id: str) -> list[RobotCapability]:
        self._require_external_id(external_id)
        return [capability.model_copy(deep=True) for capability in self._capabilities]

    async def get_state(self, external_id: str) -> RobotStateSnapshot:
        self._require_external_id(external_id)
        return self._state_snapshot()

    async def execute_task(
        self,
        request: RegisteredRobotTaskRequest,
    ) -> RobotExecutionResult:
        self._validate_parameters(request.capability, request.parameters)
        self._raise_for_connection()
        self._raise_for_safety()
        capability = self._capability(request.capability)
        self._raise_for_capability(capability)
        self._raise_for_motion_preconditions(request.capability)
        await self._sleep(0)
        if self._timeout:
            raise TimeoutError("The mock robot task timed out.")

        result: dict[str, Any]
        if request.capability is RobotCapabilityName.NAVIGATE_TO:
            target = request.parameters["target_location"]
            self._validate_navigation_target(target)
            if self._localization_lost:
                raise RobotLocalizationLostError()
            if self._navigation_failure:
                raise RobotNavigationError("The mock robot could not reach the target.")
            self._location = RobotLocation.model_validate(
                {
                    **target,
                    "position_confidence": 0.9,
                    "localization_state": "known",
                }
            )
            result = {"moved_to": self._location.model_dump(mode="json")}
        elif request.capability is RobotCapabilityName.OBSERVE:
            self._device_states.camera = "capturing"
            result = {"media_handle": f"mock-image-{uuid4()}", "mock_only": True}
            self._device_states.camera = "disabled"
        elif request.capability is RobotCapabilityName.LISTEN:
            self._device_states.microphone = "recording"
            result = {"audio_handle": f"mock-audio-{uuid4()}", "mock_only": True}
            self._device_states.microphone = "disabled"
        elif request.capability is RobotCapabilityName.SPEAK:
            self._device_states.speaker = "speaking"
            result = {"spoken": request.parameters["text"]}
            self._device_states.speaker = "idle"
        else:
            result = {"acknowledged": True}

        return RobotExecutionResult(
            success=True,
            request_id=request.id,
            message="The mock robot completed the high-level task.",
            result=result,
            state=self._state_snapshot(),
            events=[
                self._event(
                    "task_succeeded",
                    request_id=request.id,
                    payload={"capability": request.capability.value, "result": result},
                )
            ],
        )

    async def cancel_task(self, request: RegisteredRobotTaskRequest) -> RobotExecutionResult:
        self._raise_for_connection()
        return RobotExecutionResult(
            success=True,
            request_id=request.id,
            message="The mock robot task was cancelled.",
            state=self._state_snapshot(),
            events=[self._event("task_cancelled", request_id=request.id, payload={})],
        )

    async def subscribe_events(self, subscriber: RobotEventSubscriber) -> Callable[[], None]:
        subscription_id = 1 + max(self._subscribers, default=0)
        self._subscribers[subscription_id] = subscriber

        def close() -> None:
            self._subscribers.pop(subscription_id, None)

        return close

    def set_offline(self, *, offline: bool = True) -> None:
        self._offline = offline

    def set_timeout(self, *, timeout: bool = True) -> None:
        self._timeout = timeout

    def set_emergency_stop(self, *, active: bool = True) -> None:
        self._emergency_stop = active

    def set_manual_takeover(self, *, active: bool = True) -> None:
        self._manual_takeover = active

    def set_battery_percent(self, value: float) -> None:
        self._battery_percent = value

    def set_navigation_failure(self, *, enabled: bool = True) -> None:
        self._navigation_failure = enabled

    def set_localization_lost(self, *, lost: bool = True) -> None:
        self._localization_lost = lost

    def set_capability(
        self,
        capability: RobotCapabilityName,
        *,
        runtime_enabled: bool,
        verification_status: CapabilityVerification,
        requires_confirmation: bool = True,
    ) -> None:
        current = self._capability(capability)
        current.runtime_enabled = runtime_enabled
        current.verification_status = verification_status
        current.requires_confirmation = requires_confirmation

    def _robot(self) -> RegisteredRobot:
        now = self._clock()
        return RegisteredRobot(
            id="adapter-projection",
            adapter_id=self.adapter_id,
            external_id=self._external_id,
            name=self._name,
            vendor="custom",
            model="custom_desktop_robot",
            hardware_version="mock-hw-1",
            firmware_version="mock-fw-1",
            edge_runtime_version="mock-edge-1",
            is_enabled=False,
            connection_state=self._connection_state(),
            is_online=not self._offline,
            motion_safety_state=self._motion_safety_state(),
            emergency_stop=self._emergency_stop,
            manual_takeover=self._manual_takeover,
            battery_percent=self._battery_percent,
            device_states=self._device_states.model_copy(deep=True),
            location=self._location.model_copy(deep=True),
            last_seen_at=None if self._offline else now,
            created_at=now,
            updated_at=now,
        )

    def _state_snapshot(self) -> RobotStateSnapshot:
        return RobotStateSnapshot(
            robot_id=self._external_id,
            connection_state=self._connection_state(),
            is_online=not self._offline,
            motion_safety_state=self._motion_safety_state(),
            emergency_stop=self._emergency_stop,
            manual_takeover=self._manual_takeover,
            battery_percent=self._battery_percent,
            device_states=self._device_states.model_copy(deep=True),
            location=self._location.model_copy(deep=True),
            source="mock",
            observed_at=self._clock(),
        )

    def _connection_state(self) -> RobotConnectionState:
        if self._offline:
            return RobotConnectionState.DISCONNECTED
        if self._timeout:
            return RobotConnectionState.DEGRADED
        return RobotConnectionState.CONNECTED

    def _motion_safety_state(self) -> RobotMotionSafetyState:
        if self._emergency_stop:
            return RobotMotionSafetyState.STOPPED
        if self._manual_takeover:
            return RobotMotionSafetyState.MANUAL_TAKEOVER
        if self._localization_lost:
            return RobotMotionSafetyState.UNKNOWN
        return RobotMotionSafetyState.NORMAL

    def _event(
        self,
        event_type: str,
        *,
        request_id: str,
        payload: dict[str, Any],
    ) -> RobotEvent:
        return RobotEvent(
            robot_id=self._external_id,
            task_request_id=request_id,
            event_type=event_type,  # type: ignore[arg-type]
            severity="info",
            source=self.adapter_id,
            payload=payload,
            occurred_at=self._clock(),
        )

    def _require_external_id(self, external_id: str) -> None:
        if external_id != self._external_id:
            raise RobotNotFoundError()

    def _capability(self, capability: RobotCapabilityName) -> RobotCapability:
        item = next(
            (candidate for candidate in self._capabilities if candidate.capability is capability),
            None,
        )
        if item is None:
            raise RobotCapabilityUnsupportedError()
        return item

    def _raise_for_connection(self) -> None:
        if self._offline:
            raise RobotConnectionError()

    def _raise_for_safety(self) -> None:
        if self._emergency_stop:
            raise RobotSafetyStateError("The mock robot emergency stop is active.")
        if self._manual_takeover:
            raise RobotSafetyStateError("The mock robot is under manual takeover.")

    def _raise_for_capability(self, capability: RobotCapability) -> None:
        if not capability.runtime_enabled:
            raise RobotCapabilityDisabledError()

    def _raise_for_motion_preconditions(self, capability: RobotCapabilityName) -> None:
        motion_capabilities = {
            RobotCapabilityName.NAVIGATE_TO,
            RobotCapabilityName.RETURN_TO_DOCK,
            RobotCapabilityName.CHARGE,
        }
        if capability in motion_capabilities and self._battery_percent <= 15:
            raise RobotLowBatteryError()

    def _validate_parameters(
        self,
        capability: RobotCapabilityName,
        parameters: dict[str, Any],
    ) -> None:
        _reject_low_level_parameters(parameters)
        if capability is RobotCapabilityName.NAVIGATE_TO:
            if not isinstance(parameters.get("target_location"), dict):
                raise RobotInvalidParameterError("navigate_to requires target_location.")
        elif capability is RobotCapabilityName.SPEAK and not isinstance(
            parameters.get("text"),
            str,
        ):
            raise RobotInvalidParameterError("speak requires text.")

    def _validate_navigation_target(self, target: dict[str, Any]) -> None:
        _reject_low_level_parameters(target)
        allowed = {
            "space_id",
            "reference_frame",
            "x",
            "y",
            "z",
            "yaw",
            "position_confidence",
        }
        unsupported = set(target) - allowed
        if unsupported:
            raise RobotInvalidParameterError(
                f"Unsupported navigation target fields: {sorted(unsupported)}."
            )
        if not all(isinstance(target.get(field), (int, float)) for field in ("x", "y")):
            raise RobotInvalidParameterError("target_location.x and y must be numeric.")


def _reject_low_level_parameters(parameters: dict[str, Any]) -> None:
    forbidden = {"motor", "motors", "joint", "joints", "pwm", "servo", "firmware", "shell"}

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in forbidden:
                    raise RobotInvalidParameterError("Low-level robot control is forbidden.")
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(parameters)


def _default_capabilities() -> list[RobotCapability]:
    definitions: list[tuple[RobotCapabilityName, str, bool]] = [
        (RobotCapabilityName.NAVIGATE_TO, "medium_risk", True),
        (RobotCapabilityName.OBSERVE, "read_only", True),
        (RobotCapabilityName.INSPECT, "read_only", True),
        (RobotCapabilityName.SPEAK, "low_risk", True),
        (RobotCapabilityName.LISTEN, "read_only", True),
        (RobotCapabilityName.RETURN_TO_DOCK, "medium_risk", True),
        (RobotCapabilityName.CHARGE, "medium_risk", True),
        (RobotCapabilityName.REPORT_STATUS, "read_only", True),
    ]
    capabilities: list[RobotCapability] = []
    for capability, risk, requires_confirmation in definitions:
        consents: list[str] = []
        if capability is RobotCapabilityName.OBSERVE:
            consents.append("camera")
        if capability is RobotCapabilityName.LISTEN:
            consents.append("microphone")
        if capability is RobotCapabilityName.SPEAK:
            consents.append("speaker")
        if risk == "medium_risk":
            consents.append("motion")
        capabilities.append(
            RobotCapability(
                capability=capability,
                verification_status="concept",
                runtime_enabled=False,
                risk_level=risk,  # type: ignore[arg-type]
                requires_confirmation=requires_confirmation,
                requires_consents=consents,  # type: ignore[arg-type]
                evidence={"mock_only": True},
            )
        )
    return capabilities
