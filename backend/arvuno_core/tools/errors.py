from arvuno_core.errors import ArvunoError
from arvuno_core.tools.models import ToolErrorCode


class ToolError(ArvunoError):
    tool_code = ToolErrorCode.EXECUTION_FAILED
    default_status_code = 500

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(
            code=self.tool_code.value,
            message=message,
            status_code=self.default_status_code,
            details=details or {},
        )


class ToolValidationError(ToolError):
    tool_code = ToolErrorCode.VALIDATION
    default_status_code = 422


class ToolNotFoundError(ToolError):
    tool_code = ToolErrorCode.NOT_FOUND
    default_status_code = 404


class ToolPermissionDeniedError(ToolError):
    tool_code = ToolErrorCode.PERMISSION_DENIED
    default_status_code = 403


class ToolRiskRejectedError(ToolError):
    tool_code = ToolErrorCode.RISK_REJECTED
    default_status_code = 422


class ToolConfirmationRequiredError(ToolError):
    tool_code = ToolErrorCode.CONFIRMATION_REQUIRED
    default_status_code = 428


class ToolDeviceUnavailableError(ToolError):
    tool_code = ToolErrorCode.DEVICE_UNAVAILABLE
    default_status_code = 409


class ToolStateConflictError(ToolError):
    tool_code = ToolErrorCode.STATE_CONFLICT
    default_status_code = 409


class ToolAdapterTimeoutError(ToolError):
    tool_code = ToolErrorCode.ADAPTER_TIMEOUT
    default_status_code = 504


class ToolAdapterError(ToolError):
    tool_code = ToolErrorCode.ADAPTER_ERROR
    default_status_code = 502


class ToolExecutionFailedError(ToolError):
    tool_code = ToolErrorCode.EXECUTION_FAILED
    default_status_code = 500


class ToolPersistenceError(ToolError):
    tool_code = ToolErrorCode.PERSISTENCE_FAILED
    default_status_code = 500
