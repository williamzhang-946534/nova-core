import asyncio
from collections.abc import Callable
from typing import Any

from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.robots.errors import (
    RobotAdapterUnavailableError,
    RobotCapabilityDisabledError,
    RobotCapabilityUnsupportedError,
    RobotConnectionError,
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
    RegisteredRobot,
    RegisteredRobotTaskRequest,
    RobotCapability,
    RobotCapabilityName,
    RobotEvent,
    RobotStateSnapshot,
    RobotTaskRequestCreate,
    RobotTaskStatus,
    utc_now,
)
from arvuno_core.robots.registry import RobotRegistry


class RobotApplicationService:
    """High-level robot boundary used by API and future controlled tools."""

    def __init__(
        self,
        registry: RobotRegistry,
        adapters: dict[str, RobotAdapter],
        *,
        unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork],
    ) -> None:
        self._registry = registry
        self._adapters = dict(adapters)
        self._unit_of_work_factory = unit_of_work_factory

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

    async def capabilities(self, robot_id: str) -> list[RobotCapability]:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()
        return await self._registry.capabilities(robot.id)

    async def state(self, robot_id: str) -> RegisteredRobot:
        robot = await self.get_robot(robot_id)
        adapter = self._adapter(robot.adapter_id)
        snapshot = await adapter.get_state(robot.external_id)
        updated = await self._registry.record_state(
            snapshot.model_copy(update={"robot_id": robot.id})
        )
        if updated is None:
            raise RobotNotFoundError()
        return updated

    async def events(
        self,
        robot_id: str,
        *,
        task_request_id: str | None = None,
        limit: int = 100,
    ) -> list[RobotEvent]:
        robot = await self.get_robot(robot_id)

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
        if stored.status is RobotTaskStatus.CREATED and request.confirmed:
            return await self._execute(stored, adapter)
        return stored

    async def confirm_task_request(
        self,
        robot_id: str,
        request_id: str,
        *,
        confirmed: bool,
        confirmed_by: str,
    ) -> RegisteredRobotTaskRequest:
        del confirmed_by  # API authentication is the current confirmation actor boundary
        robot = await self.get_robot(robot_id)
        request = self._request(request_id)
        if request.robot_id != robot.id:
            raise RobotTaskNotFoundError()
        if request.status is not RobotTaskStatus.AWAITING_CONFIRMATION:
            raise RobotTaskStateError("Only a task awaiting confirmation can be confirmed.")
        if not confirmed:
            return await self._update_request(
                request_id,
                status=RobotTaskStatus.REJECTED,
                error={"code": "ROBOT_TASK_REJECTED", "message": "Rejected by the user."},
                completed_at=utc_now(),
            )

        capability = await self._capability(robot.id, request.capability)
        self._require_executable_capability(capability)
        submitted = await self._update_request(
            request_id,
            status=RobotTaskStatus.SUBMITTED,
            confirmed_by_user=True,
            submitted_at=utc_now(),
        )
        adapter = self._adapter(robot.adapter_id)
        return await self._execute(
            submitted.model_copy(update={"confirmed_by_user": True}),
            adapter,
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
        try:
            result = await adapter.cancel_task(request)
        except (RobotConnectionError, RobotUnavailableError):
            await self._registry.mark_unavailable(
                robot.adapter_id,
                robot.external_id,
                reason="cancel_task_failed",
            )
            return await self._update_request(
                request_id,
                status=RobotTaskStatus.UNAVAILABLE,
                error={"code": "ROBOT_CONNECTION_FAILED", "message": "The robot is disconnected."},
                completed_at=utc_now(),
            )
        await self._record_adapter_state(request.robot_id, result.state)
        await self._save_events(self._normalize_events(request, result.events))
        return await self._update_request(
            request_id,
            status=RobotTaskStatus.CANCELLED,
            result=result.result,
            completed_at=utc_now(),
        )

    async def task_request(self, robot_id: str, request_id: str) -> RegisteredRobotTaskRequest:
        robot = await self.get_robot(robot_id)
        request = self._request(request_id)
        if request.robot_id != robot.id:
            raise RobotTaskNotFoundError()
        return request

    async def task_request_by_id(self, request_id: str) -> RegisteredRobotTaskRequest:
        request = self._request(request_id)
        await self.get_robot(request.robot_id)
        return request

    async def list_task_requests(
        self,
        robot_id: str,
        *,
        status: RobotTaskStatus | None = None,
        limit: int = 100,
    ) -> list[RegisteredRobotTaskRequest]:
        robot = await self.get_robot(robot_id)

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
            result = await adapter.execute_task(request)
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

        await self._record_adapter_state(request.robot_id, result.state)
        await self._save_events(self._normalize_events(request, result.events))
        return await self._update_request(
            request.id,
            status=RobotTaskStatus.SUCCEEDED if result.success else RobotTaskStatus.FAILED,
            result=result.result,
            error=(
                None if result.success else {"code": "ROBOT_TASK_FAILED", "message": result.message}
            ),
            completed_at=utc_now(),
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
                            observed_at=utc_now(),
                        )
                    )
        except Exception:
            pass

        event_type = {
            RobotTaskStatus.SAFE_STOPPED: "task_safe_stopped",
            RobotTaskStatus.TIMEOUT: "task_failed",
            RobotTaskStatus.UNAVAILABLE: "task_unavailable",
        }.get(status, "task_failed")
        await self._save_events(
            [
                RobotEvent(
                    robot_id=request.robot_id,
                    task_request_id=request.id,
                    event_type=event_type,  # type: ignore[arg-type]
                    severity="warning" if status is RobotTaskStatus.TIMEOUT else "critical",
                    source="robot_service",
                    payload={"error": error},
                    occurred_at=utc_now(),
                )
            ]
        )
        return await self._update_request(
            request.id,
            status=status,
            error=error,
            completed_at=utc_now(),
        )

    async def _record_adapter_state(
        self,
        robot_id: str,
        snapshot: RobotStateSnapshot,
    ) -> None:
        robot = await self._registry.get_robot(robot_id)
        if robot is None:
            raise RobotNotFoundError()
        await self._registry.record_state(snapshot.model_copy(update={"robot_id": robot.id}))

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

    async def _save_events(self, events: list[RobotEvent]) -> None:
        if not events:
            return

        def execute() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                for event in events:
                    unit_of_work.robots.add_event(event)
                unit_of_work.commit()

        await asyncio.to_thread(execute)

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
        if not capability.runtime_enabled:
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
    }


__all__ = ["RobotApplicationService"]
