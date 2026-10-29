from arvuno_core.errors import ArvunoError


class AgentValidationError(ArvunoError):
    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(
            code="AGENT_VALIDATION_ERROR",
            message=message,
            status_code=422,
            details=dict(details or {}),
        )


__all__ = ["AgentValidationError"]
