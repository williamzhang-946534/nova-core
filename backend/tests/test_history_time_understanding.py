import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import aliased

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.history.errors import HistoryNotFoundError, HistoryValidationError
from arvuno_core.history.service import HistoryService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import (
    Entity,
    EntitySpaceAssignment,
    Environment,
    EnvironmentSnapshot,
    Event,
    Observation,
    ObservationSource,
    Space,
    SpacePath,
    Task,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.spatial.service import SpatialService

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
HEADERS = {"Authorization": "Bearer test-api-token"}


def settings(tmp_path: Path) -> Settings:
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
    test_manager = DatabaseManager(settings(tmp_path))
    test_manager.initialize_database()
    yield test_manager
    test_manager.dispose()


def factory(manager: DatabaseManager) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(manager.session_factory)


def service(manager: DatabaseManager) -> HistoryService:
    return HistoryService(lambda: factory(manager), environment_name="home")


def client_for(manager: DatabaseManager, tmp_path: Path) -> TestClient:
    app = create_app(
        settings(tmp_path),
        unit_of_work_factory=lambda: factory(manager),
    )
    return TestClient(app)


def default_environment_id(manager: DatabaseManager) -> str:
    with factory(manager) as unit_of_work:
        assert unit_of_work.environments is not None
        return unit_of_work.environments.ensure_default("home").id


def environment_id(manager: DatabaseManager, space_id: str) -> str:
    with manager.session_factory() as session:
        root_space = aliased(Space)
        statement = (
            select(Environment)
            .join(root_space, Environment.root_space_id == root_space.id)
            .join(SpacePath, SpacePath.ancestor_id == root_space.id)
            .where(SpacePath.descendant_id == space_id)
        )
        return session.scalars(statement).one().id


def create_space(manager: DatabaseManager, name: str, parent_id: str | None = None) -> str:
    spatial = SpatialService(lambda: factory(manager), environment_name="home")
    if parent_id is None:
        parent_id = asyncio.run(spatial.ensure_root()).id
    space = asyncio.run(spatial.create_space(parent_id=parent_id, name=name, space_type="room"))
    return space.id


def create_entity(
    manager: DatabaseManager,
    *,
    name: str,
    space_id: str,
    entity_type: str = "sensor",
    tags: list[str] | None = None,
) -> str:
    entity_id = f"entity-{name.casefold().replace(' ', '-')}"
    device_id = entity_id.replace("entity-", "device-")
    with manager.session_factory() as session:
        session.add(
            Entity(
                id=entity_id,
                environment_id=environment_id(manager, space_id),
                entity_type=entity_type,
                name=name,
                normalized_name=name.casefold(),
                status="active",
                semantic_tags=tags or ["device", "sensor"],
                metadata_summary={"device_id": device_id},
            )
        )
        session.flush()
        session.add(
            EntitySpaceAssignment(
                entity_id=entity_id,
                space_id=space_id,
                assignment_type="fixed_installation",
                valid_from=NOW - timedelta(days=30),
                confidence=1.0,
                source_type="user",
                source_id=device_id,
                reason="history fixture",
            )
        )
        session.commit()
    return entity_id


def add_observation(
    manager: DatabaseManager,
    *,
    entity_id: str,
    space_id: str,
    attribute: str,
    value: Any,
    received_at: datetime,
    observed_at: datetime | None = None,
    collected_time_available: bool = True,
    quality_status: str = "valid",
) -> str:
    observation_id = str(uuid.uuid4())
    collected = (
        observed_at if observed_at is not None or not collected_time_available else received_at
    )
    with manager.session_factory() as session:
        source = session.scalars(
            select(ObservationSource).where(ObservationSource.adapter_id == "mock")
        ).one()
        issues: list[dict[str, Any]] = []
        normalized = value
        if quality_status == "invalid":
            issues = [{"code": "invalid_observation", "severity": "invalid"}]
            normalized = None
        session.add(
            Observation(
                observation_id=observation_id,
                source_id=source.id,
                source_type=source.source_type,
                entity_id=entity_id,
                space_id=space_id,
                attribute=attribute,
                raw_value=value,
                raw_unit="°C" if attribute == "temperature" else None,
                normalized_value=normalized,
                normalized_unit="°C" if attribute == "temperature" else None,
                value_type="number" if attribute in {"temperature", "humidity"} else "enum",
                observed_at=collected,
                observed_at_source="device_clock",
                observed_at_uncertainty_ms=0,
                received_at=received_at,
                processed_at=received_at + timedelta(milliseconds=10),
                quality_status=quality_status,
                quality_issues=issues,
                valid_from=received_at,
                valid_until=received_at + timedelta(minutes=5),
                freshness_policy="valid_300s",
                freshness_evaluated_at=received_at,
                correlation_id=f"correlation-{observation_id}",
                external_id=f"{source.id}:{entity_id}:{attribute}:{observation_id}",
                dedupe_key=hashlib.sha256(observation_id.encode()).hexdigest(),
                payload_hash=hashlib.sha256(str(value).encode()).hexdigest(),
                normalization_rule_version="1.0.0",
                retention_class="standard_30d",
                retention_until=received_at + timedelta(days=30),
            )
        )
        session.commit()
    return observation_id


def add_event(
    manager: DatabaseManager,
    *,
    event_id: str,
    occurred_at: datetime,
    subject_id: str | None = None,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> None:
    with manager.session_factory() as session:
        session.add(
            Event(
                id=event_id,
                event_type="device_state_changed",
                source="mock",
                subject_type="entity",
                subject_id=subject_id,
                payload=payload or {},
                correlation_id=correlation_id,
                occurred_at=occurred_at,
                created_at=occurred_at + timedelta(seconds=1),
            )
        )
        session.commit()


def add_task(
    manager: DatabaseManager,
    *,
    task_id: str,
    created_at: datetime,
    correlation_id: str | None = None,
) -> None:
    with manager.session_factory() as session:
        session.add(
            Task(
                id=task_id,
                task_type="device_control",
                title="Close the air conditioner",
                status="completed",
                origin="user",
                plan={"steps": []},
                result={"ok": True},
                error=None,
                correlation_id=correlation_id,
                created_at=created_at,
                started_at=created_at,
                completed_at=created_at + timedelta(seconds=2),
            )
        )
        session.commit()


def add_snapshot(
    manager: DatabaseManager,
    *,
    snapshot_id: str,
    created_at: datetime,
    context: dict[str, Any],
) -> None:
    with manager.session_factory() as session:
        session.add(
            EnvironmentSnapshot(
                id=snapshot_id,
                environment_id=default_environment_id(manager),
                context=context,
                active_task_ids=[],
                anomaly_count=0,
                context_version=1,
                state_generated_at=created_at - timedelta(seconds=1),
                created_at=created_at,
            )
        )
        session.commit()


def test_history_api_requires_authorization(manager: DatabaseManager, tmp_path: Path) -> None:
    client = client_for(manager, tmp_path)
    params = {
        "start_time": "2026-11-02T00:00:00+00:00",
        "end_time": "2026-11-02T01:00:00+00:00",
    }

    missing = client.get("/api/history/time-range", params=params)
    rejected = client.get(
        "/api/history/time-range",
        headers={"Authorization": "Bearer wrong-token"},
        params=params,
    )

    assert missing.status_code == 401
    assert rejected.status_code == 401


def test_time_range_local_boundary_selection_and_missing_interval(
    manager: DatabaseManager,
) -> None:
    root = create_space(manager, "Home")
    living = create_space(manager, "Living room", root)
    entity = create_entity(manager, name="Living sensor", space_id=living)
    first = add_observation(
        manager,
        entity_id=entity,
        space_id=living,
        attribute="temperature",
        value=22,
        received_at=datetime(2026, 11, 2, 16, 10, tzinfo=UTC),
    )
    add_observation(
        manager,
        entity_id=entity,
        space_id=living,
        attribute="temperature",
        value=23,
        received_at=datetime(2026, 11, 2, 17, 10, tzinfo=UTC),
    )

    result = asyncio.run(
        service(manager).time_range(
            start_time=datetime(2026, 11, 2, 16, tzinfo=UTC),
            end_time=datetime(2026, 11, 2, 17, tzinfo=UTC),
            timezone="Asia/Shanghai",
            expected_interval_seconds=600,
        )
    )

    assert result.range.local_start_time == "2026-11-03T00:00:00+08:00"
    assert [record.record_id for record in result.records] == [first]
    assert result.records[0].local_time == "2026-11-03T00:10:00+08:00"
    assert result.missing_ranges[0].duration_seconds == 3000


def test_time_semantics_reports_late_future_and_missing_collected_time(
    manager: DatabaseManager,
) -> None:
    root = create_space(manager, "Home")
    bedroom = create_space(manager, "Bedroom", root)
    entity = create_entity(manager, name="Bedroom sensor", space_id=bedroom)
    late = add_observation(
        manager,
        entity_id=entity,
        space_id=bedroom,
        attribute="temperature",
        value=20,
        received_at=NOW,
        observed_at=NOW - timedelta(minutes=5),
    )
    future = add_observation(
        manager,
        entity_id=entity,
        space_id=bedroom,
        attribute="temperature",
        value=21,
        received_at=NOW,
        observed_at=NOW + timedelta(minutes=5),
    )
    missing = add_observation(
        manager,
        entity_id=entity,
        space_id=bedroom,
        attribute="temperature",
        value=22,
        received_at=NOW + timedelta(minutes=1),
        observed_at=None,
        collected_time_available=False,
    )

    result = asyncio.run(
        service(manager).time_range(
            start_time=NOW - timedelta(minutes=1),
            end_time=NOW + timedelta(minutes=2),
        )
    )

    assert result.time_semantics.late_observations == [late]
    assert result.time_semantics.future_clock_skew_observations == [future]
    assert result.time_semantics.observations_without_collected_time == [missing]
    assert result.warnings[0].startswith("Observations are selected by received_at")


def test_spatial_history_includes_descendants_and_entity_history(
    manager: DatabaseManager,
) -> None:
    root = create_space(manager, "Home")
    living = create_space(manager, "Living room", root)
    entity = create_entity(manager, name="Living light", space_id=living)
    observation = add_observation(
        manager,
        entity_id=entity,
        space_id=living,
        attribute="actuator_state",
        value="on",
        received_at=NOW,
    )
    add_event(
        manager,
        event_id="event-power-on",
        occurred_at=NOW,
        subject_id=entity,
        payload={"state": "on"},
    )

    spatial = asyncio.run(
        service(manager).spatial_history(
            root,
            start_time=NOW - timedelta(minutes=1),
            end_time=NOW + timedelta(minutes=1),
        )
    )
    entity_history = asyncio.run(
        service(manager).entity_history(
            entity,
            start_time=NOW - timedelta(minutes=1),
            end_time=NOW + timedelta(minutes=1),
        )
    )

    assert spatial.descendants == [living]
    assert spatial.assignments_in_range[0]["entity_id"] == entity
    assert {record.record_id for record in spatial.records} >= {observation, "event-power-on"}
    assert entity_history.entity_name == "Living light"
    assert entity_history.device_id == "device-living-light"
    assert entity_history.space_assignments[0]["space_id"] == living


def test_trends_rank_spaces_and_ignore_invalid_values(manager: DatabaseManager) -> None:
    root = create_space(manager, "Home")
    living = create_space(manager, "Living room", root)
    bedroom = create_space(manager, "Bedroom", root)
    living_entity = create_entity(manager, name="Living humidity", space_id=living)
    bedroom_entity = create_entity(manager, name="Bedroom humidity", space_id=bedroom)
    add_observation(
        manager,
        entity_id=living_entity,
        space_id=living,
        attribute="humidity",
        value=60,
        received_at=NOW - timedelta(hours=1),
    )
    add_observation(
        manager,
        entity_id=bedroom_entity,
        space_id=bedroom,
        attribute="humidity",
        value=70,
        received_at=NOW - timedelta(hours=2),
    )
    add_observation(
        manager,
        entity_id=bedroom_entity,
        space_id=bedroom,
        attribute="humidity",
        value=None,
        received_at=NOW - timedelta(minutes=30),
        quality_status="invalid",
    )

    result = asyncio.run(
        service(manager).trends(
            start_time=NOW - timedelta(days=1),
            end_time=NOW,
            attribute="humidity",
        )
    )

    assert [item.group_key for item in result.statistics] == [living, bedroom]
    assert result.statistics[1].valid_count == 1
    assert result.statistics[1].average == 70


def test_snapshot_lookup_warns_and_diff_separates_device_and_physical_changes(
    manager: DatabaseManager,
) -> None:
    baseline_context = {
        "devices": {"ac": {"name": "Air conditioner", "state": "on"}},
        "sensors": {"temp": {"sensor_type": "temperature", "value": 22, "unit": "°C"}},
    }
    target_context = {
        "devices": {"ac": {"name": "Air conditioner", "state": "off"}},
        "sensors": {"temp": {"sensor_type": "temperature", "value": 24, "unit": "°C"}},
    }
    add_snapshot(
        manager,
        snapshot_id="snapshot-before",
        created_at=NOW - timedelta(minutes=30),
        context=baseline_context,
    )
    add_snapshot(
        manager,
        snapshot_id="snapshot-after",
        created_at=NOW,
        context=target_context,
    )

    missing = asyncio.run(service(manager).snapshot_at(at_time=NOW - timedelta(hours=2)))
    diff = asyncio.run(
        service(manager).snapshot_diff(
            baseline_id="snapshot-before",
            target_id="snapshot-after",
        )
    )

    assert missing.snapshot is None
    assert missing.warning is not None
    changes = {change.path: change for change in diff.changes}
    assert changes["/devices/ac/state"].recoverable_by_device is True
    assert changes["/sensors/temp/value"].recoverability == "physical_observation"
    assert changes["/sensors/temp/value"].physical_rollback_possible is False
    assert diff.reality_git["rollback"].startswith("Device commands may restore")


def test_correlate_observation_with_event_and_task(manager: DatabaseManager) -> None:
    root = create_space(manager, "Home")
    living = create_space(manager, "Living room", root)
    entity = create_entity(manager, name="Living climate", space_id=living, tags=["climate"])
    observation = add_observation(
        manager,
        entity_id=entity,
        space_id=living,
        attribute="temperature",
        value=25,
        received_at=NOW,
    )
    with manager.session_factory() as session:
        row = session.get(Observation, observation)
        row.correlation_id = "shared-action"
        session.commit()
    add_event(
        manager,
        event_id="event-shared-action",
        occurred_at=NOW,
        subject_id=entity,
        payload={"state": "off"},
        correlation_id="shared-action",
    )
    add_task(
        manager,
        task_id="task-shared-action",
        created_at=NOW - timedelta(seconds=1),
        correlation_id="shared-action",
    )

    result = asyncio.run(
        service(manager).correlate(record_type="observation", record_id=observation)
    )

    assert result.record.record_id == observation
    assert result.events[0].record_id == "event-shared-action"
    assert result.tasks[0].record_id == "task-shared-action"
    assert result.observations[0].record_id == observation
    assert result.warnings


def test_natural_language_answers_are_based_on_retained_records(
    manager: DatabaseManager,
) -> None:
    root = create_space(manager, "Home")
    living = create_space(manager, "Living room", root)
    bedroom = create_space(manager, "Bedroom", root)
    living_sensor = create_entity(manager, name="Living sensor", space_id=living)
    bedroom_sensor = create_entity(manager, name="Bedroom sensor", space_id=bedroom)
    climate = create_entity(
        manager,
        name="Air conditioner",
        space_id=living,
        entity_type="climate",
        tags=["device", "climate"],
    )
    yesterday_event = datetime(2026, 11, 2, 2, 0, tzinfo=UTC)
    add_event(
        manager,
        event_id="event-living-yesterday",
        occurred_at=yesterday_event,
        subject_id=living_sensor,
        payload={"state": "on"},
    )
    add_observation(
        manager,
        entity_id=living_sensor,
        space_id=living,
        attribute="humidity",
        value=60,
        received_at=datetime(2026, 11, 2, 5, 0, tzinfo=UTC),
    )
    add_observation(
        manager,
        entity_id=bedroom_sensor,
        space_id=bedroom,
        attribute="humidity",
        value=70,
        received_at=datetime(2026, 11, 2, 5, 0, tzinfo=UTC),
    )
    add_event(
        manager,
        event_id="event-ac-off",
        occurred_at=datetime(2026, 11, 2, 7, 0, tzinfo=UTC),
        subject_id=climate,
        payload={"state": "off"},
    )
    add_observation(
        manager,
        entity_id=climate,
        space_id=living,
        attribute="temperature",
        value=27,
        received_at=datetime(2026, 11, 2, 6, 55, tzinfo=UTC),
    )
    add_observation(
        manager,
        entity_id=climate,
        space_id=living,
        attribute="temperature",
        value=25,
        received_at=datetime(2026, 11, 2, 7, 20, tzinfo=UTC),
    )
    add_snapshot(
        manager,
        snapshot_id="snapshot-leaving-home",
        created_at=datetime(2026, 11, 2, 12, 0, tzinfo=UTC),
        context={"devices": {"light": {"name": "Light", "state": "on"}}},
    )
    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    ask = service(manager).ask

    events = asyncio.run(ask("昨天客厅发生了什么？", timezone="Asia/Shanghai", now=now))
    ranking = asyncio.run(ask("过去七天哪个房间最潮湿？", timezone="Asia/Shanghai", now=now))
    trend = asyncio.run(
        ask("昨天下午关闭空调之后，温度变化如何？", timezone="Asia/Shanghai", now=now)
    )
    running = asyncio.run(
        ask("昨天晚上离开家时，有哪些设备还在运行？", timezone="Asia/Shanghai", now=now)
    )

    assert events.interpretation.question_type == "events_in_space"
    assert events.interpretation.space_id == living
    assert events.records[0].record_id == "event-living-yesterday"
    assert ranking.interpretation.question_type == "space_ranking"
    assert "Bedroom" in ranking.answer
    assert trend.interpretation.question_type == "entity_attribute_trend"
    assert trend.interpretation.action_resolved is True
    assert trend.answer.startswith("记录显示 temperature 从 27.00 变为 25.00")
    assert running.interpretation.question_type == "running_devices"
    assert "Light=on" in running.answer


def test_natural_language_rejects_unknown_pattern_and_naive_time(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    client = client_for(manager, tmp_path)

    unsupported = client.post(
        "/api/history/ask",
        headers=HEADERS,
        json={"query": "明天会发生什么？", "timezone": "Asia/Shanghai"},
    )
    naive = client.get(
        "/api/history/time-range",
        headers=HEADERS,
        params={
            "start_time": "2026-11-02T00:00:00",
            "end_time": "2026-11-02T01:00:00Z",
        },
    )
    direct = HistoryService(lambda: factory(manager))

    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == "HISTORY_QUERY_UNSUPPORTED"
    assert naive.status_code == 400
    with pytest.raises(HistoryValidationError):
        asyncio.run(
            direct.time_range(
                start_time=datetime(2026, 11, 2),
                end_time=datetime(2026, 11, 2, 1, tzinfo=UTC),
            )
        )
    with pytest.raises(HistoryNotFoundError):
        asyncio.run(
            direct.spatial_history(
                "missing-space",
                start_time=datetime(2026, 11, 2, tzinfo=UTC),
                end_time=datetime(2026, 11, 2, 1, tzinfo=UTC),
            )
        )
