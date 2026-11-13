from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from arvuno_core.errors import ArvunoError
from arvuno_core.observations.models import ObservationInput
from arvuno_core.observations.service import ObservationService
from arvuno_core.perception.models import ActivePerceptionRequestView
from arvuno_core.perception.service import ActivePerceptionService
from arvuno_core.persistence.models import ObservationAttributePolicy
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.robots.errors import RobotExecutionLockedError
from arvuno_core.robots.models import (
    RobotCapabilityName,
    RobotTaskRequestCreate,
    RobotTaskStatus,
)
from arvuno_core.robots.service import RobotApplicationService
from arvuno_core.schemas.perception import ActivePerceptionEvaluateRequest

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]

SUPPORTED_ATTRIBUTES = {"scene_label", "object_presence", "occupancy", "motion"}
DEFAULT_LOCATION = {
    "reference_frame": "room",
    "x": 1.0,
    "y": 1.0,
    "yaw": 0,
    "position_confidence": 0.8,
}


class RobotMobilePerceptionError(ArvunoError):
    """Raised when a mobile perception request cannot safely use the robot."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(code=code, message=message, status_code=status_code)


class _FunctionObserver:
    """Adapt a focused mobile perception callback to the service protocol."""

    def __init__(self, callback: Any) -> None:
        self._callback = callback

    async def observe(self, request: ActivePerceptionRequestView) -> ObservationInput:
        return await self._callback(request)


class RobotMobilePerceptionService:
    """Coordinate Active Perception decisions with the high-level robot boundary."""

    def __init__(
        self,
        active_perception_service: ActivePerceptionService,
        robot_service: RobotApplicationService,
        observation_service: ObservationService,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        environment_name: str = "home",
        clock: Any = lambda: datetime.now(UTC),
        request_id_factory: Any = lambda: str(uuid4()),
    ) -> None:
        self._active_perception_service = active_perception_service
        self._robot_service = robot_service
        self._observation_service = observation_service
        self._unit_of_work_factory = unit_of_work_factory
        self._environment_name = environment_name
        self._clock = clock
        self._request_id_factory = request_id_factory

    async def evaluate(
        self,
        request: ActivePerceptionEvaluateRequest,
        *,
        robot_id: str | None = None,
    ) -> ActivePerceptionRequestView:
        if request.entity_id is not None or request.space_id is None:
            raise RobotMobilePerceptionError(
                "ROBOT_MOBILE_SPACE_REQUIRED",
                "Mobile robot observation currently requires an exact target space.",
            )
        readiness = await self._readiness(robot_id)
        if not readiness["ready"]:
            raise RobotMobilePerceptionError(
                "ROBOT_MOBILE_UNAVAILABLE",
                str(readiness["reason"]),
            )
        source_id = await self._ensure_source(readiness)
        self._ensure_robot_mobile_policies()
        evaluation = await self._active_perception_service.evaluate_gap(
            request.model_copy(update={"preferred_source_type": "robot_mobile"})
        )
        proposed_source = evaluation.proposed_input.get("source_id")
        if evaluation.status not in {"proposed", "awaiting_consent"}:
            return evaluation
        if proposed_source != source_id:
            raise RobotMobilePerceptionError(
                "ROBOT_MOBILE_SOURCE_MISMATCH",
                "Active Perception selected a different mobile observation source.",
            )
        return await self._attach_mobile_plan(evaluation, readiness, source_id)

    async def authorize(
        self,
        request_id: str,
        *,
        confirmed_navigation: bool,
        confirmed_camera_capture: bool,
        authorization_seconds: int = 3600,
    ) -> ActivePerceptionRequestView:
        current = await self._active_perception_service.get_request(request_id)
        plan = self._mobile_plan(current)
        scope = self._authorization_scope(
            current,
            plan,
            confirmed_navigation=confirmed_navigation,
            confirmed_camera_capture=confirmed_camera_capture,
        )
        return await self._active_perception_service.authorize(
            request_id,
            scope=scope,
            authorization_seconds=authorization_seconds,
        )

    async def execute(self, request_id: str) -> ActivePerceptionRequestView:
        del request_id
        raise RobotExecutionLockedError()

    async def _legacy_execute(self, request_id: str) -> ActivePerceptionRequestView:
        # WP7 will replace this direct robot-service path with the unified tool chain.
        # Keep the implementation temporarily to preserve the unfinished ARS-06.4 work,
        # but no production caller may reach it before that refactor lands.
        request = await self._active_perception_service.get_request(request_id)
        plan = self._mobile_plan(request)
        self._validate_authorization(request, plan)

        async def observe(current: ActivePerceptionRequestView) -> ObservationInput:
            current_plan = self._mobile_plan(current)
            if current.status != "queued":
                raise RobotMobilePerceptionError(
                    "ROBOT_MOBILE_STATE_INVALID",
                    f"The mobile observer received request status '{current.status}'.",
                )
            self._validate_authorization(current, current_plan, expected_status="queued")
            readiness = await self._readiness(current_plan["robot_id"])
            if not readiness["ready"]:
                await self._trace(
                    current.id,
                    {
                        "blocked_reason": readiness["reason"],
                        "robot_ready_at_execution": False,
                    },
                )
                raise RobotMobilePerceptionError(
                    "ROBOT_MOBILE_UNAVAILABLE",
                    str(readiness["reason"]),
                )
            await self._ensure_source(readiness)

            now = self._utc_clock()
            navigation = await self._robot_service.create_task_request(
                current_plan["robot_id"],
                RobotTaskRequestCreate(
                    capability=RobotCapabilityName.NAVIGATE_TO,
                    parameters={"target_location": dict(current_plan["target_location"])},
                    requested_by="robot_mobile_perception",
                    origin_type="active_perception",
                    idempotency_key=f"robot-mobile-{current.id}-navigate",
                    confirmed=True,
                    correlation_id=current.id,
                    timeout_seconds=30,
                ),
            )
            await self._trace(
                current.id,
                {
                    "navigation_task_id": navigation.id,
                    "navigation_task_status": navigation.status.value,
                },
            )
            if navigation.status is not RobotTaskStatus.SUCCEEDED:
                raise RobotMobilePerceptionError(
                    "ROBOT_NAVIGATION_FAILED",
                    "The confirmed robot navigation task did not succeed.",
                )

            capture = await self._robot_service.create_task_request(
                current_plan["robot_id"],
                RobotTaskRequestCreate(
                    capability=RobotCapabilityName.OBSERVE,
                    parameters={"capture_mode": "on_demand_image"},
                    requested_by="robot_mobile_perception",
                    origin_type="active_perception",
                    idempotency_key=f"robot-mobile-{current.id}-observe",
                    confirmed=True,
                    correlation_id=current.id,
                    timeout_seconds=15,
                ),
            )
            await self._trace(
                current.id,
                {
                    "observation_task_id": capture.id,
                    "observation_task_status": capture.status.value,
                },
            )
            if capture.status is not RobotTaskStatus.SUCCEEDED:
                raise RobotMobilePerceptionError(
                    "ROBOT_OBSERVATION_FAILED",
                    "The confirmed robot observation task did not succeed.",
                )
            result = capture.result or {}
            media_handle = result.get("media_handle")
            if not isinstance(media_handle, str):
                raise RobotMobilePerceptionError(
                    "ROBOT_OBSERVATION_INVALID",
                    "The robot observer did not return a media handle.",
                )
            await self._trace(
                current.id,
                {
                    "media_handle": media_handle,
                    "mock_only": result.get("mock_only") is True,
                },
            )
            return self._observation_input(
                current,
                current_plan,
                media_handle,
                now,
                mock_only=readiness.get("adapter_id") == "mock_robot",
            )

        fulfilled = await self._active_perception_service.execute(
            request_id,
            _FunctionObserver(observe),
        )
        await self._trace(
            request_id,
            {
                "observation_id": fulfilled.fulfilled_by_id,
                "follow_up_reasoning_session_id": fulfilled.follow_up_reasoning_session_id,
                "completed_at": self._utc_clock().isoformat(),
            },
        )
        return await self._active_perception_service.get_request(request_id)

    async def get_request(self, request_id: str) -> ActivePerceptionRequestView:
        return await self._active_perception_service.get_request(request_id)

    async def _readiness(self, robot_id: str | None) -> dict[str, Any]:
        robots = await self._robot_service.list_robots(enabled_only=True)
        robot = next((item for item in robots if item.id == robot_id), None)
        if robot is None and robot_id is None and robots:
            robot = robots[0]
        if robot is None:
            return {"ready": False, "reason": "No enabled robot is available."}
        try:
            state = await self._robot_service.state(robot.id)
            capabilities = {
                item.capability: item for item in await self._robot_service.capabilities(robot.id)
            }
        except Exception:
            return {
                "ready": False,
                "reason": "The robot state or capabilities could not be read.",
                "robot_id": robot.id,
                "robot_name": robot.name,
            }

        checks: dict[str, Any] = {
            "robot_id": robot.id,
            "robot_name": robot.name,
            "adapter_id": robot.adapter_id,
            "online": state.is_online,
            "emergency_stop": state.emergency_stop,
            "manual_takeover": state.manual_takeover,
            "localization_state": state.location.localization_state,
            "battery_percent": state.battery_percent,
        }
        for name in (RobotCapabilityName.NAVIGATE_TO, RobotCapabilityName.OBSERVE):
            capability = capabilities.get(name)
            checks[f"{name.value}_ready"] = bool(
                capability
                and capability.runtime_enabled
                and capability.verification_status
                in {"bench_verified", "integration_verified", "safety_approved"}
            )
        battery_limits = [robot.low_battery_percent]
        for name in (RobotCapabilityName.NAVIGATE_TO, RobotCapabilityName.OBSERVE):
            capability = capabilities.get(name)
            if capability is not None:
                battery_limits.append(float(capability.min_battery_percent))
        minimum_battery = max(battery_limits)
        checks["minimum_battery_percent"] = minimum_battery
        reason: str | None = None
        if not checks["online"]:
            reason = "The robot is offline."
        elif checks["emergency_stop"]:
            reason = "The robot emergency stop is active."
        elif checks["manual_takeover"]:
            reason = "The robot is under manual takeover."
        elif checks["localization_state"] != "known":
            reason = "The robot localization is not known."
        elif not checks["navigate_to_ready"]:
            reason = "Verified and enabled navigate_to capability is required."
        elif not checks["observe_ready"]:
            reason = "Verified and enabled observe capability is required."
        elif state.battery_percent is None or state.battery_percent <= minimum_battery:
            reason = "The robot battery is at or below the mobile perception minimum."
        checks.update({"ready": reason is None, "reason": reason})
        return checks

    async def _ensure_source(self, readiness: dict[str, Any]) -> str:
        location = dict(DEFAULT_LOCATION)
        sources = await self._observation_service.list_sources()
        existing = next(
            (item for item in sources if item.source_type == "robot_mobile"),
            None,
        )
        allowed_space_ids = (
            (existing.config or {}).get("allowed_space_ids") if existing is not None else None
        )
        source_config: dict[str, Any] = {
            "kind": "robot_mobile",
            "capture_mode": "on_demand_only",
            "continuous_video_analysis": False,
            "supported_attributes": sorted(SUPPORTED_ATTRIBUTES),
            "capabilities": ["navigate_to", "observe"],
            "perception_cost": 8.0,
            "default_observation_location": location,
            "mock_only": readiness.get("adapter_id") == "mock_robot",
        }
        if isinstance(allowed_space_ids, list):
            source_config["allowed_space_ids"] = allowed_space_ids
        source = await self._observation_service.register_source(
            source_type="robot_mobile",
            adapter_id="robot_mobile",
            name="Mobile robot on-demand perception",
            status="active" if readiness.get("ready") else "unavailable",
            trust_level=0.7,
            time_trust="device_clock",
            config=source_config,
            privacy_scope={
                "sensitive": True,
                "media_storage": "reference_handle_only",
                "raw_media_default": "do_not_store",
            },
        )
        return source.id

    def _ensure_robot_mobile_policies(self) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            assert unit_of_work.observation_attributes is not None
            for attribute in sorted(SUPPORTED_ATTRIBUTES):
                policy = unit_of_work.observation_attributes.latest_policy(attribute)
                if policy is not None and "robot_mobile" in policy.allowed_source_types:
                    continue
                definition = unit_of_work.observation_attributes.get(attribute)
                if definition is None or policy is None:
                    raise RobotMobilePerceptionError(
                        "ROBOT_MOBILE_POLICY_INVALID",
                        f"The controlled observation policy for '{attribute}' is missing.",
                        status_code=500,
                    )
                previous_created_at = policy.created_at
                if previous_created_at.tzinfo is None:
                    previous_created_at = previous_created_at.replace(tzinfo=UTC)
                # SQLite DATETIME ordering has millisecond precision, so the new
                # policy version must be measurably newer than the seed policy.
                policy_created_at = max(
                    previous_created_at + timedelta(seconds=1),
                    self._utc_clock(),
                )
                unit_of_work.observation_attributes.add(
                    ObservationAttributePolicy(
                        attribute=attribute,
                        sensitivity=policy.sensitivity,
                        requires_consent=True,
                        allowed_source_types=[
                            *policy.allowed_source_types,
                            "robot_mobile",
                        ],
                        allowed_spaces=policy.allowed_spaces,
                        raw_storage_allowed=policy.raw_storage_allowed,
                        record_retention_days=policy.record_retention_days,
                        normalized_only=policy.normalized_only,
                        redaction_rule=policy.redaction_rule,
                        version="robot-mobile-v1",
                        created_at=policy_created_at,
                        updated_at=policy_created_at,
                    )
                )
                unit_of_work.commit()

    async def _attach_mobile_plan(
        self,
        evaluation: ActivePerceptionRequestView,
        readiness: dict[str, Any],
        source_id: str,
    ) -> ActivePerceptionRequestView:
        def execute() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.perception is not None
                assert unit_of_work.observation_sources is not None
                row = unit_of_work.perception.get(evaluation.id)
                source = unit_of_work.observation_sources.get(source_id)
                if row is None or source is None:
                    raise RobotMobilePerceptionError(
                        "ROBOT_MOBILE_REQUEST_NOT_FOUND",
                        "The mobile perception request or source disappeared.",
                        status_code=404,
                    )
                if row.proposed_input.get("source_id") != source_id:
                    raise RobotMobilePerceptionError(
                        "ROBOT_MOBILE_SOURCE_MISMATCH",
                        "The stored request does not reference the mobile source.",
                    )
                config = source.config or {}
                target_location = config.get("default_observation_location")
                if not isinstance(target_location, dict):
                    target_location = dict(DEFAULT_LOCATION)
                target_location = {**target_location, "space_id": evaluation.space_id}
                allowed_space_ids = config.get("allowed_space_ids")
                if (
                    isinstance(allowed_space_ids, list)
                    and evaluation.space_id not in allowed_space_ids
                ):
                    raise RobotMobilePerceptionError(
                        "ROBOT_MOBILE_SPACE_NOT_ALLOWED",
                        "The target space is not in the robot source allowlist.",
                    )
                plan = {
                    "robot_id": readiness["robot_id"],
                    "source_id": source_id,
                    "source_type": "robot_mobile",
                    "target_space_id": evaluation.space_id,
                    "target_location": target_location,
                    "steps": ["navigate_to", "observe"],
                    "requires_exact_scope": True,
                }
                row.proposed_input = {
                    **row.proposed_input,
                    "mobile_plan": plan,
                }
                if row.execution_trace is None:
                    row.execution_trace = {
                        "origin": "robot_mobile_perception",
                        "robot_id": readiness["robot_id"],
                        "capabilities_checked": {
                            "navigate_to": readiness["navigate_to_ready"],
                            "observe": readiness["observe_ready"],
                        },
                        "mock_only": readiness.get("adapter_id") == "mock_robot",
                        "created_at": self._utc_clock().isoformat(),
                    }
                unit_of_work.perception.mark(row)
                unit_of_work.commit()

        await asyncio.to_thread(execute)
        return await self._active_perception_service.get_request(evaluation.id)

    @staticmethod
    def _mobile_plan(request: ActivePerceptionRequestView) -> dict[str, Any]:
        plan = request.proposed_input.get("mobile_plan")
        if not isinstance(plan, dict):
            raise RobotMobilePerceptionError(
                "ROBOT_MOBILE_PLAN_MISSING",
                "This request is not a mobile robot perception plan.",
            )
        required = {
            "robot_id",
            "source_id",
            "source_type",
            "target_space_id",
            "target_location",
            "steps",
            "requires_exact_scope",
        }
        if set(plan) != required or plan.get("source_type") != "robot_mobile":
            raise RobotMobilePerceptionError(
                "ROBOT_MOBILE_PLAN_INVALID",
                "The mobile perception plan is incomplete or malformed.",
            )
        if plan["steps"] != ["navigate_to", "observe"] or plan["requires_exact_scope"] is not True:
            raise RobotMobilePerceptionError(
                "ROBOT_MOBILE_PLAN_INVALID",
                "The mobile perception plan has an unsafe step sequence.",
            )
        if request.space_id != plan["target_space_id"]:
            raise RobotMobilePerceptionError(
                "ROBOT_MOBILE_TARGET_MISMATCH",
                "The authorization target does not match the perception request.",
            )
        return plan

    @staticmethod
    def _authorization_scope(
        request: ActivePerceptionRequestView,
        plan: dict[str, Any],
        *,
        confirmed_navigation: bool,
        confirmed_camera_capture: bool,
    ) -> dict[str, Any]:
        if not confirmed_navigation or not confirmed_camera_capture:
            raise RobotMobilePerceptionError(
                "ROBOT_MOBILE_CONFIRMATION_REQUIRED",
                "Both navigation and camera capture require explicit confirmation.",
            )
        return {
            "robot_mobile": True,
            "robot_id": plan["robot_id"],
            "target_space_id": plan["target_space_id"],
            "target_location": plan["target_location"],
            "steps": plan["steps"],
            "confirmed_navigation": True,
            "confirmed_camera_capture": True,
            "active_perception_source_id": plan["source_id"],
        }

    def _validate_authorization(
        self,
        request: ActivePerceptionRequestView,
        plan: dict[str, Any],
        *,
        expected_status: str = "proposed",
    ) -> None:
        if request.status != expected_status:
            raise RobotMobilePerceptionError(
                "ROBOT_MOBILE_STATE_INVALID",
                f"A mobile observation cannot execute from status '{request.status}'.",
            )
        scope = request.authorization_scope or {}
        expected = self._authorization_scope(
            request,
            plan,
            confirmed_navigation=True,
            confirmed_camera_capture=True,
        )
        if any(scope.get(key) != value for key, value in expected.items()):
            raise RobotMobilePerceptionError(
                "ROBOT_MOBILE_SCOPE_MISMATCH",
                "The authorization scope does not exactly match the mobile plan.",
            )

    @staticmethod
    def _observation_input(
        request: ActivePerceptionRequestView,
        plan: dict[str, Any],
        media_handle: str,
        now: datetime,
        *,
        mock_only: bool,
    ) -> ObservationInput:
        attribute = request.attribute
        if attribute not in SUPPORTED_ATTRIBUTES or request.space_id is None:
            raise RobotMobilePerceptionError(
                "ROBOT_MOBILE_ATTRIBUTE_UNSUPPORTED",
                "The requested attribute cannot be answered by this robot observer.",
            )
        if attribute in {"scene_label", "object_presence"}:
            raw_value = {
                "scene_labels": [],
                "objects": [],
                "confidence": 0.0,
                "media_handle": media_handle,
                "analysis": "not_performed",
                "mock_only": mock_only,
            }
        elif attribute == "occupancy":
            raw_value = "unknown"
        else:
            raw_value = "unknown"
        return ObservationInput(
            source_id=plan["source_id"],
            subject_type=request.subject_type,
            subject_id=request.subject_id,
            space_id=request.space_id,
            attribute=attribute,
            raw_value=raw_value,
            observed_at=now,
            observed_at_source="device_clock",
            observed_at_uncertainty_ms=1000,
            received_at=now,
            correlation_id=request.id,
            external_id=f"robot-mobile-{request.id}-observation",
        )

    async def _trace(self, request_id: str, updates: dict[str, Any]) -> None:
        def execute() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.perception is not None
                row = unit_of_work.perception.get(request_id)
                if row is None:
                    return
                row.execution_trace = {
                    **(row.execution_trace or {}),
                    **updates,
                }
                unit_of_work.perception.mark(row)
                unit_of_work.commit()

        await asyncio.to_thread(execute)

    def _utc_clock(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = [
    "RobotMobilePerceptionError",
    "RobotMobilePerceptionService",
]
