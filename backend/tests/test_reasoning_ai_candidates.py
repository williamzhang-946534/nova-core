import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from arvuno_core.ai.models import ProviderRequest, ProviderResponse, ProviderUsage
from arvuno_core.config import Settings
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import (
    Entity,
    EntitySpaceAssignment,
    Environment,
    Observation,
    ObservationSource,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.reasoning.service import ReasoningService
from arvuno_core.schemas.reasoning import ReasoningDiagnoseRequest
from arvuno_core.spatial.service import SpatialService

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class CandidateProvider:
    def __init__(self, output_factory: Any) -> None:
        self.output_factory = output_factory
        self.requests: list[ProviderRequest] = []

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        output = self.output_factory(request)
        return ProviderResponse(
            provider="candidate-test",
            model="candidate-model",
            request_kind=request.request_kind,
            output=output,
            latency_ms=0,
            usage=ProviderUsage(prompt_tokens=1, completion_tokens=1),
            provider_log_id="candidate-log",
        )


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


def seed_observation(manager: DatabaseManager) -> tuple[str, str]:
    spatial = SpatialService(
        lambda: SqlAlchemyUnitOfWork(manager.session_factory),
        environment_name="home",
    )
    root = asyncio.run(spatial.ensure_root())
    room = asyncio.run(
        spatial.create_space(
            parent_id=root.id,
            name="AI Diagnosis Room",
            space_type="room",
        )
    )
    with manager.session_factory() as session:
        environment = session.scalars(select(Environment).limit(1)).one()
        entity = Entity(
            id="ai-diagnosis-entity",
            environment_id=environment.id,
            entity_type="sensor",
            name="AI Diagnosis Sensor",
            normalized_name="ai diagnosis sensor",
            status="active",
            semantic_tags=["sensor_temperature"],
            metadata_summary={},
        )
        session.add(entity)
        session.flush()
        session.add(
            EntitySpaceAssignment(
                entity_id=entity.id,
                space_id=room.id,
                assignment_type="fixed_installation",
                valid_from=NOW - timedelta(hours=2),
                confidence=1.0,
                source_type="user",
                source_id="ai-diagnosis-test",
                reason="reasoning candidate test",
            )
        )
        source = session.scalars(
            select(ObservationSource).where(ObservationSource.adapter_id == "mock")
        ).one()
        received_at = NOW - timedelta(minutes=5)
        session.add(
            Observation(
                observation_id="ai-diagnosis-observation",
                source_id=source.id,
                source_type=source.source_type,
                entity_id=entity.id,
                space_id=room.id,
                attribute="temperature",
                raw_value=30.0,
                raw_unit="°C",
                normalized_value=30.0,
                normalized_unit="°C",
                value_type="number",
                observed_at=received_at,
                observed_at_source="device_clock",
                observed_at_uncertainty_ms=0,
                received_at=received_at,
                processed_at=received_at,
                quality_status="valid",
                quality_issues=[],
                valid_from=received_at,
                valid_until=received_at + timedelta(minutes=5),
                freshness_policy="valid_300s",
                freshness_evaluated_at=received_at,
                correlation_id="ai-diagnosis-correlation",
                external_id=f"{source.id}:{entity.id}:ai",
                dedupe_key=hashlib.sha256(b"ai-diagnosis-observation").hexdigest(),
                payload_hash=hashlib.sha256(b"30.0").hexdigest(),
                normalization_rule_version="1.0.0",
                retention_class="standard_30d",
                retention_until=received_at + timedelta(days=30),
            )
        )
        session.commit()
    return entity.id, room.id


def first_evidence_id(request: ProviderRequest) -> str:
    payload = json.loads(request.messages[-1].content)
    return payload["evidence"][0]["evidence_id"]


def test_ai_candidates_are_persisted_as_unverified_model_hypotheses(tmp_path: Path) -> None:
    manager = DatabaseManager(settings_for(tmp_path))
    manager.initialize_database()
    try:
        entity_id, room_id = seed_observation(manager)

        def valid_output(request: ProviderRequest) -> dict[str, Any]:
            evidence_id = first_evidence_id(request)
            return {
                "candidates": [
                    {
                        "statement": "Recent heat gain may explain the elevated temperature.",
                        "explanation": (
                            "The cited estimate is high and the observation confirms it."
                        ),
                        "evidence_ids": [evidence_id],
                        "causal_claim": True,
                        "limitations": ["No mechanism or counterfactual was measured."],
                        "unknowns": ["The heat source is unknown."],
                    }
                ]
            }

        provider = CandidateProvider(valid_output)
        service = ReasoningService(
            lambda: SqlAlchemyUnitOfWork(manager.session_factory),
            environment_name="home",
            ai_provider=provider,
        )
        session = asyncio.run(
            service.diagnose(
                ReasoningDiagnoseRequest(
                    question=f"Why is entity {entity_id} hot?",
                    space_id=room_id,
                    entity_id=entity_id,
                    attribute="temperature",
                    start_time=NOW - timedelta(hours=1),
                    end_time=NOW,
                    now=NOW,
                )
            )
        )
        assert session.status == "completed"
        assert session.analyzer_versions["ai_candidate_generator"] == "configured"
        assert session.analyzer_versions["ai_candidate_generator_status"] == "validated"
        ai_hypotheses = [
            item for item in session.hypotheses if item.hypothesis_type == "ai_candidate"
        ]
        assert len(ai_hypotheses) == 1
        assert ai_hypotheses[0].origin_type == "model"
        assert ai_hypotheses[0].status == "plausible"
        assert ai_hypotheses[0].confidence_level == "low"
        assert ai_hypotheses[0].causal_claim is False
        assert len(ai_hypotheses[0].evidence) == 1
        assert session.scope["ai_candidates"]["accepted"] == 1
        assert "independent review" in " ".join(ai_hypotheses[0].limitations)
    finally:
        manager.dispose()


def test_invalid_evidence_references_are_rejected_not_promoted(tmp_path: Path) -> None:
    manager = DatabaseManager(settings_for(tmp_path))
    manager.initialize_database()
    try:
        entity_id, room_id = seed_observation(manager)
        provider = CandidateProvider(
            lambda _request: {
                "candidates": [
                    {
                        "statement": "This cites fabricated evidence.",
                        "explanation": "The model attempted to cite a nonexistent record.",
                        "evidence_ids": ["not-a-real-evidence-id"],
                    }
                ]
            }
        )
        service = ReasoningService(
            lambda: SqlAlchemyUnitOfWork(manager.session_factory),
            environment_name="home",
            ai_provider=provider,
        )
        session = asyncio.run(
            service.diagnose(
                ReasoningDiagnoseRequest(
                    question=f"Why is entity {entity_id} hot?",
                    space_id=room_id,
                    entity_id=entity_id,
                    attribute="temperature",
                    start_time=NOW - timedelta(hours=1),
                    end_time=NOW,
                    now=NOW,
                )
            )
        )
        assert not [item for item in session.hypotheses if item.hypothesis_type == "ai_candidate"]
        assert session.scope["ai_candidates"]["accepted"] == 0
        assert session.scope["ai_candidates"]["rejected"] == 1
        assert session.analyzer_versions["ai_candidate_generator_status"] == "validated"
    finally:
        manager.dispose()


def test_provider_failure_keeps_deterministic_session_completed(tmp_path: Path) -> None:
    manager = DatabaseManager(settings_for(tmp_path))
    manager.initialize_database()
    try:
        entity_id, room_id = seed_observation(manager)

        class FailingProvider(CandidateProvider):
            async def generate(self, request: ProviderRequest) -> ProviderResponse:
                self.requests.append(request)
                raise RuntimeError("provider unavailable")

        service = ReasoningService(
            lambda: SqlAlchemyUnitOfWork(manager.session_factory),
            environment_name="home",
            ai_provider=FailingProvider(lambda _request: {}),
        )
        session = asyncio.run(
            service.diagnose(
                ReasoningDiagnoseRequest(
                    question=f"Why is entity {entity_id} hot?",
                    space_id=room_id,
                    entity_id=entity_id,
                    attribute="temperature",
                    start_time=NOW - timedelta(hours=1),
                    end_time=NOW,
                    now=NOW,
                )
            )
        )
        assert session.status == "completed"
        assert session.bundle is not None
        assert session.bundle.coverage["evidence_count"] > 0
        assert session.analyzer_versions["ai_candidate_generator_status"] == "provider_failed"
    finally:
        manager.dispose()


def test_without_provider_the_deterministic_version_is_reported(tmp_path: Path) -> None:
    manager = DatabaseManager(settings_for(tmp_path))
    manager.initialize_database()
    try:
        entity_id, room_id = seed_observation(manager)
        service = ReasoningService(
            lambda: SqlAlchemyUnitOfWork(manager.session_factory),
            environment_name="home",
        )
        session = asyncio.run(
            service.diagnose(
                ReasoningDiagnoseRequest(
                    question=f"Why is entity {entity_id} hot?",
                    space_id=room_id,
                    entity_id=entity_id,
                    attribute="temperature",
                    start_time=NOW - timedelta(hours=1),
                    end_time=NOW,
                    now=NOW,
                )
            )
        )
        assert session.analyzer_versions["ai_candidate_generator"] == "not_configured"
    finally:
        manager.dispose()
