from arvuno_core.errors import ArvunoError


class HistoryError(ArvunoError):
    """Base error for read-only history queries."""


class HistoryValidationError(HistoryError):
    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(
            code="HISTORY_VALIDATION_ERROR",
            message=message,
            status_code=400,
            details=details or {},
        )


class HistoryNotFoundError(HistoryError):
    def __init__(self, message: str = "The history record does not exist.") -> None:
        super().__init__(code="HISTORY_NOT_FOUND", message=message, status_code=404)


class HistoryQueryUnsupportedError(HistoryError):
    def __init__(self, message: str) -> None:
        super().__init__(
            code="HISTORY_QUERY_UNSUPPORTED",
            message=message,
            status_code=422,
        )


__all__ = [
    "HistoryError",
    "HistoryNotFoundError",
    "HistoryQueryUnsupportedError",
    "HistoryValidationError",
]
