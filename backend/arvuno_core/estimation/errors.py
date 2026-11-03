from arvuno_core.errors import ArvunoError


class EstimationError(ArvunoError):
    """A stable error raised by the state estimation contract."""


class StateEstimateNotFoundError(EstimationError):
    def __init__(self) -> None:
        super().__init__(
            code="STATE_ESTIMATE_NOT_FOUND",
            message="The state estimate does not exist.",
            status_code=404,
        )


class StateEstimationEnvironmentError(EstimationError):
    def __init__(self) -> None:
        super().__init__(
            code="STATE_ESTIMATION_ENVIRONMENT_NOT_INITIALIZED",
            message="The default environment spatial root is not initialized.",
            status_code=409,
        )


__all__ = [
    "EstimationError",
    "StateEstimateNotFoundError",
    "StateEstimationEnvironmentError",
]
