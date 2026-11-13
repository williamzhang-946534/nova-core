from arvuno_core.errors import ArvunoError


class RobotError(ArvunoError):
    """Base class for normalized robot integration errors."""


class RobotNotFoundError(RobotError):
    def __init__(self, message: str = "The robot is not available to Arvuno.") -> None:
        super().__init__(code="ROBOT_NOT_FOUND", message=message, status_code=404)


class RobotUnavailableError(RobotError):
    def __init__(self, message: str = "The robot adapter is unavailable.") -> None:
        super().__init__(code="ROBOT_UNAVAILABLE", message=message, status_code=503)


class RobotAdapterUnavailableError(RobotUnavailableError):
    def __init__(self, message: str = "The robot adapter is not registered.") -> None:
        super().__init__(message)


class RobotConnectionError(RobotUnavailableError):
    def __init__(self, message: str = "The robot is disconnected.") -> None:
        ArvunoError.__init__(
            self,
            code="ROBOT_CONNECTION_FAILED",
            message=message,
            status_code=503,
        )


class RobotCapabilityUnsupportedError(RobotError):
    def __init__(self, message: str = "The robot does not support this capability.") -> None:
        super().__init__(
            code="ROBOT_CAPABILITY_UNSUPPORTED",
            message=message,
            status_code=400,
        )


class RobotCapabilityDisabledError(RobotError):
    def __init__(self, message: str = "The robot capability is not enabled.") -> None:
        super().__init__(
            code="ROBOT_CAPABILITY_DISABLED",
            message=message,
            status_code=403,
        )


class RobotCapabilityGovernanceError(RobotError):
    def __init__(self, message: str) -> None:
        super().__init__(
            code="ROBOT_CAPABILITY_GOVERNANCE_INVALID",
            message=message,
            status_code=409,
        )


class RobotExecutionLockedError(RobotError):
    def __init__(
        self,
        message: str = ("Robot execution is locked until the unified safety chain is available."),
    ) -> None:
        super().__init__(
            code="ROBOT_EXECUTION_LOCKED",
            message=message,
            status_code=403,
            details={
                "required_boundary": "task_system+tool_registry+safety_policy+tool_executor",
                "temporary_lock": True,
            },
        )


class RobotInvalidParameterError(RobotError):
    def __init__(self, message: str) -> None:
        super().__init__(
            code="ROBOT_INVALID_PARAMETER",
            message=message,
            status_code=400,
        )


class RobotSafetyStateError(RobotError):
    def __init__(self, message: str = "The robot is in a safety stop state.") -> None:
        super().__init__(code="ROBOT_SAFETY_STATE", message=message, status_code=409)


class RobotLowBatteryError(RobotUnavailableError):
    def __init__(self, message: str = "The robot battery is too low for this task.") -> None:
        super().__init__(message)


class RobotNavigationError(RobotError):
    def __init__(self, message: str = "The robot navigation task failed.") -> None:
        super().__init__(code="ROBOT_NAVIGATION_FAILED", message=message, status_code=409)


class RobotLocalizationLostError(RobotError):
    def __init__(self, message: str = "Robot localization is unavailable.") -> None:
        super().__init__(code="ROBOT_LOCALIZATION_LOST", message=message, status_code=409)


class RobotTaskCancelledError(RobotError):
    def __init__(self, message: str = "The robot task was cancelled.") -> None:
        super().__init__(code="ROBOT_TASK_CANCELLED", message=message, status_code=409)


class RobotTaskNotFoundError(RobotError):
    def __init__(self, message: str = "The robot task request was not found.") -> None:
        super().__init__(code="ROBOT_TASK_NOT_FOUND", message=message, status_code=404)


class RobotConsentNotFoundError(RobotError):
    def __init__(self, message: str = "The robot consent was not found.") -> None:
        super().__init__(code="ROBOT_CONSENT_NOT_FOUND", message=message, status_code=404)


class RobotConsentInvalidError(RobotError):
    def __init__(
        self,
        message: str = "Valid robot consent is required before execution.",
    ) -> None:
        super().__init__(
            code="ROBOT_CONSENT_REQUIRED",
            message=message,
            status_code=403,
        )


class RobotTaskStateError(RobotError):
    def __init__(self, message: str) -> None:
        super().__init__(code="ROBOT_TASK_STATE", message=message, status_code=409)


class RobotTaskIdempotencyConflictError(RobotError):
    def __init__(
        self,
        message: str = "The idempotency key was reused with different task semantics.",
    ) -> None:
        super().__init__(
            code="ROBOT_TASK_IDEMPOTENCY_CONFLICT",
            message=message,
            status_code=409,
        )
