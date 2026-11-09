from collections.abc import Awaitable, Callable
from typing import Protocol

from arvuno_core.robots.models import (
    RegisteredRobot,
    RegisteredRobotTaskRequest,
    RobotCapability,
    RobotExecutionResult,
    RobotStateSnapshot,
)

RobotEventSubscriber = Callable[[object], Awaitable[None]]


class RobotAdapter(Protocol):
    """Contract for high-level robot capabilities only.

    Implementations must never expose joints, motors, PWM, firmware payloads,
    shell commands, or arbitrary vendor SDK calls through this interface.
    """

    adapter_id: str
    version: str

    async def get_robot(self, external_id: str) -> RegisteredRobot: ...

    async def get_capabilities(self, external_id: str) -> list[RobotCapability]: ...

    async def get_state(self, external_id: str) -> RobotStateSnapshot: ...

    async def execute_task(
        self,
        request: RegisteredRobotTaskRequest,
    ) -> RobotExecutionResult: ...

    async def cancel_task(self, request: RegisteredRobotTaskRequest) -> RobotExecutionResult: ...
