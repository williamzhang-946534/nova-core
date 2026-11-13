import asyncio
import hashlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from arvuno_core.config import Settings
from arvuno_core.estimation.service import StateEstimationService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import (
    Device,
    Entity,
    EntitySpaceAssignment,
    Environment,
    Observation,
    ObservationSource,
    StateEstimate,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.spatial.service import SpatialService

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


@pytest.mark.parametrize("sensor_count", [20, 50, 200])
def test_state_estimation_handles_target_sensor_counts(tmp_path: Path, sensor_count: int) -> None:
    manager = DatabaseManager(settings(tmp_path))
    manager.initialize_database()

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(manager.session_factory)

    try:
        spatial = SpatialService(factory, environment_name="home")
        root = asyncio.run(spatial.ensure_root())
        room = asyncio.run(
            spatial.create_space(parent_id=root.id, name="Performance Room", space_type="room")
        )
        with manager.session_factory() as session:
            source_id = "performance-source"
            environment = session.execute(
                select(Environment).where(Environment.name == "home")
            ).scalar_one()
            session.add(
                ObservationSource(
                    id=source_id,
                    source_type="adapter",
                    adapter_id="performance",
                    name="Performance sensor fleet",
                    status="active",
                    trust_level=1.0,
                    time_trust="device_clock",
                    config={},
                    privacy_scope={},
                )
            )
            for index in range(sensor_count):
                entity_id = f"performance-entity-{index}"
                entity = Entity(
                    id=entity_id,
                    environment_id=environment.id,
                    entity_type="sensor",
                    name=f"Sensor {index}",
                    normalized_name=f"sensor-{index}",
                    status="active",
                    semantic_tags=["sensor", "temperature"],
                    metadata_summary={},
                )
                session.add(entity)
                # SQLite enforces insertion order here, so flush the entity
                # before assigning it as the device's foreign key target.
                session.flush()
                session.add(
                    Device(
                        id=f"performance-device-{index}",
                        adapter_id="performance",
                        external_id=f"sensor-{index}",
                        name=f"Sensor {index}",
                        normalized_name=f"sensor-{index}",
                        device_type="sensor_temperature",
                        area=room.name,
                        entity_id=entity_id,
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
                        id=f"performance-assignment-{index}",
                        entity_id=entity_id,
                        space_id=room.id,
                        assignment_type="fixed_installation",
                        valid_from=NOW - timedelta(seconds=1),
                        confidence=1.0,
                        source_type="user",
                        source_id=f"performance-device-{index}",
                        reason="performance fixture",
                    )
                )
            session.commit()
            observations = []
            for index in range(sensor_count):
                entity_id = f"performance-entity-{index}"
                observation_id = str(uuid.uuid4())
                received_at = NOW - timedelta(seconds=sensor_count - index)
                observations.append(
                    Observation(
                        observation_id=observation_id,
                        source_id=source_id,
                        source_type="adapter",
                        entity_id=entity_id,
                        attribute="temperature",
                        raw_value=20.0,
                        normalized_value=20.0,
                        normalized_unit="C",
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
                        correlation_id=f"performance-{observation_id}",
                        external_id=f"{source_id}:{entity_id}:temperature",
                        dedupe_key=hashlib.sha256(observation_id.encode()).hexdigest(),
                        payload_hash=hashlib.sha256(f"{entity_id}:20.0".encode()).hexdigest(),
                        normalization_rule_version="1.0.0",
                        retention_class="standard_30d",
                        retention_until=received_at + timedelta(days=30),
                    )
                )
            session.add_all(observations)
            session.commit()

        service = StateEstimationService(factory, environment_name="home")
        started = time.perf_counter()
        result = asyncio.run(service.rebuild(NOW))
        elapsed = time.perf_counter() - started
        # Each sensor contributes availability and temperature targets. Add
        # the root entity plus the default temperature/humidity/occupancy
        # targets for both the root and performance room.
        expected_targets = sensor_count * 2 + 6
        assert result.targets == expected_targets
        assert result.appended == expected_targets
        assert result.unchanged == 0
        assert elapsed < 15.0

        with manager.session_factory() as session:
            estimate_count = session.scalar(select(func.count()).select_from(StateEstimate))
            assert estimate_count == expected_targets
    finally:
        manager.dispose()
