import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from arvuno_core.ai.mock import MockAIProvider
from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.environment.query import EnvironmentQueryService
from arvuno_core.environment.query_models import EnvironmentStateQueryInput
from arvuno_core.estimation.service import StateEstimationService
from arvuno_core.observations.service import ObservationService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import (
    Device,
    Entity,
    EntitySpaceAssignment,
    Environment,
    Observation,
    ObservationSource,
)
from arvuno_core.persistence.provider_logs import SqlProviderLogStore
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.spatial.service import SpatialService

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
HEADERS = {"Authorization": "Bearer test-api-token"}


def query_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


@pytest.fixture
def query_manager(tmp_path: Path):
    manager = DatabaseManager(query_settings(tmp_path))
    manager.initialize_database()
    yield manager
    manager.dispose()


def factory(manager: DatabaseManager) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(manager.session_factory)


def estimation_parts(
    manager: DatabaseManager,
) -> tuple[StateEstimationService, EnvironmentQueryService]:
    estimation = StateEstimationService(lambda: factory(manager), environment_name="home")
    query = EnvironmentQueryService(
        lambda: factory(manager),
        estimation,
        environment_name="home",
    )
    return estimation, query


def seed_space_with_entity(
    manager: DatabaseManager,
    *,
    name: str,
    parent_id: str | None = None,
    space_type: str = "room",
    device_type: str = "sensor_temperature",
) -> tuple[str, str]:
    spatial = SpatialService(lambda: factory(manager), environment_name="home")
    parent_id = parent_id or asyncio.run(spatial.ensure_root()).id
    space = asyncio.run(
        spatial.create_space(
            parent_id=parent_id,
            name=f"Space {name}",
            space_type=space_type,
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
            semantic_tags=["device", device_type],
            metadata_summary={},
        )
        session.add(entity)
        session.flush()
        session.add(
            Device(
                id=f"device-{name}",
                adapter_id="mock",
                external_id=name,
                name=name,
                normalized_name=name.casefold(),
                device_type=device_type,
                area=space.name,
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
                space_id=space.id,
                assignment_type="fixed_installation",
                valid_from=NOW - timedelta(days=1),
                confidence=1.0,
                source_type="user",
                source_id=f"device-{name}",
                reason="environment query fixture",
            )
        )
        session.commit()
        return entity.id, space.id


def seed_observation(
    manager: DatabaseManager,
    *,
    entity_id: str,
    space_id: str,
    attribute: str,
    value: Any,
    received_at: datetime = NOW,
    observed_at: datetime | None = NOW,
    quality_status: str = "valid",
    valid_seconds: int = 300,
) -> str:
    observation_id = str(uuid.uuid4())
    with manager.session_factory() as session:
        source = session.scalars(
            select(ObservationSource).where(ObservationSource.adapter_id == "mock")
        ).one()
        value_types = {
            "temperature": "number",
            "contact": "enum",
            "motion": "boolean",
            "device_availability": "enum",
        }
        units = {"temperature": "°C"}
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
                raw_unit=units.get(attribute),
                normalized_value=normalized,
                normalized_unit=units.get(attribute),
                value_type=value_types[attribute],
                observed_at=observed_at,
                observed_at_source="device_clock" if observed_at else "poll_clock",
                observed_at_uncertainty_ms=0 if observed_at else None,
                received_at=received_at,
                processed_at=received_at + timedelta(milliseconds=10),
                quality_status=quality_status,
                quality_issues=issues,
                valid_from=received_at,
                valid_until=received_at + timedelta(seconds=valid_seconds),
                freshness_policy=f"valid_{valid_seconds}s",
                freshness_evaluated_at=received_at,
                correlation_id=f"query-{observation_id}",
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


def root_space(manager: DatabaseManager) -> str:
    spatial = SpatialService(lambda: factory(manager), environment_name="home")
    return asyncio.run(spatial.ensure_root()).id


def test_environment_query_filters_descendants_paths_attributes_and_evidence(
    query_manager,
) -> None:
    root = root_space(query_manager)
    living_entity, living = seed_space_with_entity(query_manager, name="living-temp")
    _, dining = seed_space_with_entity(query_manager, name="dining-empty")
    seed_observation(
        query_manager,
        entity_id=living_entity,
        space_id=living,
        attribute="temperature",
        value=22.5,
    )
    estimation, service = estimation_parts(query_manager)
    asyncio.run(estimation.rebuild(NOW))

    root_result = asyncio.run(
        service.query(
            EnvironmentStateQueryInput(
                include_descendants=True,
                include_evidence=True,
                attributes=["temperature", "contact"],
            ),
            now=NOW,
        )
    )
    assert {space.space_id for space in root_result.spaces} == {root, living, dining}
    assert {entity.entity_id for entity in root_result.entities} == {
        living_entity,
        "entity-dining-empty",
    }
    assert root_result.states
    assert root_result.evidence
    assert all(item.attribute == "temperature" for item in root_result.evidence)
    assert root_result.coverage == [
        item for item in root_result.coverage if item.attribute in {"temperature", "contact"}
    ]

    exact = asyncio.run(
        service.query(
            EnvironmentStateQueryInput(space_id=root, include_descendants=False),
            now=NOW,
        )
    )
    assert [space.space_id for space in exact.spaces] == [root]
    assert exact.entities == []

    room_path = "/".join(
        next(space.path for space in root_result.spaces if space.space_id == living)
    )
    by_path = asyncio.run(
        service.query(
            EnvironmentStateQueryInput(space_path=room_path),
            now=NOW,
        )
    )
    assert by_path.selected_space is not None
    assert by_path.selected_space.space_id == living
    assert {space.space_id for space in by_path.spaces} == {living}

    filtered = asyncio.run(
        service.query(
            EnvironmentStateQueryInput(space_id=root, attributes=["contact"]),
            now=NOW,
        )
    )
    assert filtered.attributes == ["contact"]
    assert not filtered.states


def test_environment_query_accepts_exact_space_name_as_conservative_fallback(
    query_manager,
) -> None:
    spatial = SpatialService(lambda: factory(query_manager), environment_name="home")
    root = asyncio.run(spatial.ensure_root()).id
    room = asyncio.run(spatial.create_space(parent_id=root, name="客厅", space_type="room"))
    _, service = estimation_parts(query_manager)

    result = asyncio.run(
        service.query(
            EnvironmentStateQueryInput(space_path="客厅", include_descendants=True),
            now=NOW,
        )
    )

    assert result.selected_space is not None
    assert result.selected_space.space_id == room.id


def test_coverage_preserves_all_state_semantics(query_manager) -> None:
    conflict_a, conflict_room = seed_space_with_entity(
        query_manager, name="contact-a", device_type="sensor_contact"
    )
    conflict_b, _ = seed_space_with_entity(
        query_manager, name="contact-b", device_type="sensor_contact"
    )
    seed_observation(
        query_manager,
        entity_id=conflict_a,
        space_id=conflict_room,
        attribute="contact",
        value="open",
        valid_seconds=600,
    )
    seed_observation(
        query_manager,
        entity_id=conflict_b,
        space_id=conflict_room,
        attribute="contact",
        value="closed",
        valid_seconds=600,
    )

    motion_entity, motion_room = seed_space_with_entity(
        query_manager, name="motion", device_type="sensor_motion"
    )
    seed_observation(
        query_manager,
        entity_id=motion_entity,
        space_id=motion_room,
        attribute="motion",
        value=True,
        valid_seconds=600,
    )

    stale_entity, stale_room = seed_space_with_entity(query_manager, name="stale")
    seed_observation(
        query_manager,
        entity_id=stale_entity,
        space_id=stale_room,
        attribute="temperature",
        value=20.0,
    )

    offline_entity, offline_room = seed_space_with_entity(query_manager, name="offline")
    seed_observation(
        query_manager,
        entity_id=offline_entity,
        space_id=offline_room,
        attribute="temperature",
        value=20.0,
    )
    seed_observation(
        query_manager,
        entity_id=offline_entity,
        space_id=offline_room,
        attribute="device_availability",
        value="offline",
    )

    invalid_entity, invalid_room = seed_space_with_entity(query_manager, name="invalid")
    seed_observation(
        query_manager,
        entity_id=invalid_entity,
        space_id=invalid_room,
        attribute="temperature",
        value="hot",
        quality_status="invalid",
    )

    estimation, service = estimation_parts(query_manager)
    asyncio.run(estimation.rebuild(NOW))
    result = asyncio.run(
        service.query(
            EnvironmentStateQueryInput(
                attributes=["contact", "occupancy", "temperature"],
                include_descendants=True,
            ),
            now=NOW,
        )
    )
    coverage = {(item.space_id, item.attribute): item for item in result.coverage}
    assert coverage[(conflict_room, "contact")].coverage == "partial"
    assert coverage[(conflict_room, "contact")].state_status == "conflict"
    assert coverage[(motion_room, "occupancy")].coverage == "partial"
    assert coverage[(motion_room, "occupancy")].state_status == "inferred"
    assert coverage[(stale_room, "temperature")].coverage == "covered"
    assert coverage[(offline_room, "temperature")].coverage == "covered"
    assert coverage[(invalid_room, "temperature")].coverage == "blind"
    assert coverage[(invalid_room, "temperature")].state_status == "unknown"

    statuses = {state.status for state in result.states}
    assert {"observed", "inferred", "unknown", "unavailable", "conflict"}.issubset(statuses)
    later_result = asyncio.run(
        service.query(
            EnvironmentStateQueryInput(attributes=["temperature"]),
            now=NOW + timedelta(minutes=6),
        )
    )
    later_coverage = {(item.space_id, item.attribute): item for item in later_result.coverage}
    assert later_coverage[(stale_room, "temperature")].coverage == "lost"
    assert later_coverage[(stale_room, "temperature")].state_status == "stale"


def test_space_overview_coverage_and_observation_apis(query_manager, tmp_path: Path) -> None:
    root = root_space(query_manager)
    entity, room = seed_space_with_entity(query_manager, name="api-temp")
    observation_id = seed_observation(
        query_manager,
        entity_id=entity,
        space_id=room,
        attribute="temperature",
        value=21.0,
    )
    estimation, _ = estimation_parts(query_manager)
    asyncio.run(estimation.rebuild(NOW))
    app = create_app(
        query_settings(tmp_path),
        unit_of_work_factory=lambda: factory(query_manager),
    )

    with TestClient(app) as client:
        unauthenticated = client.get(f"/api/spaces/{root}/overview")
        assert unauthenticated.status_code == 401

        overview = client.get(
            f"/api/spaces/{root}/overview",
            headers=HEADERS,
            params={
                "include_descendants": True,
                "include_evidence": True,
                "attributes": ["temperature"],
            },
        )
        assert overview.status_code == 200
        payload = overview.json()["data"]
        assert payload["selected_space"]["space_id"] == root
        assert payload["states"]
        assert payload["coverage"]
        assert payload["evidence"][0]["observation_id"] == observation_id

        coverage = client.get(
            f"/api/spaces/{root}/coverage",
            headers=HEADERS,
            params={"attributes": "temperature", "include_descendants": True},
        )
        assert coverage.status_code == 200
        assert coverage.json()["data"]

        observations = client.get(
            "/api/observations",
            headers=HEADERS,
            params={
                "space_id": root,
                "include_descendants": True,
                "attribute": "temperature",
                "page_size": 100,
            },
        )
        assert observations.status_code == 200
        assert observations.json()["total"] == 1
        assert observations.json()["data"][0]["observation_id"] == observation_id
        assert observations.json()["data"][0]["raw_value"] is None

        exact = client.get(
            "/api/observations",
            headers=HEADERS,
            params={"space_id": root, "include_descendants": False},
        )
        assert exact.json()["total"] == 0

        oversized_page = client.get(
            "/api/observations",
            headers=HEADERS,
            params={"page_size": 101},
        )
        assert oversized_page.status_code == 400

        missing = client.get("/api/spaces/missing-space/overview", headers=HEADERS)
        assert missing.status_code == 404


def test_environment_tool_without_provider_returns_no_facts(tmp_path: Path) -> None:
    from arvuno_core.devices.mock import MockDeviceAdapter
    from arvuno_core.devices.registry import DeviceRegistry
    from arvuno_core.devices.service import DeviceApplicationService
    from arvuno_core.events.bus import EventBus
    from arvuno_core.observations.pipeline import ObservationPipeline
    from arvuno_core.persistence.tools import SqlToolExecutionStore
    from arvuno_core.tools.confirmation import ConfirmationService
    from arvuno_core.tools.executor import ToolExecutor
    from arvuno_core.tools.models import PermissionResult, ToolExecutionContext
    from arvuno_core.tools.registry import build_default_tool_registry
    from arvuno_core.tools.safety import SafetyPolicy

    manager = DatabaseManager(query_settings(tmp_path))
    try:
        manager.initialize_database()
        adapter = MockDeviceAdapter()
        registry = DeviceRegistry(lambda: factory(manager))
        pipeline = ObservationPipeline(lambda: factory(manager), ObservationService(factory))
        service = DeviceApplicationService(registry, {"mock": adapter}, pipeline)
        executor = ToolExecutor(
            registry=build_default_tool_registry(service),
            safety_policy=SafetyPolicy(service, tool_permissions={}),
            confirmation_service=ConfirmationService(ttl_seconds=300),
            execution_store=SqlToolExecutionStore(lambda: factory(manager)),
            event_publisher=EventBus(lambda: factory(manager)),
        )

        async def scenario() -> str:
            result = await executor.execute(
                "get_environment_state",
                {},
                context=ToolExecutionContext(correlation_id="environment-tool"),
            )
            assert result.output is not None
            return result.execution_id

        execution_id = asyncio.run(scenario())
        output_store = SqlToolExecutionStore(lambda: factory(manager))
        output = output_store.get_execution(execution_id).output or {}
        assert output["service_available"] is False
        assert output["spaces"] == []
        assert output["states"] == []
        assert output["coverage"] == []

        record = output_store.get_execution(execution_id)
        assert record.status == "completed"
        assert record.permission_result == PermissionResult.ALLOWED.value
    finally:
        manager.dispose()


def test_agent_environment_reply_cites_tool_evidence(query_manager, tmp_path: Path) -> None:
    current_time = datetime.now(UTC)
    root = root_space(query_manager)
    inferred_entity, inferred_room = seed_space_with_entity(
        query_manager, name="agent-motion", device_type="sensor_motion"
    )
    unknown_entity, unknown_room = seed_space_with_entity(query_manager, name="agent-invalid")
    motion_observation = seed_observation(
        query_manager,
        entity_id=inferred_entity,
        space_id=inferred_room,
        attribute="motion",
        value=True,
        received_at=current_time,
        observed_at=current_time,
        valid_seconds=7 * 24 * 60 * 60,
    )
    seed_observation(
        query_manager,
        entity_id=unknown_entity,
        space_id=unknown_room,
        attribute="temperature",
        value="bad",
        received_at=current_time,
        observed_at=current_time,
        quality_status="invalid",
    )
    estimation, _ = estimation_parts(query_manager)
    asyncio.run(estimation.rebuild(current_time))
    provider = MockAIProvider(
        SqlProviderLogStore(lambda: factory(query_manager)),
        outputs=[
            {
                "intent": {
                    "type": "environment_query",
                    "confidence": 0.95,
                    "target": None,
                    "action": None,
                },
                "requires_tool": True,
                "plan": [
                    {
                        "name": "environment",
                        "tool_name": "get_environment_state",
                        "input": {
                            "attributes": ["occupancy", "temperature"],
                            "include_descendants": True,
                        },
                    }
                ],
                "reply_to_user": "候选回答。",
            }
        ],
    )
    app = create_app(
        query_settings(tmp_path),
        unit_of_work_factory=lambda: factory(query_manager),
        ai_provider=provider,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            headers=HEADERS,
            json={"message": "家里有哪些未知状态？"},
        )
        assert response.status_code == 200
        result = response.json()["data"]
        assert result["status"] == "completed"
        reply = result["reply"]
        assert "推断" in reply
        assert motion_observation in reply
        assert "未知" in reply
        assert "Only invalid observations are available" in reply
        assert root not in reply or "估计" in reply

        tool_catalog = client.get("/api/tools", headers=HEADERS).json()["data"]
        environment_tool = next(
            item for item in tool_catalog if item["name"] == "get_environment_state"
        )
        assert environment_tool["version"] == "2.0.0"
        assert environment_tool["risk_level"] == "read_only"
