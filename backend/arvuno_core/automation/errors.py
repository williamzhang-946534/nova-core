from arvuno_core.errors import ArvunoError


class AutomationError(ArvunoError):
    status_code = 500
    code = "AUTOMATION_ERROR"


class AutomationNotFoundError(AutomationError):
    status_code = 404
    code = "NOT_FOUND"


class AutomationValidationError(AutomationError):
    status_code = 400
    code = "VALIDATION_ERROR"


class AutomationStateError(AutomationError):
    status_code = 409
    code = "STATE_CONFLICT"


class NotificationNotFoundError(AutomationError):
    status_code = 404
    code = "NOT_FOUND"
