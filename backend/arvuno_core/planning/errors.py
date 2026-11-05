from arvuno_core.errors import ArvunoError


class PlanningEnvironmentNotFoundError(ArvunoError):
    def __init__(self) -> None:
        super().__init__(
            code="PLANNING_ENVIRONMENT_NOT_FOUND",
            message="The planning environment is unavailable.",
            status_code=404,
        )


class GoalNotFoundError(ArvunoError):
    def __init__(self) -> None:
        super().__init__(
            code="PLANNING_GOAL_NOT_FOUND",
            message="The goal was not found.",
            status_code=404,
        )


class PlanNotFoundError(ArvunoError):
    def __init__(self) -> None:
        super().__init__(
            code="PLANNING_PLAN_NOT_FOUND",
            message="The plan was not found.",
            status_code=404,
        )


class PlanningStateError(ArvunoError):
    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(
            code="PLANNING_STATE_ERROR",
            message=message,
            status_code=409,
            details=details,
        )


class PlanValidationError(ArvunoError):
    def __init__(self, errors: list[dict[str, object]]) -> None:
        super().__init__(
            code="PLAN_VALIDATION_FAILED",
            message="The plan failed validation.",
            status_code=422,
            details={"errors": errors},
        )


class GoalClarificationRequiredError(ArvunoError):
    def __init__(self, clarifications: list[str], unknowns: list[str]) -> None:
        super().__init__(
            code="GOAL_CLARIFICATION_REQUIRED",
            message="The objective cannot be compiled without user clarification.",
            status_code=422,
            details={"clarifications": clarifications, "unknowns": unknowns},
        )


__all__ = [
    "GoalClarificationRequiredError",
    "GoalNotFoundError",
    "PlanNotFoundError",
    "PlanValidationError",
    "PlanningEnvironmentNotFoundError",
    "PlanningStateError",
]
