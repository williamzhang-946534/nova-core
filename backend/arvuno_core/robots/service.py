import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from arvuno_core.events.models import (
    ArvunoEvent,
    ArvunoEventSource,
    ArvunoEventType,
    RobotSafetyChangedPayload,
    RobotStateChangedPayload,
    RobotTaskUpdatedPayload,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.robots.errors import (
    RobotAdapterUnavailableError,
    RobotCapabilityDisabledError,
    RobotCapabilityUnsupportedError,
    RobotConnectionError,
    RobotExecutionLockedError,
    RobotLocalizationLostError,
    RobotLowBatteryError,
    RobotNavigationError,
    RobotNotFoundError,
    RobotSafetyStateError,
    RobotTaskNotFoundError,
    RobotTaskStateError,
    RobotUnavailableError,
)
from arvuno_core.robots.interface import RobotAdapter
from arvuno_core.robots.models import (
    ACTIVE_ROBOT_TASK_STATUSES,
    RegisteredRobot,
    RegisteredRobotTaskRequest,
    RobotCapability,
    RobotCapabilityName,
    RobotConnectionState,
    RobotConsent,
    RobotConsentGrant,
    RobotEvent,
    RobotHeartbeatReport,
    RobotHeartbeatResult,
    RobotMotionSafetyState,
    RobotPolicySnapshot,
    RobotRuntimeState,
    RobotRuntimeStatus,
    RobotStateSnapshot,
    RobotTaskRequestCreate,
    RobotTaskStatus,
    utc_now,
)
from arvuno_core.robots.registry import RobotRegistry

logger = logging.getLogger(__name__)


class RobotEventPublisher(Protocol):
    """Structural contract for the application EventBus."""

    async def publish(self, event: ArvunoEvent) -> None: ...


class RobotApplicationService:
    """High-level robot boundary used by API and future controlled tools."""

    def __init__(
        self,
        registry: RobotRegistry,
        adapters: dict[str, RobotAdapter],
        *,
        unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork],
        event_publisher: RobotEventPublisher | None = None,
        clock: Callable[[], datetime] = utc_now,
        heartbeat_timeout_seconds: float = 30.0,
    ) -> None:
        self._registry = registry
        self._adapters = dict(adapters)
        self._unit_of_work_factory = unit_of_work_factory
        self._event_publisher = event_publisher
        self._clock = clock
        if heartbeat_timeout_seconds <= 0:
            raise ValueError("heartbeat_timeout_seconds must be positive.")
        self._heartbeat_timeout_seconds = heartbeat_timeout_seconds

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    async def sync_robot(self, adapter: RobotAdapter, external_id: str) -> None:
        await self._registry.sync_robot(adapter, external_id)

    async def list_robots(self, *, enabled_only: bool = False) -> list[RegisteredRobot]:
        return await self._registry.list_robots(enabled_only=enabled_only)

    async def get_robot(self, robot_id: str) -> RegisteredRobot:
        robot = await self._registry.get_robot(robot_id)
        if robot is None or not robot.is_enabled:
            raise RobotNotFoundError()
        return robot

    async def enable_robot(self, robot_id: str, *, enabled: bool) -> RegisteredRobot:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()
        return await self._registry.set_enabled(robot_id, enabled=enabled)

    async def set_capability_governance(
        self,
        robot_id: str,
        capability: RobotCapabilityName,
        *,
        enabled: bool | None = None,
        approved: bool | None = None,
        consent_granted: bool | None = None,
        approved_by: str = "system",
    ) -> RobotCapability:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()
        return await self._registry.set_capability_governance(
            robot_id,
            capability,
            enabled=enabled,
            approved=approved,
            consent_granted=consent_granted,
            approved_by=approved_by,
        )

    async def grant_consent(
        self,
        robot_id: str,
        grant: RobotConsentGrant,
    ) -> RobotConsent:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()

        def execute() -> RobotConsent:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                result = unit_of_work.robots.create_consent(robot.id, grant)
                unit_of_work.commit()
                return result

        return await asyncio.to_thread(execute)

    async def revoke_consent(
        self,
        robot_id: str,
        consent_id: str,
        *,
        revoked_by: str,
    ) -> RobotConsent:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()

        def execute() -> RobotConsent:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                result = unit_of_work.robots.revoke_consent(
                    robot.id,
                    consent_id,
                    revoked_by=revoked_by,
                )
                unit_of_work.commit()
                return result

        return await asyncio.to_thread(execute)

    async def list_consents(
        self,
        robot_id: str,
        *,
        capability: RobotCapabilityName | None = None,
        active_only: bool = False,
    ) -> list[RobotConsent]:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()

        def execute() -> list[RobotConsent]:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                return unit_of_work.robots.list_consents(
                    robot.id,
                    capability=capability,
                    active_only=active_only,
                )

        return await asyncio.to_thread(execute)

    async def find_robot_for_policy(self, robot_id: str) -> RobotPolicySnapshot | None:
        def execute() -> RobotPolicySnapshot | None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                return unit_of_work.robots.policy_snapshot(robot_id)

        return await asyncio.to_thread(execute)

    async def capabilities(self, robot_id: str) -> list[RobotCapability]:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()
        return await self._registry.capabilities(robot.id)

    async def state(self, robot_id: str) -> RegisteredRobot:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()
        adapter = self._adapter(robot.adapter_id)
        snapshot = await adapter.get_state(robot.external_id)
        return await self._record_state(robot, snapshot)

    async def runtime_status(
        self,
        robot_id: str,
        *,
        now: datetime | None = None,
    ) -> RobotRuntimeStatus:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()
        active_tasks = await self.list_task_requests(
            robot.id,
            limit=500,
        )
        return self._evaluate_runtime(
            robot,
            [request for request in active_tasks if request.status in ACTIVE_ROBOT_TASK_STATUSES],
            now or self._now(),
        )

    async def heartbeat(
        self,
        robot_id: str,
        report: RobotHeartbeatReport,
    ) -> RobotHeartbeatResult:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()
        observed_at = self._normalize_datetime(report.observed_at)
        now = self._now()
        if observed_at > now + timedelta(seconds=5):
            status = await self.runtime_status(robot.id, now=now)
            return RobotHeartbeatResult(
                accepted=False,
                reason="future_heartbeat",
                robot=robot,
                runtime_state=status,
            )
        last_seen_at = (
            None if robot.last_seen_at is None else self._normalize_datetime(robot.last_seen_at)
        )
        if last_seen_at is not None and observed_at <= last_seen_at:
            status = await self.runtime_status(robot.id, now=now)
            return RobotHeartbeatResult(
                accepted=False,
                reason="late_heartbeat",
                robot=robot,
                runtime_state=status,
            )

        snapshot = RobotStateSnapshot(
            robot_id=robot.id,
            connection_state=RobotConnectionState.CONNECTED,
            is_online=True,
            motion_safety_state=report.motion_safety_state or robot.motion_safety_state,
            emergency_stop=(
                report.emergency_stop if report.emergency_stop is not None else robot.emergency_stop
            ),
            manual_takeover=(
                report.manual_takeover
                if report.manual_takeover is not None
                else robot.manual_takeover
            ),
            battery_percent=(
                report.battery_percent
                if report.battery_percent is not None
                else robot.battery_percent
            ),
            device_states=report.device_states or robot.device_states,
            location=report.location or robot.location,
            source=report.source,
            observed_at=observed_at,
        )
        updated = await self._record_state(robot, snapshot)
        status = await self.runtime_status(robot.id, now=now)
        return RobotHeartbeatResult(
            accepted=True,
            reason="accepted",
            robot=updated,
            runtime_state=status,
        )

    async def resynchronize(self, robot_id: str) -> RobotRuntimeStatus:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()
        adapter = self._adapter(robot.adapter_id)
        try:
            snapshot = await adapter.get_state(robot.external_id)
            await self._record_state(robot, snapshot)
        except (
            RobotAdapterUnavailableError,
            RobotConnectionError,
            RobotUnavailableError,
            TimeoutError,
        ) as exc:
            await self._registry.mark_unavailable(
                robot.adapter_id,
                robot.external_id,
                reason=exc.code,
                occurred_at=self._now(),
            )
        return await self.runtime_status(robot.id)

    async def events(
        self,
        robot_id: str,
        *,
        task_request_id: str | None = None,
        limit: int = 100,
    ) -> list[RobotEvent]:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()

        def execute() -> list[RobotEvent]:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                return unit_of_work.robots.list_events(
                    robot.id,
                    task_request_id=task_request_id,
                    limit=limit,
                )

        return await asyncio.to_thread(execute)

    async def create_task_request(
        self,
        robot_id: str,
        request: RobotTaskRequestCreate,
    ) -> RegisteredRobotTaskRequest:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()
        adapter = self._adapter(robot.adapter_id)
        capability = await self._capability(robot.id, request.capability)
        self._require_executable_capability(capability)
        if not robot.is_enabled:
            raise RobotNotFoundError()

        def execute() -> RegisteredRobotTaskRequest:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                stored = unit_of_work.robots.create_task_request(
                    robot.id,
                    request,
                    capability=capability,
                )
                unit_of_work.commit()
                return stored

        stored = await asyncio.to_thread(execute)
        del adapter
        return stored

    async def execute_preauthorized_task_request(
        self,
        robot_id: str,
        request: RobotTaskRequestCreate,
        *,
        task_id: str,
        task_step_id: str,
        tool_execution_id: str,
    ) -> RegisteredRobotTaskRequest:
        """Execute a request only after ToolExecutor has consumed a server token."""

        robot = await self._registry.get_robot(robot_id)
        if robot is None or not robot.is_enabled:
            raise RobotNotFoundError()
        adapter = self._adapter(robot.adapter_id)
        capability = await self._capability(robot.id, request.capability)
        self._require_executable_capability(capability)

        authorized_request = request.model_copy(
            update={
                "confirmed": False,
                "task_id": task_id,
            }
        )

        def create() -> RegisteredRobotTaskRequest:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                stored = unit_of_work.robots.create_task_request(
                    robot.id,
                    authorized_request,
                    capability=capability,
                    task_step_id=task_step_id,
                    tool_execution_id=tool_execution_id,
                )
                unit_of_work.commit()
                return stored

        stored = await asyncio.to_thread(create)
        if _is_final(stored.status):
            raise RobotTaskStateError(
                "The idempotency key matches an already completed robot task."
            )
        submitted = await self._update_request(
            stored.id,
            status=RobotTaskStatus.SUBMITTED,
            task_id=task_id,
            task_step_id=task_step_id,
            tool_execution_id=tool_execution_id,
            confirmed_by_user=True,
            submitted_at=self._now(),
        )
        await self._save_events(
            self._task_transition_events(
                submitted,
                "task_running",
            ),
            task=submitted,
        )
        return await self._execute(
            submitted.model_copy(update={"confirmed_by_user": True}),
            adapter,
        )

    async def confirm_task_request(
        self,
        robot_id: str,
        request_id: str,
        *,
        confirmed: bool,
        confirmed_by: str,
    ) -> RegisteredRobotTaskRequest:
        del robot_id, request_id, confirmed, confirmed_by
        raise RobotExecutionLockedError(
            "Legacy robot confirmation was removed; use the unified safety chain."
        )

    async def cancel_task_request(
        self,
        robot_id: str,
        request_id: str,
        *,
        cancelled_by: str,
    ) -> RegisteredRobotTaskRequest:
        del cancelled_by  # API authentication is the current cancellation actor boundary
        robot = await self.get_robot(robot_id)
        request = self._request(request_id)
        if request.robot_id != robot.id:
            raise RobotTaskNotFoundError()
        if _is_final(request.status):
            raise RobotTaskStateError("The robot task is already finished.")
        adapter = self._adapter(robot.adapter_id)
        requested = await self._update_request(
            request.id,
            status=RobotTaskStatus.CANCEL_REQUESTED,
        )
        await self._save_events(
            self._task_transition_events(
                requested,
                "task_cancel_requested",
                severity="warning",
            ),
            task=requested,
        )
        stopping = await self._update_request(request.id, status=RobotTaskStatus.STOPPING)
        await self._save_events(
            self._task_transition_events(
                stopping,
                "task_stopping",
                severity="warning",
            ),
            task=stopping,
        )
        try:
            result = await asyncio.wait_for(
                adapter.cancel_task(request),
                timeout=request.timeout_seconds,
            )
        except TimeoutError:
            await self._resynchronize_after_failure(robot, "cancel_task_timeout")
            unknown = await self._update_request(
                request.id,
                status=RobotTaskStatus.EXECUTION_UNKNOWN,
                error={
                    "code": "ROBOT_TASK_TIMEOUT",
                    "message": "The robot cancellation result is unknown.",
                },
                completed_at=self._now(),
            )
            await self._save_events(
                self._task_transition_events(
                    unknown,
                    "task_execution_unknown",
                    severity="critical",
                    error_code="ROBOT_TASK_TIMEOUT",
                ),
                task=unknown,
            )
            return unknown
        except (RobotConnectionError, RobotUnavailableError) as exc:
            await self._registry.mark_unavailable(
                robot.adapter_id,
                robot.external_id,
                reason="cancel_task_failed",
                occurred_at=self._now(),
            )
            unknown = await self._update_request(
                request_id,
                status=RobotTaskStatus.EXECUTION_UNKNOWN,
                error={
                    "code": exc.code,
                    "message": "The robot cancellation result is unknown.",
                },
                completed_at=self._now(),
            )
            await self._save_events(
                self._task_transition_events(
                    unknown,
                    "task_execution_unknown",
                    severity="critical",
                    error_code=exc.code,
                ),
                task=unknown,
            )
            return unknown
        except Exception as exc:
            failed = await self._update_request(
                request_id,
                status=RobotTaskStatus.CANCEL_FAILED,
                error={"code": "ROBOT_CANCEL_FAILED", "message": str(exc)},
                completed_at=self._now(),
            )
            await self._save_events(
                self._task_transition_events(
                    failed,
                    "task_cancel_failed",
                    severity="critical",
                    error_code="ROBOT_CANCEL_FAILED",
                ),
                task=failed,
            )
            return failed

        if not result.success:
            await self._record_adapter_state(request.robot_id, result.state)
            failed = await self._update_request(
                request_id,
                status=RobotTaskStatus.CANCEL_FAILED,
                error={
                    "code": "ROBOT_CANCEL_FAILED",
                    "message": result.message or "The robot rejected cancellation.",
                },
                completed_at=self._now(),
            )
            await self._save_events(
                self._task_transition_events(
                    failed,
                    "task_cancel_failed",
                    severity="critical",
                    error_code="ROBOT_CANCEL_FAILED",
                ),
                task=failed,
            )
            return failed

        await self._record_adapter_state(request.robot_id, result.state)
        cancelled = await self._update_request(
            request_id,
            status=RobotTaskStatus.CANCELLED,
            result=result.result,
            error=None,
            completed_at=self._now(),
        )
        await self._save_events(
            self._normalize_events(request, result.events),
            task=cancelled,
        )
        await self._save_events(
            self._task_transition_events(
                cancelled,
                "task_cancelled",
            ),
            task=cancelled,
        )
        return cancelled

    async def task_request(self, robot_id: str, request_id: str) -> RegisteredRobotTaskRequest:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()
        request = self._request(request_id)
        if request.robot_id != robot.id:
            raise RobotTaskNotFoundError()
        return request

    async def task_request_by_id(self, request_id: str) -> RegisteredRobotTaskRequest:
        request = self._request(request_id)
        robot = await self._registry.get_robot(request.robot_id)
        if robot is None:
            raise RobotNotFoundError()
        return request

    async def list_task_requests(
        self,
        robot_id: str,
        *,
        status: RobotTaskStatus | None = None,
        limit: int = 100,
    ) -> list[RegisteredRobotTaskRequest]:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()

        def execute() -> list[RegisteredRobotTaskRequest]:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                return unit_of_work.robots.list_task_requests(
                    robot.id,
                    status=status,
                    limit=limit,
                )

        return await asyncio.to_thread(execute)

    async def _execute(
        self,
        request: RegisteredRobotTaskRequest,
        adapter: RobotAdapter,
    ) -> RegisteredRobotTaskRequest:
        try:
            result = await asyncio.wait_for(
                adapter.execute_task(request),
                timeout=request.timeout_seconds,
            )
        except TimeoutError as exc:
            return await self._fail_from_adapter(
                request,
                status=RobotTaskStatus.TIMEOUT,
                error={"code": "ROBOT_TASK_TIMEOUT", "message": str(exc)},
            )
        except RobotSafetyStateError as exc:
            return await self._fail_from_adapter(
                request,
                status=RobotTaskStatus.SAFE_STOPPED,
                error={"code": exc.code, "message": exc.message},
            )
        except (RobotConnectionError, RobotLowBatteryError, RobotUnavailableError) as exc:
            return await self._fail_from_adapter(
                request,
                status=RobotTaskStatus.UNAVAILABLE,
                error={"code": exc.code, "message": exc.message},
            )
        except (RobotNavigationError, RobotLocalizationLostError) as exc:
            return await self._fail_from_adapter(
                request,
                status=RobotTaskStatus.FAILED,
                error={"code": exc.code, "message": exc.message},
            )
        except Exception as exc:
            return await self._fail_from_adapter(
                request,
                status=RobotTaskStatus.FAILED,
                error={"code": "ROBOT_TASK_FAILED", "message": str(exc)},
            )

        if result.success and not _result_matches_capability(
            request.capability,
            result.result,
            result.state,
        ):
            return await self._fail_from_adapter(
                request,
                status=RobotTaskStatus.FAILED,
                error={
                    "code": "ROBOT_STATE_VERIFICATION_FAILED",
                    "message": "The adapter result did not satisfy the capability contract.",
                },
            )

        await self._record_adapter_state(request.robot_id, result.state)
        updated = await self._update_request(
            request.id,
            status=RobotTaskStatus.SUCCEEDED if result.success else RobotTaskStatus.FAILED,
            result=result.result,
            error=(
                None if result.success else {"code": "ROBOT_TASK_FAILED", "message": result.message}
            ),
            completed_at=self._now(),
        )
        await self._save_events(
            self._normalize_events(request, result.events),
            task=updated,
        )
        return updated

    async def _resynchronize_after_failure(
        self,
        robot: RegisteredRobot,
        reason: str,
    ) -> None:
        try:
            adapter = self._adapter(robot.adapter_id)
            snapshot = await adapter.get_state(robot.external_id)
            await self._record_state(robot, snapshot)
        except Exception as exc:
            logger.warning(
                "robot_resynchronize_after_failure_failed",
                extra={
                    "robot_id": robot.id,
                    "reason": reason,
                    "error_code": getattr(exc, "code", None),
                },
            )
            try:
                await self._registry.mark_unavailable(
                    robot.adapter_id,
                    robot.external_id,
                    reason=reason,
                    occurred_at=self._now(),
                )
            except Exception:
                logger.exception(
                    "robot_unavailable_projection_failed",
                    extra={"robot_id": robot.id, "reason": reason},
                )

    def _normalize_events(
        self,
        request: RegisteredRobotTaskRequest,
        events: list[RobotEvent],
    ) -> list[RobotEvent]:
        return [event.model_copy(update={"robot_id": request.robot_id}) for event in events]

    async def _fail_from_adapter(
        self,
        request: RegisteredRobotTaskRequest,
        *,
        status: RobotTaskStatus,
        error: dict[str, Any],
    ) -> RegisteredRobotTaskRequest:
        try:
            robot = await self._registry.get_robot(request.robot_id)
            if robot is not None:
                if status is RobotTaskStatus.UNAVAILABLE:
                    await self._registry.mark_unavailable(
                        robot.adapter_id,
                        robot.external_id,
                        reason=error["code"],
                        occurred_at=self._now(),
                    )
                else:
                    await self._registry.record_state(
                        RobotStateSnapshot(
                            robot_id=robot.id,
                            connection_state="degraded",
                            is_online=True,
                            motion_safety_state=(
                                "stopped" if status is RobotTaskStatus.SAFE_STOPPED else "unknown"
                            ),
                            emergency_stop=robot.emergency_stop,
                            manual_takeover=robot.manual_takeover,
                            battery_percent=robot.battery_percent,
                            device_states=robot.device_states,
                            location=robot.location,
                            source="adapter_derived",
                            observed_at=self._now(),
                        )
                    )
        except Exception:
            pass

        event_type = {
            RobotTaskStatus.SAFE_STOPPED: "task_safe_stopped",
            RobotTaskStatus.TIMEOUT: "task_failed",
            RobotTaskStatus.UNAVAILABLE: "task_unavailable",
        }.get(status, "task_failed")
        updated = await self._update_request(
            request.id,
            status=status,
            error=error,
            completed_at=self._now(),
        )
        await self._save_events(
            self._task_transition_events(
                updated,
                event_type,  # type: ignore[arg-type]
                severity="warning" if status is RobotTaskStatus.TIMEOUT else "critical",
                error_code=error.get("code"),
            ),
            task=updated,
        )
        return updated

    async def _record_adapter_state(
        self,
        robot_id: str,
        snapshot: RobotStateSnapshot,
    ) -> None:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()
        await self._record_state(robot, snapshot)

    async def _record_state(
        self,
        robot: RegisteredRobot,
        snapshot: RobotStateSnapshot,
    ) -> RegisteredRobot:
        now = self._now()
        last_seen_at = (
            None if robot.last_seen_at is None else self._normalize_datetime(robot.last_seen_at)
        )
        observed_at = self._normalize_datetime(snapshot.observed_at)
        if last_seen_at is not None and observed_at < last_seen_at:
            late_event = RobotEvent(
                robot_id=robot.id,
                event_type="state_changed",
                severity="info",
                source="robot_service",
                payload={
                    "reason": "late_observation_ignored",
                    "observed_at": observed_at.isoformat(),
                    "last_seen_at": last_seen_at.isoformat(),
                },
                occurred_at=now,
                late_arrival=True,
            )
            await self._save_events([late_event])
            return robot

        updated = await self._registry.record_state(
            snapshot.model_copy(update={"robot_id": robot.id})
        )
        if updated is None:
            raise RobotNotFoundError()
        previous_runtime = self._evaluate_runtime(robot, [], now)
        current_runtime = self._evaluate_runtime(updated, [], now)
        connection_changed = (
            updated.connection_state != robot.connection_state
            or updated.is_online != robot.is_online
        )
        runtime_state_changed = previous_runtime.state != current_runtime.state
        if connection_changed:
            await self._save_events(
                [
                    RobotEvent(
                        robot_id=robot.id,
                        event_type="connection_changed",
                        severity="critical" if not updated.is_online else "info",
                        source="adapter_derived",
                        payload={
                            "previous_connection_state": robot.connection_state.value,
                            "connection_state": updated.connection_state.value,
                            "is_online": updated.is_online,
                        },
                        occurred_at=snapshot.observed_at,
                    )
                ]
            )
        if runtime_state_changed:
            await self._save_events(
                [
                    RobotEvent(
                        robot_id=robot.id,
                        event_type="state_changed",
                        severity="critical"
                        if current_runtime.state
                        in {
                            RobotRuntimeState.OFFLINE,
                            RobotRuntimeState.ERROR,
                            RobotRuntimeState.STALE,
                        }
                        else "info",
                        source="adapter_derived",
                        payload={
                            "previous_runtime_state": previous_runtime.state.value,
                            "runtime_state": current_runtime.state.value,
                        },
                        occurred_at=snapshot.observed_at,
                    )
                ]
            )
        safety_changed = (
            updated.motion_safety_state != robot.motion_safety_state
            or updated.emergency_stop != robot.emergency_stop
            or updated.manual_takeover != robot.manual_takeover
        )
        if safety_changed:
            await self._save_events(
                [
                    RobotEvent(
                        robot_id=robot.id,
                        event_type="safety_changed",
                        severity=(
                            "info"
                            if updated.motion_safety_state
                            in {RobotMotionSafetyState.NORMAL, RobotMotionSafetyState.STOPPED}
                            and not updated.manual_takeover
                            else "warning"
                        ),
                        source="adapter_derived",
                        payload={
                            "previous_safety_state": robot.motion_safety_state.value,
                            "safety_state": updated.motion_safety_state.value,
                            "emergency_stop": updated.emergency_stop,
                            "manual_takeover": updated.manual_takeover,
                        },
                        occurred_at=snapshot.observed_at,
                    )
                ]
            )
        return updated

    async def _update_request(
        self,
        request_id: str,
        **changes: Any,
    ) -> RegisteredRobotTaskRequest:
        def execute() -> RegisteredRobotTaskRequest:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                stored = unit_of_work.robots.update_task_request(request_id, **changes)
                unit_of_work.commit()
                return stored

        return await asyncio.to_thread(execute)

    async def _save_events(
        self,
        events: list[RobotEvent],
        *,
        task: RegisteredRobotTaskRequest | None = None,
    ) -> None:
        if not events:
            return

        def execute() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                for event in events:
                    unit_of_work.robots.add_event(event)
                unit_of_work.commit()

        await asyncio.to_thread(execute)

        for event in events:
            if self._event_publisher is None:
                continue
            try:
                await self._event_publisher.publish(self._domain_event(event, task))
            except Exception:
                logger.exception(
                    "robot_event_bus_publish_failed",
                    extra={
                        "robot_event_id": event.id,
                        "robot_id": event.robot_id,
                        "event_type": event.event_type,
                    },
                )

    def _domain_event(
        self,
        event: RobotEvent,
        task: RegisteredRobotTaskRequest | None,
    ) -> ArvunoEvent:
        if event.task_request_id is not None or task is not None:
            request_id = event.task_request_id or (task.id if task else "")
            error_code = None
            if task is not None and task.error:
                error_code_value = task.error.get("code")
                if isinstance(error_code_value, str):
                    error_code = error_code_value
            payload = RobotTaskUpdatedPayload(
                robot_id=event.robot_id,
                task_request_id=request_id,
                capability=task.capability.value if task else "unknown",
                task_status=task.status.value if task else "unknown",
                task_id=task.task_id if task else None,
                task_step_id=task.task_step_id if task else None,
                tool_execution_id=task.tool_execution_id if task else None,
                correlation_id=event.correlation_id or (task.correlation_id if task else None),
                error_code=error_code,
            )
            event_type = ArvunoEventType.ROBOT_TASK_UPDATED
        elif event.event_type == "safety_changed":
            payload = RobotSafetyChangedPayload(
                robot_id=event.robot_id,
                previous_safety_state=str(event.payload.get("previous_safety_state", "unknown")),
                current_safety_state=str(event.payload.get("safety_state", "unknown")),
                emergency_stop=bool(event.payload.get("emergency_stop", False)),
                manual_takeover=bool(event.payload.get("manual_takeover", False)),
            )
            event_type = ArvunoEventType.ROBOT_SAFETY_CHANGED
        else:
            payload = RobotStateChangedPayload(
                robot_id=event.robot_id,
                previous_state=str(
                    event.payload.get(
                        "previous_runtime_state",
                        event.payload.get("previous_connection_state", "unknown"),
                    )
                ),
                current_state=str(
                    event.payload.get(
                        "runtime_state",
                        event.payload.get("connection_state", "unknown"),
                    )
                ),
                attributes=event.payload,
            )
            event_type = ArvunoEventType.ROBOT_STATE_CHANGED

        return ArvunoEvent(
            id=event.id,
            event_type=event_type,
            source=ArvunoEventSource.ROBOT,
            subject_type="robot",
            subject_id=event.robot_id,
            payload=payload,
            correlation_id=event.correlation_id,
            occurred_at=self._normalize_datetime(event.occurred_at),
            created_at=self._now(),
        )

    def _task_transition_events(
        self,
        request: RegisteredRobotTaskRequest,
        event_type: str,
        *,
        severity: str = "info",
        error_code: str | None = None,
    ) -> list[RobotEvent]:
        return [
            RobotEvent(
                robot_id=request.robot_id,
                task_request_id=request.id,
                event_type=event_type,  # type: ignore[arg-type]
                severity=severity,  # type: ignore[arg-type]
                source="robot_service",
                payload={
                    "capability": request.capability.value,
                    "task_status": request.status.value,
                    **({"error": {"code": error_code}} if error_code else {}),
                },
                occurred_at=self._now(),
                correlation_id=request.correlation_id,
            )
        ]

    def _normalize_datetime(self, value: datetime | None) -> datetime:
        if value is None:
            raise ValueError("A robot timestamp is required.")
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _evaluate_runtime(
        self,
        robot: RegisteredRobot,
        active_tasks: list[RegisteredRobotTaskRequest],
        now: datetime,
    ) -> RobotRuntimeStatus:
        normalized_now = self._normalize_datetime(now)
        last_seen_at = (
            None if robot.last_seen_at is None else self._normalize_datetime(robot.last_seen_at)
        )
        state = RobotRuntimeState.UNKNOWN
        error_code: str | None = None
        if last_seen_at is None:
            state = RobotRuntimeState.UNKNOWN
        elif not robot.is_online and robot.connection_state is RobotConnectionState.DISCONNECTED:
            state = RobotRuntimeState.OFFLINE
        elif normalized_now - last_seen_at > timedelta(seconds=self._heartbeat_timeout_seconds):
            state = RobotRuntimeState.STALE
            error_code = "ROBOT_STATE_STALE"
        elif robot.emergency_stop or robot.motion_safety_state is RobotMotionSafetyState.STOPPED:
            state = RobotRuntimeState.EMERGENCY_STOPPED
        elif robot.motion_safety_state in {
            RobotMotionSafetyState.MANUAL_TAKEOVER,
            RobotMotionSafetyState.LIMIT_REACHED,
            RobotMotionSafetyState.STALLED,
            RobotMotionSafetyState.OVER_CURRENT,
            RobotMotionSafetyState.TILT_DETECTED,
        }:
            state = RobotRuntimeState.ERROR
            error_code = f"ROBOT_SAFETY_{robot.motion_safety_state.value.upper()}"
        elif (
            robot.connection_state is RobotConnectionState.DEGRADED
            and robot.motion_safety_state is RobotMotionSafetyState.UNKNOWN
        ):
            state = RobotRuntimeState.ERROR
            error_code = "ROBOT_ADAPTER_DEGRADED"
        elif active_tasks:
            state = RobotRuntimeState.BUSY
        elif (
            robot.connection_state is RobotConnectionState.CONNECTED
            and robot.motion_safety_state is RobotMotionSafetyState.NORMAL
        ):
            state = RobotRuntimeState.IDLE
        else:
            state = RobotRuntimeState.ONLINE
        is_fresh = (
            last_seen_at is not None
            and state is not RobotRuntimeState.OFFLINE
            and normalized_now - last_seen_at <= timedelta(seconds=self._heartbeat_timeout_seconds)
        )

        return RobotRuntimeStatus(
            robot_id=robot.id,
            state=state,
            connection_state=robot.connection_state,
            motion_safety_state=robot.motion_safety_state,
            is_fresh=is_fresh,
            last_seen_at=last_seen_at,
            last_evaluated_at=normalized_now,
            heartbeat_timeout_seconds=self._heartbeat_timeout_seconds,
            active_task_count=len(active_tasks),
            error_code=error_code,
        )

    def _request(self, request_id: str) -> RegisteredRobotTaskRequest:
        with self._unit_of_work_factory() as unit_of_work:
            assert unit_of_work.robots is not None
            return unit_of_work.robots.require_task_request(request_id)

    def _adapter(self, adapter_id: str) -> RobotAdapter:
        adapter = self._adapters.get(adapter_id)
        if adapter is None:
            raise RobotAdapterUnavailableError()
        return adapter

    async def _capability(
        self,
        robot_id: str,
        name: RobotCapabilityName,
    ) -> RobotCapability:
        capabilities = await self._registry.capabilities(robot_id)
        capability = next((item for item in capabilities if item.capability is name), None)
        if capability is None:
            raise RobotCapabilityUnsupportedError()
        return capability

    @staticmethod
    def _require_executable_capability(capability: RobotCapability) -> None:
        if not capability.supported or not capability.executable or not capability.runtime_enabled:
            raise RobotCapabilityDisabledError()
        if capability.verification_status in {"concept", "specified"}:
            raise RobotCapabilityDisabledError(
                "The robot capability has not passed bench verification."
            )


def _is_final(status: RobotTaskStatus) -> bool:
    return status in {
        RobotTaskStatus.REJECTED,
        RobotTaskStatus.SUCCEEDED,
        RobotTaskStatus.FAILED,
        RobotTaskStatus.TIMEOUT,
        RobotTaskStatus.CANCELLED,
        RobotTaskStatus.SAFE_STOPPED,
        RobotTaskStatus.UNAVAILABLE,
        RobotTaskStatus.CANCEL_FAILED,
        RobotTaskStatus.EXECUTION_UNKNOWN,
    }


def _result_matches_capability(
    capability: RobotCapabilityName,
    result: dict[str, Any] | None,
    state: RobotStateSnapshot,
) -> bool:
    if not isinstance(result, dict) or not result:
        return False
    if capability is RobotCapabilityName.SPEAK:
        return isinstance(result.get("spoken"), str) and bool(result["spoken"])
    if capability in {RobotCapabilityName.OBSERVE, RobotCapabilityName.OBSERVE_SCENE}:
        return isinstance(result.get("media_handle"), str) and bool(result["media_handle"])
    if capability is RobotCapabilityName.LISTEN:
        return isinstance(result.get("audio_handle"), str) and bool(result["audio_handle"])
    if capability is RobotCapabilityName.REQUEST_SAFE_STOP:
        return (
            bool(result.get("verified"))
            and state.motion_safety_state is RobotMotionSafetyState.STOPPED
            and state.emergency_stop
        )
    if capability is RobotCapabilityName.NAVIGATE_TO:
        moved_to = result.get("moved_to")
        return (
            isinstance(moved_to, dict)
            and bool(moved_to)
            and isinstance(moved_to.get("x"), (int, float))
            and isinstance(moved_to.get("y"), (int, float))
        )
    return bool(result.get("acknowledged"))


__all__ = ["RobotApplicationService"]
