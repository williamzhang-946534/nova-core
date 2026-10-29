from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.events.models import (
    ArvunoEvent,
    ArvunoEventSource,
    ArvunoEventType,
    DeviceStateChangedPayload,
    SensorUpdatedPayload,
)
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.repositories import EventRecordCreate
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork


def api_settings(tmp_path: Path) -> Settings:
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
    test_manager = DatabaseManager(api_settings(tmp_path))
    test_manager.initialize_database()
    yield test_manager
    test_manager.dispose()


def stored_event(
    *,
    event_type: ArvunoEventType,
    subject_id: str,
    correlation_id: str,
    occurred_at: datetime,
) -> EventRecordCreate:
    payload: object
    if event_type == ArvunoEventType.SENSOR_UPDATED:
        payload = SensorUpdatedPayload(
            device_id=subject_id,
            sensor_type="temperature",
            value=25.5,
            unit="C",
            previous_value=24.5,
        )
    else:
        payload = DeviceStateChangedPayload(
            device_id=subject_id,
            previous_state="off",
            current_state="on",
            attributes={},
        )
    event = ArvunoEvent(
        event_type=event_type,
        source=ArvunoEventSource.MOCK_ADAPTER,
        subject_type="device",
        subject_id=subject_id,
        payload=payload,
        correlation_id=correlation_id,
        occurred_at=occurred_at,
        created_at=occurred_at + timedelta(seconds=1),
    )
    return EventRecordCreate(
        id=event.id,
        event_type=event.event_type.value,
        source=event.source.value,
        subject_type=event.subject_type,
        subject_id=event.subject_id,
        payload=event.payload.model_dump(mode="json"),
        correlation_id=event.correlation_id,
        occurred_at=event.occurred_at,
        created_at=event.created_at,
    )


def seed_events(manager: DatabaseManager) -> tuple[list[str], datetime, datetime]:
    start = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
    records = [
        stored_event(
            event_type=ArvunoEventType.DEVICE_STATE_CHANGED,
            subject_id="device-1",
            correlation_id="correlation-1",
            occurred_at=start,
        ),
        stored_event(
            event_type=ArvunoEventType.SENSOR_UPDATED,
            subject_id="device-2",
            correlation_id="correlation-2",
            occurred_at=start + timedelta(minutes=1),
        ),
        stored_event(
            event_type=ArvunoEventType.DEVICE_STATE_CHANGED,
            subject_id="device-3",
            correlation_id="correlation-3",
            occurred_at=start + timedelta(minutes=2),
        ),
    ]
    with SqlAlchemyUnitOfWork(manager.session_factory) as unit_of_work:
        assert unit_of_work.events is not None
        for record in records:
            unit_of_work.events.create_event(record)
        unit_of_work.commit()
    return [record.id for record in records], start, start + timedelta(minutes=2)


def test_events_api_requires_a_valid_bearer_token(manager: DatabaseManager, tmp_path: Path) -> None:
    app = create_app(
        api_settings(tmp_path),
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
    )
    client = TestClient(app)

    without_token = client.get("/api/events")
    wrong_token = client.get("/api/events", headers={"Authorization": "Bearer wrong-token"})
    with_token = client.get("/api/events", headers={"Authorization": "Bearer test-api-token"})

    assert without_token.status_code == 401
    assert without_token.json()["error"]["code"] == "UNAUTHORIZED"
    assert wrong_token.status_code == 401
    assert wrong_token.json()["error"]["code"] == "UNAUTHORIZED"
    assert with_token.status_code == 200
    assert with_token.json()["total"] == 0


def test_events_api_filters_sorts_and_paginates(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    event_ids, start, end = seed_events(manager)
    app = create_app(
        api_settings(tmp_path),
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-api-token"}

    device_events = client.get(
        "/api/events",
        headers=headers,
        params={"event_type": "device_state_changed", "order": "asc"},
    )
    subject_event = client.get(
        "/api/events",
        headers=headers,
        params={"subject_id": "device-2"},
    )
    correlated_event = client.get(
        "/api/events",
        headers=headers,
        params={"correlation_id": "correlation-3"},
    )
    time_ranged_events = client.get(
        "/api/events",
        headers=headers,
        params={"start_time": start.isoformat(), "end_time": end.isoformat()},
    )
    first_page = client.get(
        "/api/events",
        headers=headers,
        params={"order": "asc", "page": 1, "page_size": 2},
    )
    second_page = client.get(
        "/api/events",
        headers=headers,
        params={"order": "asc", "page": 2, "page_size": 2},
    )

    assert device_events.status_code == 200
    assert [item["id"] for item in device_events.json()["data"]] == [
        event_ids[0],
        event_ids[2],
    ]
    assert subject_event.status_code == 200
    assert [item["subject_id"] for item in subject_event.json()["data"]] == ["device-2"]
    assert correlated_event.status_code == 200
    assert [item["id"] for item in correlated_event.json()["data"]] == [event_ids[2]]
    assert time_ranged_events.status_code == 200
    assert time_ranged_events.json()["total"] == 3
    assert [item["id"] for item in first_page.json()["data"]] == event_ids[:2]
    assert [item["id"] for item in second_page.json()["data"]] == [event_ids[2]]


def test_events_api_returns_event_detail_and_not_found(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    event_ids, _, _ = seed_events(manager)
    app = create_app(
        api_settings(tmp_path),
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-api-token"}

    detail = client.get(f"/api/events/{event_ids[1]}", headers=headers)
    missing = client.get(f"/api/events/{uuid4()}", headers=headers)

    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == event_ids[1]
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_openapi_contains_events_api(manager: DatabaseManager, tmp_path: Path) -> None:
    app = create_app(
        api_settings(tmp_path),
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
    )
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/events" in response.json()["paths"]
    assert "/api/events/{event_id}" in response.json()["paths"]
