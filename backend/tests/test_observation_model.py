import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.observations.errors import ObservationError
from arvuno_core.observations.models import ObservationInput
from arvuno_core.observations.service import ObservationService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import Device, DeviceState, Observation, Space
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.spatial.service import SpatialService

RECEIVED_AT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def observation_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


@pytest.fixture
def manager(tmp_path: Path):
    test_manager = DatabaseManager(observation_settings(tmp_path))
    test_manager.initialize_database()
    yield test_manager
    test_manager.dispose()


def seed_home_and_device(
    test_manager: DatabaseManager,
    *,
    device_id: str = "device-observation",
) -> tuple[Device, Space, str, str]:
    spatial = SpatialService(lambda: SqlAlchemyUnitOfWork(test_manager.session_factory))
    root = asyncio.run(spatial.ensure_root())
    room = asyncio.run(
        spatial.create_space(parent_id=root.id, name="Living Room", space_type="room")
    )
    with test_manager.session_factory() as session:
        environment = session.execute(
            text("SELECT id FROM environments WHERE is_default = 1")
        ).scalar_one()
        from arvuno_core.persistence.models import Entity, ObservationSource

        entity = Entity(
            id=f"entity-{device_id}",
            environment_id=environment,
            entity_type="sensor",
            name="Living Room Sensor",
            normalized_name="living room sensor",
            status="active",
            semantic_tags=["device", "sensor_temperature"],
            metadata_summary={},
        )
        device = Device(
            id=device_id,
            adapter_id="mock",
            external_id="sensor.external",
            name="Living Room Sensor",
            normalized_name="living room sensor",
            device_type="sensor_temperature",
            area=None,
            entity_id=entity.id,
            is_online=True,
            is_enabled=True,
            risk_level="low",
            capabilities={},
            metadata_summary={},
            last_seen_at=RECEIVED_AT,
        )
        session.add(entity)
        session.flush()
        session.add(device)
        state = DeviceState(
            id="legacy-state",
            device_id=device.id,
            state="on",
            attributes={"legacy": True},
            raw_state="on",
            source="mock",
            observed_at=RECEIVED_AT - timedelta(minutes=10),
        )
        session.add(state)
        session.commit()
        session.refresh(device)
        mock_source_id = session.scalar(
            select(ObservationSource.id).where(ObservationSource.adapter_id == "mock")
        )
        assert mock_source_id is not None
        return device, room, str(entity.id), mock_source_id


def observation(
    *,
    attribute: str = "temperature",
    raw_value: object = 21.5,
    raw_unit: str | None = "°C",
    observed_at: datetime | None = RECEIVED_AT - timedelta(seconds=10),
    observed_at_source: str | None = "device_clock",
    external_id: str | None = None,
    received_at: datetime = RECEIVED_AT,
    **overrides: object,
) -> ObservationInput:
    values: dict[str, object] = {
        "adapter_id": "mock",
        "device_external_id": "sensor.external",
        "attribute": attribute,
        "raw_value": raw_value,
        "raw_unit": raw_unit,
        "observed_at": observed_at,
        "observed_at_source": observed_at_source,
        "received_at": received_at,
        "external_id": external_id,
    }
    values.update(overrides)
    return ObservationInput.model_validate(values)


def test_valid_observation_normalizes_persists_and_survives_restart(manager) -> None:
    device, room, entity_id, _mock_source_id = seed_home_and_device(manager)
    service = ObservationService(lambda: SqlAlchemyUnitOfWork(manager.session_factory))

    result = asyncio.run(
        service.record(
            observation(
                external_id="ha-event-1",
                space_id=room.id,
                observed_at_uncertainty_ms=100,
            )
        )
    )
    record = result.data
    assert result.duplicate is False
    assert record.source_type == "adapter"
    assert record.entity_id == entity_id
    assert record.subject_type is None and record.subject_id is None
    assert record.space_id == room.id
    assert record.attribute == "temperature"
    assert record.raw_value == 21.5
    assert record.raw_unit == "°C"
    assert record.normalized_value == 21.5
    assert record.normalized_unit == "°C"
    assert record.observed_at == RECEIVED_AT - timedelta(seconds=10)
    assert record.observed_at_source == "device_clock"
    assert record.received_at == RECEIVED_AT
    assert record.processed_at is not None
    assert record.quality_status == "valid"
    assert record.quality_issues == []
    assert record.valid_from == record.observed_at
    assert record.valid_until == record.observed_at + timedelta(seconds=300)
    assert record.normalization_rule_version == "1.0.0"
    assert record.retention_class == "standard_30d"
    assert device.entity_id == entity_id

    database_path = Path(manager.engine.url.database).resolve()
    manager.dispose()
    reopened = DatabaseManager(observation_settings(database_path.parent.parent))
    try:
        reopened.initialize_database()
        restarted = ObservationService(lambda: SqlAlchemyUnitOfWork(reopened.session_factory))
        loaded = asyncio.run(restarted.get(record.observation_id))
        assert loaded.dedupe_key == record.dedupe_key
        assert loaded.payload_hash == record.payload_hash
    finally:
        reopened.dispose()


def test_unit_and_enum_normalization_preserves_raw_values(manager) -> None:
    _, _, entity_id, _mock_source_id = seed_home_and_device(manager)
    service = ObservationService(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
    cases = [
        ("temperature", 68, "°F", 20, "°C"),
        ("humidity", 45, "%", 45, "%RH"),
        ("motion", "on", None, True, None),
        ("contact", "closed", None, "closed", None),
        ("device_availability", "unavailable", None, "offline", None),
    ]
    for index, (attribute, raw, unit, normalized, normalized_unit) in enumerate(cases):
        result = asyncio.run(
            service.record(
                observation(
                    attribute=attribute,
                    raw_value=raw,
                    raw_unit=unit,
                    external_id=f"normalization-{index}",
                )
            )
        )
        assert result.data.quality_status == "valid"
        assert result.data.raw_value == raw
        assert result.data.raw_unit == unit
        assert result.data.normalized_value == normalized
        assert result.data.normalized_unit == normalized_unit
        assert result.data.entity_id == entity_id


def test_time_sources_are_distinguished_and_not_fabricated(manager) -> None:
    seed_home_and_device(manager)
    service = ObservationService(lambda: SqlAlchemyUnitOfWork(manager.session_factory))

    device_clock = asyncio.run(
        service.record(observation(external_id="device-clock", observed_at_uncertainty_ms=250))
    )
    assert device_clock.data.observed_at is not None
    assert device_clock.data.observed_at_source == "device_clock"

    gateway_clock = asyncio.run(
        service.record(
            observation(
                external_id="gateway-clock",
                observed_at_source="gateway_state_clock",
            )
        )
    )
    assert gateway_clock.data.observed_at is not None
    assert gateway_clock.data.observed_at_source == "gateway_state_clock"

    no_time = asyncio.run(
        service.record(
            observation(
                observed_at=None,
                observed_at_source=None,
                external_id="poll-event",
            )
        )
    )
    assert no_time.data.observed_at is None
    assert no_time.data.observed_at_source == "poll_clock"
    assert no_time.data.received_at == RECEIVED_AT
    assert no_time.data.valid_from == RECEIVED_AT
    assert any(
        issue["code"] == "unreliable_observation_time" for issue in no_time.data.quality_issues
    )
    assert no_time.data.quality_status == "warning"


def test_dedupe_is_idempotent_for_external_and_time_keys(manager) -> None:
    seed_home_and_device(manager)
    service = ObservationService(lambda: SqlAlchemyUnitOfWork(manager.session_factory))

    external_first = asyncio.run(service.record(observation(external_id="event-id")))
    external_second = asyncio.run(
        service.record(
            observation(
                external_id="event-id",
                received_at=RECEIVED_AT + timedelta(minutes=5),
            )
        )
    )
    assert external_second.duplicate is True
    assert external_second.data.observation_id == external_first.data.observation_id

    time_first = asyncio.run(service.record(observation()))
    time_second = asyncio.run(service.record(observation()))
    assert time_second.duplicate is True
    assert time_second.data.observation_id == time_first.data.observation_id

    with manager.session_factory() as session:
        count = session.scalar(select(func.count()).select_from(Observation))
        assert count == 2


def test_abnormal_observations_are_marked_not_silently_normalized(manager) -> None:
    seed_home_and_device(manager)
    service = ObservationService(lambda: SqlAlchemyUnitOfWork(manager.session_factory))

    delayed = asyncio.run(
        service.record(
            observation(
                external_id="delayed",
                observed_at=RECEIVED_AT - timedelta(minutes=7),
            )
        )
    )
    assert delayed.data.observed_at == RECEIVED_AT - timedelta(minutes=7)
    assert delayed.data.quality_status == "warning"
    delayed_issue = next(
        issue for issue in delayed.data.quality_issues if issue["code"] == "delayed_observation"
    )
    assert delayed_issue["observed_delay_seconds"] == 420
    assert delayed_issue["threshold_seconds"] == 300

    out_of_range = asyncio.run(service.record(observation(external_id="range", raw_value=120)))
    assert out_of_range.data.quality_status == "invalid"
    assert any(issue["code"] == "value_out_of_range" for issue in out_of_range.data.quality_issues)

    type_mismatch = asyncio.run(service.record(observation(external_id="type", raw_value="hot")))
    assert type_mismatch.data.quality_status == "invalid"
    assert type_mismatch.data.normalized_value is None
    assert type_mismatch.data.raw_value == "hot"

    missing_unit = asyncio.run(service.record(observation(external_id="unit", raw_unit=None)))
    assert missing_unit.data.quality_status == "warning"
    assert missing_unit.data.normalized_value is None
    assert missing_unit.data.raw_unit is None
    assert any(
        issue["code"] == "missing_required_unit" for issue in missing_unit.data.quality_issues
    )


def test_missing_source_subject_space_and_attribute_are_rejected(manager) -> None:
    _, _, _, mock_source_id = seed_home_and_device(manager)
    service = ObservationService(lambda: SqlAlchemyUnitOfWork(manager.session_factory))

    with pytest.raises(ObservationError, match="registered source"):
        asyncio.run(
            service.record(
                ObservationInput(
                    subject_type="space",
                    subject_id="space-subject",
                    attribute="temperature",
                    raw_value=21,
                    raw_unit="°C",
                    received_at=RECEIVED_AT,
                )
            )
        )

    with pytest.raises(ObservationError, match="source does not exist"):
        asyncio.run(
            service.record(
                ObservationInput(
                    source_id="missing-source",
                    subject_type="space",
                    subject_id="space-subject",
                    attribute="temperature",
                    raw_value=21,
                    raw_unit="°C",
                    received_at=RECEIVED_AT,
                )
            )
        )

    with pytest.raises(ObservationError, match="entity does not exist"):
        asyncio.run(
            service.record(
                observation(
                    source_id=mock_source_id,
                    adapter_id=None,
                    device_external_id=None,
                    entity_id="missing-entity",
                )
            )
        )

    with pytest.raises(ObservationError, match="controlled observation"):
        asyncio.run(
            service.record(
                observation(attribute="current_temperature", external_id="bad-attribute")
            )
        )

    with pytest.raises(ObservationError, match="space does not exist"):
        asyncio.run(service.record(observation(space_id="missing-space")))


def test_query_filters_pagination_and_legacy_state_is_untouched(manager) -> None:
    device, room, entity_id, _mock_source_id = seed_home_and_device(
        manager, device_id="query-device"
    )
    service = ObservationService(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
    observations = []
    for index in range(3):
        observations.append(
            asyncio.run(
                service.record(
                    observation(
                        attribute="humidity",
                        raw_value=40 + index,
                        raw_unit="%",
                        external_id=f"query-{index}",
                        space_id=room.id,
                        received_at=RECEIVED_AT - timedelta(seconds=2 - index),
                    )
                )
            ).data
        )

    page = asyncio.run(
        service.query(
            entity_id=entity_id,
            attribute="humidity",
            space_id=room.id,
            page=1,
            page_size=2,
        )
    )
    assert page.total == 3
    assert len(page.data) == 2
    assert page.data[0].external_id == "query-2"

    filtered = asyncio.run(service.query(correlation_id="missing"))
    assert filtered.total == 0

    detail = asyncio.run(service.get(observations[0].observation_id))
    assert detail.source_id == observations[0].source_id

    with manager.session_factory() as session:
        states = list(session.scalars(select(DeviceState)))
        assert len(states) == 1
        assert states[0].id == "legacy-state"
        assert states[0].attributes == {"legacy": True}
        assert states[0].device_id == device.id


def test_observation_api_hides_raw_by_default(manager, tmp_path: Path) -> None:
    _, room, _, _mock_source_id = seed_home_and_device(manager)
    service = ObservationService(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
    record = asyncio.run(
        service.record(observation(external_id="api-event", space_id=room.id))
    ).data
    app = create_app(
        observation_settings(tmp_path),
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
    )

    with TestClient(app) as client:
        unauthorized = client.get("/api/observations")
        assert unauthorized.status_code == 401

        headers = {"Authorization": "Bearer test-api-token"}
        listed = client.get("/api/observations", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["data"][0]["raw_value"] is None

        detail = client.get(
            f"/api/observations/{record.observation_id}",
            headers=headers,
            params={"include_raw": True},
        )
        assert detail.status_code == 200
        assert detail.json()["data"]["raw_value"] == 21.5

        sources = client.get("/api/observation-sources", headers=headers)
        assert sources.status_code == 200
        assert {source["adapter_id"] for source in sources.json()["data"]} == {
            "home_assistant",
            "mock",
        }
