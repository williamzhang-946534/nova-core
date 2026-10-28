from nova_core.errors import NovaError


class AgentValidationError(NovaError):
    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(
            code="AGENT_VALIDATION_ERROR",
            message=message,
            status_code=422,
            details=dict(details or {}),
        )


__all__ = ["AgentValidationError"]
