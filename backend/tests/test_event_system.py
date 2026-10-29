import asyncio
import logging
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from arvuno_core.config import Settings
from arvuno_core.events.bus import EventBus, normalize_datetime
from arvuno_core.events.errors import EventPersistenceError, EventRecursionLimitExceeded
from arvuno_core.events.models import (
    ArvunoEvent,
    ArvunoEventSource,
    ArvunoEventType,
    DeviceStateChangedPayload,
    DeviceUnavailablePayload,
    SensorUpdatedPayload,
)
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import Event
from arvuno_core.persistence.repositories import EventRecordCreate
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork


def phase_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


@pytest.fixture
def manager(tmp_path: Path) -> DatabaseManager:
    test_manager = DatabaseManager(phase_settings(tmp_path))
    test_manager.initialize_database()
    yield test_manager
    test_manager.dispose()


def event(
    event_type: ArvunoEventType = ArvunoEventType.DEVICE_STATE_CHANGED,
    *,
    occurred_at: datetime | None = None,
) -> ArvunoEvent:
    payload: object
    if event_type == ArvunoEventType.SENSOR_UPDATED:
        payload = SensorUpdatedPayload(
            device_id="device-1",
            sensor_type="temperature",
            value=24.5,
            unit="C",
            previous_value=24.0,
        )
    elif event_type == ArvunoEventType.DEVICE_UNAVAILABLE:
        payload = DeviceUnavailablePayload(
            device_id="device-1",
            reason="The adapter reported unavailable.",
            observed_state="unavailable",
        )
    else:
        payload = DeviceStateChangedPayload(
            device_id="device-1",
            previous_state="off",
            current_state="on",
            attributes={"brightness": 80},
        )
    return ArvunoEvent(
        event_type=event_type,
        source=ArvunoEventSource.MOCK_ADAPTER,
        subject_type="device",
        subject_id="device-1",
        payload=payload,
        correlation_id="correlation-1",
        occurred_at=occurred_at or datetime.now(UTC),
    )


def test_event_schema_normalizes_time_and_rejects_invalid_input() -> None:
    occurred_at = datetime(2026, 10, 27, 10, 0, tzinfo=timezone(timedelta(hours=8)))
    valid = event(occurred_at=occurred_at)

    assert valid.occurred_at == datetime(2026, 10, 27, 2, 0, tzinfo=UTC)
    assert valid.id
    assert valid.correlation_id == "correlation-1"

    with pytest.raises(ValidationError, match="UTC offset"):
        ArvunoEvent.model_validate(
            {**event().model_dump(mode="json"), "occurred_at": datetime.now().isoformat()}
        )

    with pytest.raises(ValidationError, match="requires a SensorUpdatedPayload"):
        ArvunoEvent(
            event_type=ArvunoEventType.SENSOR_UPDATED,
            source=ArvunoEventSource.MOCK_ADAPTER,
            subject_type="device",
            subject_id="device-1",
            payload=DeviceStateChangedPayload(
                device_id="device-1",
                previous_state="off",
                current_state="on",
            ),
        )

    with pytest.raises(ValidationError, match="payload.device_id must match"):
        ArvunoEvent(
            event_type=ArvunoEventType.DEVICE_UNAVAILABLE,
            source=ArvunoEventSource.MOCK_ADAPTER,
            subject_type="device",
            subject_id="other-device",
            payload=DeviceUnavailablePayload(
                device_id="device-1",
                reason="unavailable",
                observed_state="unavailable",
            ),
        )


def test_normalize_datetime_assumes_sqlite_utc_values() -> None:
    naive = datetime(2026, 10, 27, 2, 0)
    offset = datetime(2026, 10, 27, 10, 0, tzinfo=timezone(timedelta(hours=8)))

    assert normalize_datetime(naive) == datetime(2026, 10, 27, 2, 0, tzinfo=UTC)
    assert normalize_datetime(offset) == datetime(2026, 10, 27, 2, 0, tzinfo=UTC)


def test_event_bus_persists_before_dispatch_and_rejects_duplicate_ids(
    manager: DatabaseManager,
) -> None:
    event_id = ""

    async def scenario() -> None:
        nonlocal event_id
        bus = EventBus(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
        received: list[ArvunoEvent] = []
        bus.subscribe(lambda item: received.append(item) or asyncio.sleep(0))
        item = event()
        event_id = item.id

        await bus.publish(item)

        with pytest.raises(EventPersistenceError):
            await bus.publish(item.model_copy(deep=True))

        assert received == [item]

    asyncio.run(scenario())

    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        assert uow.events is not None
        stored, total = uow.events.query(event_type="device_state_changed")
        assert total == 1
        assert stored[0].id == event_id


def test_event_bus_isolates_and_logs_subscriber_failures(
    manager: DatabaseManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def failing_subscriber(_event: ArvunoEvent) -> None:
        raise RuntimeError("expected subscriber failure")

    async def scenario() -> None:
        bus = EventBus(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
        received: list[ArvunoEvent] = []
        bus.subscribe(failing_subscriber)
        bus.subscribe(lambda item: received.append(item) or asyncio.sleep(0))

        with caplog.at_level(logging.ERROR, logger="arvuno_core.events.bus"):
            await bus.publish(event())

        assert received
        assert any(record.message == "event_subscriber_failed" for record in caplog.records)

    asyncio.run(scenario())

    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        assert uow.events is not None
        _, total = uow.events.query()
        assert total == 1


def test_event_bus_filters_subscriptions(manager: DatabaseManager) -> None:
    async def scenario() -> None:
        bus = EventBus(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
        received: list[ArvunoEvent] = []
        bus.subscribe(
            lambda item: received.append(item) or asyncio.sleep(0),
            event_types={ArvunoEventType.SENSOR_UPDATED.value},
        )

        await bus.publish(event())
        await bus.publish(event(ArvunoEventType.SENSOR_UPDATED))

        assert [item.event_type for item in received] == [ArvunoEventType.SENSOR_UPDATED]

    asyncio.run(scenario())


def test_event_bus_does_not_dispatch_when_persistence_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        bus = EventBus(lambda: None)
        received: list[ArvunoEvent] = []
        bus.subscribe(lambda item: received.append(item) or asyncio.sleep(0))

        def fail_persistence(_event: ArvunoEvent) -> None:
            raise RepositoryError("expected persistence failure")

        monkeypatch.setattr(bus, "_persist", fail_persistence)
        with pytest.raises(EventPersistenceError):
            await bus.publish(event())
        assert received == []

    asyncio.run(scenario())


def test_event_bus_stops_unbounded_recursive_publishing(
    manager: DatabaseManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        bus = EventBus(lambda: SqlAlchemyUnitOfWork(manager.session_factory), max_publish_depth=1)
        attempts = 0

        async def recursive_subscriber(_event: ArvunoEvent) -> None:
            nonlocal attempts
            attempts += 1
            next_type = (
                ArvunoEventType.SENSOR_UPDATED
                if _event.event_type == ArvunoEventType.DEVICE_STATE_CHANGED
                else ArvunoEventType.DEVICE_STATE_CHANGED
            )
            await bus.publish(event(next_type))

        bus.subscribe(recursive_subscriber)
        with caplog.at_level(logging.ERROR, logger="arvuno_core.events.bus"):
            await bus.publish(event())

        assert attempts == 2
        assert any(
            record.exc_info and isinstance(record.exc_info[1], EventRecursionLimitExceeded)
            for record in caplog.records
        )

    asyncio.run(scenario())


def test_event_retention_policy_removes_only_expired_events(manager: DatabaseManager) -> None:
    now = datetime.now(UTC)

    def record(event_type: str, source: str, age_days: int) -> Event:
        return Event(
            event_type=event_type,
            source=source,
            subject_type="device" if event_type.startswith("device") else None,
            subject_id="device-1" if event_type.startswith("device") else None,
            payload={"device_id": "device-1"},
            occurred_at=now - timedelta(days=age_days),
        )

    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        assert uow.events is not None
        for item in [
            record("device_state_changed", "mock_adapter", 181),
            record("device_state_changed", "mock_adapter", 100),
            record("automation_triggered", "automation", 181),
            record("task_started", "task", 400),
            record("diagnostic", "system", 91),
            record("diagnostic", "system", 80),
        ]:
            uow.events.add(item)
        uow.commit()

        deleted = uow.events.cleanup_expired(
            now=now,
            retention_days=180,
            diagnostic_retention_days=90,
            long_term_event_types=["task_started"],
        )
        uow.commit()
        assert deleted == 3

        remaining, _ = uow.events.query(order="asc")
        assert [item.event_type for item in remaining] == [
            "task_started",
            "device_state_changed",
            "diagnostic",
        ]


def test_event_repository_wraps_duplicate_records(manager: DatabaseManager) -> None:
    item = event()
    record = EventRecordCreate(
        id=item.id,
        event_type=item.event_type.value,
        source=item.source.value,
        subject_type=item.subject_type,
        subject_id=item.subject_id,
        payload=item.payload.model_dump(mode="json"),
        correlation_id=item.correlation_id,
        occurred_at=item.occurred_at,
        created_at=item.created_at,
    )
    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        assert uow.events is not None
        uow.events.create_event(record)
        uow.commit()

    with (
        SqlAlchemyUnitOfWork(manager.session_factory) as uow,
        pytest.raises(RepositoryError, match="Failed to save an event"),
    ):
        assert uow.events is not None
        uow.events.create_event(record)
        uow.commit()


def test_event_ids_must_be_uuids() -> None:
    with pytest.raises(ValidationError):
        ArvunoEvent.model_validate(
            {**event().model_dump(mode="json"), "id": str(uuid4()) + "invalid"}
        )
