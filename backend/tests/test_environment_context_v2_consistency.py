import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from arvuno_core.app import create_app
from arvuno_core.environment.context_v2 import EnvironmentContextV2Service
from arvuno_core.environment.query_models import EnvironmentQueryResult
from arvuno_core.estimation.models import EnvironmentContextV2
from arvuno_core.estimation.service import StateEstimationService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import StateEstimate
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.spatial.service import SpatialService
from tests.test_state_estimation import add_observation, seed_entity, state_settings

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
HEADERS = {"Authorization": "Bearer test-api-token"}


def uow(manager: DatabaseManager) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(manager.session_factory)


def estimation_service(manager: DatabaseManager) -> StateEstimationService:
    return StateEstimationService(lambda: uow(manager), environment_name="home")


def context_service(manager: DatabaseManager) -> EnvironmentContextV2Service:
    return EnvironmentContextV2Service(lambda: uow(manager), estimation_service(manager))


def current_state_ids(manager: DatabaseManager) -> set[str]:
    with manager.session_factory() as session:
        rows = session.scalars(
            select(StateEstimate.id).where(StateEstimate.superseded_at.is_(None))
        )
        return set(rows)


def context_state_ids(context: EnvironmentContextV2) -> set[str]:
    result: set[str] = set()

    def visit(spaces: Any) -> None:
        for space in spaces:
            result.update(state.id for state in space.states.values())
            for entity in space.entities:
                result.update(state.id for state in entity.states.values())
            visit(space.children)

    visit(context.spaces)
    return result


def context_states(context: EnvironmentContextV2) -> list[Any]:
    result: list[Any] = []

    def visit(spaces: Any) -> None:
        for space in spaces:
            result.extend(space.states.values())
            for entity in space.entities:
                result.extend(entity.states.values())
            visit(space.children)

    visit(context.spaces)
    return result


def context_space(context: EnvironmentContextV2, space_id: str) -> Any:
    def visit(spaces: Any) -> Any:
        for space in spaces:
            if space.space_id == space_id:
                return space
            child = visit(space.children)
            if child is not None:
                return child
        return None

    return visit(context.spaces)


def context_entity(context: EnvironmentContextV2, entity_id: str) -> Any:
    for space in context_space_all(context):
        for entity in space.entities:
            if entity.entity_id == entity_id:
                return entity
    return None


def context_space_all(context: EnvironmentContextV2) -> list[Any]:
    result: list[Any] = []

    def visit(spaces: Any) -> None:
        for space in spaces:
            result.append(space)
            visit(space.children)

    visit(context.spaces)
    return result


def test_context_v2_projects_all_space_states_consistently(tmp_path: Path) -> None:
    settings = state_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    spatial = SpatialService(lambda: uow(manager), environment_name="home")
    root = asyncio.run(spatial.ensure_root())
    floor = asyncio.run(
        spatial.create_space(parent_id=root.id, name="Second floor", space_type="floor")
    )
    room = asyncio.run(spatial.create_space(parent_id=floor.id, name="Bedroom", space_type="room"))
    zone = asyncio.run(spatial.create_space(parent_id=room.id, name="Sleep", space_type="zone"))
    missing_room = asyncio.run(
        spatial.create_space(parent_id=floor.id, name="Office", space_type="room")
    )
    entity_id, assigned_room = seed_entity(manager, name="context-sensor")

    cases = (
        (root.id, 21.0),
        (floor.id, 22.0),
        (room.id, 23.0),
        (zone.id, 24.0),
    )
    for space_id, value in cases:
        add_observation(
            manager,
            entity_id=entity_id,
            space_id=space_id,
            attribute="temperature",
            value=value,
        )
    add_observation(
        manager,
        entity_id=entity_id,
        space_id=root.id,
        attribute="temperature",
        value=30.0,
        adapter_id="home_assistant",
    )
    add_observation(
        manager,
        entity_id=entity_id,
        space_id=assigned_room,
        attribute="device_availability",
        value="offline",
    )

    service = estimation_service(manager)
    asyncio.run(service.rebuild(NOW))
    expected_ids = current_state_ids(manager)
    assert expected_ids

    immediate = asyncio.run(context_service(manager).build(NOW))
    assert context_space(immediate, root.id) is not None
    assert context_space(immediate, floor.id) is not None
    assert context_space(immediate, room.id) is not None
    assert context_space(immediate, zone.id) is not None
    assert context_state_ids(immediate) == expected_ids
    assert context_space(immediate, root.id).states["temperature"].status == "conflict"
    assert context_space(immediate, missing_room.id).states["temperature"].status == "unknown"

    unavailable = {state.id for state in context_states(immediate) if state.status == "unavailable"}
    assert unavailable

    snapshot, anomalies = asyncio.run(context_service(manager).rebuild_snapshot(NOW))
    assert context_state_ids(snapshot) == expected_ids
    assert snapshot.quality == {
        "conflict_count": sum(state.status == "conflict" for state in context_states(snapshot)),
        "stale_count": sum(state.status == "stale" for state in context_states(snapshot)),
        "unavailable_count": sum(
            state.status == "unavailable" for state in context_states(snapshot)
        ),
        "unknown_count": sum(state.status == "unknown" for state in context_states(snapshot)),
    }

    app = create_app(
        settings,
        unit_of_work_factory=lambda: uow(manager),
        initialize_event_runtime=True,
        initialize_tool_runtime=False,
    )
    with TestClient(app) as client:
        api_context = client.get("/api/environment/context-v2", headers=HEADERS).json()["data"]
        tool_context = client.post(
            "/api/tools/get_environment_state/execute",
            headers=HEADERS,
            json={"input": {}},
        )
        assert tool_context.status_code == 200
        tool_result = EnvironmentQueryResult.model_validate(tool_context.json()["data"]["output"])
        assert {state.id for state in tool_result.states} == expected_ids
    assert context_state_ids(EnvironmentContextV2.model_validate(api_context)) == expected_ids

    stale_context = asyncio.run(context_service(manager).build(NOW + timedelta(seconds=301)))
    assert context_state_ids(stale_context) == expected_ids
    assert context_space(stale_context, root.id).states["temperature"].status == "conflict"
    assert context_space(stale_context, room.id).states["temperature"].status == "stale"

    manager.dispose()
    restarted = DatabaseManager(settings)
    restarted.initialize_database()
    try:
        restarted_context = asyncio.run(context_service(restarted).build(NOW))
        assert context_state_ids(restarted_context) == expected_ids
        repeated = asyncio.run(estimation_service(restarted).rebuild(NOW))
        assert repeated.appended == 0
        assert repeated.unchanged > 0
        assert current_state_ids(restarted) == expected_ids
    finally:
        restarted.dispose()


def test_context_v2_refreshes_projection_after_a_state_update(tmp_path: Path) -> None:
    settings = state_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    try:
        entity_id, assigned_room = seed_entity(manager, name="update-sensor")
        add_observation(
            manager,
            entity_id=entity_id,
            space_id=assigned_room,
            attribute="temperature",
            value=20.0,
        )
        asyncio.run(estimation_service(manager).rebuild(NOW))
        first = asyncio.run(context_service(manager).build(NOW))
        first_ids = context_state_ids(first)
        assert context_entity(first, entity_id).states["temperature"].value == 20.0

        add_observation(
            manager,
            entity_id=entity_id,
            space_id=assigned_room,
            attribute="temperature",
            value=21.5,
            received_at=NOW + timedelta(minutes=1),
            observed_at=NOW + timedelta(minutes=1),
        )
        updated_at = NOW + timedelta(minutes=1)
        asyncio.run(estimation_service(manager).rebuild(updated_at))
        second = asyncio.run(context_service(manager).build(updated_at))

        assert context_state_ids(second) == current_state_ids(manager)
        assert context_state_ids(second) != first_ids
        assert context_entity(second, entity_id).states["temperature"].value == 21.5
    finally:
        manager.dispose()


def test_context_v2_follows_entity_after_space_migration(tmp_path: Path) -> None:
    settings = state_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    spatial = SpatialService(lambda: uow(manager), environment_name="home")
    root = asyncio.run(spatial.ensure_root())
    new_room = asyncio.run(
        spatial.create_space(parent_id=root.id, name="New Room", space_type="room")
    )
    entity_id, assigned_room = seed_entity(manager, name="migrating-sensor")
    add_observation(
        manager,
        entity_id=entity_id,
        space_id=assigned_room,
        attribute="temperature",
        value=22.0,
    )
    asyncio.run(estimation_service(manager).rebuild(NOW))

    before = asyncio.run(context_service(manager).build(NOW))
    assert context_entity(before, entity_id).space_id == assigned_room

    asyncio.run(
        spatial.assign_device(
            "device-migrating-sensor",
            space_id=new_room.id,
        )
    )
    asyncio.run(estimation_service(manager).rebuild(NOW))
    after = asyncio.run(context_service(manager).build(NOW))

    migrated = context_entity(after, entity_id)
    assert migrated.space_id == new_room.id
    assert context_space(after, new_room.id).entities[0].entity_id == entity_id
    assert context_space(after, assigned_room).entities == []
    assert {state.id for state in context_states(after)} == current_state_ids(manager)
