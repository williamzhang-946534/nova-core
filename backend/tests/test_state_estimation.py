import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.estimation.service import StateEstimationService
from arvuno_core.observations.pipeline import ObservationPipeline
from arvuno_core.observations.service import ObservationService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import (
    CurrentStateEstimate,
    Device,
    Entity,
    EntitySpaceAssignment,
    Environment,
    EstimationTarget,
    Observation,
    ObservationSource,
    StateEstimate,
    StateEstimateObservation,
)
from arvuno_core.persistence.state_estimates import stored_as_utc
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.spatial.service import SpatialService

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
HEADERS = {"Authorization": "Bearer test-api-token"}


def state_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


@pytest.fixture
def estimation_manager(tmp_path: Path):
    manager = DatabaseManager(state_settings(tmp_path))
    manager.initialize_database()
    yield manager
    manager.dispose()


def unit_of_work(manager: DatabaseManager) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(manager.session_factory)


def estimation_service(manager: DatabaseManager) -> StateEstimationService:
    return StateEstimationService(lambda: unit_of_work(manager), environment_name="home")


def seed_entity(
    manager: DatabaseManager,
    *,
    name: str,
    device_type: str = "sensor_temperature",
    adapter_id: str = "mock",
) -> tuple[str, str]:
    spatial = SpatialService(lambda: unit_of_work(manager), environment_name="home")
    root = asyncio.run(spatial.ensure_root())
    room = asyncio.run(
        spatial.create_space(
            parent_id=root.id,
            name=f"Room {name}",
            space_type="room",
        )
    )
    with manager.session_factory() as session:
        environment = session.scalars(select(Environment).limit(1)).one()
        assert environment is not None
        entity = Entity(
            id=f"entity-{name}",
            environment_id=environment.id,
            entity_type="sensor",
            name=name,
            normalized_name=name.casefold(),
            status="active",
            semantic_tags=["device", device_type],
            metadata_summary={},
        )
        session.add(entity)
        session.flush()
        session.add(
            Device(
                id=f"device-{name}",
                adapter_id=adapter_id,
                external_id=name,
                name=name,
                normalized_name=name.casefold(),
                device_type=device_type,
                area=room.name,
                entity_id=entity.id,
                is_online=True,
                is_enabled=True,
                risk_level="low_risk",
                capabilities={},
                metadata_summary={},
                last_seen_at=NOW,
            )
        )
        session.add(
            EntitySpaceAssignment(
                entity_id=entity.id,
                space_id=room.id,
                assignment_type="fixed_installation",
                valid_from=NOW - timedelta(days=1),
                confidence=1.0,
                source_type="user",
                source_id=f"device-{name}",
                reason="state estimation fixture",
            )
        )
        session.commit()
        return entity.id, room.id


def add_observation(
    manager: DatabaseManager,
    *,
    entity_id: str,
    space_id: str,
    attribute: str,
    value: Any,
    adapter_id: str = "mock",
    received_at: datetime = NOW,
    valid_seconds: int = 300,
    quality_status: str = "valid",
    observed_at: datetime | None = NOW,
) -> str:
    observation_id = str(uuid.uuid4())
    with manager.session_factory() as session:
        source = session.scalars(
            select(ObservationSource).where(ObservationSource.adapter_id == adapter_id)
        ).one()
        value_type = {
            "temperature": "number",
            "humidity": "number",
            "illumination": "number",
            "co2": "number",
            "motion": "boolean",
            "contact": "enum",
            "occupancy": "enum",
            "device_availability": "enum",
            "actuator_state": "json",
        }[attribute]
        unit = {
            "temperature": "°C",
            "humidity": "%RH",
            "illumination": "lux",
            "co2": "ppm",
        }.get(attribute)
        session.add(
            Observation(
                observation_id=observation_id,
                source_id=source.id,
                source_type=source.source_type,
                entity_id=entity_id,
                space_id=space_id,
                attribute=attribute,
                raw_value=value,
                raw_unit=unit,
                normalized_value=value if quality_status != "invalid" else None,
                normalized_unit=unit,
                value_type=value_type,
                observed_at=observed_at,
                observed_at_source="device_clock" if observed_at is not None else "poll_clock",
                observed_at_uncertainty_ms=0 if observed_at is not None else None,
                received_at=received_at,
                processed_at=received_at + timedelta(milliseconds=10),
                quality_status=quality_status,
                quality_issues=(
                    [{"code": "invalid_observation", "severity": "invalid"}]
                    if quality_status == "invalid"
                    else []
                ),
                valid_from=received_at,
                valid_until=received_at + timedelta(seconds=valid_seconds),
                freshness_policy=f"valid_{valid_seconds}s",
                freshness_evaluated_at=received_at,
                correlation_id=f"estimation-{observation_id}",
                external_id=f"{source.id}:{entity_id}:{attribute}",
                dedupe_key=hashlib.sha256(observation_id.encode()).hexdigest(),
                payload_hash=hashlib.sha256(str(value).encode()).hexdigest(),
                normalization_rule_version="1.0.0",
                retention_class="standard_30d",
                retention_until=received_at + timedelta(days=30),
            )
        )
        session.commit()
    return observation_id


def current_estimate(
    manager: DatabaseManager,
    *,
    target_type: str,
    entity_id: str | None,
    space_id: str | None,
    attribute: str,
) -> StateEstimate:
    with manager.session_factory() as session:
        return session.execute(
            select(StateEstimate)
            .join(EstimationTarget, StateEstimate.target_id == EstimationTarget.id)
            .where(
                EstimationTarget.target_type == target_type,
                EstimationTarget.entity_id == entity_id,
                EstimationTarget.space_id == space_id,
                EstimationTarget.attribute == attribute,
                StateEstimate.superseded_at.is_(None),
            )
        ).scalar_one()


def test_numeric_estimates_are_trusted_derived_and_traceable(estimation_manager) -> None:
    high_trust, room = seed_entity(
        estimation_manager,
        name="temp-room-ha",
        adapter_id="home_assistant",
    )
    standard_trust, _ = seed_entity(
        estimation_manager,
        name="temp-room-mock",
        adapter_id="mock",
    )
    high_observation = add_observation(
        estimation_manager,
        entity_id=high_trust,
        space_id=room,
        attribute="temperature",
        value=21.0,
        adapter_id="home_assistant",
    )
    low_observation = add_observation(
        estimation_manager,
        entity_id=standard_trust,
        space_id=room,
        attribute="temperature",
        value=20.0,
        adapter_id="mock",
    )

    result = asyncio.run(estimation_service(estimation_manager).rebuild(NOW))
    assert result.targets > 0

    entity_estimate = current_estimate(
        estimation_manager,
        target_type="entity",
        entity_id=high_trust,
        space_id=None,
        attribute="temperature",
    )
    assert entity_estimate.status == "observed"
    assert entity_estimate.value == 21.0
    assert entity_estimate.rule_id == "temperature_weighted_median_v1"

    space_estimate = current_estimate(
        estimation_manager,
        target_type="space",
        entity_id=None,
        space_id=room,
        attribute="temperature",
    )
    assert space_estimate.status == "derived"
    assert space_estimate.value == 21.0
    assert space_estimate.unit == "°C"
    assert set(space_estimate.evidence_summary["observation_ids"]) == {
        high_observation,
        low_observation,
    }
    assert stored_as_utc(space_estimate.effective_from) == NOW
    assert stored_as_utc(space_estimate.generated_at) == NOW
    assert stored_as_utc(space_estimate.valid_until) == NOW + timedelta(minutes=5)

    service = estimation_service(estimation_manager)
    evidence = asyncio.run(service.evidence(space_estimate.id))
    evidence_by_id = {item.observation_id: item for item in evidence}
    assert evidence_by_id[high_observation].weight > evidence_by_id[low_observation].weight
    assert all(item.contribution == "candidate" for item in evidence)


def test_conflict_stale_unknown_unavailable_and_invalid_evidence(estimation_manager) -> None:
    conflict_a, room_a = seed_entity(estimation_manager, name="conflict-a")
    conflict_b, _ = seed_entity(estimation_manager, name="conflict-b")
    add_observation(
        estimation_manager,
        entity_id=conflict_a,
        space_id=room_a,
        attribute="temperature",
        value=18.0,
    )
    add_observation(
        estimation_manager,
        entity_id=conflict_b,
        space_id=room_a,
        attribute="temperature",
        value=25.0,
    )

    stale_entity, stale_room = seed_entity(estimation_manager, name="stale-sensor")
    add_observation(
        estimation_manager,
        entity_id=stale_entity,
        space_id=stale_room,
        attribute="temperature",
        value=20.0,
    )

    offline_entity, offline_room = seed_entity(estimation_manager, name="offline-sensor")
    add_observation(
        estimation_manager,
        entity_id=offline_entity,
        space_id=offline_room,
        attribute="temperature",
        value=20.0,
    )
    add_observation(
        estimation_manager,
        entity_id=offline_entity,
        space_id=offline_room,
        attribute="device_availability",
        value="offline",
    )

    invalid_entity, invalid_room = seed_entity(estimation_manager, name="invalid-sensor")
    invalid_observation = add_observation(
        estimation_manager,
        entity_id=invalid_entity,
        space_id=invalid_room,
        attribute="temperature",
        value="hot",
        quality_status="invalid",
    )

    asyncio.run(estimation_service(estimation_manager).rebuild(NOW))
    conflict = current_estimate(
        estimation_manager,
        target_type="space",
        entity_id=None,
        space_id=room_a,
        attribute="temperature",
    )
    assert conflict.status == "conflict"
    assert conflict.value is None
    assert conflict.conflict_details is not None
    assert conflict.conflict_details["reason"] == "credible_observations_conflict"

    unavailable = current_estimate(
        estimation_manager,
        target_type="entity",
        entity_id=offline_entity,
        space_id=None,
        attribute="temperature",
    )
    assert unavailable.status == "unavailable"

    service = estimation_service(estimation_manager)
    invalid = current_estimate(
        estimation_manager,
        target_type="entity",
        entity_id=invalid_entity,
        space_id=None,
        attribute="temperature",
    )
    assert invalid.status == "unknown"
    invalid_evidence = asyncio.run(service.evidence(invalid.id))
    assert [item.observation_id for item in invalid_evidence] == [invalid_observation]
    assert invalid_evidence[0].contribution == "context"
    assert invalid_evidence[0].exclusion_reason == "invalid_observation"

    later = NOW + timedelta(seconds=301)
    asyncio.run(estimation_service(estimation_manager).rebuild(later))
    stale = current_estimate(
        estimation_manager,
        target_type="entity",
        entity_id=stale_entity,
        space_id=None,
        attribute="temperature",
    )
    assert stale.status == "stale"
    assert stale.value == 20.0


def test_occupancy_motion_semantics_do_not_fake_negative_conclusion(estimation_manager) -> None:
    false_entity, room = seed_entity(
        estimation_manager,
        name="motion-false",
        device_type="sensor_motion",
    )
    add_observation(
        estimation_manager,
        entity_id=false_entity,
        space_id=room,
        attribute="motion",
        value=False,
        valid_seconds=60,
    )
    asyncio.run(estimation_service(estimation_manager).rebuild(NOW))
    false_state = current_estimate(
        estimation_manager,
        target_type="space",
        entity_id=None,
        space_id=room,
        attribute="occupancy",
    )
    assert false_state.status == "unknown"
    assert false_state.value is None

    service = estimation_service(estimation_manager)
    evidence = asyncio.run(service.evidence(false_state.id))
    assert evidence[0].exclusion_reason == "pir_false_is_not_unoccupied"

    true_entity, true_room = seed_entity(
        estimation_manager,
        name="motion-true",
        device_type="sensor_motion",
    )
    motion_observation = add_observation(
        estimation_manager,
        entity_id=true_entity,
        space_id=true_room,
        attribute="motion",
        value=True,
        valid_seconds=60,
    )
    asyncio.run(estimation_service(estimation_manager).rebuild(NOW))
    occupied = current_estimate(
        estimation_manager,
        target_type="space",
        entity_id=None,
        space_id=true_room,
        attribute="occupancy",
    )
    assert occupied.status == "inferred"
    assert occupied.value == "occupied"
    assert occupied.rule_id == "occupancy_coverage_aware_v1"
    assert occupied.evidence_summary["observation_ids"] == [motion_observation]


def test_history_is_append_only_current_is_rebuildable_and_idempotent(estimation_manager) -> None:
    entity, room = seed_entity(estimation_manager, name="history-sensor")
    add_observation(
        estimation_manager,
        entity_id=entity,
        space_id=room,
        attribute="temperature",
        value=20.0,
    )
    service = estimation_service(estimation_manager)
    first = asyncio.run(service.rebuild(NOW))
    first_estimate = current_estimate(
        estimation_manager,
        target_type="entity",
        entity_id=entity,
        space_id=None,
        attribute="temperature",
    )

    repeated = asyncio.run(service.rebuild(NOW))
    with estimation_manager.session_factory() as session:
        history = list(
            session.scalars(
                select(StateEstimate)
                .join(EstimationTarget, StateEstimate.target_id == EstimationTarget.id)
                .where(
                    EstimationTarget.entity_id == entity,
                    EstimationTarget.attribute == "temperature",
                )
                .order_by(StateEstimate.generated_at, StateEstimate.id)
            )
        )
    assert first.appended == first.targets
    assert repeated.unchanged == repeated.targets
    assert len(history) == 1

    second_received = NOW + timedelta(seconds=120)
    add_observation(
        estimation_manager,
        entity_id=entity,
        space_id=room,
        attribute="temperature",
        value=21.0,
        received_at=second_received,
    )
    asyncio.run(service.rebuild(second_received))
    with estimation_manager.session_factory() as session:
        history = list(
            session.scalars(
                select(StateEstimate)
                .join(EstimationTarget, StateEstimate.target_id == EstimationTarget.id)
                .where(
                    EstimationTarget.entity_id == entity,
                    EstimationTarget.attribute == "temperature",
                )
                .order_by(StateEstimate.generated_at, StateEstimate.id)
            )
        )
        current = session.get(CurrentStateEstimate, history[0].target_id)
    assert len(history) == 2
    assert history[0].id == first_estimate.id
    assert stored_as_utc(history[0].superseded_at) == second_received
    assert history[1].superseded_at is None
    assert history[1].value == 21.0
    assert current is not None
    assert current.latest_estimate_id == history[1].id
    assert current.value == 21.0

    items, total = asyncio.run(
        service.list(entity_id=entity, attribute="temperature", include_history=True)
    )
    assert total == 2
    assert len(items) == 2


def test_expired_positive_estimates_degrade_to_stale_on_query(estimation_manager) -> None:
    entity, room = seed_entity(estimation_manager, name="query-stale")
    add_observation(
        estimation_manager,
        entity_id=entity,
        space_id=room,
        attribute="temperature",
        value=20.0,
    )
    service = estimation_service(estimation_manager)
    asyncio.run(service.rebuild(NOW))
    estimate = current_estimate(
        estimation_manager,
        target_type="entity",
        entity_id=entity,
        space_id=None,
        attribute="temperature",
    )
    with estimation_manager.session_factory() as session:
        persisted = session.get(StateEstimate, estimate.id)
        persisted.valid_until = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    latest = asyncio.run(service.get(estimate.id))
    assert latest.status == "stale"


def test_context_v2_api_is_read_only_until_explicit_rebuild(
    estimation_manager, tmp_path: Path
) -> None:
    app = create_app(
        state_settings(tmp_path),
        unit_of_work_factory=lambda: unit_of_work(estimation_manager),
        initialize_event_runtime=True,
        initialize_tool_runtime=True,
    )
    with TestClient(app) as client:
        snapshots_before = client.get("/api/environment/snapshots", headers=HEADERS).json()["total"]
        context = client.get("/api/environment/context-v2", headers=HEADERS).json()["data"]
        snapshots_after_get = client.get("/api/environment/snapshots", headers=HEADERS).json()[
            "total"
        ]
        assert context["root_space_id"]
        assert context["spaces"]
        assert snapshots_before == snapshots_after_get == 1

        rebuilt = client.post("/api/environment/context-v2/rebuild", headers=HEADERS).json()["data"]
        assert rebuilt["context"]["environment_id"] == context["environment_id"]
        snapshots = client.get("/api/environment/snapshots", headers=HEADERS).json()
        assert snapshots["total"] == snapshots_before + 1
        assert snapshots["data"][0]["context_version"] == 2
        assert snapshots["data"][0]["state_generated_at"] is not None

        space_id = context["root_space_id"]
        state = client.get(f"/api/spaces/{space_id}/state", headers=HEADERS).json()["data"]
        assert state["space_id"] == space_id


def test_pipeline_triggers_estimation_and_callback_failure_is_isolated(estimation_manager) -> None:
    entity, room = seed_entity(estimation_manager, name="callback-sensor")
    calls: list[datetime] = []

    async def callback(received_at: datetime) -> None:
        calls.append(received_at)
        if len(calls) == 1:
            raise RuntimeError("simulated callback failure")

    pipeline = ObservationPipeline(
        lambda: unit_of_work(estimation_manager),
        ObservationService(lambda: unit_of_work(estimation_manager)),
        estimation_callback=callback,
    )
    from arvuno_core.devices.models import DeviceState, DeviceStateName

    state = DeviceState(
        external_id="callback-sensor",
        state=DeviceStateName.ON,
        attributes={"temperature": 68, "unit_of_measurement": "°F"},
        raw_state="68",
        observed_at=NOW,
        observed_at_source="device_clock",
    )
    failed_callback = asyncio.run(
        pipeline.ingest_states(
            adapter_id="mock",
            states=[state],
            batch_id="estimation-callback",
            received_at=NOW,
        )
    )
    assert failed_callback.status == "completed"
    assert failed_callback.accepted == 2
    assert calls == [NOW]
    with estimation_manager.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 2

    service = estimation_service(estimation_manager)
    asyncio.run(service.rebuild(NOW))
    estimate = current_estimate(
        estimation_manager,
        target_type="entity",
        entity_id=entity,
        space_id=None,
        attribute="temperature",
    )
    assert estimate.value == 20.0
    with estimation_manager.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(EstimationTarget)) > 0
        assert session.scalar(select(func.count()).select_from(StateEstimateObservation)) > 0
