from arvuno_core.errors import ArvunoError


class MultimodalError(ArvunoError):
    """Raised when the controlled multimodal pipeline rejects a request."""

    def __init__(
        self,
        *,
        code: str,
        message: str | None = None,
        status_code: int = 400,
    ) -> None:
        super().__init__(code=code, message=message or code, status_code=status_code)


__all__ = ["MultimodalError"]
