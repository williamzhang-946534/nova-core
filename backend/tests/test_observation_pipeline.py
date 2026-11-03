import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, text

from arvuno_core.config import Settings
from arvuno_core.devices.models import DeviceState, DeviceStateName
from arvuno_core.observations.pipeline import ObservationPipeline
from arvuno_core.observations.service import ObservationService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import (
    Device,
    Entity,
    EntitySpaceAssignment,
    Event,
    Observation,
    ObservationIngestionBatch,
    ObservationSource,
    ObservationSourceHeartbeat,
)
from arvuno_core.persistence.models import (
    DeviceState as DeviceStateRow,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.spatial.service import SpatialService

RECEIVED_AT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def pipeline_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


def stored_as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@pytest.fixture
def observation_manager(tmp_path: Path):
    test_manager = DatabaseManager(pipeline_settings(tmp_path))
    test_manager.initialize_database()
    yield test_manager
    test_manager.dispose()


def seed_device(
    test_manager: DatabaseManager,
    *,
    external_id: str = "sensor.temperature",
    adapter_id: str = "mock",
    device_type: str = "sensor_temperature",
) -> tuple[str, str, str]:
    spatial = SpatialService(lambda: SqlAlchemyUnitOfWork(test_manager.session_factory))
    root = asyncio.run(spatial.ensure_root())
    room = asyncio.run(
        spatial.create_space(
            parent_id=root.id,
            name=f"Room {external_id}",
            space_type="room",
        )
    )
    with test_manager.session_factory() as session:
        environment_id = session.execute(
            text("SELECT id FROM environments WHERE is_default = 1")
        ).scalar_one()
        entity = Entity(
            id=f"entity-{external_id}",
            environment_id=environment_id,
            entity_type="sensor",
            name=external_id,
            normalized_name=external_id.casefold(),
            status="active",
            semantic_tags=["device", device_type],
            metadata_summary={},
        )
        session.add(entity)
        session.flush()
        device = Device(
            id=f"device-{external_id}",
            adapter_id=adapter_id,
            external_id=external_id,
            name=external_id,
            normalized_name=external_id.casefold(),
            device_type=device_type,
            area="Living Room",
            entity_id=entity.id,
            is_online=True,
            is_enabled=True,
            risk_level="low_risk",
            capabilities={},
            metadata_summary={},
            last_seen_at=RECEIVED_AT - timedelta(hours=1),
        )
        session.add(device)
        session.add(
            EntitySpaceAssignment(
                entity_id=entity.id,
                space_id=room.id,
                assignment_type="fixed_installation",
                valid_from=RECEIVED_AT - timedelta(days=1),
                confidence=1.0,
                source_type="user",
                source_id=device.id,
                reason="pipeline fixture",
            )
        )
        session.commit()
        return device.id, entity.id, room.id


def adapter_state(
    *,
    external_id: str = "sensor.temperature",
    temperature: Any = 68,
    unit: str | None = "°F",
    observed_at: datetime | None = None,
    observed_at_source: str = "poll_clock",
    received_state: DeviceStateName = DeviceStateName.ON,
) -> DeviceState:
    return DeviceState(
        external_id=external_id,
        state=received_state,
        attributes=(
            {} if temperature is None else {"temperature": temperature, "unit_of_measurement": unit}
        ),
        raw_state=None if temperature is None else str(temperature),
        observed_at=observed_at or RECEIVED_AT,
        observed_at_source=observed_at_source,  # type: ignore[arg-type]
    )


def pipeline_for(test_manager: DatabaseManager, service: ObservationService | None = None):
    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(test_manager.session_factory)

    return ObservationPipeline(factory, service or ObservationService(factory))


def ingest(
    pipeline: ObservationPipeline,
    *,
    adapter_id: str,
    state: DeviceState,
    batch_id: str,
    received_at: datetime = RECEIVED_AT,
) -> Any:
    return asyncio.run(
        pipeline.ingest_states(
            adapter_id=adapter_id,
            states=[state],
            batch_id=batch_id,
            received_at=received_at,
        )
    )


def observation_count(test_manager: DatabaseManager) -> int:
    with test_manager.session_factory() as session:
        return int(session.scalar(select(func.count()).select_from(Observation)) or 0)


def observations_for_entity(test_manager: DatabaseManager, entity_id: str) -> list[Observation]:
    with test_manager.session_factory() as session:
        return list(
            session.scalars(
                select(Observation)
                .where(Observation.entity_id == entity_id)
                .order_by(Observation.attribute, Observation.received_at)
            )
        )


def test_mock_state_is_normalized_persisted_and_projected(observation_manager) -> None:
    device_id, entity_id, room_id = seed_device(observation_manager)
    pipeline = pipeline_for(observation_manager)

    result = ingest(
        pipeline,
        adapter_id="mock",
        state=adapter_state(observed_at_source="poll_clock"),
        batch_id="mock-first",
    )

    assert result.status == "completed"
    assert (result.accepted, result.deduplicated, result.sampled, result.invalid) == (2, 0, 0, 0)
    records = observations_for_entity(observation_manager, entity_id)
    assert [(record.attribute, record.normalized_value) for record in records] == [
        ("device_availability", "online"),
        ("temperature", 20.0),
    ]
    assert all(record.space_id == room_id for record in records)
    assert all(record.observed_at is None for record in records)
    assert all(record.observed_at_source == "poll_clock" for record in records)
    assert all(record.quality_status == "warning" for record in records)
    assert all(stored_as_utc(record.received_at) == RECEIVED_AT for record in records)
    assert all(record.processed_at is not None for record in records)

    with observation_manager.session_factory() as session:
        current = session.scalars(
            select(DeviceStateRow).where(
                DeviceStateRow.device_id == device_id,
                DeviceStateRow.is_current.is_(True),
            )
        ).one()
        assert current.attributes["temperature"] == 68
        assert session.scalar(select(func.count()).select_from(Event)) == 0
        batch = session.get(ObservationIngestionBatch, "mock-first")
        heartbeat = session.get(ObservationSourceHeartbeat, batch.source_id)
        assert batch.status == "completed"
        assert heartbeat.status == "healthy"
        assert heartbeat.last_batch_id == "mock-first"


def test_home_assistant_shape_uses_gateway_clock_without_http_client(observation_manager) -> None:
    _device_id, entity_id, _room_id = seed_device(
        observation_manager,
        external_id="sensor.ha_temperature",
        adapter_id="home_assistant",
    )
    pipeline = pipeline_for(observation_manager)
    observed_at = RECEIVED_AT - timedelta(seconds=2)

    result = ingest(
        pipeline,
        adapter_id="home_assistant",
        state=adapter_state(
            external_id="sensor.ha_temperature",
            temperature=68,
            unit="°F",
            observed_at=observed_at,
            observed_at_source="gateway_state_clock",
        ),
        batch_id="ha-first",
    )

    assert result.status == "completed"
    records = observations_for_entity(observation_manager, entity_id)
    temperature = next(record for record in records if record.attribute == "temperature")
    assert temperature.raw_value == 68
    assert temperature.raw_unit == "°F"
    assert temperature.normalized_value == 20.0
    assert stored_as_utc(temperature.observed_at) == observed_at
    assert temperature.observed_at_source == "gateway_state_clock"
    assert temperature.observed_at_uncertainty_ms == 1000
    assert temperature.quality_status == "valid"


def test_sampling_blocks_unchanged_polls_and_keeps_important_change(observation_manager) -> None:
    device_id, _entity_id, _room_id = seed_device(observation_manager)
    pipeline = pipeline_for(observation_manager)

    first = ingest(
        pipeline,
        adapter_id="mock",
        state=adapter_state(temperature=68),
        batch_id="sample-1",
    )
    unchanged = ingest(
        pipeline,
        adapter_id="mock",
        state=adapter_state(temperature=68),
        batch_id="sample-2",
        received_at=RECEIVED_AT + timedelta(seconds=10),
    )
    changed = ingest(
        pipeline,
        adapter_id="mock",
        state=adapter_state(temperature=69),
        batch_id="sample-3",
        received_at=RECEIVED_AT + timedelta(seconds=20),
    )

    assert (first.accepted, first.sampled) == (2, 0)
    assert (unchanged.accepted, unchanged.sampled) == (0, 2)
    assert (changed.accepted, changed.sampled) == (1, 1)
    assert observation_count(observation_manager) == 3

    with observation_manager.session_factory() as session:
        states = list(
            session.scalars(select(DeviceStateRow).where(DeviceStateRow.device_id == device_id))
        )
        assert len(states) == 1
        assert states[0].is_current is True
        assert states[0].attributes["temperature"] == 69


def test_same_batch_retry_and_duplicate_payload_are_idempotent(observation_manager) -> None:
    _device_id, entity_id, _room_id = seed_device(observation_manager)
    pipeline = pipeline_for(observation_manager)
    state = adapter_state(temperature=68)

    first = asyncio.run(
        pipeline.ingest_states(
            adapter_id="mock",
            states=[state, state.model_copy()],
            batch_id="idempotent",
            received_at=RECEIVED_AT,
        )
    )
    retried = asyncio.run(
        pipeline.ingest_states(
            adapter_id="mock",
            states=[state, state.model_copy()],
            batch_id="idempotent",
            received_at=RECEIVED_AT,
        )
    )

    assert (first.accepted, first.deduplicated) == (2, 2)
    assert retried.status == "completed"
    assert retried.items == []
    assert (retried.accepted, retried.deduplicated) == (2, 2)
    assert observation_count(observation_manager) == 2
    records = observations_for_entity(observation_manager, entity_id)
    assert len({record.dedupe_key for record in records}) == 2


def test_delayed_future_and_invalid_values_are_marked(observation_manager) -> None:
    cases = [
        (
            "delayed",
            adapter_state(
                external_id="sensor.delayed",
                temperature=68,
                observed_at=RECEIVED_AT - timedelta(minutes=7),
                observed_at_source="device_clock",
            ),
            "warning",
            "delayed_observation",
        ),
        (
            "future",
            adapter_state(
                external_id="sensor.future",
                temperature=68,
                observed_at=RECEIVED_AT + timedelta(minutes=7),
                observed_at_source="device_clock",
            ),
            "warning",
            "future_observation_time",
        ),
        (
            "range",
            adapter_state(external_id="sensor.range", temperature=250),
            "invalid",
            "value_out_of_range",
        ),
        (
            "type",
            adapter_state(external_id="sensor.type", temperature="hot", unit="°C"),
            "invalid",
            "normalization_failed",
        ),
        (
            "unit",
            adapter_state(external_id="sensor.unit", temperature=68, unit=None),
            "warning",
            "missing_required_unit",
        ),
    ]
    pipeline = pipeline_for(observation_manager)
    for index, (_name, state, _quality, _issue) in enumerate(cases):
        seed_device(observation_manager, external_id=state.external_id)
        result = ingest(
            pipeline,
            adapter_id="mock",
            state=state,
            batch_id=f"quality-{index}",
        )
        assert result.status == "completed"

    for _name, state, quality, issue in cases:
        with observation_manager.session_factory() as session:
            device = session.scalars(
                select(Device).where(Device.external_id == state.external_id)
            ).one()
            temperature = session.scalars(
                select(Observation).where(
                    Observation.entity_id == device.entity_id,
                    Observation.attribute == "temperature",
                )
            ).one()
            assert temperature.quality_status == quality
            assert any(item["code"] == issue for item in temperature.quality_issues)


def test_missing_and_inactive_sources_are_rejected(observation_manager) -> None:
    seed_device(observation_manager)
    pipeline = pipeline_for(observation_manager)

    missing = ingest(
        pipeline,
        adapter_id="missing_adapter",
        state=adapter_state(),
        batch_id="missing-source",
    )
    assert missing.status == "completed"
    assert missing.accepted == 0
    assert missing.invalid >= 1
    assert all(item.status == "invalid" for item in missing.items)
    assert any(
        item.error and item.error["code"] == "OBSERVATION_SOURCE_NOT_FOUND"
        for item in missing.items
    )
    assert observation_count(observation_manager) == 0

    with observation_manager.session_factory() as session:
        source = session.scalars(
            select(ObservationSource).where(ObservationSource.adapter_id == "mock")
        ).one()
        source.status = "paused"
        session.commit()

    inactive = ingest(
        pipeline,
        adapter_id="mock",
        state=adapter_state(),
        batch_id="inactive-source",
    )
    assert inactive.status == "completed"
    assert inactive.accepted == 0
    assert any(
        item.error and item.error["code"] == "OBSERVATION_SOURCE_INACTIVE"
        for item in inactive.items
    )
    assert observation_count(observation_manager) == 0


def test_failed_batch_is_retryable_without_duplicate_observations(observation_manager) -> None:
    seed_device(observation_manager)
    real_service = ObservationService(
        lambda: SqlAlchemyUnitOfWork(observation_manager.session_factory)
    )

    class FlakyService:
        def __init__(self) -> None:
            self.fail = True

        async def record(self, request: Any):
            if self.fail and request.attribute == "temperature":
                raise RuntimeError("simulated persistence failure")
            return await real_service.record(request)

    flaky = FlakyService()
    pipeline = pipeline_for(observation_manager, flaky)  # type: ignore[arg-type]
    state = adapter_state(temperature=68)

    failed = asyncio.run(
        pipeline.ingest_states(
            adapter_id="mock",
            states=[state],
            batch_id="retry-batch",
            received_at=RECEIVED_AT,
        )
    )
    assert failed.status == "failed"
    assert failed.error is not None
    assert observation_count(observation_manager) == 1

    with observation_manager.session_factory() as session:
        batch = session.get(ObservationIngestionBatch, "retry-batch")
        heartbeat = session.get(ObservationSourceHeartbeat, batch.source_id)
        assert batch.status == "failed"
        assert heartbeat.status == "failed"
        assert heartbeat.consecutive_failures == 1
        assert session.scalar(select(func.count()).select_from(DeviceStateRow)) == 0

    flaky.fail = False
    retried = asyncio.run(
        pipeline.ingest_states(
            adapter_id="mock",
            states=[state],
            batch_id="retry-batch",
            received_at=RECEIVED_AT,
        )
    )
    assert retried.status == "completed"
    assert (retried.accepted, retried.deduplicated, retried.sampled) == (1, 0, 1)
    assert observation_count(observation_manager) == 2

    with observation_manager.session_factory() as session:
        batch = session.get(ObservationIngestionBatch, "retry-batch")
        heartbeat = session.get(ObservationSourceHeartbeat, batch.source_id)
        assert batch.status == "completed"
        assert heartbeat.status == "healthy"
        assert heartbeat.consecutive_failures == 0
        assert session.scalar(select(func.count()).select_from(DeviceStateRow)) == 1


def test_retention_cleanup_and_restart_recovery(observation_manager, tmp_path: Path) -> None:
    _device_id, _entity_id, _room_id = seed_device(
        observation_manager,
        external_id="sensor.motion",
        device_type="sensor_motion",
    )
    pipeline = pipeline_for(observation_manager)
    state = DeviceState(
        external_id="sensor.motion",
        state=DeviceStateName.DETECTED,
        attributes={},
        raw_state="detected",
        observed_at=RECEIVED_AT,
        observed_at_source="poll_clock",
    )
    result = ingest(pipeline, adapter_id="mock", state=state, batch_id="motion-first")
    assert result.accepted == 2

    deleted = asyncio.run(pipeline.cleanup_expired(now=RECEIVED_AT + timedelta(days=8), limit=100))
    assert deleted == 1
    with observation_manager.session_factory() as session:
        attributes = list(session.scalars(select(Observation.attribute)))
        assert attributes == ["device_availability"]
        assert session.get(ObservationIngestionBatch, "motion-first") is not None
        heartbeat = session.scalars(select(ObservationSourceHeartbeat)).one()
        assert heartbeat.last_batch_id == "motion-first"

    database_path = Path(observation_manager.engine.url.database).resolve()
    observation_manager.dispose()
    reopened = DatabaseManager(pipeline_settings(database_path.parent.parent))
    try:
        reopened.initialize_database()
        with reopened.session_factory() as session:
            assert session.get(ObservationIngestionBatch, "motion-first") is not None
            assert session.scalars(select(ObservationSourceHeartbeat)).one().status == "healthy"
            assert session.scalar(select(func.count()).select_from(Observation)) == 1
    finally:
        reopened.dispose()
