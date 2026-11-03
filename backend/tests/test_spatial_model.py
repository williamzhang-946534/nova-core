import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import Device, DeviceState, Environment, Space
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.spatial.errors import SpatialError
from arvuno_core.spatial.service import SpatialService


def spatial_settings(tmp_path: Path) -> Settings:
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
    test_manager = DatabaseManager(spatial_settings(tmp_path))
    test_manager.initialize_database()
    yield test_manager
    test_manager.dispose()


def service(manager: DatabaseManager) -> SpatialService:
    return SpatialService(lambda: SqlAlchemyUnitOfWork(manager.session_factory))


def seed_device(
    manager: DatabaseManager,
    *,
    device_id: str,
    name: str,
    area: str | None = None,
    device_type: str = "sensor_temperature",
) -> Device:
    now = datetime.now(UTC)
    with manager.session_factory() as session:
        device = Device(
            id=device_id,
            adapter_id="mock",
            external_id=device_id,
            name=name,
            normalized_name=name.casefold(),
            device_type=device_type,
            area=area,
            entity_id=None,
            is_online=True,
            is_enabled=True,
            risk_level="low",
            capabilities={},
            metadata_summary={},
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(device)
        session.flush()
        session.commit()
        session.refresh(device)
        return device


def query_space(manager: DatabaseManager, space_id: str) -> Space:
    with manager.session_factory() as session:
        space = session.get(Space, space_id)
        assert space is not None
        return space


def query_paths(manager: DatabaseManager) -> list[tuple[str, str, int]]:
    with manager.session_factory() as session:
        rows = (
            session.execute(text("SELECT ancestor_id, descendant_id, depth FROM space_paths"))
            .mappings()
            .all()
        )
        result: list[tuple[str, str, int]] = []
        for row in rows:
            ancestor_id = row["ancestor_id"]
            descendant_id = row["descendant_id"]
            depth = row["depth"]
            result.append((ancestor_id, descendant_id, depth))
        return result


def test_migration_initializes_spaces_from_legacy_devices(tmp_path: Path) -> None:
    test_manager = DatabaseManager(spatial_settings(tmp_path))
    created_at = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    try:
        test_manager.initialize_database()
        test_manager.downgrade("07b82937bedb")
        with test_manager.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO environments (
                        id, name, description, is_default, created_at
                    ) VALUES (
                        'environment-legacy', 'legacy home', NULL, 1, :created_at
                    )
                    """
                ),
                {"created_at": created_at.isoformat()},
            )
            for device_id, area in [
                ("device-known", "Living Room"),
                ("device-unknown", "  "),
            ]:
                connection.execute(
                    text(
                        """
                        INSERT INTO devices (
                            id, adapter_id, external_id, name, normalized_name,
                            device_type, area, manufacturer, model, is_online,
                            is_enabled, risk_level, capabilities, metadata,
                            last_seen_at, created_at, updated_at
                        ) VALUES (
                            :id, 'mock', :id, :name, :name, 'sensor_temperature',
                            :area, NULL, NULL, 1, 1, 'low', '{}', '{}',
                            :created_at, :created_at, :created_at
                        )
                        """
                    ),
                    {
                        "id": device_id,
                        "name": device_id.replace("-", " ").title(),
                        "area": area,
                        "created_at": created_at.isoformat(),
                    },
                )
            connection.execute(
                text(
                    """
                    INSERT INTO device_states (
                        id, device_id, state, attributes, raw_state, source,
                        observed_at, created_at
                    ) VALUES (
                        'state-known', 'device-known', 'on', '{}', 'on', 'mock',
                        :observed_at, :created_at
                    )
                    """
                ),
                {
                    "observed_at": (created_at + timedelta(minutes=1)).isoformat(),
                    "created_at": (created_at + timedelta(minutes=2)).isoformat(),
                },
            )

        test_manager.initialize_database()

        with test_manager.session_factory() as session:
            legacy_environment = session.get(Environment, "environment-legacy")
            environment = session.query(Environment).filter_by(name="home").one()
            assert legacy_environment is not None
            assert legacy_environment.root_space_id is not None
            assert legacy_environment.root_space_id != environment.root_space_id
            known = session.get(Device, "device-known")
            unknown = session.get(Device, "device-unknown")
            assert environment is not None and environment.root_space_id is not None
            assert known is not None and unknown is not None
            assert known.entity_id is not None
            assert unknown.entity_id is not None
            assert known.area == "Living Room"
            assert unknown.area == "  "

            root = session.get(Space, environment.root_space_id)
            assert root is not None
            assert root.space_type == "home"
            assert root.path == "home"

            rooms = list(session.query(Space).filter_by(space_type="room"))
            assert len(rooms) == 1
            assert rooms[0].name == "Living Room"
            assert rooms[0].parent_id == root.id
            assert rooms[0].path == "home/living-room"

            assignment_rows = session.execute(
                text(
                    """
                    SELECT entity_id, space_id, assignment_type, valid_from,
                           valid_until, source_type
                    FROM entity_space_assignments
                    """
                )
            ).mappings()
            assignments = list(assignment_rows)
            assert len(assignments) == 1
            assert assignments[0]["entity_id"] == known.entity_id
            assert assignments[0]["space_id"] == rooms[0].id
            assert assignments[0]["assignment_type"] == "fixed_installation"
            assert datetime.fromisoformat(str(assignments[0]["valid_from"])) == created_at
            assert assignments[0]["valid_until"] is None
            assert assignments[0]["source_type"] == "migration"

            state = session.get(DeviceState, "state-known")
            assert state is not None
            assert state.observed_at == created_at + timedelta(minutes=1)
    finally:
        test_manager.dispose()


def test_spatial_service_builds_tree_paths_and_updates_derived_paths(
    manager: DatabaseManager,
) -> None:
    spatial = service(manager)

    root = asyncio.run(spatial.ensure_root())
    floor = asyncio.run(
        spatial.create_space(parent_id=root.id, name="First Floor", space_type="floor")
    )
    room = asyncio.run(
        spatial.create_space(parent_id=floor.id, name="Living Room", space_type="room")
    )
    zone = asyncio.run(spatial.create_space(parent_id=room.id, name="Sofa Area", space_type="zone"))
    second_floor = asyncio.run(
        spatial.create_space(parent_id=root.id, name="Second Floor", space_type="floor")
    )

    tree = asyncio.run(spatial.tree())
    assert tree.id == root.id
    assert [child.name for child in tree.children] == ["First Floor", "Second Floor"]
    assert tree.children[0].children[0].id == room.id
    assert tree.children[0].children[0].children[0].id == zone.id
    assert zone.path == "home/first-floor/living-room/sofa-area"

    closure = query_paths(manager)
    assert any(row == (root.id, root.id, 0) for row in closure)
    assert any(row[0] == root.id and row[1] == zone.id and row[2] == 3 for row in closure)
    assert len(closure) == 12

    moved_room = asyncio.run(spatial.move_space(room.id, new_parent_id=second_floor.id))
    assert moved_room.path == "home/second-floor/living-room"
    assert query_space(manager, zone.id).path == "home/second-floor/living-room/sofa-area"

    renamed_room = asyncio.run(spatial.update_space(room.id, name="Family Room"))
    assert renamed_room.slug == "living-room"
    assert renamed_room.path == "home/second-floor/living-room"
    assert query_space(manager, zone.id).path == "home/second-floor/living-room/sofa-area"


def test_spatial_service_rejects_slug_conflicts_cycles_and_cross_tree_moves(
    manager: DatabaseManager,
) -> None:
    spatial = service(manager)
    root = asyncio.run(spatial.ensure_root())
    floor = asyncio.run(
        spatial.create_space(parent_id=root.id, name="First Floor", space_type="floor")
    )
    room = asyncio.run(
        spatial.create_space(parent_id=floor.id, name="Living Room", space_type="room")
    )
    other_floor = asyncio.run(
        spatial.create_space(parent_id=root.id, name="Second Floor", space_type="floor")
    )

    with pytest.raises(SpatialError, match="sibling space"):
        asyncio.run(spatial.create_space(parent_id=root.id, name="first floor", space_type="room"))

    with pytest.raises(SpatialError, match="root space cannot be moved"):
        asyncio.run(spatial.move_space(root.id, new_parent_id=floor.id))

    with pytest.raises(SpatialError, match="own parent"):
        asyncio.run(spatial.move_space(floor.id, new_parent_id=floor.id))

    with pytest.raises(SpatialError, match="descendant"):
        asyncio.run(spatial.move_space(floor.id, new_parent_id=room.id))

    other_root = Space(
        parent_id=None,
        space_type="home",
        name="Other Home",
        normalized_name="other home",
        slug="other-home",
        path="other-home",
        sort_order=0,
        status="active",
        metadata_summary={},
    )
    with manager.session_factory() as session:
        session.add(other_root)
        session.flush()
        other_root_id = other_root.id
        session.commit()

    with pytest.raises(SpatialError, match="does not exist"):
        asyncio.run(spatial.move_space(room.id, new_parent_id=other_root_id))
    assert query_space(manager, room.id).parent_id == floor.id
    assert other_floor.parent_id == root.id


def test_device_assignment_keeps_history_and_legacy_area_compatible(
    manager: DatabaseManager,
) -> None:
    spatial = service(manager)
    root = asyncio.run(spatial.ensure_root())
    living_room = asyncio.run(
        spatial.create_space(parent_id=root.id, name="Living Room", space_type="room")
    )
    bedroom = asyncio.run(
        spatial.create_space(parent_id=root.id, name="Bedroom", space_type="room")
    )
    device = seed_device(manager, device_id="device-spatial", name="Temperature")

    first = asyncio.run(
        spatial.assign_device(
            device.id,
            space_id=living_room.id,
            reason="Initial placement",
        )
    )
    assert first.assignment.space_id == living_room.id
    assert first.assignment.valid_until is None

    asyncio.run(spatial.assign_device(device.id, space_id=bedroom.id, reason="Moved by user"))
    history = asyncio.run(spatial.device_history(device.id))
    assert [item.space_id for item in history] == [bedroom.id, living_room.id]
    assert history[0].valid_until is None
    assert history[1].valid_until is not None
    assert history[1].valid_until <= history[0].valid_from
    assert query_space(manager, history[1].space_id).id == living_room.id

    with manager.session_factory() as session:
        stored = session.get(Device, device.id)
        assert stored is not None
        assert stored.entity_id == history[0].entity_id
        assert stored.area == "Bedroom"

    asyncio.run(spatial.update_space(living_room.id, name="Old Room"))
    history_after_rename = asyncio.run(spatial.device_history(device.id))
    assert history_after_rename[1].space_id == living_room.id
    assert history_after_rename[1].space_name == "Old Room"


def test_space_status_changes_protect_active_children_and_assignments(
    manager: DatabaseManager,
) -> None:
    spatial = service(manager)
    root = asyncio.run(spatial.ensure_root())
    floor = asyncio.run(
        spatial.create_space(parent_id=root.id, name="First Floor", space_type="floor")
    )
    room = asyncio.run(
        spatial.create_space(parent_id=floor.id, name="Living Room", space_type="room")
    )
    bedroom = asyncio.run(
        spatial.create_space(parent_id=root.id, name="Bedroom", space_type="room")
    )
    device = seed_device(manager, device_id="device-status", name="Door Sensor")
    asyncio.run(spatial.assign_device(device.id, space_id=room.id))

    with pytest.raises(SpatialError, match="Handle child spaces"):
        asyncio.run(spatial.archive_space(floor.id))

    with pytest.raises(SpatialError, match="Move current device assignments"):
        asyncio.run(spatial.archive_space(room.id))

    asyncio.run(spatial.assign_device(device.id, space_id=bedroom.id))
    archived_room = asyncio.run(spatial.archive_space(room.id))
    assert archived_room.status == "archived"
    assert archived_room.archived_at is not None
    assert query_space(manager, floor.id).status == "active"


def test_spatial_api_requires_auth_and_manages_spaces_and_history(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    app = create_app(
        spatial_settings(tmp_path),
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
        initialize_event_runtime=False,
        initialize_tool_runtime=False,
    )
    device = seed_device(manager, device_id="device-api", name="API Sensor")

    with TestClient(app) as client:
        unauthorized = client.get("/api/spaces")
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["code"] == "UNAUTHORIZED"

        headers = {"Authorization": "Bearer test-api-token"}
        tree_response = client.get("/api/spaces/tree", headers=headers)
        assert tree_response.status_code == 200
        root = tree_response.json()["data"]
        assert root["space_type"] == "home"
        assert "metadata" in root

        room_response = client.post(
            "/api/spaces",
            headers=headers,
            json={
                "parent_id": root["id"],
                "name": "Living Room",
                "space_type": "room",
                "metadata": {"source": "test"},
            },
        )
        assert room_response.status_code == 200
        room = room_response.json()["data"]
        assert room["metadata"] == {"source": "test"}

        conflict = client.post(
            "/api/spaces",
            headers=headers,
            json={
                "parent_id": root["id"],
                "name": "living room",
                "space_type": "room",
            },
        )
        assert conflict.status_code == 400
        assert conflict.json()["error"]["code"] == "SPACE_SLUG_CONFLICT"

        assignment_response = client.post(
            f"/api/devices/{device.id}/assignment",
            headers=headers,
            json={"space_id": room["id"], "reason": "API test"},
        )
        assert assignment_response.status_code == 200
        assignment = assignment_response.json()["data"]["assignment"]
        assert assignment["space_id"] == room["id"]

        history_response = client.get(
            f"/api/devices/{device.id}/space-history",
            headers=headers,
        )
        assert history_response.status_code == 200
        assert [item["id"] for item in history_response.json()["data"]] == [assignment["id"]]

        missing = client.get(
            f"/api/spaces/{uuid4()}",
            headers=headers,
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "SPACE_NOT_FOUND"
