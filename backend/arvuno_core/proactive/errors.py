class ProactiveError(Exception):
    """Base exception for the Proactive Intelligence module."""


class ProactiveEnvironmentNotFoundError(ProactiveError):
    def __init__(self) -> None:
        super().__init__("The proactive environment does not exist.")


class ProactiveSuggestionNotFoundError(ProactiveError):
    def __init__(self) -> None:
        super().__init__("The proactive suggestion does not exist.")


class ProactiveStateError(ProactiveError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


__all__ = [
    "ProactiveEnvironmentNotFoundError",
    "ProactiveError",
    "ProactiveStateError",
    "ProactiveSuggestionNotFoundError",
]
