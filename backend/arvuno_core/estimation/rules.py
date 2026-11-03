from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from arvuno_core.persistence.models import Observation, ObservationSource


@dataclass(frozen=True)
class EstimationRuleSpec:
    strategy_id: str
    strategy_version: str
    rule_id: str
    rule_version: str
    valid_seconds: int
    conflict_policy: dict[str, Any]
    coverage_policy: dict[str, Any]


@dataclass(frozen=True)
class EvidenceLink:
    observation: Observation
    source: ObservationSource
    contribution: str
    weight: float | None = None
    exclusion_reason: str | None = None


@dataclass(frozen=True)
class RuleResult:
    status: str
    value: Any | None
    unit: str | None
    confidence: float | None
    evidence_summary: dict[str, Any]
    conflict_details: dict[str, Any] | None
    rule_id: str
    rule_version: str
    effective_from: datetime
    valid_until: datetime | None
    links: tuple[EvidenceLink, ...]


RULE_SPECS: dict[str, EstimationRuleSpec] = {
    "temperature": EstimationRuleSpec(
        strategy_id="numeric_weighted_median",
        strategy_version="1.0.0",
        rule_id="temperature_weighted_median_v1",
        rule_version="1.0.0",
        valid_seconds=300,
        conflict_policy={"max_spread": 2.0},
        coverage_policy={"minimum_sources": 1},
    ),
    "humidity": EstimationRuleSpec(
        strategy_id="numeric_weighted_median",
        strategy_version="1.0.0",
        rule_id="humidity_weighted_median_v1",
        rule_version="1.0.0",
        valid_seconds=600,
        conflict_policy={"max_spread": 8.0},
        coverage_policy={"minimum_sources": 1},
    ),
    "illumination": EstimationRuleSpec(
        strategy_id="numeric_weighted_median",
        strategy_version="1.0.0",
        rule_id="illumination_weighted_median_v1",
        rule_version="1.0.0",
        valid_seconds=600,
        conflict_policy={"max_spread": 300.0},
        coverage_policy={"minimum_sources": 1, "position_aware": True},
    ),
    "co2": EstimationRuleSpec(
        strategy_id="numeric_weighted_median",
        strategy_version="1.0.0",
        rule_id="co2_weighted_median_v1",
        rule_version="1.0.0",
        valid_seconds=600,
        conflict_policy={"max_spread": 150.0},
        coverage_policy={"minimum_sources": 1},
    ),
    "motion": EstimationRuleSpec(
        strategy_id="event_positive_evidence",
        strategy_version="1.0.0",
        rule_id="motion_positive_evidence_v1",
        rule_version="1.0.0",
        valid_seconds=60,
        conflict_policy={"contradictory_values": True},
        coverage_policy={"false_means_unoccupied": False},
    ),
    "contact": EstimationRuleSpec(
        strategy_id="direct_enum_latest",
        strategy_version="1.0.0",
        rule_id="contact_direct_v1",
        rule_version="1.0.0",
        valid_seconds=300,
        conflict_policy={"contradictory_values": True},
        coverage_policy={"minimum_sources": 1},
    ),
    "occupancy": EstimationRuleSpec(
        strategy_id="coverage_aware_occupancy",
        strategy_version="1.0.0",
        rule_id="occupancy_coverage_aware_v1",
        rule_version="1.0.0",
        valid_seconds=120,
        conflict_policy={"contradictory_direct_values": True},
        coverage_policy={"negative_coverage_declared": False},
    ),
    "device_availability": EstimationRuleSpec(
        strategy_id="adapter_availability",
        strategy_version="1.0.0",
        rule_id="device_availability_direct_v1",
        rule_version="1.0.0",
        valid_seconds=300,
        conflict_policy={"contradictory_values": True},
        coverage_policy={"minimum_sources": 1},
    ),
    "actuator_state": EstimationRuleSpec(
        strategy_id="direct_json_latest",
        strategy_version="1.0.0",
        rule_id="actuator_state_direct_v1",
        rule_version="1.0.0",
        valid_seconds=300,
        conflict_policy={"contradictory_values": True},
        coverage_policy={"feedback_preferred": True},
    ),
}

DEFAULT_RULE = EstimationRuleSpec(
    strategy_id="attribute_direct",
    strategy_version="1.0.0",
    rule_id="attribute_direct_v1",
    rule_version="1.0.0",
    valid_seconds=300,
    conflict_policy={"contradictory_values": True},
    coverage_policy={"minimum_sources": 1},
)


def rule_for(attribute: str) -> EstimationRuleSpec:
    return RULE_SPECS.get(attribute, DEFAULT_RULE)


def estimate(
    *,
    attribute: str,
    target_type: str,
    candidates: list[tuple[Observation, ObservationSource]],
    availability_candidates: list[tuple[Observation, ObservationSource]] | None = None,
    motion_candidates: list[tuple[Observation, ObservationSource]] | None = None,
    now: datetime,
) -> RuleResult:
    now = stored_as_utc(now)
    spec = rule_for(attribute)
    grouped = _latest_by_series(candidates)
    usable = [pair for pair in grouped if _usable(pair[0])]
    invalid = [pair for pair in grouped if not _usable(pair[0])]

    if target_type == "entity" and attribute != "device_availability":
        availability = _latest_by_series(availability_candidates or [])
        fresh_offline = [
            pair
            for pair in availability
            if _fresh(pair[0], now) and pair[0].normalized_value == "offline"
        ]
        if fresh_offline:
            return _result(
                spec=spec,
                status="unavailable",
                value=None,
                unit=None,
                links=tuple(
                    EvidenceLink(observation, source, "direct", _weight(source, observation))
                    for observation, source in fresh_offline
                ),
                now=now,
                summary_reason="A fresh source explicitly reported the entity as offline.",
            )

    if not grouped:
        if attribute == "occupancy" and target_type == "space":
            return _space_occupancy(
                spec,
                [],
                _latest_by_series(motion_candidates or []),
                now,
            )
        return _unknown(spec, now)

    if attribute == "occupancy" and target_type == "space":
        return _space_occupancy(
            spec,
            [pair for pair in grouped if _usable(pair[0]) and _fresh(pair[0], now)],
            _latest_by_series(motion_candidates or []),
            now,
        )

    fresh = [pair for pair in usable if _fresh(pair[0], now)]
    if not fresh:
        if usable:
            return _stale(spec, usable, now)
        return _unknown_with_invalid(spec, invalid, now)

    if attribute in {"temperature", "humidity", "illumination", "co2"}:
        return _numeric_result(spec, fresh, now)

    if attribute == "occupancy" and target_type == "space":
        return _space_occupancy(spec, fresh, _latest_by_series(motion_candidates or []), now)

    result = _direct_result(spec, fresh, now)
    if attribute == "device_availability" and result.value == "offline":
        return replace(
            result,
            status="unavailable",
            evidence_summary={
                **result.evidence_summary,
                "reason": "A fresh source explicitly reported the entity as offline.",
            },
        )
    return result


def _latest_by_series(
    rows: list[tuple[Observation, ObservationSource]],
) -> list[tuple[Observation, ObservationSource]]:
    selected: dict[
        tuple[str, str | None, str | None, str | None, str], tuple[Observation, ObservationSource]
    ] = {}
    for observation, source in rows:
        key = (
            source.id,
            observation.entity_id,
            observation.subject_type,
            observation.subject_id,
            observation.external_id or "",
        )
        current = selected.get(key)
        if current is None or _sequence(observation) > _sequence(current[0]):
            selected[key] = (observation, source)
    return list(selected.values())


def _numeric_result(
    spec: EstimationRuleSpec,
    candidates: list[tuple[Observation, ObservationSource]],
    now: datetime,
) -> RuleResult:
    numeric: list[tuple[float, Observation, ObservationSource, float]] = []
    for observation, source in candidates:
        try:
            value = float(observation.normalized_value)
        except (TypeError, ValueError):
            continue
        numeric.append((value, observation, source, _weight(source, observation)))
    if not numeric:
        return _unknown(spec, now)
    numeric.sort(key=lambda item: item[0])
    low, high = numeric[0][0], numeric[-1][0]
    if high - low > float(spec.conflict_policy.get("max_spread", 0)):
        return _conflict(spec, candidates, now, spread=high - low)
    total_weight = sum(item[3] for item in numeric)
    remaining = total_weight / 2.0
    selected = numeric[-1]
    for value, observation, source, weight in numeric:
        remaining -= weight
        if remaining <= 0:
            selected = (value, observation, source, weight)
            break
    status = "observed" if len(numeric) == 1 else "derived"
    return _result(
        spec=spec,
        status=status,
        value=selected[0],
        unit=selected[1].normalized_unit,
        links=tuple(
            EvidenceLink(observation, source, "candidate", _weight(source, observation))
            for _, observation, source, _ in numeric
        ),
        now=now,
        summary_reason="Representative weighted median across fresh numeric observations.",
    )


def _direct_result(
    spec: EstimationRuleSpec,
    candidates: list[tuple[Observation, ObservationSource]],
    now: datetime,
) -> RuleResult:
    values = _distinct_values(observation for observation, _ in candidates)
    if len(values) > 1:
        return _conflict(spec, candidates, now)
    observation, source = candidates[0]
    return _result(
        spec=spec,
        status="observed",
        value=observation.normalized_value,
        unit=observation.normalized_unit,
        links=(EvidenceLink(observation, source, "direct", _weight(source, observation)),),
        now=now,
        summary_reason="One or more fresh observations directly agree on the value.",
    )


def _space_occupancy(
    spec: EstimationRuleSpec,
    direct: list[tuple[Observation, ObservationSource]],
    motion: list[tuple[Observation, ObservationSource]],
    now: datetime,
) -> RuleResult:
    direct_values = _distinct_values(observation for observation, _ in direct)
    if len(direct_values) > 1:
        return _conflict(spec, direct, now)

    positive_motion = [
        pair
        for pair in motion
        if _usable(pair[0]) and _fresh(pair[0], now) and pair[0].normalized_value is True
    ]
    if direct_values == ["occupied"]:
        return _result(
            spec=spec,
            status="observed",
            value="occupied",
            unit=None,
            links=tuple(
                EvidenceLink(observation, source, "direct", _weight(source, observation))
                for observation, source in direct
            ),
            now=now,
            summary_reason="A direct occupancy sensor reported occupied.",
        )
    if positive_motion:
        return _result(
            spec=spec,
            status="inferred",
            value="occupied",
            unit=None,
            links=tuple(
                EvidenceLink(observation, source, "candidate", _weight(source, observation))
                for observation, source in positive_motion
            ),
            now=now,
            summary_reason="Motion is positive evidence that the space is occupied.",
        )

    negative_links: list[EvidenceLink] = []
    for observation, source in direct:
        if observation.normalized_value == "unoccupied":
            negative_links.append(
                EvidenceLink(
                    observation,
                    source,
                    "negative_evidence",
                    _weight(source, observation),
                    "negative_occupancy_coverage_not_declared",
                )
            )
    for observation, source in motion:
        if (
            _usable(observation)
            and _fresh(observation, now)
            and observation.normalized_value is False
        ):
            negative_links.append(
                EvidenceLink(
                    observation,
                    source,
                    "negative_evidence",
                    _weight(source, observation),
                    "pir_false_is_not_unoccupied",
                )
            )
    return _result(
        spec=spec,
        status="unknown",
        value=None,
        unit=None,
        links=tuple(negative_links),
        now=now,
        summary_reason="No complete coverage declaration permits a negative occupancy conclusion.",
    )


def _stale(
    spec: EstimationRuleSpec,
    candidates: list[tuple[Observation, ObservationSource]],
    now: datetime,
) -> RuleResult:
    latest = max(candidates, key=lambda pair: _sequence(pair[0]))
    return _result(
        spec=spec,
        status="stale",
        value=latest[0].normalized_value,
        unit=latest[0].normalized_unit,
        links=tuple(
            EvidenceLink(
                observation,
                source,
                "context",
                _weight(source, observation),
                "evidence_expired",
            )
            for observation, source in candidates
        ),
        now=now,
        summary_reason="All credible observations exceeded their attribute validity window.",
    )


def _unknown(spec: EstimationRuleSpec, now: datetime) -> RuleResult:
    return _result(
        spec=spec,
        status="unknown",
        value=None,
        unit=None,
        links=(),
        now=now,
        summary_reason="No usable evidence is available for this target.",
    )


def _unknown_with_invalid(
    spec: EstimationRuleSpec,
    candidates: list[tuple[Observation, ObservationSource]],
    now: datetime,
) -> RuleResult:
    return _result(
        spec=spec,
        status="unknown",
        value=None,
        unit=None,
        links=tuple(
            EvidenceLink(observation, source, "context", None, "invalid_observation")
            for observation, source in candidates
        ),
        now=now,
        summary_reason="Only invalid observations are available; they are retained as context.",
    )


def _conflict(
    spec: EstimationRuleSpec,
    candidates: list[tuple[Observation, ObservationSource]],
    now: datetime,
    *,
    spread: float | None = None,
) -> RuleResult:
    details = {
        "reason": "credible_observations_conflict",
        "candidates": [
            _candidate_summary(observation, source) for observation, source in candidates
        ],
    }
    if spread is not None:
        details["spread"] = spread
        details["threshold"] = spec.conflict_policy.get("max_spread")
    return _result(
        spec=spec,
        status="conflict",
        value=None,
        unit=None,
        links=tuple(
            EvidenceLink(observation, source, "candidate", _weight(source, observation))
            for observation, source in candidates
        ),
        now=now,
        summary_reason="Credible observations conflict beyond the attribute policy.",
        conflict_details=details,
    )


def _result(
    *,
    spec: EstimationRuleSpec,
    status: str,
    value: Any,
    unit: str | None,
    links: tuple[EvidenceLink, ...],
    now: datetime,
    summary_reason: str,
    conflict_details: dict[str, Any] | None = None,
) -> RuleResult:
    candidate_validities = [
        stored_as_utc(link.observation.valid_until)
        for link in links
        if link.observation.valid_until is not None
    ]
    if status == "stale":
        valid_until = max(candidate_validities, default=None)
    elif not candidate_validities:
        valid_until = None if status == "unknown" else now + timedelta(seconds=spec.valid_seconds)
    else:
        valid_until = min([now + timedelta(seconds=spec.valid_seconds), *candidate_validities])
    effective_from = max(
        (
            stored_as_utc(link.observation.valid_from or link.observation.received_at)
            for link in links
        ),
        default=now,
    )
    return RuleResult(
        status=status,
        value=value,
        unit=unit,
        confidence=None,
        evidence_summary={
            "input_count": len(links),
            "source_ids": sorted({link.source.id for link in links}),
            "observation_ids": [link.observation.observation_id for link in links],
            "reason": summary_reason,
        },
        conflict_details=conflict_details,
        rule_id=spec.rule_id,
        rule_version=spec.rule_version,
        effective_from=effective_from,
        valid_until=valid_until,
        links=links,
    )


def _usable(observation: Observation) -> bool:
    return observation.quality_status != "invalid" and observation.normalized_value is not None


def _fresh(observation: Observation, now: datetime) -> bool:
    if observation.valid_until is None:
        return False
    return stored_as_utc(observation.valid_until) > now


def _sequence(observation: Observation) -> tuple[datetime, str]:
    return (stored_as_utc(observation.received_at), observation.observation_id)


def _weight(source: ObservationSource, observation: Observation) -> float:
    quality_factor = 1.0 if observation.quality_status == "valid" else 0.7
    return max(0.01, float(source.trust_level) * quality_factor)


def stored_as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _distinct_values(observations: Any) -> list[Any]:
    values: list[Any] = []
    for observation in observations:
        value = observation.normalized_value
        if value not in values:
            values.append(value)
    return values


def _candidate_summary(observation: Observation, source: ObservationSource) -> dict[str, Any]:
    return {
        "observation_id": observation.observation_id,
        "source_id": source.id,
        "entity_id": observation.entity_id,
        "value": observation.normalized_value,
        "unit": observation.normalized_unit,
        "observed_at": stored_as_utc(observation.observed_at).isoformat()
        if observation.observed_at is not None
        else None,
        "received_at": stored_as_utc(observation.received_at).isoformat(),
        "quality_status": observation.quality_status,
    }


__all__ = [
    "EvidenceLink",
    "EstimationRuleSpec",
    "RuleResult",
    "estimate",
    "rule_for",
]
