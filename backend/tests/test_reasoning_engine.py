import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.estimation.service import StateEstimationService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import (
    Entity,
    EntitySpaceAssignment,
    Environment,
    Event,
    Memory,
    Observation,
    ObservationSource,
    StateEstimate,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.spatial.service import SpatialService

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
HEADERS = {"Authorization": "Bearer test-api-token"}


def reasoning_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


@pytest.fixture
def manager(tmp_path: Path) -> DatabaseManager:
    test_manager = DatabaseManager(reasoning_settings(tmp_path))
    test_manager.initialize_database()
    yield test_manager
    test_manager.dispose()


def uow(manager: DatabaseManager) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(manager.session_factory)


def client_for(manager: DatabaseManager, tmp_path: Path) -> TestClient:
    app = create_app(
        reasoning_settings(tmp_path),
        unit_of_work_factory=lambda: uow(manager),
    )
    return TestClient(app)


def seed_sensor(
    manager: DatabaseManager,
    *,
    name: str,
    attribute: str = "temperature",
) -> tuple[str, str]:
    spatial = SpatialService(lambda: uow(manager), environment_name="home")
    root = asyncio.run(spatial.ensure_root())
    room = asyncio.run(
        spatial.create_space(
            parent_id=root.id,
            name=f"Reasoning {name}",
            space_type="room",
        )
    )
    with manager.session_factory() as session:
        environment = session.scalars(select(Environment).limit(1)).one()
        entity = Entity(
            id=f"entity-{name}",
            environment_id=environment.id,
            entity_type="sensor",
            name=name,
            normalized_name=name.casefold(),
            status="active",
            semantic_tags=["device", f"sensor_{attribute}"],
            metadata_summary={},
        )
        session.add(entity)
        session.flush()
        session.add(
            EntitySpaceAssignment(
                entity_id=entity.id,
                space_id=room.id,
                assignment_type="fixed_installation",
                valid_from=NOW - timedelta(days=1),
                confidence=1.0,
                source_type="user",
                source_id=f"entity-{name}",
                reason="reasoning fixture",
            )
        )
        session.commit()
    return entity.id, room.id


def add_observation(
    manager: DatabaseManager,
    *,
    observation_id: str,
    entity_id: str,
    space_id: str,
    value: Any,
    received_at: datetime,
    observed_at: datetime | None,
    correlation_id: str,
    quality_status: str = "valid",
) -> None:
    with manager.session_factory() as session:
        source = session.scalars(
            select(ObservationSource).where(ObservationSource.adapter_id == "mock")
        ).one()
        session.add(
            Observation(
                observation_id=observation_id,
                source_id=source.id,
                source_type=source.source_type,
                entity_id=entity_id,
                space_id=space_id,
                attribute="temperature",
                raw_value=value,
                raw_unit="°C",
                normalized_value=value if quality_status == "valid" else None,
                normalized_unit="°C",
                value_type="number",
                observed_at=observed_at,
                observed_at_source="device_clock" if observed_at is not None else "poll_clock",
                observed_at_uncertainty_ms=0 if observed_at is not None else None,
                received_at=received_at,
                processed_at=received_at,
                quality_status=quality_status,
                quality_issues=(
                    [{"code": "invalid_observation", "severity": "invalid"}]
                    if quality_status == "invalid"
                    else []
                ),
                valid_from=received_at,
                valid_until=received_at + timedelta(minutes=5),
                freshness_policy="valid_300s",
                freshness_evaluated_at=received_at,
                correlation_id=correlation_id,
                external_id=f"{source.id}:{entity_id}:{observation_id}",
                dedupe_key=hashlib.sha256(observation_id.encode()).hexdigest(),
                payload_hash=hashlib.sha256(str(value).encode()).hexdigest(),
                normalization_rule_version="1.0.0",
                retention_class="standard_30d",
                retention_until=received_at + timedelta(days=30),
            )
        )
        session.commit()


def estimate_snapshot(manager: DatabaseManager) -> dict[str, tuple[Any, Any, Any]]:
    with manager.session_factory() as session:
        rows = list(session.scalars(select(StateEstimate)))
    return {row.id: (row.status, row.value, row.generated_at.replace(tzinfo=UTC)) for row in rows}


def diagnose(
    client: TestClient,
    *,
    question: str,
    space_id: str | None,
    attribute: str | None,
) -> dict[str, Any]:
    response = client.post(
        "/api/reasoning/sessions",
        headers=HEADERS,
        json={
            "question": question,
            "space_id": space_id,
            "attribute": attribute,
            "start_time": (NOW - timedelta(hours=1)).isoformat(),
            "end_time": NOW.isoformat(),
            "now": NOW.isoformat(),
        },
    )
    assert response.status_code == 201
    return response.json()["data"]


def test_reasoning_api_requires_authorization_and_reports_missing_scope(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    client = client_for(manager, tmp_path)
    assert client.get("/api/reasoning/sessions").status_code == 401
    assert (
        client.get(
            "/api/reasoning/sessions", headers={"Authorization": "Bearer wrong-token"}
        ).status_code
        == 401
    )

    session = diagnose(
        client,
        question="What is the pressure in the living room?",
        space_id=None,
        attribute="pressure",
    )
    assert session["status"] == "completed"
    assert session["bundle"]["coverage"]["evidence_count"] == 0
    assert session["diagnosis"]["unknowns"] == [
        "No retained observation or world-model estimate for pressure.",
        "No relevant source record was available in the queried scope.",
    ]
    assert session["analyzer_versions"]["ai_candidate_generator"] == "not_configured"
    assert [item["hypothesis_type"] for item in session["hypotheses"]] == ["unknown"]


def test_replay_builds_traceable_evidence_and_keeps_correlation_non_causal(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    entity_id, room_id = seed_sensor(manager, name="replay")
    add_observation(
        manager,
        observation_id="observation-cold",
        entity_id=entity_id,
        space_id=room_id,
        value=23.0,
        received_at=NOW - timedelta(minutes=6),
        observed_at=NOW - timedelta(minutes=30),
        correlation_id="reasoning-replay",
    )
    add_observation(
        manager,
        observation_id="observation-warm",
        entity_id=entity_id,
        space_id=room_id,
        value=28.0,
        received_at=NOW - timedelta(minutes=5),
        observed_at=NOW - timedelta(minutes=10),
        correlation_id="reasoning-replay",
    )
    with manager.session_factory() as session:
        session.add(
            Event(
                id="event-correlated",
                event_type="hvac_mode_changed",
                source="mock",
                subject_type="device",
                subject_id="hvac",
                payload={"state": "off"},
                correlation_id="reasoning-replay",
                occurred_at=NOW - timedelta(minutes=20),
                created_at=NOW - timedelta(minutes=20),
            )
        )
        session.commit()

    estimation = StateEstimationService(lambda: uow(manager), environment_name="home")
    asyncio.run(estimation.rebuild(NOW))
    estimates_before = estimate_snapshot(manager)
    client = client_for(manager, tmp_path)
    session = diagnose(
        client,
        question="Why did the temperature rise?",
        space_id=room_id,
        attribute="temperature",
    )

    assert session["status"] == "completed"
    assert session["analyzer_versions"]["deterministic_environment_rules"] == "1.0.0"
    assert session["analyzer_versions"]["ai_candidate_generator"] == "not_configured"
    coverage = session["bundle"]["coverage"]
    assert coverage["by_source"] == {"event": 1, "observation": 2, "state_estimate": 2}
    assert session["diagnosis"]["observed_facts"]
    assert (
        "temperature increased from 23 to 28°C in the queried period."
        in (session["diagnosis"]["deterministic_findings"])
    )
    hypotheses = {item["hypothesis_type"]: item for item in session["hypotheses"]}
    assert hypotheses["deterministic_rule"]["confidence_level"] == "high"
    assert hypotheses["correlation"]["confidence_level"] == "low"
    assert hypotheses["correlation"]["causal_claim"] is False
    assert (
        "Temporal adjacency alone does not establish causation."
        in (hypotheses["correlation"]["limitations"])
    )
    assert session["diagnosis"]["candidate_causes"]
    assert session["diagnosis"]["verified_causes"] == []

    evidence = client.get(
        f"/api/reasoning/sessions/{session['id']}/evidence",
        headers=HEADERS,
        params={"classification": "observed"},
    ).json()["data"]
    observation_evidence = next(item for item in evidence if item["source_type"] == "observation")
    source = client.get(
        f"/api/reasoning/evidence/{observation_evidence['id']}/source", headers=HEADERS
    ).json()["data"]
    assert source["record_type"] == "observation"
    assert source["observation_id"] in {"observation-cold", "observation-warm"}
    assert source["normalized_value"] in {23.0, 28.0}

    assert estimate_snapshot(manager) == estimates_before


def test_verified_event_metadata_can_promote_a_causal_hypothesis(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    entity_id, room_id = seed_sensor(manager, name="verified")
    add_observation(
        manager,
        observation_id="observation-before",
        entity_id=entity_id,
        space_id=room_id,
        value=24.0,
        received_at=NOW - timedelta(minutes=20),
        observed_at=NOW - timedelta(minutes=20),
        correlation_id="reasoning-verified",
    )
    add_observation(
        manager,
        observation_id="observation-after",
        entity_id=entity_id,
        space_id=room_id,
        value=28.0,
        received_at=NOW - timedelta(minutes=5),
        observed_at=NOW - timedelta(minutes=5),
        correlation_id="reasoning-verified",
    )
    with manager.session_factory() as session:
        session.add(
            Event(
                id="event-verified",
                event_type="hvac_mode_changed",
                source="mock",
                payload={"state": "off", "verified_cause": True},
                correlation_id="reasoning-verified",
                occurred_at=NOW - timedelta(minutes=10),
                created_at=NOW - timedelta(minutes=10),
            )
        )
        session.commit()
    asyncio.run(StateEstimationService(lambda: uow(manager), environment_name="home").rebuild(NOW))

    client = client_for(manager, tmp_path)
    session = diagnose(
        client,
        question="What changed after the verified HVAC event?",
        space_id=room_id,
        attribute="temperature",
    )
    verified = next(
        item for item in session["hypotheses"] if item["hypothesis_type"] == "verified_cause"
    )
    assert verified["status"] == "supported"
    assert verified["confidence_level"] == "high"
    assert verified["causal_claim"] is True
    assert session["diagnosis"]["verified_causes"]


def test_bad_data_is_reported_without_being_promoted_to_fact(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    invalid_entity, invalid_room = seed_sensor(manager, name="invalid")
    late_entity, late_room = seed_sensor(manager, name="late")
    future_entity, future_room = seed_sensor(manager, name="future")
    missing_entity, missing_room = seed_sensor(manager, name="missing-time")
    add_observation(
        manager,
        observation_id="observation-invalid",
        entity_id=invalid_entity,
        space_id=invalid_room,
        value="hot",
        received_at=NOW - timedelta(minutes=30),
        observed_at=NOW - timedelta(minutes=30),
        correlation_id="reasoning-invalid",
        quality_status="invalid",
    )
    add_observation(
        manager,
        observation_id="observation-late",
        entity_id=late_entity,
        space_id=late_room,
        value=22.0,
        received_at=NOW,
        observed_at=NOW - timedelta(minutes=20),
        correlation_id="reasoning-late",
    )
    add_observation(
        manager,
        observation_id="observation-future",
        entity_id=future_entity,
        space_id=future_room,
        value=23.0,
        received_at=NOW,
        observed_at=NOW + timedelta(minutes=2),
        correlation_id="reasoning-future",
    )
    add_observation(
        manager,
        observation_id="observation-missing-time",
        entity_id=missing_entity,
        space_id=missing_room,
        value=24.0,
        received_at=NOW - timedelta(minutes=5),
        observed_at=None,
        correlation_id="reasoning-missing-time",
    )
    asyncio.run(StateEstimationService(lambda: uow(manager), environment_name="home").rebuild(NOW))

    client = client_for(manager, tmp_path)
    session = diagnose(
        client,
        question="Diagnose the sensors",
        space_id=None,
        attribute="temperature",
    )
    issues = set(session["diagnosis"]["data_quality_issues"])
    assert "The observation is marked invalid." in issues
    assert "The observation has no collected time." in issues
    assert "The observation arrived more than 10 minutes late." in issues
    assert "The device clock is more than 30 seconds ahead." in issues
    assert session["bundle"]["coverage"]["invalid_count"] >= 1
    assert session["bundle"]["coverage"]["missing_collected_time"] == 1
    assert session["bundle"]["coverage"]["late_arrivals"] == 1
    assert session["bundle"]["coverage"]["future_clock_skew"] == 1
    assert not any(
        "Sensor observed temperature=hot" in fact for fact in session["diagnosis"]["observed_facts"]
    )


def test_verified_memory_is_derived_evidence_but_not_an_observed_fact(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    entity_id, room_id = seed_sensor(manager, name="memory")
    with manager.session_factory() as session:
        environment = session.scalars(select(Environment).limit(1)).one()
        session.add(
            Memory(
                id="memory-semantic",
                memory_type="semantic",
                title="Living room heater",
                content="The living room heater is below the window.",
                summary="The heater is below the window.",
                keywords=["living room", "heater"],
                importance=3,
                source_type="user",
                source_id="chat-statement-1",
                user_confirmed=True,
                status="active",
                verification_status="verified",
                environment_id=environment.id,
                space_id=room_id,
                entity_id=entity_id,
            )
        )
        session.commit()

    client = client_for(manager, tmp_path)
    session = diagnose(
        client,
        question="Where is the heater?",
        space_id=room_id,
        attribute=None,
    )
    memory_evidence = [
        item
        for item in client.get(
            f"/api/reasoning/sessions/{session['id']}/evidence",
            headers=HEADERS,
            params={"classification": "derived"},
        ).json()["data"]
        if item["source_type"] == "memory"
    ]
    assert len(memory_evidence) == 1
    assert memory_evidence[0]["source_record_id"] == "memory-semantic"
    assert memory_evidence[0]["quality_status"] == "valid"
    assert (
        "Memory states: The heater is below the window."
        not in session["diagnosis"]["observed_facts"]
    )
    source = client.get(
        f"/api/reasoning/evidence/{memory_evidence[0]['id']}/source", headers=HEADERS
    ).json()["data"]
    assert source == {
        "record_type": "memory",
        "id": "memory-semantic",
        "memory_type": "semantic",
        "title": "Living room heater",
        "verification_status": "verified",
    }
