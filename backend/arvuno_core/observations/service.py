import asyncio
import hashlib
import json
from collections.abc import Callable as CallableType
from datetime import UTC, datetime, timedelta
from typing import Any

from arvuno_core.observations.errors import ObservationError
from arvuno_core.observations.models import (
    ObservationInput,
    ObservationPage,
    ObservationRecord,
    ObservationResult,
    ObservationSourceRecord,
)
from arvuno_core.observations.normalization import normalize
from arvuno_core.persistence.models import Observation, ObservationSource
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork

_RELIABLE_TIME_SOURCES = {
    "device_clock",
    "gateway_state_clock",
    "user_asserted",
    "derived",
}


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ObservationError(
            code="OBSERVATION_TIME_NOT_UTC",
            message=f"The {field} timestamp must include a timezone.",
        )
    return value.astimezone(UTC)


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _hash(parts: list[Any]) -> str:
    return hashlib.sha256(_canonical(parts).encode("utf-8")).hexdigest()


def _issue(code: str, severity: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, **details}


def _quality_status(issues: list[dict[str, Any]]) -> str:
    severities = {issue.get("severity") for issue in issues}
    if "invalid" in severities:
        return "invalid"
    if "warning" in severities:
        return "warning"
    return "valid"


def _source_record(source: ObservationSource) -> ObservationSourceRecord:
    return ObservationSourceRecord.model_validate(source)


def _observation_record(observation: Observation) -> ObservationRecord:
    return ObservationRecord.model_validate(observation)


class ObservationService:
    """Normalizes and persists one actual observation without estimating state."""

    def __init__(self, unit_of_work_factory: CallableType[[], SqlAlchemyUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def record(self, request: ObservationInput) -> ObservationResult:
        return await asyncio.to_thread(self._record, request)

    async def get(self, observation_id: str) -> ObservationRecord:
        return await asyncio.to_thread(self._get, observation_id)

    async def query(
        self,
        *,
        source_id: str | None = None,
        entity_id: str | None = None,
        space_id: str | None = None,
        attribute: str | None = None,
        quality_status: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        correlation_id: str | None = None,
        external_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ObservationPage:
        def execute() -> ObservationPage:
            with self._unit_of_work_factory() as uow:
                assert uow.observations is not None
                rows, total = uow.observations.query(
                    source_id=source_id,
                    entity_id=entity_id,
                    space_id=space_id,
                    attribute=attribute,
                    quality_status=quality_status,
                    start_time=start_time,
                    end_time=end_time,
                    correlation_id=correlation_id,
                    external_id=external_id,
                    page=page,
                    page_size=page_size,
                )
                return ObservationPage(
                    data=[_observation_record(row) for row in rows],
                    page=page,
                    page_size=page_size,
                    total=total,
                )

        return await asyncio.to_thread(execute)

    async def list_sources(self) -> list[ObservationSourceRecord]:
        def execute() -> list[ObservationSourceRecord]:
            with self._unit_of_work_factory() as uow:
                assert uow.observation_sources is not None
                return [_source_record(source) for source in uow.observation_sources.list_sources()]

        return await asyncio.to_thread(execute)

    async def register_source(
        self,
        *,
        source_type: str,
        name: str,
        adapter_id: str | None = None,
        status: str = "active",
        trust_level: float = 0.5,
        time_trust: str = "unknown",
        config: dict[str, Any] | None = None,
        privacy_scope: dict[str, Any] | None = None,
    ) -> ObservationSourceRecord:
        if source_type not in {
            "adapter",
            "user_report",
            "derived_job",
            "vision",
            "future_external",
        }:
            raise ObservationError(code="OBSERVATION_SOURCE_TYPE_INVALID")
        if status not in {"active", "paused", "unavailable", "revoked"}:
            raise ObservationError(code="OBSERVATION_SOURCE_STATUS_INVALID")
        if not 0 <= trust_level <= 1:
            raise ObservationError(code="OBSERVATION_SOURCE_TRUST_INVALID")
        if time_trust not in {
            "device_clock",
            "gateway_clock",
            "poll_clock",
            "user_asserted",
            "unknown",
        }:
            raise ObservationError(code="OBSERVATION_SOURCE_TIME_TRUST_INVALID")

        def execute() -> ObservationSourceRecord:
            with self._unit_of_work_factory() as uow:
                assert uow.observation_sources is not None
                source = (
                    uow.observation_sources.get_by_adapter(adapter_id)
                    if adapter_id is not None
                    else None
                )
                if source is None:
                    source = ObservationSource(
                        source_type=source_type,
                        adapter_id=adapter_id,
                        name=name,
                        status=status,
                        trust_level=trust_level,
                        time_trust=time_trust,
                        config=config or {},
                        privacy_scope=privacy_scope or {},
                    )
                    uow.observation_sources.add(source)
                else:
                    source.source_type = source_type
                    source.name = name
                    source.status = status
                    source.trust_level = trust_level
                    source.time_trust = time_trust
                    source.config = config or source.config
                    source.privacy_scope = privacy_scope or source.privacy_scope
                uow.observation_sources.flush()
                uow.commit()
                return _source_record(source)

        return await asyncio.to_thread(execute)

    def _get(self, observation_id: str) -> ObservationRecord:
        with self._unit_of_work_factory() as uow:
            assert uow.observations is not None
            observation = uow.observations.get(observation_id)
            if observation is None:
                raise ObservationError(
                    code="OBSERVATION_NOT_FOUND",
                    message="The observation does not exist.",
                    status_code=404,
                )
            return _observation_record(observation)

    def _record(self, request: ObservationInput) -> ObservationResult:
        try:
            _canonical(request.raw_value)
        except (TypeError, ValueError) as exc:
            raise ObservationError(
                code="OBSERVATION_RAW_VALUE_INVALID",
                message="The raw observation value must be JSON-compatible.",
            ) from exc

        received_at = _utc(request.received_at, "received_at")
        observed_at = (
            _utc(request.observed_at, "observed_at") if request.observed_at is not None else None
        )

        with self._unit_of_work_factory() as uow:
            assert uow.devices is not None
            assert uow.entities is not None
            assert uow.environments is not None
            assert uow.observation_attributes is not None
            assert uow.observation_consents is not None
            assert uow.observation_sources is not None
            assert uow.observations is not None
            assert uow.space_assignments is not None
            assert uow.spaces is not None

            source = self._source(uow, request)
            if source.status != "active":
                raise ObservationError(
                    code="OBSERVATION_SOURCE_INACTIVE",
                    message="Observations cannot be accepted from an inactive source.",
                )

            entity_id, subject_type, subject_id = self._subject(uow, request)
            definition = uow.observation_attributes.get(request.attribute)
            if definition is None:
                raise ObservationError(
                    code="OBSERVATION_ATTRIBUTE_UNKNOWN",
                    message="The attribute is not in the controlled observation vocabulary.",
                )
            policy = uow.observation_attributes.latest_policy(definition.attribute)
            if policy is not None:
                if source.source_type not in policy.allowed_source_types:
                    raise ObservationError(code="OBSERVATION_SOURCE_TYPE_NOT_ALLOWED")
                if policy.requires_consent:
                    consent_subject_type = subject_type or "entity"
                    consent_subject_id = subject_id or entity_id
                    assert consent_subject_id is not None
                    if (
                        uow.observation_consents.effective(
                            subject_type=consent_subject_type,
                            subject_id=consent_subject_id,
                            attribute=definition.attribute,
                            now=received_at,
                        )
                        is None
                    ):
                        raise ObservationError(code="OBSERVATION_CONSENT_REQUIRED")

            space_id = self._space(uow, request, entity_id, observed_at, received_at)
            if policy is not None and policy.allowed_spaces:
                allowed = policy.allowed_spaces.get("space_ids")
                if space_id is None or not isinstance(allowed, list) or space_id not in allowed:
                    raise ObservationError(code="OBSERVATION_SPACE_NOT_ALLOWED")

            normalization = normalize(
                attribute=definition.attribute,
                value_type=definition.value_type,
                raw_value=request.raw_value,
                raw_unit=request.raw_unit,
            )
            issues = list(normalization.issues)
            issues.extend(
                self._time_issues(
                    observed_at=observed_at,
                    observed_at_source=request.observed_at_source,
                    source_time_trust=source.time_trust,
                    received_at=received_at,
                    quality_policy=definition.quality_policy,
                )
            )
            issues.extend(
                self._range_issues(
                    definition.valid_range,
                    normalization.normalized_value,
                )
            )
            issues.sort(key=lambda item: (item["severity"] != "invalid", item["code"]))

            now = datetime.now(UTC)
            effective_from = observed_at or received_at
            valid_seconds = int(definition.freshness_policy.get("valid_seconds", 300))
            retention = definition.retention_policy
            retention_days = int(retention.get("retention_days", 30))
            retention_class = str(retention.get("class", "standard_30d"))
            quality_status = _quality_status(issues)
            if quality_status == "invalid":
                retention_days = 7
                retention_class = "invalid_7d"

            payload_parts = [
                source.id,
                entity_id,
                subject_type,
                subject_id,
                space_id,
                definition.attribute,
                request.raw_value,
                request.raw_unit,
                observed_at.isoformat() if observed_at is not None else None,
                request.correlation_id,
                request.external_id,
            ]
            payload_hash = _hash(payload_parts)
            dedupe_key = self._dedupe_key(
                request=request,
                source_id=source.id,
                entity_id=entity_id,
                subject_type=subject_type,
                subject_id=subject_id,
                space_id=space_id,
                received_at=received_at,
                payload_hash=payload_hash,
            )

            stored_raw_value = request.raw_value
            if policy is not None and not policy.raw_storage_allowed:
                stored_raw_value = {"redacted": True}
                issues.append(_issue("raw_value_redacted", "warning", policy_id=policy.id))
                quality_status = _quality_status(issues)

            observed_at_source = request.observed_at_source
            if observed_at is None and observed_at_source is None:
                observed_at_source = (
                    source.time_trust
                    if source.time_trust in {"poll_clock", "unknown"}
                    else "unknown"
                )

            observation = Observation(
                source_id=source.id,
                source_type=source.source_type,
                entity_id=entity_id,
                subject_type=subject_type,
                subject_id=subject_id,
                space_id=space_id,
                attribute=definition.attribute,
                raw_value=stored_raw_value,
                raw_unit=request.raw_unit,
                normalized_value=normalization.normalized_value,
                normalized_unit=normalization.normalized_unit,
                value_type=definition.value_type,
                observed_at=observed_at,
                observed_at_source=observed_at_source,
                observed_at_uncertainty_ms=request.observed_at_uncertainty_ms,
                received_at=received_at,
                processed_at=now,
                quality_status=quality_status,
                quality_issues=issues,
                valid_from=effective_from,
                valid_until=effective_from + timedelta(seconds=valid_seconds),
                freshness_policy=(
                    f"{definition.attribute}:valid_seconds={valid_seconds}:version=1.0.0"
                ),
                freshness_evaluated_at=now,
                correlation_id=request.correlation_id,
                external_id=request.external_id,
                dedupe_key=dedupe_key,
                payload_hash=payload_hash,
                normalization_rule_version=definition.normalization_rule_version
                if normalization.normalized_value is not None or not normalization.issues
                else None,
                retention_class=retention_class,
                retention_until=received_at + timedelta(days=retention_days),
            )
            observation, duplicate = uow.observations.append(observation)
            uow.commit()
            return ObservationResult(
                data=_observation_record(observation),
                duplicate=duplicate,
            )

    def _source(
        self,
        uow: SqlAlchemyUnitOfWork,
        request: ObservationInput,
    ) -> ObservationSource:
        assert uow.devices is not None
        assert uow.observation_sources is not None
        if request.adapter_id is not None:
            source = uow.observation_sources.get_by_adapter(request.adapter_id)
            if source is None:
                raise ObservationError(
                    code="OBSERVATION_SOURCE_NOT_FOUND",
                    message="No observation source is registered for the adapter.",
                    status_code=404,
                )
            return source
        source_id = request.source_id
        if source_id is None and request.device_id is not None:
            device = uow.devices.get_by_id(request.device_id)
            if device is not None:
                source = uow.observation_sources.get_by_adapter(device.adapter_id)
                if source is not None:
                    return source
        if source_id is None:
            raise ObservationError(
                code="OBSERVATION_SOURCE_MISSING",
                message="An observation requires a registered source.",
            )
        source = uow.observation_sources.get(source_id)
        if source is None:
            raise ObservationError(
                code="OBSERVATION_SOURCE_NOT_FOUND",
                message="The observation source does not exist.",
                status_code=404,
            )
        return source

    def _subject(
        self,
        uow: SqlAlchemyUnitOfWork,
        request: ObservationInput,
    ) -> tuple[str | None, str | None, str | None]:
        assert uow.devices is not None
        assert uow.entities is not None
        assert uow.environments is not None
        if request.entity_id is not None:
            if uow.entities.get(request.entity_id) is None:
                raise ObservationError(
                    code="OBSERVATION_SUBJECT_NOT_FOUND",
                    message="The observed entity does not exist.",
                    status_code=404,
                )
            return request.entity_id, None, None
        if request.subject_type is not None and request.subject_id is not None:
            return None, request.subject_type, request.subject_id

        device = None
        if request.adapter_id is not None:
            if request.device_external_id is None:
                raise ObservationError(
                    code="OBSERVATION_DEVICE_IDENTITY_MISSING",
                    message="Adapter observations require device_external_id for Registry mapping.",
                )
            device = uow.devices.get_by_external_id(
                request.adapter_id,
                request.device_external_id,
            )
        elif request.device_id is not None:
            device = uow.devices.get_by_id(request.device_id)
        if device is None:
            raise ObservationError(
                code="OBSERVATION_SUBJECT_NOT_FOUND",
                message="The device subject could not be resolved through Device Registry.",
                status_code=404,
            )
        environment = uow.environments.ensure_default()
        entity = uow.entities.ensure_device_entity(device, environment)
        return entity.id, None, None

    def _space(
        self,
        uow: SqlAlchemyUnitOfWork,
        request: ObservationInput,
        entity_id: str | None,
        observed_at: datetime | None,
        received_at: datetime,
    ) -> str | None:
        assert uow.space_assignments is not None
        assert uow.spaces is not None
        if request.space_id is not None:
            space = uow.spaces.get(request.space_id)
            if space is None:
                raise ObservationError(
                    code="OBSERVATION_SPACE_NOT_FOUND",
                    message="The observation space does not exist.",
                    status_code=404,
                )
            if space.status != "active":
                raise ObservationError(code="OBSERVATION_SPACE_INACTIVE")
            return space.id
        if entity_id is None:
            return None
        effective_at = observed_at or received_at
        assignments = uow.space_assignments.list_for_entity(entity_id)
        for assignment in assignments:
            if assignment.valid_from <= effective_at and (
                assignment.valid_until is None or assignment.valid_until > effective_at
            ):
                return assignment.space_id
        return None

    def _time_issues(
        self,
        *,
        observed_at: datetime | None,
        observed_at_source: str | None,
        source_time_trust: str,
        received_at: datetime,
        quality_policy: dict[str, Any],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        if observed_at is None:
            issues.append(
                _issue(
                    "unreliable_observation_time",
                    "warning",
                    source_time_trust=source_time_trust,
                    received_at=received_at.isoformat(),
                )
            )
            if observed_at_source in _RELIABLE_TIME_SOURCES:
                issues.append(
                    _issue("inconsistent_time_source", "invalid", expected_time=observed_at_source)
                )
            return issues
        if observed_at_source is None:
            issues.append(_issue("missing_time_source", "invalid"))
        elif observed_at_source == "poll_clock":
            issues.append(_issue("inconsistent_time_source", "warning", source=observed_at_source))

        delay_seconds = (received_at - observed_at).total_seconds()
        delay_threshold = int(quality_policy.get("delay_warning_seconds", 300))
        if delay_seconds > delay_threshold:
            issues.append(
                _issue(
                    "delayed_observation",
                    "warning",
                    observed_delay_seconds=round(delay_seconds),
                    threshold_seconds=delay_threshold,
                )
            )
        future_threshold = int(quality_policy.get("future_warning_seconds", 300))
        if -delay_seconds > future_threshold:
            issues.append(
                _issue(
                    "future_observation_time",
                    "warning",
                    future_seconds=round(-delay_seconds),
                    threshold_seconds=future_threshold,
                )
            )
        return issues

    def _range_issues(
        self,
        valid_range: dict[str, Any],
        normalized_value: Any,
    ) -> list[dict[str, Any]]:
        if normalized_value is None or not valid_range:
            return []
        if "values" in valid_range:
            allowed = valid_range["values"]
            if normalized_value not in allowed and None not in allowed:
                return [
                    _issue(
                        "value_out_of_range",
                        "invalid",
                        allowed_values=allowed,
                        actual_value=normalized_value,
                    )
                ]
            return []
        minimum = valid_range.get("min")
        maximum = valid_range.get("max")
        if minimum is not None and normalized_value < minimum:
            return [
                _issue(
                    "value_out_of_range",
                    "invalid",
                    minimum=minimum,
                    maximum=maximum,
                    actual_value=normalized_value,
                )
            ]
        if maximum is not None and normalized_value > maximum:
            return [
                _issue(
                    "value_out_of_range",
                    "invalid",
                    minimum=minimum,
                    maximum=maximum,
                    actual_value=normalized_value,
                )
            ]
        return []

    def _dedupe_key(
        self,
        *,
        request: ObservationInput,
        source_id: str,
        entity_id: str | None,
        subject_type: str | None,
        subject_id: str | None,
        space_id: str | None,
        received_at: datetime,
        payload_hash: str,
    ) -> str:
        if request.external_id:
            return _hash([source_id, request.external_id, request.attribute])
        reliable_time = (
            request.observed_at is not None and request.observed_at_source in _RELIABLE_TIME_SOURCES
        )
        if reliable_time:
            observed_at = _utc(request.observed_at, "observed_at")  # type: ignore[arg-type]
            return _hash(
                [
                    source_id,
                    entity_id,
                    subject_type,
                    subject_id,
                    space_id,
                    request.attribute,
                    observed_at.isoformat(),
                    request.raw_value,
                    request.raw_unit,
                ]
            )
        poll_window = request.poll_window or request.correlation_id
        if poll_window is None:
            poll_window = received_at.isoformat(timespec="minutes")
        return _hash(
            [
                source_id,
                entity_id,
                subject_type,
                subject_id,
                request.attribute,
                payload_hash,
                poll_window,
            ]
        )


__all__ = ["ObservationService"]
