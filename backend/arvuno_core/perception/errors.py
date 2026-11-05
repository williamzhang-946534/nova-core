from arvuno_core.errors import ArvunoError


class PerceptionEnvironmentNotFoundError(ArvunoError):
    def __init__(self) -> None:
        super().__init__(
            code="PERCEPTION_ENVIRONMENT_NOT_FOUND",
            message="The active perception environment does not exist.",
            status_code=404,
        )


class PerceptionRequestNotFoundError(ArvunoError):
    def __init__(self) -> None:
        super().__init__(
            code="PERCEPTION_REQUEST_NOT_FOUND",
            message="The active perception request does not exist.",
            status_code=404,
        )


class PerceptionStateError(ArvunoError):
    def __init__(self, message: str) -> None:
        super().__init__(
            code="PERCEPTION_INVALID_STATE",
            message=message,
            status_code=409,
        )


class PerceptionSourceMismatchError(ArvunoError):
    def __init__(self, message: str) -> None:
        super().__init__(
            code="PERCEPTION_OBSERVATION_MISMATCH",
            message=message,
            status_code=409,
        )


__all__ = [
    "PerceptionEnvironmentNotFoundError",
    "PerceptionRequestNotFoundError",
    "PerceptionSourceMismatchError",
    "PerceptionStateError",
]
