from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from arvuno_core.estimation.service import StateEstimationService
from arvuno_core.observations.models import ObservationInput
from arvuno_core.observations.service import ObservationService
from arvuno_core.perception.errors import (
    PerceptionEnvironmentNotFoundError,
    PerceptionRequestNotFoundError,
    PerceptionSourceMismatchError,
    PerceptionStateError,
)
from arvuno_core.perception.models import (
    ActivePerceptionRequestView,
    PerceptionObserverProtocol,
)
from arvuno_core.persistence.models import ActivePerceptionRequest, ObservationConsent
from arvuno_core.persistence.perception import stored_datetime
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.reasoning.service import ReasoningService
from arvuno_core.schemas.perception import ActivePerceptionEvaluateRequest
from arvuno_core.schemas.reasoning import ReasoningDiagnoseRequest

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]

DEFAULT_SOURCE_COSTS: dict[str, float] = {
    "adapter": 2.0,
    "user_report": 6.0,
    "derived_job": 4.0,
    "future_external": 10.0,
    "vision": 10.0,
    "robot_mobile": 8.0,
}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    converted = _utc(value)
    return converted.isoformat() if converted is not None else None


def _parse_iso(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return _utc(value)
    try:
        return _utc(datetime.fromisoformat(str(value)))
    except ValueError:
        return None


class ActivePerceptionService:
    """Decides whether a missing piece of evidence is worth an extra read-only observation."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        observation_service: ObservationService,
        state_estimation_service: StateEstimationService,
        reasoning_service: ReasoningService,
        *,
        environment_name: str = "home",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        request_id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._observation_service = observation_service
        self._state_estimation_service = state_estimation_service
        self._reasoning_service = reasoning_service
        self._environment_name = environment_name
        self._clock = clock
        self._request_id_factory = request_id_factory

    async def evaluate_gap(
        self,
        request: ActivePerceptionEvaluateRequest,
    ) -> ActivePerceptionRequestView:
        reasoning_session_id = request.reasoning_session_id
        if reasoning_session_id is None:
            diagnosis = await self._reasoning_service.diagnose(
                ReasoningDiagnoseRequest(
                    question=request.question,
                    environment_id=request.environment_id,
                    space_id=request.space_id,
                    entity_id=request.entity_id,
                    attribute=request.attribute,
                    start_time=request.start_time,
                    end_time=request.end_time,
                    now=request.now,
                )
            )
            reasoning_session_id = diagnosis.id
        request = request.model_copy(update={"reasoning_session_id": reasoning_session_id})
        return await asyncio.to_thread(self._evaluate_gap, request)

    async def list_requests(
        self,
        *,
        environment_id: str | None = None,
        status: str | None = None,
        gap_type: str | None = None,
        privacy_level: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ActivePerceptionRequestView], int]:
        def execute() -> tuple[list[ActivePerceptionRequestView], int]:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.perception is not None
                rows, total = unit_of_work.perception.list(
                    environment_id=environment_id,
                    status=status,
                    gap_type=gap_type,
                    privacy_level=privacy_level,
                    page=page,
                    page_size=page_size,
                )
                return [self._view(row) for row in rows], total

        return await asyncio.to_thread(execute)

    async def get_request(self, request_id: str) -> ActivePerceptionRequestView:
        def execute() -> ActivePerceptionRequestView:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.perception is not None
                row = unit_of_work.perception.get(request_id)
                if row is None:
                    raise PerceptionRequestNotFoundError()
                return self._view(row)

        return await asyncio.to_thread(execute)

    async def authorize(
        self,
        request_id: str,
        *,
        scope: dict[str, Any] | None = None,
        authorization_seconds: int = 3600,
    ) -> ActivePerceptionRequestView:
        now = self._clock()

        def execute() -> ActivePerceptionRequestView:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.perception is not None
                row = unit_of_work.perception.get(request_id)
                if row is None:
                    raise PerceptionRequestNotFoundError()
                if row.expires_at is not None and row.expires_at <= stored_datetime(now):
                    row.status = "expired"
                    unit_of_work.perception.mark(row)
                    unit_of_work.commit()
                    raise PerceptionStateError("The observation request has expired.")
                if row.status != "awaiting_consent":
                    raise PerceptionStateError(
                        f"Cannot authorize a request in status '{row.status}'."
                    )
                if not row.requires_user_consent:
                    raise PerceptionStateError("This observation request does not require consent.")

                assert unit_of_work.observation_attributes is not None
                assert unit_of_work.observation_consents is not None
                attribute = row.attribute
                if attribute is None:
                    raise PerceptionStateError("The observation request has no attribute.")
                policy = unit_of_work.observation_attributes.latest_policy(attribute)
                authorization_expiry = min(
                    now + timedelta(seconds=authorization_seconds),
                    row.expires_at.replace(tzinfo=UTC)
                    if row.expires_at is not None
                    else now + timedelta(seconds=authorization_seconds),
                )
                consent = ObservationConsent(
                    subject_type=row.subject_type,
                    subject_id=row.subject_id,
                    attribute=attribute,
                    policy_id=policy.id if policy is not None else None,
                    status="granted",
                    granted_at=stored_datetime(now),
                    expires_at=stored_datetime(authorization_expiry),
                    scope={
                        "active_perception_request_id": row.id,
                        "environment_id": row.environment_id,
                    },
                    evidence={"authorization": "explicit_user_action", **(scope or {})},
                )
                unit_of_work.observation_consents.add(consent)
                row.status = "proposed"
                row.authorized_at = stored_datetime(now)
                row.authorization_scope = {
                    **(scope or {}),
                    "consent_id": consent.id,
                    "expires_at": _iso(authorization_expiry),
                }
                unit_of_work.perception.mark(row)
                unit_of_work.commit()
                return self._view(row)

        return await asyncio.to_thread(execute)

    async def reject(
        self,
        request_id: str,
        *,
        reason: str | None = None,
    ) -> ActivePerceptionRequestView:
        now = self._clock()

        def execute() -> ActivePerceptionRequestView:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.perception is not None
                row = unit_of_work.perception.get(request_id)
                if row is None:
                    raise PerceptionRequestNotFoundError()
                if row.status not in ("proposed", "awaiting_consent"):
                    raise PerceptionStateError(f"Cannot reject a request in status '{row.status}'.")
                consent_id = (row.authorization_scope or {}).get("consent_id")
                if isinstance(consent_id, str):
                    consent = unit_of_work.perception.get_consent(consent_id)
                    if consent is not None and consent.status == "granted":
                        consent.status = "revoked"
                        consent.revoked_at = stored_datetime(now)
                row.status = "rejected"
                row.unavailable_reason = reason or "The user rejected the observation request."
                unit_of_work.perception.mark(row)
                unit_of_work.commit()
                return self._view(row)

        return await asyncio.to_thread(execute)

    async def execute(
        self,
        request_id: str,
        observer: PerceptionObserverProtocol | None,
        *,
        now: datetime | None = None,
    ) -> ActivePerceptionRequestView:
        current_time = _utc(now or self._clock())
        if current_time is None:
            raise PerceptionStateError("A timezone-aware execution time is required.")

        request_view: ActivePerceptionRequestView
        with self._unit_of_work_factory() as unit_of_work:
            assert unit_of_work.perception is not None
            row = unit_of_work.perception.get(request_id)
            if row is None:
                raise PerceptionRequestNotFoundError()
            if row.expires_at is not None and row.expires_at <= stored_datetime(current_time):
                row.status = "expired"
                unit_of_work.perception.mark(row)
                unit_of_work.commit()
                request_view = self._view(row)
            elif row.status != "proposed":
                request_view = self._view(row)
            else:
                consent_error = self._validate_authorization(row, current_time)
                if consent_error is not None:
                    row.status = "unavailable"
                    row.unavailable_reason = consent_error
                    unit_of_work.perception.mark(row)
                    unit_of_work.commit()
                    request_view = self._view(row)
                    raise PerceptionStateError(consent_error)
                row.status = "queued"
                unit_of_work.perception.mark(row)
                unit_of_work.commit()
                request_view = self._view(row)

        if request_view.status != "queued":
            raise PerceptionStateError(
                f"Cannot execute an observation request in status '{request_view.status}'."
            )

        if observer is None:
            await self._mark_unavailable(
                request_id,
                "No read-only observer is configured for this deployment.",
            )
            return await self.get_request(request_id)

        try:
            observation = await observer.observe(request_view)
        except Exception:
            await self._mark_unavailable(
                request_id,
                "The configured observer failed before returning a real observation.",
            )
            raise

        if observation is None:
            await self._mark_unavailable(
                request_id,
                "No read-only observer is available for the requested perception gap.",
            )
            return await self.get_request(request_id)

        try:
            self._validate_observation(request_view, observation)
            result = await self._observation_service.record(observation)
        except Exception:
            await self._mark_unavailable(
                request_id,
                "The observer result was rejected by the Observation Service.",
            )
            raise

        await self._mark_executed(request_id, result.data.observation_id)
        try:
            await self._state_estimation_service.rebuild(observation.received_at)
            follow_up = await self._rerun_reasoning(request_view, observation.received_at)
        except Exception as exc:
            await self._mark_execution_issue(
                request_id,
                "The observation was recorded, but state estimation or reasoning failed.",
            )
            raise PerceptionStateError(
                "The observation was recorded, but state estimation or reasoning failed."
            ) from exc

        def finish() -> ActivePerceptionRequestView:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.perception is not None
                row = unit_of_work.perception.get(request_id)
                if row is None:
                    raise PerceptionRequestNotFoundError()
                row.status = "fulfilled"
                row.fulfilled_by_type = "observation"
                row.fulfilled_by_id = result.data.observation_id
                row.follow_up_reasoning_session_id = follow_up.id
                row.unavailable_reason = None
                unit_of_work.perception.mark(row)
                unit_of_work.commit()
                return self._view(row)

        return await asyncio.to_thread(finish)

    async def expire_stale(self, *, now: datetime | None = None) -> int:
        current_time = now or self._clock()

        def execute() -> int:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.perception is not None
                count = unit_of_work.perception.expire_stale(now=current_time)
                unit_of_work.commit()
                return count

        return await asyncio.to_thread(execute)

    async def delete_request(self, request_id: str) -> dict[str, str]:
        now = self._clock()

        def execute() -> dict[str, str]:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.perception is not None
                row = unit_of_work.perception.get(request_id)
                if row is None:
                    raise PerceptionRequestNotFoundError()
                consent_id = (row.authorization_scope or {}).get("consent_id")
                if isinstance(consent_id, str):
                    consent = unit_of_work.perception.get_consent(consent_id)
                    if consent is not None and consent.status == "granted":
                        consent.status = "revoked"
                        consent.revoked_at = stored_datetime(now)
                unit_of_work.perception.delete(row)
                unit_of_work.commit()
                return {"id": request_id, "deleted": "true"}

        return await asyncio.to_thread(execute)

    def _evaluate_gap(
        self,
        request: ActivePerceptionEvaluateRequest,
    ) -> ActivePerceptionRequestView:
        now = _utc(request.now or self._clock())
        if now is None:
            raise PerceptionStateError("A timezone-aware evaluation time is required.")
        end_time = _utc(request.end_time) or now
        start_time = _utc(request.start_time) or end_time - timedelta(minutes=5)
        if start_time > end_time:
            raise PerceptionStateError("start_time must not be after end_time.")
        if request.space_id is None and request.entity_id is None:
            raise PerceptionStateError("A space_id or entity_id is required.")

        with self._unit_of_work_factory() as unit_of_work:
            assert unit_of_work.perception is not None
            assert unit_of_work.observation_sources is not None
            assert unit_of_work.observations is not None
            assert unit_of_work.observation_attributes is not None
            assert unit_of_work.state_estimates is not None
            repository = unit_of_work.perception
            environment = repository.environment(request.environment_id, self._environment_name)
            if environment is None:
                raise PerceptionEnvironmentNotFoundError()
            reasoning_session = repository.reasoning_session(request.reasoning_session_id or "")
            if reasoning_session is None or (
                request.environment_id is not None
                and reasoning_session.environment_id != request.environment_id
            ):
                raise PerceptionStateError("The reasoning session does not exist in this scope.")
            if request.hypothesis_id is not None:
                hypothesis = repository.hypothesis(request.hypothesis_id)
                if hypothesis is None or hypothesis.session_id != reasoning_session.id:
                    raise PerceptionStateError(
                        "The hypothesis is not part of this reasoning session."
                    )

            subject_type = "entity" if request.entity_id is not None else "space"
            subject_id = request.entity_id or request.space_id
            assert subject_id is not None
            observations, observation_count = unit_of_work.observations.query(
                entity_id=request.entity_id,
                space_id=request.space_id,
                attribute=request.attribute,
                start_time=start_time,
                end_time=end_time,
                page_size=20,
            )
            valid_count = sum(item.quality_status == "valid" for item in observations)
            current_states = unit_of_work.state_estimates.current_rows(
                environment_id=environment.id,
                space_id=request.space_id,
                entity_id=request.entity_id,
                attribute=request.attribute,
            )
            current_available = any(
                estimate.status in ("observed", "derived", "inferred")
                and (estimate.valid_until is None or estimate.valid_until > stored_datetime(now))
                for _, _, estimate in current_states
            )
            gap_type = request.gap_type
            has_gap = observation_count == 0 or valid_count == 0 or not current_available
            if gap_type in ("space_coverage", "time_coverage"):
                has_gap = observation_count == 0 or valid_count == 0

            definition = unit_of_work.observation_attributes.get(request.attribute)
            if definition is None:
                raise PerceptionStateError(
                    f"The attribute '{request.attribute}' is not in the observation vocabulary."
                )
            policy = unit_of_work.observation_attributes.latest_policy(request.attribute)
            historical_source_ids = unit_of_work.observations.source_ids_for_attribute(
                request.attribute
            )
            candidates = self._candidates(
                sources=unit_of_work.observation_sources.list_sources(),
                attribute=request.attribute,
                historical_source_ids=historical_source_ids,
                allowed_source_types=(policy.allowed_source_types if policy is not None else None),
                min_trust_level=request.min_trust_level,
                max_cost_score=request.max_cost_score,
                preferred_source_type=request.preferred_source_type,
            )

            existing = repository.active_for_gap(
                environment_id=environment.id,
                gap_type=gap_type,
                subject_type=subject_type,
                subject_id=subject_id,
                attribute=request.attribute,
            )
            if existing is not None:
                return self._view(existing)

            affordable = [item for item in candidates if item["cost"]["worthwhile"]]
            selected = affordable[0] if affordable else None
            sensitive = definition.sensitivity == "sensitive" or (
                selected is not None and selected["privacy_level"] == "sensitive"
            )
            expires_at = end_time + timedelta(seconds=request.time_limit_seconds)
            if expires_at <= now:
                expires_at = now + timedelta(seconds=request.time_limit_seconds)
            coverage = {
                "observation_count": observation_count,
                "valid_observation_count": valid_count,
                "latest_quality_status": observations[0].quality_status if observations else None,
                "current_estimate_available": current_available,
                "candidate_sources": [item["summary"] for item in candidates],
                "rejected_sources": [
                    {**item["summary"], "reason": "cost_above_limit"}
                    for item in candidates
                    if not item["cost"]["worthwhile"]
                ],
            }
            reason = (
                f"Additional {request.attribute} evidence is needed to answer: {request.question}"
            )
            unavailable_reason: str | None
            status: str
            if not has_gap:
                status = "unavailable"
                unavailable_reason = "The requested evidence is already covered."
            elif request.gap_type == "procedure":
                status = "unavailable"
                unavailable_reason = (
                    "Procedure gaps require a validated procedure, not an observation."
                )
            elif selected is None:
                status = "unavailable"
                unavailable_reason = (
                    "No active, trusted, and affordable observation source is available."
                )
            elif sensitive:
                status = "awaiting_consent"
                unavailable_reason = None
            else:
                status = "proposed"
                unavailable_reason = None

            executable_source = selected if request.gap_type != "procedure" else None
            row = ActivePerceptionRequest(
                id=self._request_id_factory(),
                environment_id=environment.id,
                reasoning_session_id=reasoning_session.id,
                hypothesis_id=request.hypothesis_id,
                question=request.question,
                gap_type=gap_type,
                subject_type=subject_type,
                subject_id=subject_id,
                space_id=request.space_id,
                entity_id=request.entity_id,
                attribute=request.attribute,
                needed_time_range={
                    "start": _iso(start_time),
                    "end": _iso(end_time),
                    "time_limit_seconds": request.time_limit_seconds,
                },
                current_coverage=coverage,
                expected_value={"attribute": request.attribute},
                would_resolve={"reduces_unknown": True, "reason": reason},
                proposed_capability=(
                    "observation_source.poll_read_only" if executable_source is not None else None
                ),
                proposed_input=(
                    {
                        "source_id": executable_source["source_id"],
                        "source_type": executable_source["source_type"],
                        "attribute": request.attribute,
                        "subject_type": subject_type,
                        "subject_id": subject_id,
                        "space_id": request.space_id,
                        "entity_id": request.entity_id,
                    }
                    if executable_source is not None
                    else {}
                ),
                privacy_level="sensitive" if sensitive else "normal",
                requires_user_consent=sensitive,
                cost_estimate=(
                    executable_source["cost"]
                    if executable_source is not None
                    else {"score": None, "worthwhile": False}
                ),
                status=status,
                unavailable_reason=unavailable_reason,
                created_at=stored_datetime(now),
                updated_at=stored_datetime(now),
                expires_at=stored_datetime(expires_at),
            )
            repository.add(row)
            unit_of_work.commit()
            return self._view(row)

    @staticmethod
    def _candidates(
        *,
        sources: list[Any],
        attribute: str,
        historical_source_ids: set[str],
        allowed_source_types: list[str] | None,
        min_trust_level: float,
        max_cost_score: float,
        preferred_source_type: str | None = None,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for source in sources:
            if source.status != "active":
                continue
            if allowed_source_types is not None and source.source_type not in allowed_source_types:
                continue
            if preferred_source_type is not None and source.source_type != preferred_source_type:
                continue
            if source.trust_level < min_trust_level:
                continue
            if source.id not in historical_source_ids and not ActivePerceptionService._supports(
                source, attribute
            ):
                continue
            cost_value = ActivePerceptionService._cost(source)
            privacy_scope = source.privacy_scope or {}
            privacy_level = "sensitive" if privacy_scope.get("sensitive") is True else "normal"
            candidates.append(
                {
                    "source_id": source.id,
                    "source_type": source.source_type,
                    "adapter_id": source.adapter_id,
                    "trust_level": float(source.trust_level),
                    "privacy_level": privacy_level,
                    "cost": {
                        "score": cost_value,
                        "basis": (
                            "source.config.perception_cost or conservative source-type default"
                        ),
                        "worthwhile": cost_value <= max_cost_score,
                    },
                    "summary": {
                        "source_id": source.id,
                        "name": source.name,
                        "source_type": source.source_type,
                        "trust_level": float(source.trust_level),
                        "cost_score": cost_value,
                        "capability_basis": (
                            "declared"
                            if ActivePerceptionService._supports(source, attribute)
                            else "historical_use"
                        ),
                    },
                }
            )
        return sorted(
            candidates,
            key=lambda item: (-item["trust_level"], item["cost"]["score"], item["source_id"]),
        )

    @staticmethod
    def _supports(source: Any, attribute: str) -> bool:
        config = source.config or {}
        declared = config.get("supported_attributes", config.get("attributes", []))
        if isinstance(declared, str):
            declared = [declared]
        if attribute in declared:
            return True
        capabilities = config.get("capabilities", [])
        if isinstance(capabilities, str):
            capabilities = [capabilities]
        for capability in capabilities:
            if isinstance(capability, str) and capability == attribute:
                return True
            if isinstance(capability, dict) and (
                capability.get("attribute") == attribute
                or attribute in capability.get("supported_attributes", [])
            ):
                return True
        return False

    @staticmethod
    def _cost(source: Any) -> float:
        config = source.config or {}
        configured = config.get("perception_cost", config.get("cost"))
        if isinstance(configured, dict):
            configured = configured.get("score")
        if isinstance(configured, int | float) and configured >= 0:
            return float(configured)
        return DEFAULT_SOURCE_COSTS.get(source.source_type, 10.0)

    @staticmethod
    def _validate_observation(
        request: ActivePerceptionRequestView,
        observation: ObservationInput,
    ) -> None:
        expected_source = request.proposed_input.get("source_id")
        if expected_source is not None and observation.source_id != expected_source:
            raise PerceptionSourceMismatchError("The observer returned a different source.")
        if observation.attribute != request.attribute:
            raise PerceptionSourceMismatchError("The observer returned a different attribute.")
        if request.entity_id is not None and observation.entity_id != request.entity_id:
            raise PerceptionSourceMismatchError("The observer returned a different entity.")
        if request.space_id is not None and observation.space_id != request.space_id:
            raise PerceptionSourceMismatchError("The observer returned a different space.")
        if request.entity_id is None and observation.subject_type != request.subject_type:
            raise PerceptionSourceMismatchError("The observer returned a different subject.")
        if request.entity_id is None and observation.subject_id != request.subject_id:
            raise PerceptionSourceMismatchError("The observer returned a different subject.")

    def _validate_authorization(
        self,
        row: ActivePerceptionRequest,
        current_time: datetime,
    ) -> str | None:
        if not row.requires_user_consent:
            return None
        scope = row.authorization_scope or {}
        consent_id = scope.get("consent_id")
        if row.authorized_at is None or not isinstance(consent_id, str):
            return "The observation request requires explicit user consent."
        with self._unit_of_work_factory() as unit_of_work:
            assert unit_of_work.perception is not None
            consent = unit_of_work.perception.get_consent(consent_id)
        if consent is None or consent.status != "granted":
            return "The observation authorization has been revoked."
        if consent.expires_at is not None and consent.expires_at <= stored_datetime(current_time):
            return "The observation authorization has expired."
        expected_scope = {
            "active_perception_request_id": row.id,
            "environment_id": row.environment_id,
        }
        if not expected_scope.items() <= (consent.scope or {}).items():
            return "The observation authorization scope does not match this request."
        return None

    async def _rerun_reasoning(
        self,
        request: ActivePerceptionRequestView,
        now: datetime,
    ) -> Any:
        start_time = _parse_iso(request.needed_time_range.get("start")) or now - timedelta(hours=1)
        end_time = _parse_iso(request.needed_time_range.get("end")) or now
        return await self._reasoning_service.diagnose(
            ReasoningDiagnoseRequest(
                question=request.question,
                environment_id=request.environment_id,
                space_id=request.space_id,
                entity_id=request.entity_id,
                attribute=request.attribute,
                start_time=min(start_time, now),
                end_time=max(end_time, now),
                now=now,
                trigger="automation",
                actor_type="system",
                actor_id="active_perception",
            )
        )

    async def _mark_unavailable(self, request_id: str, reason: str) -> None:
        def execute() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.perception is not None
                row = unit_of_work.perception.get(request_id)
                if row is None:
                    raise PerceptionRequestNotFoundError()
                if row.status in ("queued", "proposed", "awaiting_consent"):
                    row.status = "unavailable"
                    row.unavailable_reason = reason
                    unit_of_work.perception.mark(row)
                unit_of_work.commit()

        await asyncio.to_thread(execute)

    async def _mark_executed(self, request_id: str, observation_id: str) -> None:
        def execute() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.perception is not None
                row = unit_of_work.perception.get(request_id)
                if row is None:
                    raise PerceptionRequestNotFoundError()
                row.status = "executed"
                row.fulfilled_by_type = "observation"
                row.fulfilled_by_id = observation_id
                unit_of_work.perception.mark(row)
                unit_of_work.commit()

        await asyncio.to_thread(execute)

    async def _mark_execution_issue(self, request_id: str, reason: str) -> None:
        def execute() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.perception is not None
                row = unit_of_work.perception.get(request_id)
                if row is None:
                    raise PerceptionRequestNotFoundError()
                if row.status == "executed":
                    row.unavailable_reason = reason
                    unit_of_work.perception.mark(row)
                unit_of_work.commit()

        await asyncio.to_thread(execute)

    @staticmethod
    def _view(row: ActivePerceptionRequest) -> ActivePerceptionRequestView:
        view = ActivePerceptionRequestView.model_validate(row)
        for field in ("authorized_at", "created_at", "updated_at", "expires_at"):
            value = getattr(view, field)
            if value is not None:
                setattr(view, field, _utc(value))
        return view


__all__ = ["ActivePerceptionService"]
