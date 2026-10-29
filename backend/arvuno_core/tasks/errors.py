from arvuno_core.errors import ArvunoError


class TaskError(ArvunoError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(
            code="TASK_ERROR",
            message=message,
            status_code=status_code,
        )


class TaskNotFoundError(TaskError):
    def __init__(self) -> None:
        super().__init__(
            "The task does not exist.",
            status_code=404,
        )


class TaskStateError(TaskError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=409)


class TaskValidationError(TaskError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=400)
