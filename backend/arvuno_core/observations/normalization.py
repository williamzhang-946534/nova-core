from dataclasses import dataclass
from numbers import Real
from typing import Any


@dataclass(frozen=True)
class NormalizationResult:
    normalized_value: Any = None
    normalized_unit: str | None = None
    issues: tuple[dict[str, Any], ...] = ()


def _issue(code: str, severity: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, **details}


def _number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def normalize(
    *,
    attribute: str,
    value_type: str,
    raw_value: Any,
    raw_unit: str | None,
) -> NormalizationResult:
    unit = (raw_unit or "").strip()
    lowered_unit = unit.casefold()
    lowered_value = str(raw_value).strip().casefold() if isinstance(raw_value, str) else raw_value

    if attribute == "temperature":
        if not _number(raw_value):
            return NormalizationResult(
                issues=(_issue("normalization_failed", "invalid", reason="not_a_number"),)
            )
        if not unit:
            return NormalizationResult(
                issues=(_issue("missing_required_unit", "warning", attribute=attribute),)
            )
        if lowered_unit in {"°c", "c", "celsius"}:
            return NormalizationResult(raw_value, "°C")
        if lowered_unit in {"°f", "f", "fahrenheit"}:
            return NormalizationResult(round((raw_value - 32) * 5 / 9, 3), "°C")
        if lowered_unit in {"k", "kelvin"}:
            return NormalizationResult(round(raw_value - 273.15, 3), "°C")
        return NormalizationResult(
            issues=(_issue("normalization_failed", "warning", unsupported_unit=unit),)
        )

    if attribute == "humidity":
        if not _number(raw_value):
            return NormalizationResult(
                issues=(_issue("normalization_failed", "invalid", reason="not_a_number"),)
            )
        if not unit:
            return NormalizationResult(
                issues=(_issue("missing_required_unit", "warning", attribute=attribute),)
            )
        if lowered_unit in {"%", "%rh", "rh"}:
            return NormalizationResult(raw_value, "%RH")
        return NormalizationResult(
            issues=(_issue("normalization_failed", "warning", unsupported_unit=unit),)
        )

    if attribute == "motion":
        if isinstance(raw_value, bool):
            return NormalizationResult(raw_value, None)
        if lowered_value in {"on", "true", "detected"}:
            return NormalizationResult(True, None)
        if lowered_value in {"off", "false", "clear"}:
            return NormalizationResult(False, None)
        if lowered_value in {"unknown", "unavailable", "none"}:
            return NormalizationResult(None, None)
        return NormalizationResult(issues=(_issue("normalization_failed", "invalid"),))

    if attribute == "contact":
        mapping = {"open": "open", "closed": "closed", "unknown": "unknown"}
        if lowered_value in mapping:
            return NormalizationResult(mapping[lowered_value], None)
        return NormalizationResult(issues=(_issue("normalization_failed", "invalid"),))

    if attribute == "occupancy":
        mapping = {
            "occupied": "occupied",
            "unoccupied": "unoccupied",
            "unknown": "unknown",
        }
        if lowered_value in mapping:
            return NormalizationResult(mapping[lowered_value], None)
        return NormalizationResult(issues=(_issue("normalization_failed", "invalid"),))

    if attribute == "illumination":
        if not _number(raw_value):
            return NormalizationResult(
                issues=(_issue("normalization_failed", "invalid", reason="not_a_number"),)
            )
        if not unit:
            return NormalizationResult(
                issues=(_issue("missing_required_unit", "warning", attribute=attribute),)
            )
        if lowered_unit in {"lux", "lx"}:
            return NormalizationResult(raw_value, "lux")
        return NormalizationResult(
            issues=(_issue("normalization_failed", "warning", unsupported_unit=unit),)
        )

    if attribute == "co2":
        if not _number(raw_value):
            return NormalizationResult(
                issues=(_issue("normalization_failed", "invalid", reason="not_a_number"),)
            )
        if not unit:
            return NormalizationResult(
                issues=(_issue("missing_required_unit", "warning", attribute=attribute),)
            )
        if lowered_unit in {"ppm"}:
            return NormalizationResult(raw_value, "ppm")
        return NormalizationResult(
            issues=(_issue("normalization_failed", "warning", unsupported_unit=unit),)
        )

    if attribute == "device_availability":
        mapping = {
            "online": "online",
            "available": "online",
            "offline": "offline",
            "unavailable": "offline",
            "unknown": "unknown",
            "none": "unknown",
        }
        if lowered_value in mapping:
            return NormalizationResult(mapping[lowered_value], None)
        return NormalizationResult(issues=(_issue("normalization_failed", "invalid"),))

    if attribute == "actuator_state" and value_type == "json":
        if isinstance(raw_value, (dict, list)):
            return NormalizationResult(raw_value, None)
        return NormalizationResult(issues=(_issue("normalization_failed", "invalid"),))

    return NormalizationResult(issues=(_issue("normalization_failed", "warning"),))


__all__ = ["NormalizationResult", "normalize"]
