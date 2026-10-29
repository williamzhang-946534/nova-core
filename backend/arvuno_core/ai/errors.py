from arvuno_core.errors import ArvunoError


class ProviderConfigurationError(ArvunoError):
    def __init__(self, message: str) -> None:
        super().__init__(
            code="PROVIDER_CONFIGURATION_ERROR",
            message=message,
            status_code=500,
        )


class ProviderLogError(ArvunoError):
    def __init__(self) -> None:
        super().__init__(
            code="PROVIDER_LOG_ERROR",
            message="The AI provider call could not be recorded.",
            status_code=500,
        )


class ProviderHTTPError(ArvunoError):
    def __init__(self, status_code: int) -> None:
        super().__init__(
            code="PROVIDER_ERROR",
            message="The AI provider returned an error.",
            status_code=502,
            details={"provider_status_code": status_code},
        )


class ProviderAuthenticationError(ArvunoError):
    def __init__(self) -> None:
        super().__init__(
            code="PROVIDER_AUTHENTICATION_ERROR",
            message="The AI provider rejected the configured credentials.",
            status_code=502,
        )


class ProviderTimeoutError(ArvunoError):
    def __init__(self) -> None:
        super().__init__(
            code="PROVIDER_TIMEOUT",
            message="The AI provider timed out.",
            status_code=504,
        )


class ProviderInvalidOutputError(ArvunoError):
    def __init__(self, reason: str) -> None:
        super().__init__(
            code="PROVIDER_INVALID_OUTPUT",
            message="The AI provider did not return valid structured output.",
            status_code=502,
            details={"reason": reason},
        )
