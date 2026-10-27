class EventPersistenceError(Exception):
    """Raised when an event cannot be committed before dispatch."""


class EventRecursionLimitExceeded(Exception):
    """Raised when event subscribers publish events too deeply."""
