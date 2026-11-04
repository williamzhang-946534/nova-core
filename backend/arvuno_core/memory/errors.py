from arvuno_core.errors import ArvunoError


class MemoryError(ArvunoError):
    """Base error for memory lifecycle and authorization rules."""


class MemoryNotFoundError(MemoryError):
    def __init__(self) -> None:
        super().__init__(
            code="MEMORY_NOT_FOUND",
            message="The memory does not exist.",
            status_code=404,
        )


class PreferenceNotFoundError(MemoryError):
    def __init__(self) -> None:
        super().__init__(
            code="MEMORY_PREFERENCE_NOT_FOUND",
            message="The user preference does not exist.",
            status_code=404,
        )


class MemoryConflictError(MemoryError):
    def __init__(self, memory_ids: list[str]) -> None:
        super().__init__(
            code="MEMORY_CONFLICT",
            message="A confirmed semantic fact conflicts with the proposed value.",
            status_code=409,
            details={"conflicting_memory_ids": memory_ids},
        )


class MemoryValidationError(MemoryError):
    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(
            code="MEMORY_VALIDATION_ERROR",
            message=message,
            status_code=400,
            details=details or {},
        )


__all__ = [
    "MemoryConflictError",
    "MemoryError",
    "MemoryNotFoundError",
    "MemoryValidationError",
    "PreferenceNotFoundError",
]
