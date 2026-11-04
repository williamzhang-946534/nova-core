from arvuno_core.errors import ArvunoError


class ReasoningEnvironmentNotFoundError(ArvunoError):
    def __init__(self) -> None:
        super().__init__(
            code="REASONING_ENVIRONMENT_NOT_FOUND",
            message="The reasoning environment is unavailable.",
            status_code=404,
        )


class ReasoningSessionNotFoundError(ArvunoError):
    def __init__(self) -> None:
        super().__init__(
            code="REASONING_SESSION_NOT_FOUND",
            message="The reasoning session was not found.",
            status_code=404,
        )


class ReasoningEvidenceNotFoundError(ArvunoError):
    def __init__(self) -> None:
        super().__init__(
            code="REASONING_EVIDENCE_NOT_FOUND",
            message="The reasoning evidence was not found.",
            status_code=404,
        )


class ReasoningHypothesisNotFoundError(ArvunoError):
    def __init__(self) -> None:
        super().__init__(
            code="REASONING_HYPOTHESIS_NOT_FOUND",
            message="The reasoning hypothesis was not found.",
            status_code=404,
        )


class ReasoningSourceNotFoundError(ArvunoError):
    def __init__(self) -> None:
        super().__init__(
            code="REASONING_SOURCE_NOT_FOUND",
            message="The original reasoning source was not found.",
            status_code=404,
        )


__all__ = [
    "ReasoningEnvironmentNotFoundError",
    "ReasoningEvidenceNotFoundError",
    "ReasoningHypothesisNotFoundError",
    "ReasoningSessionNotFoundError",
    "ReasoningSourceNotFoundError",
]
