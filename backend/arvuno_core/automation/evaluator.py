"""Condition evaluation for Arvuno context automations."""

from typing import Any

from arvuno_core.automation.models import AutomationCondition

_COMPARABLE_MISSING = object()


def resolve_field(source: dict[str, Any], field: str) -> Any:
    """Resolve a dotted field path against a plain dictionary."""
    value: Any = source
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return _COMPARABLE_MISSING
        value = value[part]
    return value


def evaluate_condition(condition: AutomationCondition, source: dict[str, Any]) -> bool:
    actual = resolve_field(source, condition.field)
    if actual is _COMPARABLE_MISSING:
        return False
    expected = condition.value
    operator = condition.operator
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "in":
        if not isinstance(expected, list):
            return False
        return actual in expected
    if operator == "contains":
        if isinstance(actual, str) and isinstance(expected, str):
            return expected in actual
        if isinstance(actual, list):
            return expected in actual
        return False
    if operator in {"gt", "gte", "lt", "lte"}:
        try:
            if operator == "gt":
                return actual > expected
            if operator == "gte":
                return actual >= expected
            if operator == "lt":
                return actual < expected
            return actual <= expected
        except TypeError:
            return False
    return False


def evaluate_conditions(
    conditions: list[AutomationCondition],
    source: dict[str, Any],
) -> bool:
    return all(evaluate_condition(condition, source) for condition in conditions)


def matched_conditions(
    conditions: list[AutomationCondition],
    source: dict[str, Any],
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for condition in conditions:
        if evaluate_condition(condition, source):
            matched.append(condition.model_dump(mode="json"))
    return matched
