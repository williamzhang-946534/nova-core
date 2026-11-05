import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from arvuno_core.config import Settings
from arvuno_core.events.bus import EventBus
from arvuno_core.events.models import (
    ArvunoEvent,
    ArvunoEventType,
    DeviceUnavailablePayload,
    SensorUpdatedPayload,
    TaskFailedPayload,
)
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.proactive.errors import ProactiveSuggestionNotFoundError
from arvuno_core.proactive.service import ProactiveService


@dataclass
class FixedClock:
    now: datetime = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@dataclass
class FakeNotification:
    sent: list[dict[str, Any]]

    async def create(
        self,
        *,
        channel: str,
        title: str,
        content: str,
        level: Any,
        related_event_id: str | None = None,
        related_task_id: str | None = None,
    ) -> None:
        self.sent.append(
            {
                "channel": channel,
                "title": title,
                "content": content,
                "level": level,
            }
        )


def phase_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


@dataclass
class ProactiveTestEnvironment:
    manager: DatabaseManager
    factory: Any
    service: ProactiveService
    notification: FakeNotification
    clock: FixedClock
    counter: Any


def proactive_environment(
    tmp_path: Path,
    *,
    quiet_hours_start: time | None = None,
    quiet_hours_end: time | None = None,
    cooldown_seconds: int = 3600,
    max_per_hour: int = 5,
    max_per_day: int = 20,
) -> ProactiveTestEnvironment:
    manager = DatabaseManager(phase_settings(tmp_path))
    manager.initialize_database()

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(manager.session_factory)

    clock = FixedClock()
    notification = FakeNotification([])

    import itertools

    counter = itertools.count(1)
    service = ProactiveService(
        factory,
        notification,
        environment_name="home",
        clock=clock,
        suggestion_id_factory=lambda: str(uuid4()),
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
        cooldown_seconds=cooldown_seconds,
        max_per_hour=max_per_hour,
        max_per_day=max_per_day,
        default_autonomy_level=2,
        max_autonomy_level=2,
    )
    return ProactiveTestEnvironment(
        manager,
        factory,
        service,
        notification,
        clock,
        counter,
    )


def sensor_event(
    *,
    sensor_type: str = "temperature",
    value: float | str = 35.0,
    device_id: str = "sensor-1",
    occurred_at: datetime | None = None,
) -> ArvunoEvent:
    return ArvunoEvent(
        id=str(uuid4()),
        event_type=ArvunoEventType.SENSOR_UPDATED,
        source="mock_adapter",
        subject_type="device",
        subject_id=device_id,
        payload=SensorUpdatedPayload(
            device_id=device_id,
            sensor_type=sensor_type,  # type: ignore[arg-type]
            value=value,
            unit="°C" if sensor_type == "temperature" else "%",
        ),
        occurred_at=occurred_at or datetime.now(UTC),
    )


def device_unavailable_event(
    *,
    device_id: str = "device-1",
) -> ArvunoEvent:
    return ArvunoEvent(
        id=str(uuid4()),
        event_type=ArvunoEventType.DEVICE_UNAVAILABLE,
        source="mock_adapter",
        subject_type="device",
        subject_id=device_id,
        payload=DeviceUnavailablePayload(
            device_id=device_id,
            reason="Adapter disconnected",
            observed_state="unavailable",
        ),
    )


def task_failed_event(*, task_id: str = "task-1") -> ArvunoEvent:
    return ArvunoEvent(
        id=str(uuid4()),
        event_type=ArvunoEventType.TASK_FAILED,
        source="task",
        subject_type="task",
        subject_id=task_id,
        payload=TaskFailedPayload(
            task_id=task_id,
            error_code="device_offline",
            error_message="The target device is offline",
        ),
    )


def test_anomaly_creates_delivered_suggestion_with_evidence(tmp_path: Path) -> None:
    env = proactive_environment(tmp_path)
    try:
        suggestion, decision = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Temperature anomaly",
                message="Living room temperature is 35°C",
                importance="normal",
                dedupe_key="anomaly:sensor-1:temperature",
                candidate_action={"type": "inspect"},
                evidence_refs=[{"type": "observation", "id": "obs-1"}],
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        assert decision.suppressed is False
        assert decision.reason == "allowed"
        assert suggestion.status == "delivered"
        assert suggestion.delivered_at is not None
        assert suggestion.autonomy_level == 2
        assert suggestion.candidate_action == {"type": "inspect"}
        assert suggestion.evidence_refs == [{"type": "observation", "id": "obs-1"}]
        assert suggestion.cooldown_until is not None
        assert suggestion.expires_at is not None
    finally:
        env.manager.dispose()


def test_level_one_records_without_delivery_and_level_two_notifies(
    tmp_path: Path,
) -> None:
    env = proactive_environment(tmp_path)
    try:
        recorded, _ = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Record only",
                message="This candidate is only recorded",
                importance="normal",
                dedupe_key="anomaly:level:record-only",
                autonomy_level=1,
                now=env.clock.now,
            )
        )
        delivered, _ = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Notify user",
                message="This candidate should be delivered",
                importance="normal",
                dedupe_key="anomaly:level:notify",
                autonomy_level=2,
                now=env.clock.now,
            )
        )

        assert recorded.status == "evaluated"
        assert recorded.delivered_at is None
        assert delivered.status == "delivered"
        assert delivered.delivered_at is not None
        assert len(env.notification.sent) == 1
        assert env.notification.sent[0]["title"] == "Notify user"
    finally:
        env.manager.dispose()


def test_repeated_anomaly_within_cooldown_is_suppressed_without_new_notification(
    tmp_path: Path,
) -> None:
    env = proactive_environment(tmp_path, cooldown_seconds=3600)
    try:
        first, first_decision = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Temperature anomaly",
                message="Living room temperature is 35°C",
                importance="normal",
                dedupe_key="anomaly:sensor-1:temperature",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        assert first_decision.suppressed is False
        assert first.status == "delivered"

        env.clock.now += timedelta(minutes=5)
        second, second_decision = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Temperature anomaly",
                message="Living room temperature is 35°C",
                importance="normal",
                dedupe_key="anomaly:sensor-1:temperature",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        assert second_decision.suppressed is True
        assert second_decision.reason == "cooldown"
        assert second_decision.active_suggestion_id == first.id
        assert second.status == "suppressed"

        with env.factory() as unit_of_work:
            assert unit_of_work.proactive is not None
            active = unit_of_work.proactive.get(first.id)
            assert active is not None
            assert active.suppression_count == 1
    finally:
        env.manager.dispose()


def test_different_dedupe_keys_are_not_suppressed_by_each_other(tmp_path: Path) -> None:
    env = proactive_environment(tmp_path)
    try:
        _, first_decision = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Temperature anomaly",
                message="Sensor A is anomalous",
                importance="normal",
                dedupe_key="anomaly:sensor-a:temperature",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        _, second_decision = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Humidity anomaly",
                message="Sensor B is anomalous",
                importance="low",
                dedupe_key="anomaly:sensor-b:humidity",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        assert first_decision.suppressed is False
        assert second_decision.suppressed is False
    finally:
        env.manager.dispose()


def test_quiet_hours_suppress_normal_importance_but_not_high(tmp_path: Path) -> None:
    env = proactive_environment(
        tmp_path,
        quiet_hours_start=time(22, 0),
        quiet_hours_end=time(8, 0),
    )
    env.clock.now = datetime(2026, 11, 5, 23, 0, tzinfo=UTC)
    try:
        _, normal_decision = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Temperature anomaly",
                message="Temperature is high",
                importance="normal",
                dedupe_key="anomaly:quiet:normal",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        assert normal_decision.suppressed is True
        assert normal_decision.reason == "quiet_hours"

        _, high_decision = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="CO2 anomaly",
                message="CO2 is very high",
                importance="high",
                dedupe_key="anomaly:quiet:high",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        assert high_decision.suppressed is False
        assert high_decision.reason == "allowed"
    finally:
        env.manager.dispose()


def test_quiet_hours_use_the_configured_local_timezone(tmp_path: Path) -> None:
    env = proactive_environment(
        tmp_path,
        quiet_hours_start=time(22, 0),
        quiet_hours_end=time(8, 0),
    )
    env.clock.now = datetime(2026, 11, 5, 16, 0, tzinfo=UTC)
    try:
        _, decision = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Local midnight anomaly",
                message="UTC 16:00 is local midnight",
                importance="normal",
                dedupe_key="anomaly:quiet:timezone",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        assert decision.suppressed is True
        assert decision.reason == "quiet_hours"
    finally:
        env.manager.dispose()


def test_hourly_rate_limit_stops_repeated_notifications(tmp_path: Path) -> None:
    env = proactive_environment(tmp_path, max_per_hour=2)
    try:
        decisions = []
        for index in range(3):
            _, decision = asyncio.run(
                env.service.evaluate_candidate(
                    environment_id=None,
                    trigger_type="anomaly",
                    title=f"Anomaly {index}",
                    message=f"Anomaly {index}",
                    importance="normal",
                    dedupe_key=f"anomaly:rate-limit:{index}",
                    autonomy_level=2,
                    now=env.clock.now,
                )
            )
            decisions.append(decision)
        assert decisions[0].suppressed is False
        assert decisions[1].suppressed is False
        assert decisions[2].suppressed is True
        assert decisions[2].reason == "rate_limit_hour"
    finally:
        env.manager.dispose()


def test_daily_rate_limit_stops_repeated_notifications(tmp_path: Path) -> None:
    env = proactive_environment(tmp_path, max_per_hour=100, max_per_day=2)
    try:
        decisions = []
        for index in range(3):
            _, decision = asyncio.run(
                env.service.evaluate_candidate(
                    environment_id=None,
                    trigger_type="anomaly",
                    title=f"Anomaly {index}",
                    message=f"Anomaly {index}",
                    importance="normal",
                    dedupe_key=f"anomaly:daily-limit:{index}",
                    autonomy_level=2,
                    now=env.clock.now,
                )
            )
            decisions.append(decision)
        assert decisions[0].suppressed is False
        assert decisions[1].suppressed is False
        assert decisions[2].suppressed is True
        assert decisions[2].reason == "rate_limit_day"
    finally:
        env.manager.dispose()


def test_sensor_event_exceeding_threshold_creates_suggestion(tmp_path: Path) -> None:
    env = proactive_environment(tmp_path)
    try:
        asyncio.run(env.service.handle_event(sensor_event(value=35.0, sensor_type="temperature")))
        suggestions, total = asyncio.run(env.service.list_suggestions(trigger_type="anomaly"))
        assert total == 1
        assert suggestions[0].trigger_type == "anomaly"
        assert suggestions[0].status == "delivered"
        assert "temperature" in suggestions[0].dedupe_key
        assert len(suggestions[0].evidence_refs) == 1
        assert suggestions[0].evidence_refs[0]["type"] == "event"
    finally:
        env.manager.dispose()


def test_sensor_event_below_threshold_does_not_create_suggestion(tmp_path: Path) -> None:
    env = proactive_environment(tmp_path)
    try:
        asyncio.run(env.service.handle_event(sensor_event(value=22.0, sensor_type="temperature")))
        _, total = asyncio.run(env.service.list_suggestions(trigger_type="anomaly"))
        assert total == 0
    finally:
        env.manager.dispose()


def test_single_motion_reading_is_not_treated_as_an_environment_anomaly(
    tmp_path: Path,
) -> None:
    env = proactive_environment(tmp_path)
    try:
        asyncio.run(env.service.handle_event(sensor_event(value=1.0, sensor_type="motion")))
        _, total = asyncio.run(env.service.list_suggestions(trigger_type="anomaly"))
        assert total == 0
    finally:
        env.manager.dispose()


def test_device_unavailable_creates_device_fault_suggestion(tmp_path: Path) -> None:
    env = proactive_environment(tmp_path)
    try:
        asyncio.run(env.service.handle_event(device_unavailable_event()))
        suggestions, total = asyncio.run(env.service.list_suggestions(trigger_type="device_fault"))
        assert total == 1
        assert suggestions[0].trigger_type == "device_fault"
        assert suggestions[0].status == "delivered"
        assert "device-1" in suggestions[0].dedupe_key
    finally:
        env.manager.dispose()


def test_task_failure_creates_suggestion_with_error_details(tmp_path: Path) -> None:
    env = proactive_environment(tmp_path)
    try:
        asyncio.run(env.service.handle_event(task_failed_event()))
        suggestions, total = asyncio.run(env.service.list_suggestions(trigger_type="task_failure"))
        assert total == 1
        assert suggestions[0].trigger_type == "task_failure"
        assert "device_offline" in suggestions[0].dedupe_key
        assert len(suggestions[0].evidence_refs) == 1
    finally:
        env.manager.dispose()


def test_user_dismiss_with_suppress_future_blocks_future_suggestions(
    tmp_path: Path,
) -> None:
    env = proactive_environment(tmp_path, cooldown_seconds=0)
    try:
        suggestion, _ = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Annoying anomaly",
                message="This is annoying",
                importance="normal",
                dedupe_key="anomaly:suppressed:sensor-1",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        dismissed = asyncio.run(
            env.service.dismiss_suggestion(
                suggestion.id,
                feedback="I know about this",
                suppress_future=True,
                suppression_hours=48,
            )
        )
        assert dismissed.status == "dismissed"
        assert dismissed.dismissed_at is not None
        assert dismissed.user_feedback is not None
        assert dismissed.user_feedback["suppress_future"] is True

        _, repeat_decision = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Annoying anomaly",
                message="This is annoying",
                importance="normal",
                dedupe_key="anomaly:suppressed:sensor-1",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        assert repeat_decision.suppressed is True
        assert repeat_decision.reason == "user_suppressed"
    finally:
        env.manager.dispose()


def test_expired_suppression_preference_is_reused_not_duplicated(
    tmp_path: Path,
) -> None:
    env = proactive_environment(tmp_path, cooldown_seconds=0)
    try:
        first, _ = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="First suppression",
                message="Dismiss this once",
                importance="normal",
                dedupe_key="anomaly:suppression-reuse:sensor-1",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        asyncio.run(
            env.service.dismiss_suggestion(
                first.id,
                suppress_future=True,
                suppression_hours=1,
            )
        )
        env.clock.now += timedelta(hours=2)

        second, repeat_decision = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Second suppression",
                message="Dismiss this again",
                importance="normal",
                dedupe_key="anomaly:suppression-reuse:sensor-1",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        assert repeat_decision.suppressed is False
        asyncio.run(
            env.service.dismiss_suggestion(
                second.id,
                suppress_future=True,
                suppression_hours=1,
            )
        )

        with env.factory() as unit_of_work:
            assert unit_of_work.memories is not None
            preferences, total = unit_of_work.memories.list_preferences(
                status="active",
                category="proactive_suppression",
            )
        assert total == 1
        assert preferences[0].source_record_id == second.id
        expires_at = preferences[0].expires_at
        assert expires_at is not None
        assert expires_at.replace(tzinfo=UTC) == env.clock.now + timedelta(hours=1)
    finally:
        env.manager.dispose()


def test_accept_suggestion_marks_accepted_and_updates_quality(tmp_path: Path) -> None:
    env = proactive_environment(tmp_path)
    try:
        suggestion, _ = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Useful anomaly",
                message="This is useful",
                importance="normal",
                dedupe_key="anomaly:accept:sensor-1",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        accepted = asyncio.run(env.service.accept_suggestion(suggestion.id))
        assert accepted.status == "accepted"
        assert accepted.accepted_at is not None
        assert accepted.quality_score == 1.0

        quality = asyncio.run(env.service.quality_summary(trigger_type="anomaly"))
        assert quality.total == 1
        assert quality.accepted == 1
        assert quality.quality_score == 100.0
    finally:
        env.manager.dispose()


def test_open_suggestion_updates_quality_score(tmp_path: Path) -> None:
    env = proactive_environment(tmp_path)
    try:
        suggestion, _ = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Opened anomaly",
                message="This was opened",
                importance="normal",
                dedupe_key="anomaly:open:sensor-1",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        opened = asyncio.run(env.service.mark_opened(suggestion.id))
        assert opened.status == "opened"
        assert opened.opened_at is not None
        assert opened.quality_score == 0.5
    finally:
        env.manager.dispose()


def test_feedback_is_stored_on_suggestion(tmp_path: Path) -> None:
    env = proactive_environment(tmp_path)
    try:
        suggestion, _ = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Feedback anomaly",
                message="Provide feedback",
                importance="normal",
                dedupe_key="anomaly:feedback:sensor-1",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        updated = asyncio.run(
            env.service.submit_feedback(
                suggestion.id,
                useful=True,
                correct=False,
                comment="The value seems wrong",
                desired_action="more_detail",
            )
        )
        assert updated.user_feedback is not None
        assert updated.user_feedback["useful"] is True
        assert updated.user_feedback["correct"] is False
        assert updated.user_feedback["comment"] == "The value seems wrong"
        assert updated.user_feedback["desired_action"] == "more_detail"
    finally:
        env.manager.dispose()


def test_expired_suggestions_are_cleaned_up(tmp_path: Path) -> None:
    env = proactive_environment(tmp_path)
    try:
        suggestion, _ = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Expired anomaly",
                message="This will expire",
                importance="normal",
                dedupe_key="anomaly:expire:sensor-1",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        env.clock.now += timedelta(hours=25)
        expired_count = asyncio.run(env.service.cleanup_expired())
        assert expired_count == 1
        expired = asyncio.run(env.service.get_suggestion(suggestion.id))
        assert expired.status == "expired"
    finally:
        env.manager.dispose()


def test_autonomy_level_is_capped_at_two_by_default(tmp_path: Path) -> None:
    env = proactive_environment(tmp_path)
    try:
        suggestion, _ = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Over-authorized anomaly",
                message="Try to execute at L4",
                importance="normal",
                dedupe_key="anomaly:cap:sensor-1",
                autonomy_level=4,
                now=env.clock.now,
            )
        )
        assert suggestion.autonomy_level == 2
    finally:
        env.manager.dispose()


def test_delete_suggestion_removes_record(tmp_path: Path) -> None:
    env = proactive_environment(tmp_path)
    try:
        suggestion, _ = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Delete me",
                message="This will be deleted",
                importance="low",
                dedupe_key="anomaly:delete:sensor-1",
                autonomy_level=0,
                now=env.clock.now,
            )
        )
        result = asyncio.run(env.service.delete_suggestion(suggestion.id))
        assert result["deleted"] is True
        with pytest.raises(ProactiveSuggestionNotFoundError):
            asyncio.run(env.service.get_suggestion(suggestion.id))
    finally:
        env.manager.dispose()


def test_dismiss_does_not_increase_future_frequency(tmp_path: Path) -> None:
    env = proactive_environment(tmp_path, cooldown_seconds=0)
    try:
        suggestion, _ = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Ignored anomaly",
                message="User will ignore this",
                importance="low",
                dedupe_key="anomaly:ignore:sensor-1",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        dismissed = asyncio.run(env.service.dismiss_suggestion(suggestion.id, feedback=None))
        assert dismissed.status == "dismissed"

        _, next_decision = asyncio.run(
            env.service.evaluate_candidate(
                environment_id=None,
                trigger_type="anomaly",
                title="Ignored anomaly",
                message="User will ignore this",
                importance="low",
                dedupe_key="anomaly:ignore:sensor-1",
                autonomy_level=2,
                now=env.clock.now,
            )
        )
        assert next_decision.suppressed is False
        assert next_decision.delivered_last_hour == 1
    finally:
        env.manager.dispose()


def test_proactive_does_not_execute_device_actions(tmp_path: Path) -> None:
    """Proactive service only creates suggestions; it never executes tools."""
    env = proactive_environment(tmp_path)
    try:
        asyncio.run(env.service.handle_event(sensor_event(value=40.0, sensor_type="temperature")))
        suggestions, _ = asyncio.run(env.service.list_suggestions(trigger_type="anomaly"))
        assert len(suggestions) == 1
        action = suggestions[0].candidate_action
        assert action["type"] == "inspect"
        assert "control_device" not in str(action)
        assert "execute" not in str(action)
    finally:
        env.manager.dispose()


def test_event_bus_integration_creates_suggestion_on_sensor_anomaly(
    tmp_path: Path,
) -> None:
    env = proactive_environment(tmp_path)
    event_bus = EventBus(env.factory)
    event_bus.subscribe(
        env.service.handle_event,
        event_types={ArvunoEventType.SENSOR_UPDATED.value},
    )
    try:
        asyncio.run(event_bus.publish(sensor_event(value=32.0)))
        suggestions, total = asyncio.run(env.service.list_suggestions(trigger_type="anomaly"))
        assert total == 1
        assert suggestions[0].status == "delivered"
    finally:
        env.manager.dispose()
