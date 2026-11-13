from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from typing import Any, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from arvuno_core.events.models import (
    ArvunoEvent,
    ArvunoEventType,
    DeviceUnavailablePayload,
    SensorUpdatedPayload,
    TaskFailedPayload,
)
from arvuno_core.persistence.models import ProactiveSuggestion, UserPreference
from arvuno_core.persistence.proactive import ProactiveRepository
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.proactive.errors import (
    ProactiveEnvironmentNotFoundError,
    ProactiveStateError,
    ProactiveSuggestionNotFoundError,
)
from arvuno_core.proactive.models import (
    ProactiveQualitySummary,
    ProactiveSuggestionView,
    SuppressionDecision,
)

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]


class NotificationProtocol(Protocol):
    async def create(
        self,
        *,
        channel: str,
        title: str,
        content: str,
        level: Any,
        related_event_id: str | None = None,
        related_task_id: str | None = None,
    ) -> Any: ...


ANOMALY_THRESHOLDS: dict[str, tuple[float, str]] = {
    "temperature": (30.0, "temperature is above 30°C"),
    "humidity": (70.0, "humidity is above 70%"),
    "co2": (1000.0, "CO2 concentration is above 1000 ppm"),
}

IMPORTANCE_BY_ATTRIBUTE: dict[str, str] = {
    "temperature": "normal",
    "humidity": "low",
    "co2": "normal",
}


class ProactiveService:
    """Evaluates environment signals and controls when to suggest or notify.

    This service never executes device actions. It only creates, stores, and
    rate-controls suggestions. Any device operation still goes through the
    Planning and Task systems after explicit user approval.
    """

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        notification_service: NotificationProtocol | None = None,
        *,
        environment_name: str = "home",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        suggestion_id_factory: Callable[[], str] = lambda: str(uuid4()),
        quiet_hours_start: time | None = None,
        quiet_hours_end: time | None = None,
        quiet_hours_timezone: str = "Asia/Shanghai",
        cooldown_seconds: int = 3600,
        max_per_hour: int = 5,
        max_per_day: int = 20,
        default_autonomy_level: int = 2,
        max_autonomy_level: int = 2,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._notification_service = notification_service
        self._environment_name = environment_name
        self._clock = clock
        self._suggestion_id_factory = suggestion_id_factory
        self._quiet_hours_start = quiet_hours_start
        self._quiet_hours_end = quiet_hours_end
        self._quiet_hours_timezone = ZoneInfo(quiet_hours_timezone)
        self._cooldown_seconds = cooldown_seconds
        self._max_per_hour = max_per_hour
        self._max_per_day = max_per_day
        self._default_autonomy_level = default_autonomy_level
        self._max_autonomy_level = max_autonomy_level

    async def handle_event(self, event: ArvunoEvent) -> None:
        """Event bus entry point for proactive evaluation."""
        if event.event_type is ArvunoEventType.SENSOR_UPDATED and isinstance(
            event.payload, SensorUpdatedPayload
        ):
            await self._evaluate_sensor(event, event.payload)
        elif event.event_type is ArvunoEventType.DEVICE_UNAVAILABLE and isinstance(
            event.payload, DeviceUnavailablePayload
        ):
            await self._evaluate_device_unavailable(event, event.payload)
        elif event.event_type is ArvunoEventType.TASK_FAILED and isinstance(
            event.payload, TaskFailedPayload
        ):
            await self._evaluate_task_failure(event, event.payload)

    async def evaluate_candidate(
        self,
        *,
        environment_id: str | None,
        trigger_type: str,
        title: str,
        message: str,
        importance: str,
        dedupe_key: str,
        candidate_action: dict[str, Any] | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        reasoning_session_id: str | None = None,
        hypothesis_id: str | None = None,
        goal_id: str | None = None,
        autonomy_level: int | None = None,
        now: datetime | None = None,
    ) -> tuple[ProactiveSuggestionView, SuppressionDecision]:
        """Evaluate a candidate suggestion through the full frequency-control pipeline."""
        suggestion, suppression = await asyncio.to_thread(
            self._evaluate_candidate,
            environment_id=environment_id,
            trigger_type=trigger_type,
            title=title,
            message=message,
            importance=importance,
            dedupe_key=dedupe_key,
            candidate_action=candidate_action or {},
            evidence_refs=evidence_refs or [],
            reasoning_session_id=reasoning_session_id,
            hypothesis_id=hypothesis_id,
            goal_id=goal_id,
            autonomy_level=autonomy_level,
            now=now,
        )
        if suggestion.status == "delivered":
            await self._send_notification(suggestion)
        return suggestion, suppression

    async def list_suggestions(
        self,
        *,
        environment_id: str | None = None,
        status: str | None = None,
        trigger_type: str | None = None,
        importance: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ProactiveSuggestionView], int]:
        def execute() -> tuple[list[ProactiveSuggestionView], int]:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.proactive is not None
                rows, total = unit_of_work.proactive.list(
                    environment_id=environment_id,
                    status=status,
                    trigger_type=trigger_type,
                    importance=importance,
                    page=page,
                    page_size=page_size,
                )
                return [self._view(row) for row in rows], total

        return await asyncio.to_thread(execute)

    async def get_suggestion(self, suggestion_id: str) -> ProactiveSuggestionView:
        def execute() -> ProactiveSuggestionView:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.proactive is not None
                row = unit_of_work.proactive.get(suggestion_id)
                if row is None:
                    raise ProactiveSuggestionNotFoundError()
                return self._view(row)

        return await asyncio.to_thread(execute)

    async def mark_opened(self, suggestion_id: str) -> ProactiveSuggestionView:
        def execute() -> ProactiveSuggestionView:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.proactive is not None
                row = unit_of_work.proactive.get(suggestion_id)
                if row is None:
                    raise ProactiveSuggestionNotFoundError()
                if row.status not in ("delivered", "opened"):
                    raise ProactiveStateError(
                        f"Cannot mark a suggestion in status '{row.status}' as opened."
                    )
                row.status = "opened"
                row.opened_at = self._now()
                unit_of_work.proactive.mark(row)
                self._update_quality_score(row)
                unit_of_work.commit()
                return self._view(row)

        return await asyncio.to_thread(execute)

    async def accept_suggestion(
        self,
        suggestion_id: str,
        *,
        feedback: str | None = None,
    ) -> ProactiveSuggestionView:
        def execute() -> ProactiveSuggestionView:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.proactive is not None
                row = unit_of_work.proactive.get(suggestion_id)
                if row is None:
                    raise ProactiveSuggestionNotFoundError()
                if row.status not in ("delivered", "opened", "queued", "evaluated"):
                    raise ProactiveStateError(
                        f"Cannot accept a suggestion in status '{row.status}'."
                    )
                now = self._now()
                row.status = "accepted"
                row.accepted_at = now
                row.user_feedback = {
                    "action": "accept",
                    "feedback": feedback,
                    "at": now.isoformat(),
                }
                unit_of_work.proactive.mark(row)
                self._update_quality_score(row)
                unit_of_work.commit()
                return self._view(row)

        return await asyncio.to_thread(execute)

    async def dismiss_suggestion(
        self,
        suggestion_id: str,
        *,
        feedback: str | None = None,
        suppress_future: bool = False,
        suppression_hours: int = 24,
    ) -> ProactiveSuggestionView:
        def execute() -> ProactiveSuggestionView:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.proactive is not None
                repository = unit_of_work.proactive
                row = repository.get(suggestion_id)
                if row is None:
                    raise ProactiveSuggestionNotFoundError()
                if row.status in ("accepted", "dismissed", "expired"):
                    raise ProactiveStateError(
                        f"Cannot dismiss a suggestion in status '{row.status}'."
                    )
                now = self._now()
                row.status = "dismissed"
                row.dismissed_at = now
                row.user_feedback = {
                    "action": "dismiss",
                    "feedback": feedback,
                    "suppress_future": suppress_future,
                    "suppression_hours": suppression_hours if suppress_future else None,
                    "at": now.isoformat(),
                }
                repository.mark(row)
                self._update_quality_score(row)
                if suppress_future:
                    key = self._suppression_key(row.environment_id, row.dedupe_key)
                    preference = repository.preference_for_key(key)
                    is_new_preference = preference is None
                    if preference is None:
                        preference = UserPreference(key=key)
                    preference.value = {
                        "environment_id": row.environment_id,
                        "dedupe_key": row.dedupe_key,
                    }
                    preference.category = "proactive_suppression"
                    preference.description = (
                        "Do not remind for this proactive trigger in this environment"
                    )
                    preference.source = "user"
                    preference.source_type = "user"
                    preference.source_record_id = suggestion_id
                    preference.status = "active"
                    preference.scope = {"environment_id": row.environment_id}
                    preference.confirmed = True
                    preference.confirmed_at = now
                    preference.valid_from = now
                    preference.expires_at = now + timedelta(hours=max(1, suppression_hours))
                    preference.updated_at = now
                    if is_new_preference:
                        assert unit_of_work.memories is not None
                        unit_of_work.memories.add_preference(preference)
                unit_of_work.commit()
                return self._view(row)

        return await asyncio.to_thread(execute)

    async def submit_feedback(
        self,
        suggestion_id: str,
        *,
        useful: bool | None = None,
        correct: bool | None = None,
        comment: str | None = None,
        desired_action: str | None = None,
    ) -> ProactiveSuggestionView:
        def execute() -> ProactiveSuggestionView:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.proactive is not None
                row = unit_of_work.proactive.get(suggestion_id)
                if row is None:
                    raise ProactiveSuggestionNotFoundError()
                now = self._now()
                feedback: dict[str, Any] = dict(row.user_feedback or {})
                feedback.update(
                    {
                        "useful": useful,
                        "correct": correct,
                        "comment": comment,
                        "desired_action": desired_action,
                        "feedback_at": now.isoformat(),
                    }
                )
                row.user_feedback = feedback
                unit_of_work.proactive.mark(row)
                unit_of_work.commit()
                return self._view(row)

        return await asyncio.to_thread(execute)

    async def delete_suggestion(self, suggestion_id: str) -> dict[str, Any]:
        def execute() -> dict[str, Any]:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.proactive is not None
                row = unit_of_work.proactive.get(suggestion_id)
                if row is None:
                    raise ProactiveSuggestionNotFoundError()
                unit_of_work.proactive.delete(row)
                unit_of_work.commit()
                return {"id": suggestion_id, "deleted": True}

        return await asyncio.to_thread(execute)

    async def quality_summary(
        self,
        *,
        environment_id: str | None = None,
        trigger_type: str,
    ) -> ProactiveQualitySummary:
        def execute() -> ProactiveQualitySummary:
            nonlocal environment_id
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.proactive is not None
                if environment_id is None:
                    environment = unit_of_work.proactive.environment(None, self._environment_name)
                    if environment is None:
                        raise ProactiveEnvironmentNotFoundError()
                    environment_id = environment.id
                counts = unit_of_work.proactive.trigger_quality(
                    environment_id=environment_id,
                    trigger_type=trigger_type,
                )
                total = sum(counts.values())
                opened = counts.get("opened", 0) + counts.get("accepted", 0)
                accepted = counts.get("accepted", 0)
                delivered = counts.get("delivered", 0) + opened
                score = (accepted / delivered * 100.0) if delivered > 0 else None
                return ProactiveQualitySummary(
                    trigger_type=trigger_type,
                    total=total,
                    evaluated=counts.get("evaluated", 0),
                    suppressed=counts.get("suppressed", 0),
                    queued=counts.get("queued", 0),
                    delivered=delivered,
                    opened=counts.get("opened", 0),
                    accepted=counts.get("accepted", 0),
                    dismissed=counts.get("dismissed", 0),
                    expired=counts.get("expired", 0),
                    quality_score=round(score, 2) if score is not None else None,
                )

        return await asyncio.to_thread(execute)

    async def cleanup_expired(
        self,
        *,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> int:
        def execute() -> int:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.proactive is not None
                count = unit_of_work.proactive.expire_stale(
                    now=now or self._now(),
                    limit=limit,
                )
                unit_of_work.commit()
                return count

        return await asyncio.to_thread(execute)

    async def _evaluate_sensor(
        self,
        event: ArvunoEvent,
        payload: SensorUpdatedPayload,
    ) -> None:
        threshold_info = ANOMALY_THRESHOLDS.get(payload.sensor_type)
        if threshold_info is None:
            return
        threshold, reason = threshold_info
        try:
            numeric_value = float(payload.value)
        except (TypeError, ValueError):
            return
        if numeric_value <= threshold:
            return
        importance = IMPORTANCE_BY_ATTRIBUTE.get(payload.sensor_type, "normal")
        await self.evaluate_candidate(
            environment_id=None,
            trigger_type="anomaly",
            title=f"{payload.sensor_type.title()} anomaly detected",
            message=f"Sensor {payload.device_id} reported {payload.sensor_type} "
            f"{payload.value}{payload.unit or ''}, which exceeds the expected range.",
            importance=importance,
            dedupe_key=f"anomaly:{payload.device_id}:{payload.sensor_type}",
            candidate_action={
                "type": "inspect",
                "suggested_tool": "get_environment_state",
                "parameters": {"device_id": payload.device_id},
            },
            evidence_refs=[
                {
                    "type": "event",
                    "id": event.id,
                    "detail": reason,
                }
            ],
            autonomy_level=2,
            now=event.occurred_at,
        )

    async def _evaluate_device_unavailable(
        self,
        event: ArvunoEvent,
        payload: DeviceUnavailablePayload,
    ) -> None:
        await self.evaluate_candidate(
            environment_id=None,
            trigger_type="device_fault",
            title=f"Device {payload.device_id} is unavailable",
            message=f"Device {payload.device_id} became unavailable: {payload.reason}",
            importance="normal",
            dedupe_key=f"device_fault:{payload.device_id}",
            candidate_action={
                "type": "inspect",
                "suggested_tool": "get_device_state",
                "parameters": {"device_id": payload.device_id},
            },
            evidence_refs=[
                {
                    "type": "event",
                    "id": event.id,
                    "detail": payload.reason,
                }
            ],
            autonomy_level=2,
            now=event.occurred_at,
        )

    async def _evaluate_task_failure(
        self,
        event: ArvunoEvent,
        payload: TaskFailedPayload,
    ) -> None:
        await self.evaluate_candidate(
            environment_id=None,
            trigger_type="task_failure",
            title=f"Task {payload.task_id} failed",
            message=f"Task {payload.task_id} failed: {payload.error_message}",
            importance="normal",
            dedupe_key=f"task_failure:{payload.task_id}:{payload.error_code}",
            candidate_action={
                "type": "inspect",
                "suggested_query": "What caused this task to fail?",
            },
            evidence_refs=[
                {
                    "type": "event",
                    "id": event.id,
                    "detail": payload.error_message,
                }
            ],
            autonomy_level=2,
            now=event.occurred_at,
        )

    def _evaluate_candidate(
        self,
        *,
        environment_id: str | None,
        trigger_type: str,
        title: str,
        message: str,
        importance: str,
        dedupe_key: str,
        candidate_action: dict[str, Any],
        evidence_refs: list[dict[str, Any]],
        reasoning_session_id: str | None,
        hypothesis_id: str | None,
        goal_id: str | None,
        autonomy_level: int | None,
        now: datetime | None,
    ) -> tuple[ProactiveSuggestionView, SuppressionDecision]:
        current = self._now() if now is None else self._normalize(now)
        level = min(
            autonomy_level if autonomy_level is not None else self._default_autonomy_level,
            self._max_autonomy_level,
        )

        with self._unit_of_work_factory() as unit_of_work:
            assert unit_of_work.proactive is not None
            repository = unit_of_work.proactive
            environment = repository.environment(environment_id, self._environment_name)
            if environment is None:
                raise ProactiveEnvironmentNotFoundError()

            suppression = self._check_suppression(
                repository,
                environment_id=environment.id,
                dedupe_key=dedupe_key,
                importance=importance,
                autonomy_level=level,
                now=current,
            )
            suggestion = ProactiveSuggestion(
                id=self._suggestion_id_factory(),
                environment_id=environment.id,
                reasoning_session_id=reasoning_session_id,
                hypothesis_id=hypothesis_id,
                goal_id=goal_id,
                trigger_type=trigger_type,
                title=title,
                message=message,
                importance=importance,
                autonomy_level=level,
                candidate_action=candidate_action,
                evidence_refs=evidence_refs,
                dedupe_key=dedupe_key,
                status="suppressed" if suppression.suppressed else "evaluated",
                suppression_count=0,
                cooldown_until=current + timedelta(seconds=self._cooldown_seconds),
                created_at=current,
                updated_at=current,
                expires_at=current + timedelta(hours=24),
            )
            if suppression.suppressed:
                if suppression.active_suggestion_id is not None:
                    active = repository.get(suppression.active_suggestion_id)
                    if active is not None:
                        active.suppression_count += 1
                        repository.mark(active)
                        suggestion.suppression_count = active.suppression_count
                        suggestion.user_feedback = None
            else:
                if level >= 2:
                    suggestion.status = "delivered"
                    suggestion.delivered_at = current
            repository.add(suggestion)
            unit_of_work.commit()
            return self._view(suggestion), suppression

    def _check_suppression(
        self,
        repository: ProactiveRepository,
        *,
        environment_id: str,
        dedupe_key: str,
        importance: str,
        autonomy_level: int,
        now: datetime,
    ) -> SuppressionDecision:
        preference = repository.suppression_preference(
            environment_id=environment_id,
            dedupe_key=dedupe_key,
            now=now,
        )
        if preference is not None:
            return SuppressionDecision(
                suppressed=True,
                reason="user_suppressed",
                active_suggestion_id=None,
            )

        active = repository.active_in_cooldown(
            environment_id=environment_id,
            dedupe_key=dedupe_key,
            now=now,
        )
        if active is not None:
            return SuppressionDecision(
                suppressed=True,
                reason="cooldown" if active.cooldown_until is not None else "duplicate_active",
                active_suggestion_id=active.id,
            )

        if self._in_quiet_hours(now) and importance != "high":
            return SuppressionDecision(suppressed=True, reason="quiet_hours")

        hourly_count = repository.delivered_count_since(
            environment_id=environment_id,
            since=now - timedelta(hours=1),
        )
        if hourly_count >= self._max_per_hour:
            return SuppressionDecision(
                suppressed=True,
                reason="rate_limit_hour",
                delivered_last_hour=hourly_count,
            )

        daily_count = repository.delivered_count_since(
            environment_id=environment_id,
            since=now - timedelta(days=1),
        )
        if daily_count >= self._max_per_day:
            return SuppressionDecision(
                suppressed=True,
                reason="rate_limit_day",
                delivered_last_day=daily_count,
            )

        return SuppressionDecision(
            suppressed=False,
            reason="allowed",
            delivered_last_hour=hourly_count,
            delivered_last_day=daily_count,
        )

    def _in_quiet_hours(self, now: datetime) -> bool:
        if self._quiet_hours_start is None or self._quiet_hours_end is None:
            return False
        current_time = now.astimezone(self._quiet_hours_timezone).time()
        if self._quiet_hours_start <= self._quiet_hours_end:
            return self._quiet_hours_start <= current_time < self._quiet_hours_end
        return current_time >= self._quiet_hours_start or current_time < self._quiet_hours_end

    async def _send_notification(self, suggestion: ProactiveSuggestion) -> None:
        if self._notification_service is None:
            return
        level_map = {"low": "info", "normal": "warning", "high": "warning"}
        try:
            await self._notification_service.create(
                channel="web_console",
                title=suggestion.title,
                content=suggestion.message,
                level=level_map.get(suggestion.importance, "info"),
            )
        except Exception:
            return

    def _update_quality_score(self, suggestion: ProactiveSuggestion) -> None:
        opened = suggestion.opened_at is not None or suggestion.accepted_at is not None
        accepted = suggestion.accepted_at is not None
        if opened:
            suggestion.quality_score = 1.0 if accepted else 0.5
        elif suggestion.dismissed_at is not None:
            suggestion.quality_score = 0.0

    def _view(self, row: ProactiveSuggestion) -> ProactiveSuggestionView:
        return ProactiveSuggestionView(
            id=row.id,
            environment_id=row.environment_id,
            reasoning_session_id=row.reasoning_session_id,
            hypothesis_id=row.hypothesis_id,
            goal_id=row.goal_id,
            trigger_type=row.trigger_type,
            title=row.title,
            message=row.message,
            importance=row.importance,
            autonomy_level=row.autonomy_level,
            candidate_action=row.candidate_action or {},
            evidence_refs=row.evidence_refs or [],
            dedupe_key=row.dedupe_key,
            status=row.status,
            suppression_count=row.suppression_count,
            delivered_at=row.delivered_at,
            opened_at=row.opened_at,
            accepted_at=row.accepted_at,
            dismissed_at=row.dismissed_at,
            user_feedback=row.user_feedback,
            cooldown_until=row.cooldown_until,
            quality_score=row.quality_score,
            created_at=row.created_at,
            updated_at=row.updated_at,
            expires_at=row.expires_at,
        )

    def _now(self) -> datetime:
        return self._normalize(self._clock())

    @staticmethod
    def _suppression_key(environment_id: str, dedupe_key: str) -> str:
        scope = f"{environment_id}\0{dedupe_key}".encode()
        return f"proactive_suppression:{sha256(scope).hexdigest()}"

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


__all__ = ["ProactiveService"]
