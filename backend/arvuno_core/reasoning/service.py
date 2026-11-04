from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import AwareDatetime

from arvuno_core.persistence.models import (
    EstimationTarget,
    Event,
    EvidenceBundle,
    EvidenceItem,
    Hypothesis,
    HypothesisEvidence,
    Memory,
    Observation,
    ReasoningSession,
    StateEstimate,
    Task,
)
from arvuno_core.persistence.reasoning import utc
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.reasoning.errors import (
    ReasoningEnvironmentNotFoundError,
    ReasoningEvidenceNotFoundError,
    ReasoningHypothesisNotFoundError,
    ReasoningSessionNotFoundError,
    ReasoningSourceNotFoundError,
)
from arvuno_core.reasoning.models import (
    ReasoningBundleView,
    ReasoningCoverage,
    ReasoningDiagnosis,
    ReasoningEvidenceLinkView,
    ReasoningEvidenceView,
    ReasoningHypothesisView,
    ReasoningSessionView,
)

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]

THRESHOLDS = {
    "temperature": (30.0, 1.5),
    "humidity": (70.0, 5.0),
    "co2": (1000.0, 100.0),
}


class ReasoningService:
    """Builds auditable evidence bundles and candidate environment diagnoses."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        environment_name: str = "home",
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._environment_name = environment_name

    async def diagnose(self, request: Any) -> ReasoningSessionView:
        return await asyncio.to_thread(self._diagnose, request)

    async def list_sessions(self, **filters: object) -> tuple[list[ReasoningSessionView], int]:
        def execute() -> tuple[list[ReasoningSessionView], int]:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.reasoning is not None
                rows, total = unit_of_work.reasoning.list_sessions(**filters)
                return [self._session_view(row, include_children=False) for row in rows], total

        return await asyncio.to_thread(execute)

    async def get_session(self, session_id: str) -> ReasoningSessionView:
        def execute() -> ReasoningSessionView:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.reasoning is not None
                row = unit_of_work.reasoning.get_session(session_id)
                if row is None:
                    raise ReasoningSessionNotFoundError()
                return self._session_view(row)

        return await asyncio.to_thread(execute)

    async def delete_session(self, session_id: str) -> dict[str, str]:
        def execute() -> dict[str, str]:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.reasoning is not None
                row = unit_of_work.reasoning.get_session(session_id)
                if row is None:
                    raise ReasoningSessionNotFoundError()
                unit_of_work.reasoning.delete_session(row)
                unit_of_work.commit()
                return {"id": session_id, "deleted": "true"}

        return await asyncio.to_thread(execute)

    async def evidence(
        self,
        session_id: str,
        *,
        classification: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ReasoningEvidenceView], int]:
        def execute() -> tuple[list[ReasoningEvidenceView], int]:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.reasoning is not None
                session = unit_of_work.reasoning.get_session(session_id)
                if session is None:
                    raise ReasoningSessionNotFoundError()
                bundle = unit_of_work.reasoning.bundle(session_id)
                if bundle is None:
                    raise ReasoningSessionNotFoundError()
                rows, total = unit_of_work.reasoning.list_evidence(
                    bundle.id,
                    classification=classification,
                    page=page,
                    page_size=page_size,
                )
                return [self._evidence_view(row) for row in rows], total

        return await asyncio.to_thread(execute)

    async def hypothesis(self, hypothesis_id: str) -> ReasoningHypothesisView:
        def execute() -> ReasoningHypothesisView:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.reasoning is not None
                row = unit_of_work.reasoning.get_hypothesis(hypothesis_id)
                if row is None:
                    raise ReasoningHypothesisNotFoundError()
                return self._hypothesis_view(row)

        return await asyncio.to_thread(execute)

    async def hypotheses(self, **filters: object) -> tuple[list[ReasoningHypothesisView], int]:
        def execute() -> tuple[list[ReasoningHypothesisView], int]:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.reasoning is not None
                rows, total = unit_of_work.reasoning.list_hypotheses(**filters)
                return [self._hypothesis_view(row) for row in rows], total

        return await asyncio.to_thread(execute)

    async def source(self, evidence_id: str) -> dict[str, Any]:
        def execute() -> dict[str, Any]:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.reasoning is not None
                item = unit_of_work.reasoning.get_evidence(evidence_id)
                if item is None:
                    raise ReasoningEvidenceNotFoundError()
                resolved = unit_of_work.reasoning.source_record(
                    item.source_type, item.source_record_id
                )
                if resolved is None:
                    raise ReasoningSourceNotFoundError()
                _, row = resolved
                return self._source_snapshot(item.source_type, row)

        return await asyncio.to_thread(execute)

    def _diagnose(self, request: Any) -> ReasoningSessionView:
        now = _now(request.now)
        end_time = request.end_time or now
        start_time = request.start_time or end_time - timedelta(
            seconds=max(request.lookback_seconds, 60)
        )
        if start_time > end_time:
            raise ValueError("start_time must not be after end_time")
        requested_attribute = request.attribute or _attribute_from_question(request.question)
        with self._unit_of_work_factory() as unit_of_work:
            assert unit_of_work.reasoning is not None
            assert unit_of_work.state_estimates is not None
            assert unit_of_work.memories is not None
            assert unit_of_work.history is not None
            repository = unit_of_work.reasoning
            environment = repository.environment(request.environment_id, self._environment_name)
            if environment is None:
                raise ReasoningEnvironmentNotFoundError()
            space_id = request.space_id
            if space_id is None and request.space_name is not None:
                space = unit_of_work.history.find_space_by_name(request.space_name)
                space_id = space.id if space is not None else None

            session = repository.add_session(
                ReasoningSession(
                    environment_id=environment.id,
                    question=request.question,
                    trigger=request.trigger,
                    actor_type=request.actor_type,
                    actor_id=request.actor_id,
                    started_at=now,
                    scope={
                        "space_id": space_id,
                        "entity_id": request.entity_id,
                        "attribute": requested_attribute,
                        "start_time": start_time,
                        "end_time": end_time,
                    },
                )
            )
            bundle = repository.add_bundle(
                EvidenceBundle(
                    session_id=session.id,
                    environment_id=environment.id,
                    name="environment-history-and-memory",
                    selection_basis={
                        "requested_scope": session.scope,
                        "reason": "Minimum records relevant to the question and scope",
                    },
                )
            )

            current_states = unit_of_work.state_estimates.current_rows(
                environment_id=environment.id,
                space_id=None,
                entity_id=request.entity_id,
                attribute=requested_attribute,
            )
            if space_id is not None:
                assigned_entity_ids = {
                    assignment.entity_id
                    for assignment in unit_of_work.history.entity_assignments(
                        space_id=space_id,
                        at_time=end_time,
                    )
                }
                current_states = [
                    row
                    for row in current_states
                    if row[1].space_id == space_id or row[1].entity_id in assigned_entity_ids
                ]
            observations = repository.observations(
                environment_id=environment.id,
                start_time=start_time,
                end_time=end_time,
                space_id=space_id,
                entity_id=request.entity_id,
                attribute=requested_attribute,
                limit=1000,
            )
            correlations = {
                observation.correlation_id
                for observation in observations
                if observation.correlation_id is not None
            }
            events = [
                event
                for event in unit_of_work.history.events(
                    start_time=start_time - timedelta(minutes=30),
                    end_time=end_time,
                    limit=500,
                )
                if event.correlation_id in correlations
            ]
            tasks = [
                task
                for task in unit_of_work.history.tasks(
                    start_time=start_time - timedelta(minutes=30),
                    end_time=end_time,
                    limit=200,
                )
                if task.correlation_id in correlations
            ]
            memories, _ = unit_of_work.memories.list_memories(
                environment_id=environment.id,
                space_id=space_id,
                entity_id=request.entity_id,
                status="current",
                page_size=100,
            )

            evidence_by_key: dict[tuple[str, str], EvidenceItem] = {}
            for _, target, estimate in current_states:
                item = self._state_evidence(bundle.id, environment.id, target, estimate, request)
                evidence_by_key[("state_estimate", estimate.id)] = repository.add_evidence(item)
            for observation in observations:
                item = self._observation_evidence(bundle.id, environment.id, observation, request)
                evidence_by_key[("observation", observation.observation_id)] = (
                    repository.add_evidence(item)
                )
            for event in events:
                item = self._event_evidence(bundle.id, environment.id, event)
                evidence_by_key[("event", event.id)] = repository.add_evidence(item)
            for task in tasks:
                item = self._task_evidence(bundle.id, environment.id, task)
                evidence_by_key[("task", task.id)] = repository.add_evidence(item)
            for memory in memories:
                item = self._memory_evidence(bundle.id, environment.id, memory)
                evidence_by_key[("memory", memory.id)] = repository.add_evidence(item)

            diagnosis = ReasoningDiagnosis()
            evidence_rows = list(evidence_by_key.values())
            self._add_fact_summary(evidence_rows, diagnosis)
            self._add_threshold_findings(
                session.id,
                current_states,
                evidence_by_key,
                diagnosis,
                repository,
            )
            self._add_trend_and_cause_hypotheses(
                session.id,
                observations,
                events,
                evidence_by_key,
                diagnosis,
                repository,
                requested_attribute,
            )
            self._add_data_quality_hypotheses(
                session.id,
                observations,
                current_states,
                evidence_by_key,
                diagnosis,
                repository,
            )
            self._add_unknown(
                session.id,
                environment.id,
                requested_attribute,
                observations,
                current_states,
                evidence_by_key,
                diagnosis,
                repository,
            )

            bundle.coverage = self._coverage(evidence_rows).model_dump(mode="json")
            session.diagnosis = diagnosis.model_dump(mode="json")
            session.analyzer_versions = {
                "deterministic_environment_rules": "1.0.0",
                "ai_candidate_generator": "not_configured",
            }
            session.status = "completed"
            session.completed_at = now
            unit_of_work.commit()
        return self.get_session_sync(session.id)

    def get_session_sync(self, session_id: str) -> ReasoningSessionView:
        with self._unit_of_work_factory() as unit_of_work:
            assert unit_of_work.reasoning is not None
            row = unit_of_work.reasoning.get_session(session_id)
            if row is None:
                raise ReasoningSessionNotFoundError()
            return self._session_view(row)

    def _state_evidence(
        self,
        bundle_id: str,
        environment_id: str,
        target: EstimationTarget,
        estimate: StateEstimate,
        request: Any,
    ) -> EvidenceItem:
        classification = {
            "observed": "observed",
            "derived": "derived",
            "inferred": "inferred_candidate",
        }.get(estimate.status, "unknown")
        subject = request.entity_id or target.entity_id or target.space_id or environment_id
        return EvidenceItem(
            bundle_id=bundle_id,
            source_type="state_estimate",
            source_record_id=estimate.id,
            classification=classification,
            statement=(
                f"World model reports {target.attribute}={estimate.value} {estimate.unit or ''} "
                f"for {target.target_type} {subject} with status {estimate.status}."
            ).strip(),
            snapshot={
                "status": estimate.status,
                "value": estimate.value,
                "unit": estimate.unit,
                "confidence": estimate.confidence,
                "rule_id": estimate.rule_id,
                "rule_version": estimate.rule_version,
                "target_type": target.target_type,
                "attribute": target.attribute,
            },
            scope={
                "environment_id": environment_id,
                "space_id": target.space_id,
                "entity_id": target.entity_id,
                "attribute": target.attribute,
            },
            source_time=estimate.generated_at,
            received_time=estimate.created_at,
            quality_status="valid" if estimate.status in {"observed", "derived"} else "suspect",
            quality_issues=estimate.conflict_details or [],
            trust_level=(
                0.9
                if estimate.status == "observed"
                else 0.75
                if estimate.status == "derived"
                else 0.4
            ),
        )

    def _observation_evidence(
        self,
        bundle_id: str,
        environment_id: str,
        observation: Observation,
        request: Any,
    ) -> EvidenceItem:
        quality = "valid"
        if observation.quality_status == "invalid":
            quality = "invalid"
        elif observation.quality_status != "valid" or observation.observed_at is None:
            quality = "suspect"
        classification = "unknown" if quality == "invalid" else "observed"
        statement = (
            f"Sensor observed {observation.attribute}="
            f"{observation.normalized_value}{observation.normalized_unit or ''} "
            f"at {utc(observation.observed_at) or 'an unknown collection time'}."
            if quality != "invalid"
            else f"Sensor reported an invalid {observation.attribute} value; "
            f"raw value={observation.raw_value}."
        ).strip()
        return EvidenceItem(
            bundle_id=bundle_id,
            source_type="observation",
            source_record_id=observation.observation_id,
            classification=classification,
            statement=statement,
            snapshot={
                "attribute": observation.attribute,
                "value": observation.normalized_value,
                "unit": observation.normalized_unit,
                "observed_at": utc(observation.observed_at),
                "received_at": utc(observation.received_at),
                "source_id": observation.source_id,
                "correlation_id": observation.correlation_id,
            },
            scope={
                "environment_id": environment_id,
                "space_id": observation.space_id,
                "entity_id": observation.entity_id,
                "attribute": observation.attribute,
                "requested_entity_id": request.entity_id,
            },
            source_time=observation.observed_at,
            received_time=observation.received_at,
            quality_status=quality,
            quality_issues=observation.quality_issues,
            trust_level=0.95 if quality == "valid" else 0.5 if quality == "suspect" else 0.3,
        )

    def _event_evidence(
        self,
        bundle_id: str,
        environment_id: str,
        event: Event,
    ) -> EvidenceItem:
        return EvidenceItem(
            bundle_id=bundle_id,
            source_type="event",
            source_record_id=event.id,
            classification="observed",
            statement=f"Event {event.event_type} occurred with correlation {event.correlation_id}.",
            snapshot={
                "event_type": event.event_type,
                "source": event.source,
                "subject_type": event.subject_type,
                "subject_id": event.subject_id,
                "payload": event.payload,
                "occurred_at": utc(event.occurred_at),
            },
            scope={"environment_id": environment_id},
            source_time=event.occurred_at,
            received_time=event.created_at,
            quality_status="valid",
            quality_issues=[],
            trust_level=0.9,
        )

    def _task_evidence(
        self,
        bundle_id: str,
        environment_id: str,
        task: Task,
    ) -> EvidenceItem:
        return EvidenceItem(
            bundle_id=bundle_id,
            source_type="task",
            source_record_id=task.id,
            classification="observed",
            statement=f"Task {task.task_type} has status {task.status}.",
            snapshot={
                "task_type": task.task_type,
                "title": task.title,
                "status": task.status,
                "result": task.result,
                "error": task.error,
                "correlation_id": task.correlation_id,
            },
            scope={"environment_id": environment_id},
            source_time=task.created_at,
            received_time=task.created_at,
            quality_status="valid",
            quality_issues=[],
            trust_level=0.85,
        )

    def _memory_evidence(
        self,
        bundle_id: str,
        environment_id: str,
        memory: Memory,
    ) -> EvidenceItem:
        verified = memory.verification_status == "verified" and memory.user_confirmed
        return EvidenceItem(
            bundle_id=bundle_id,
            source_type="memory",
            source_record_id=memory.id,
            classification="derived" if verified else "inferred_candidate",
            statement=f"Memory states: {memory.summary or memory.content}",
            snapshot={
                "memory_type": memory.memory_type,
                "title": memory.title,
                "summary": memory.summary,
                "verification_status": memory.verification_status,
                "user_confirmed": memory.user_confirmed,
                "source_type": memory.source_type,
                "source_id": memory.source_id,
            },
            scope={
                "environment_id": memory.environment_id or environment_id,
                "space_id": memory.space_id,
                "entity_id": memory.entity_id,
                "attribute": memory.predicate,
            },
            source_time=memory.valid_from,
            received_time=memory.created_at,
            quality_status="valid" if verified else "suspect",
            quality_issues=[] if verified else [{"code": "unverified_memory"}],
            trust_level=0.9 if verified else 0.4,
        )

    def _add_threshold_findings(
        self,
        session_id: str,
        current_states: list[tuple[Any, EstimationTarget, StateEstimate]],
        evidence_by_key: dict[tuple[str, str], EvidenceItem],
        diagnosis: ReasoningDiagnosis,
        repository: Any,
    ) -> None:
        for _, target, estimate in current_states:
            rule = THRESHOLDS.get(target.attribute)
            if rule is None or not isinstance(estimate.value, (int, float)):
                continue
            threshold = rule[0]
            if estimate.value < threshold:
                continue
            statement = (
                f"{target.target_type} {target.entity_id or target.space_id} has high "
                f"{target.attribute}: {estimate.value}{estimate.unit or ''}, at or above "
                f"{threshold}{estimate.unit or ''}."
            )
            evidence = evidence_by_key[("state_estimate", estimate.id)]
            hypothesis = repository.add_hypothesis(
                Hypothesis(
                    session_id=session_id,
                    environment_id=evidence.scope["environment_id"],
                    statement=statement,
                    hypothesis_type="deterministic_rule",
                    origin_type="rule",
                    status="supported",
                    confidence_level="high",
                    causal_claim=False,
                    explanation=(
                        "The conclusion follows from a deterministic threshold rule applied "
                        "to the current world-model estimate."
                    ),
                    limitations=["This describes a condition, not its cause."],
                    rule_id=f"{target.attribute}_threshold_v1",
                    rule_version="1.0.0",
                )
            )
            repository.add_hypothesis_evidence(
                HypothesisEvidence(
                    hypothesis_id=hypothesis.id,
                    evidence_id=evidence.id,
                    relationship="supports",
                    weight=evidence.trust_level,
                    rationale="The estimate is the direct rule input.",
                )
            )
            diagnosis.deterministic_findings.append(statement)

    def _add_trend_and_cause_hypotheses(
        self,
        session_id: str,
        observations: list[Observation],
        events: list[Event],
        evidence_by_key: dict[tuple[str, str], EvidenceItem],
        diagnosis: ReasoningDiagnosis,
        repository: Any,
        requested_attribute: str | None,
    ) -> None:
        attributes = [requested_attribute] if requested_attribute else list(THRESHOLDS)
        for attribute in attributes:
            rows = [
                observation
                for observation in observations
                if observation.attribute == attribute
                and observation.quality_status == "valid"
                and observation.observed_at is not None
                and isinstance(observation.normalized_value, (int, float))
            ]
            rows.sort(key=lambda item: utc(item.observed_at) or item.received_at)
            if len(rows) < 2:
                continue
            first, last = rows[0], rows[-1]
            change = float(last.normalized_value) - float(first.normalized_value)
            if abs(change) < THRESHOLDS[attribute][1]:
                continue
            direction = "increased" if change > 0 else "decreased"
            statement = (
                f"{attribute} {direction} from {first.normalized_value} to "
                f"{last.normalized_value}{last.normalized_unit or ''} in the queried period."
            )
            first_evidence = evidence_by_key[("observation", first.observation_id)]
            last_evidence = evidence_by_key[("observation", last.observation_id)]
            hypothesis = repository.add_hypothesis(
                Hypothesis(
                    session_id=session_id,
                    environment_id=last_evidence.scope["environment_id"],
                    statement=statement,
                    hypothesis_type="deterministic_rule",
                    origin_type="rule",
                    status="supported",
                    confidence_level="high",
                    causal_claim=False,
                    explanation="The change is computed from ordered valid observations.",
                    limitations=[
                        "This is a measured temporal change, not an explanation of why it happened."
                    ],
                    rule_id=f"{attribute}_period_change_v1",
                    rule_version="1.0.0",
                )
            )
            for evidence in (first_evidence, last_evidence):
                repository.add_hypothesis_evidence(
                    HypothesisEvidence(
                        hypothesis_id=hypothesis.id,
                        evidence_id=evidence.id,
                        relationship="supports",
                        weight=evidence.trust_level,
                        rationale="Endpoint of the measured period.",
                    )
                )
            diagnosis.deterministic_findings.append(statement)

            first_time = utc(first.observed_at)
            last_time = utc(last.observed_at)
            if first_time is None or last_time is None:
                continue
            matching_events = [
                event
                for event in events
                if utc(event.occurred_at) is not None
                and first_time <= utc(event.occurred_at) <= last_time
            ][:3]
            for event in matching_events:
                evidence = evidence_by_key[("event", event.id)]
                payload = event.payload if isinstance(event.payload, dict) else {}
                verified = (
                    payload.get("verified_cause") is True
                    or payload.get("verification_status") == "verified"
                )
                if verified:
                    cause_statement = (
                        f"Verified event {event.event_type} caused the observed {attribute} change."
                    )
                    hypothesis_type = "verified_cause"
                    status = "supported"
                    confidence = "high"
                    explanation = "The event record explicitly carries verified-cause metadata."
                    limitations: list[str] = []
                    diagnosis.verified_causes.append(cause_statement)
                else:
                    cause_statement = (
                        f"Event {event.event_type} occurred before the latest {attribute} "
                        "observation and is a candidate related cause."
                    )
                    hypothesis_type = "correlation"
                    status = "plausible"
                    confidence = "low"
                    explanation = "The event and measurements are temporally related."
                    limitations = [
                        "Temporal adjacency alone does not establish causation.",
                        "No controlled counterfactual or verified mechanism is available.",
                    ]
                    diagnosis.candidate_causes.append(cause_statement)
                    diagnosis.causal_limitations.append(
                        f"The relation between {event.event_type} and {attribute} remains "
                        "correlational unless independently verified."
                    )
                cause = repository.add_hypothesis(
                    Hypothesis(
                        session_id=session_id,
                        environment_id=evidence.scope["environment_id"],
                        statement=cause_statement,
                        hypothesis_type=hypothesis_type,
                        origin_type="rule",
                        status=status,
                        confidence_level=confidence,
                        causal_claim=verified,
                        explanation=explanation,
                        limitations=limitations,
                        rule_id=f"{attribute}_event_relation_v1",
                        rule_version="1.0.0",
                    )
                )
                for linked in (evidence, last_evidence):
                    repository.add_hypothesis_evidence(
                        HypothesisEvidence(
                            hypothesis_id=cause.id,
                            evidence_id=linked.id,
                            relationship="supports" if verified else "context",
                            weight=linked.trust_level if verified else 0.3,
                            rationale="Related event and endpoint measurement.",
                        )
                    )

    def _add_data_quality_hypotheses(
        self,
        session_id: str,
        observations: list[Observation],
        current_states: list[tuple[Any, EstimationTarget, StateEstimate]],
        evidence_by_key: dict[tuple[str, str], EvidenceItem],
        diagnosis: ReasoningDiagnosis,
        repository: Any,
    ) -> None:
        issues: list[tuple[EvidenceItem, str]] = []
        for observation in observations:
            evidence = evidence_by_key[("observation", observation.observation_id)]
            if observation.quality_status == "invalid":
                issues.append((evidence, "The observation is marked invalid."))
            if observation.observed_at is None:
                issues.append((evidence, "The observation has no collected time."))
            observed = utc(observation.observed_at)
            received = utc(observation.received_at)
            if observed is not None and received is not None:
                if received - observed > timedelta(minutes=10):
                    issues.append((evidence, "The observation arrived more than 10 minutes late."))
                if observed - received > timedelta(seconds=30):
                    issues.append((evidence, "The device clock is more than 30 seconds ahead."))
        for _, target, estimate in current_states:
            if estimate.status in {"conflict", "stale", "unavailable", "unknown"}:
                evidence = evidence_by_key[("state_estimate", estimate.id)]
                issues.append(
                    (
                        evidence,
                        f"The {target.attribute} world-model estimate is {estimate.status}.",
                    )
                )
        seen: set[str] = set()
        for evidence, issue in issues:
            if issue in seen:
                continue
            seen.add(issue)
            hypothesis = repository.add_hypothesis(
                Hypothesis(
                    session_id=session_id,
                    environment_id=evidence.scope["environment_id"],
                    statement=issue,
                    hypothesis_type="data_quality",
                    origin_type="rule",
                    status="supported",
                    confidence_level="high",
                    causal_claim=False,
                    explanation="A deterministic data-quality rule found a traceable issue.",
                    limitations=["The diagnosis does not modify the original record."],
                    rule_id="reasoning_data_quality_v1",
                    rule_version="1.0.0",
                )
            )
            repository.add_hypothesis_evidence(
                HypothesisEvidence(
                    hypothesis_id=hypothesis.id,
                    evidence_id=evidence.id,
                    relationship="contradicts",
                    weight=evidence.trust_level,
                    rationale="The source record exposes the quality issue.",
                )
            )
            diagnosis.data_quality_issues.append(issue)

    def _add_unknown(
        self,
        session_id: str,
        environment_id: str,
        requested_attribute: str | None,
        observations: list[Observation],
        current_states: list[tuple[Any, EstimationTarget, StateEstimate]],
        evidence_by_key: dict[tuple[str, str], EvidenceItem],
        diagnosis: ReasoningDiagnosis,
        repository: Any,
    ) -> None:
        unknowns: list[str] = []
        if requested_attribute and not observations and not current_states:
            unknowns.append(
                f"No retained observation or world-model estimate for {requested_attribute}."
            )
        if not evidence_by_key:
            unknowns.append("No relevant source record was available in the queried scope.")
        if unknowns:
            evidence = next(iter(evidence_by_key.values())) if evidence_by_key else None
            hypothesis = repository.add_hypothesis(
                Hypothesis(
                    session_id=session_id,
                    environment_id=environment_id,
                    statement=unknowns[0],
                    hypothesis_type="unknown",
                    origin_type="rule",
                    status="unsupported",
                    confidence_level="unknown",
                    causal_claim=False,
                    explanation="The requested scope has insufficient source evidence.",
                    limitations=["Collecting an observation is required before reasoning further."],
                    unknowns=unknowns,
                    rule_id="reasoning_missing_evidence_v1",
                    rule_version="1.0.0",
                )
            )
            if evidence is not None:
                repository.add_hypothesis_evidence(
                    HypothesisEvidence(
                        hypothesis_id=hypothesis.id,
                        evidence_id=evidence.id,
                        relationship="context",
                        weight=0.2,
                        rationale="The available source did not answer the requested scope.",
                    )
                )
            diagnosis.unknowns.extend(unknowns)

    @staticmethod
    def _add_fact_summary(
        evidence_rows: list[EvidenceItem],
        diagnosis: ReasoningDiagnosis,
    ) -> None:
        diagnosis.observed_facts.extend(
            item.statement for item in evidence_rows if item.classification == "observed"
        )

    @staticmethod
    def _coverage(rows: list[EvidenceItem]) -> ReasoningCoverage:
        by_source = Counter(row.source_type for row in rows)
        by_class = Counter(row.classification for row in rows)
        missing_collected = sum(
            1 for row in rows if row.source_type == "observation" and row.source_time is None
        )
        late_arrivals = 0
        future_skew = 0
        for row in rows:
            if row.source_type != "observation":
                continue
            source_time = utc(row.source_time)
            received_time = utc(row.received_time)
            if source_time is None or received_time is None:
                continue
            if received_time - source_time > timedelta(minutes=10):
                late_arrivals += 1
            if source_time - received_time > timedelta(seconds=30):
                future_skew += 1
        return ReasoningCoverage(
            evidence_count=len(rows),
            by_source=dict(by_source),
            by_classification=dict(by_class),
            invalid_count=sum(row.quality_status in {"invalid", "unavailable"} for row in rows),
            missing_collected_time=missing_collected,
            late_arrivals=late_arrivals,
            future_clock_skew=future_skew,
        )

    def _session_view(
        self,
        row: ReasoningSession,
        *,
        include_children: bool = True,
    ) -> ReasoningSessionView:
        bundle = row.evidence_bundles[0] if row.evidence_bundles else None
        return ReasoningSessionView(
            id=row.id,
            environment_id=row.environment_id,
            question=row.question,
            trigger=row.trigger,
            status=row.status,
            scope=row.scope,
            diagnosis=ReasoningDiagnosis.model_validate(row.diagnosis),
            analyzer_versions=row.analyzer_versions,
            actor_type=row.actor_type,
            actor_id=row.actor_id,
            started_at=utc(row.started_at) or row.started_at,
            completed_at=utc(row.completed_at),
            created_at=utc(row.created_at) or row.created_at,
            bundle=self._bundle_view(bundle) if bundle is not None else None,
            hypotheses=(
                [self._hypothesis_view(item) for item in row.hypotheses] if include_children else []
            ),
        )

    @staticmethod
    def _bundle_view(row: EvidenceBundle) -> ReasoningBundleView:
        return ReasoningBundleView(
            id=row.id,
            session_id=row.session_id,
            environment_id=row.environment_id,
            name=row.name,
            selection_basis=row.selection_basis,
            coverage=row.coverage,
            created_at=utc(row.created_at) or row.created_at,
        )

    def _hypothesis_view(self, row: Hypothesis) -> ReasoningHypothesisView:
        return ReasoningHypothesisView(
            id=row.id,
            session_id=row.session_id,
            environment_id=row.environment_id,
            statement=row.statement,
            hypothesis_type=row.hypothesis_type,
            origin_type=row.origin_type,
            status=row.status,
            confidence_level=row.confidence_level,
            causal_claim=row.causal_claim,
            explanation=row.explanation,
            limitations=row.limitations,
            unknowns=row.unknowns,
            rule_id=row.rule_id,
            rule_version=row.rule_version,
            superseded_by_id=row.superseded_by_id,
            created_at=utc(row.created_at) or row.created_at,
            updated_at=utc(row.updated_at) or row.updated_at,
            evidence=[self._link_view(link) for link in row.evidence_links],
        )

    @staticmethod
    def _link_view(row: HypothesisEvidence) -> ReasoningEvidenceLinkView:
        return ReasoningEvidenceLinkView(
            relationship=row.relationship,
            weight=row.weight,
            rationale=row.rationale,
            evidence=ReasoningService._evidence_view(row.evidence),
        )

    @staticmethod
    def _evidence_view(row: EvidenceItem) -> ReasoningEvidenceView:
        return ReasoningEvidenceView(
            id=row.id,
            source_type=row.source_type,
            source_record_id=row.source_record_id,
            classification=row.classification,
            statement=row.statement,
            snapshot=row.snapshot,
            scope=row.scope,
            source_time=utc(row.source_time),
            received_time=utc(row.received_time),
            quality_status=row.quality_status,
            quality_issues=row.quality_issues,
            trust_level=row.trust_level,
            source_available=row.source_available,
            created_at=utc(row.created_at) or row.created_at,
        )

    @staticmethod
    def _source_snapshot(source_type: str, row: Any) -> dict[str, Any]:
        if source_type == "observation":
            return {
                "record_type": "observation",
                "observation_id": row.observation_id,
                "attribute": row.attribute,
                "normalized_value": row.normalized_value,
                "normalized_unit": row.normalized_unit,
                "observed_at": utc(row.observed_at),
                "received_at": utc(row.received_at),
                "quality_status": row.quality_status,
            }
        if source_type == "state_estimate":
            return {
                "record_type": "state_estimate",
                "id": row.id,
                "status": row.status,
                "value": row.value,
                "unit": row.unit,
                "generated_at": utc(row.generated_at),
            }
        if source_type == "event":
            return {
                "record_type": "event",
                "id": row.id,
                "event_type": row.event_type,
                "payload": row.payload,
                "occurred_at": utc(row.occurred_at),
            }
        if source_type == "task":
            return {
                "record_type": "task",
                "id": row.id,
                "task_type": row.task_type,
                "status": row.status,
                "result": row.result,
            }
        return {
            "record_type": "memory",
            "id": row.id,
            "memory_type": row.memory_type,
            "title": row.title,
            "verification_status": row.verification_status,
        }


def _attribute_from_question(question: str) -> str | None:
    lowered = question.casefold()
    if "humidity" in lowered or "潮湿" in lowered:
        return "humidity"
    if "co2" in lowered or "二氧化碳" in lowered:
        return "co2"
    if "temperature" in lowered or "温度" in lowered:
        return "temperature"
    if "motion" in lowered or "移动" in lowered:
        return "motion"
    if "occupancy" in lowered or "占用" in lowered:
        return "occupancy"
    if "light" in lowered or "lighting" in lowered or "灯" in lowered:
        return "illumination"
    return None


def _now(value: AwareDatetime | datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    return current if current.tzinfo is not None else current.replace(tzinfo=UTC)


__all__ = ["ReasoningService"]
