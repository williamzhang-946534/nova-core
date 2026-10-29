from typing import Literal

DeviceErrorCode = Literal[
    "adapter_unavailable",
    "adapter_timeout",
    "authorization_failed",
    "device_not_found",
    "device_unavailable",
    "action_unsupported",
    "invalid_action_parameter",
    "action_failed",
    "write_disabled",
    "state_verification_failed",
]


class DeviceError(Exception):
    """Base class for normalized device integration errors."""

    code: DeviceErrorCode = "action_failed"

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail


class AdapterUnavailableError(DeviceError):
    code = "adapter_unavailable"


class AdapterTimeoutError(DeviceError):
    code = "adapter_timeout"


class AuthorizationError(DeviceError):
    code = "authorization_failed"


class DeviceNotFoundError(DeviceError):
    code = "device_not_found"


class DeviceUnavailableError(DeviceError):
    code = "device_unavailable"


class ActionUnsupportedError(DeviceError):
    code = "action_unsupported"


class InvalidActionParameterError(DeviceError):
    code = "invalid_action_parameter"


class ActionFailedError(DeviceError):
    code = "action_failed"


class DeviceWriteDisabledError(DeviceError):
    code = "write_disabled"


class StateVerificationFailedError(DeviceError):
    code = "state_verification_failed"
