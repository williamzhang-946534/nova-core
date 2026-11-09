from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import (
    Robot,
    RobotCapabilityRecord,
    RobotEventRecord,
    RobotStateSnapshotRecord,
    RobotTaskRequestRecord,
)
from arvuno_core.robots.errors import RobotNotFoundError, RobotTaskNotFoundError
from arvuno_core.robots.models import (
    RegisteredRobot,
    RegisteredRobotTaskRequest,
    RobotCapability,
    RobotCapabilityName,
    RobotDefinition,
    RobotDeviceStates,
    RobotEvent,
    RobotLocation,
    RobotStateSnapshot,
    RobotTaskRequestCreate,
    RobotTaskStatus,
    utc_now,
)


class RobotRepository:
    """Transaction-bound persistence adapter for robot projections."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_robot(
        self,
        definition: RobotDefinition,
        capabilities: list[RobotCapability],
        snapshot: RobotStateSnapshot,
    ) -> RegisteredRobot:
        try:
            robot = self._find(definition.adapter_id, definition.external_id)
            if robot is None:
                robot = Robot(
                    id=str(uuid4()),
                    adapter_id=definition.adapter_id,
                    external_id=definition.external_id,
                    created_at=utc_now(),
                )
                self._session.add(robot)
            robot.name = definition.name
            robot.vendor = definition.vendor
            robot.model = definition.model
            robot.hardware_version = definition.hardware_version
            robot.firmware_version = definition.firmware_version
            robot.edge_runtime_version = definition.edge_runtime_version
            robot.space_id = definition.space_id
            robot.metadata_summary = definition.metadata
            normalized_snapshot = snapshot.model_copy(update={"robot_id": robot.id})
            record = self._apply_state(robot, normalized_snapshot)
            self._replace_capabilities(robot, capabilities)
            self._session.add(record)
            self._session.flush()
            return _robot(robot)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to sync a robot projection.") from exc

    def get(self, robot_id: str) -> RegisteredRobot | None:
        try:
            robot = self._session.get(Robot, robot_id)
            return None if robot is None else _robot(robot)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a robot.") from exc

    def list(self, *, enabled_only: bool = False) -> list[RegisteredRobot]:
        try:
            statement = select(Robot).order_by(Robot.name, Robot.id)
            if enabled_only:
                statement = statement.where(Robot.is_enabled.is_(True))
            return [_robot(robot) for robot in self._session.scalars(statement)]
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list robots.") from exc

    def get_by_adapter(
        self,
        adapter_id: str,
        external_id: str,
    ) -> RegisteredRobot | None:
        try:
            robot = self._find(adapter_id, external_id)
            return None if robot is None else _robot(robot)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a robot by adapter identity.") from exc

    def set_enabled(self, robot_id: str, *, enabled: bool) -> RegisteredRobot:
        try:
            robot = self._require(robot_id)
            robot.is_enabled = enabled
            robot.updated_at = utc_now()
            self._session.flush()
            return _robot(robot)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to update robot enablement.") from exc

    def capabilities(self, robot_id: str) -> list[RobotCapability]:
        try:
            robot = self._require(robot_id)
            return [_capability(item) for item in robot.capabilities]
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read robot capabilities.") from exc

    def add_state(self, snapshot: RobotStateSnapshot) -> RobotStateSnapshot:
        try:
            robot = self._require(snapshot.robot_id)
            record = self._apply_state(robot, snapshot)
            self._session.add(record)
            self._session.flush()
            return snapshot.model_copy(update={"robot_id": robot.id})
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save robot state.") from exc

    def mark_unavailable(
        self,
        adapter_id: str,
        external_id: str,
        *,
        reason: str,
        occurred_at: datetime,
    ) -> RegisteredRobot | None:
        try:
            robot = self._find(adapter_id, external_id)
            if robot is None:
                return None
            snapshot = RobotStateSnapshot(
                robot_id=robot.id,
                connection_state="disconnected",
                is_online=False,
                motion_safety_state="unknown",
                emergency_stop=robot.emergency_stop,
                manual_takeover=robot.manual_takeover,
                battery_percent=robot.battery_percent,
                device_states=RobotDeviceStates(),
                location=RobotLocation(localization_state="unknown"),
                source="adapter_derived",
                observed_at=occurred_at,
            )
            self.add_state(snapshot)
            self.add_event(
                RobotEvent(
                    robot_id=robot.id,
                    event_type="connection_changed",
                    severity="critical",
                    source="adapter_derived",
                    payload={"reason": reason, "connection_state": "disconnected"},
                    occurred_at=occurred_at,
                )
            )
            return _robot(robot)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to mark a robot unavailable.") from exc

    def add_event(self, event: RobotEvent) -> RobotEvent:
        try:
            robot = self._require(event.robot_id)
            record = RobotEventRecord(
                id=event.id,
                robot_id=robot.id,
                task_request_id=event.task_request_id,
                event_type=event.event_type,
                severity=event.severity,
                source=event.source,
                payload=event.payload,
                occurred_at=event.occurred_at,
                received_at=event.received_at,
                processed_at=event.processed_at,
                late_arrival=event.late_arrival,
                correlation_id=event.correlation_id,
            )
            self._session.add(record)
            self._session.flush()
            return event.model_copy(update={"robot_id": robot.id})
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a robot event.") from exc

    def list_events(
        self,
        robot_id: str,
        *,
        task_request_id: str | None = None,
        limit: int = 100,
    ) -> list[RobotEvent]:
        try:
            self._require(robot_id)
            statement = (
                select(RobotEventRecord)
                .where(RobotEventRecord.robot_id == robot_id)
                .order_by(RobotEventRecord.occurred_at.desc(), RobotEventRecord.id.desc())
                .limit(limit)
            )
            if task_request_id is not None:
                statement = statement.where(RobotEventRecord.task_request_id == task_request_id)
            return [_event(item) for item in self._session.scalars(statement)]
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list robot events.") from exc

    def create_task_request(
        self,
        robot_id: str,
        request: RobotTaskRequestCreate,
        *,
        capability: RobotCapability,
    ) -> RegisteredRobotTaskRequest:
        try:
            robot = self._require(robot_id)
            if request.idempotency_key is not None:
                existing = self.find_task_by_idempotency(robot_id, request.idempotency_key)
                if existing is not None:
                    return existing
            now = utc_now()
            awaiting = capability.requires_confirmation and not request.confirmed
            record = RobotTaskRequestRecord(
                id=str(uuid4()),
                robot_id=robot.id,
                capability=request.capability.value,
                status=(
                    RobotTaskStatus.AWAITING_CONFIRMATION.value
                    if awaiting
                    else RobotTaskStatus.CREATED.value
                ),
                parameters=request.parameters,
                requested_by=request.requested_by,
                origin_type=request.origin_type,
                task_id=request.task_id,
                idempotency_key=request.idempotency_key,
                confirmed_by_user=request.confirmed,
                requires_confirmation=capability.requires_confirmation,
                timeout_seconds=request.timeout_seconds,
                correlation_id=request.correlation_id,
                created_at=now,
                updated_at=now,
            )
            self._session.add(record)
            self._session.flush()
            return _task(record)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to create a robot task request.") from exc

    def task_request(self, request_id: str) -> RegisteredRobotTaskRequest | None:
        try:
            record = self._session.get(RobotTaskRequestRecord, request_id)
            return None if record is None else _task(record)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a robot task request.") from exc

    def require_task_request(self, request_id: str) -> RegisteredRobotTaskRequest:
        request = self.task_request(request_id)
        if request is None:
            raise RobotTaskNotFoundError()
        return request

    def find_task_by_idempotency(
        self,
        robot_id: str,
        idempotency_key: str,
    ) -> RegisteredRobotTaskRequest | None:
        try:
            record = self._session.scalars(
                select(RobotTaskRequestRecord)
                .where(
                    RobotTaskRequestRecord.robot_id == robot_id,
                    RobotTaskRequestRecord.idempotency_key == idempotency_key,
                )
                .limit(1)
            ).first()
            return None if record is None else _task(record)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to look up a robot task request.") from exc

    def update_task_request(
        self,
        request_id: str,
        *,
        status: RobotTaskStatus,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        confirmed_by_user: bool | None = None,
        submitted_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> RegisteredRobotTaskRequest:
        try:
            record = self._session.get(RobotTaskRequestRecord, request_id)
            if record is None:
                raise RobotTaskNotFoundError()
            record.status = status.value
            record.result = result
            record.error = error
            if confirmed_by_user is not None:
                record.confirmed_by_user = confirmed_by_user
            if submitted_at is not None:
                record.submitted_at = submitted_at
            if completed_at is not None:
                record.completed_at = completed_at
            record.updated_at = utc_now()
            self._session.flush()
            return _task(record)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to update a robot task request.") from exc

    def list_task_requests(
        self,
        robot_id: str,
        *,
        status: RobotTaskStatus | None = None,
        limit: int = 100,
    ) -> list[RegisteredRobotTaskRequest]:
        try:
            self._require(robot_id)
            statement = (
                select(RobotTaskRequestRecord)
                .where(RobotTaskRequestRecord.robot_id == robot_id)
                .order_by(RobotTaskRequestRecord.created_at.desc(), RobotTaskRequestRecord.id)
                .limit(limit)
            )
            if status is not None:
                statement = statement.where(RobotTaskRequestRecord.status == status.value)
            return [_task(item) for item in self._session.scalars(statement)]
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list robot task requests.") from exc

    def count_task_requests(self, robot_id: str) -> int:
        try:
            return int(
                self._session.scalar(
                    select(func.count())
                    .select_from(RobotTaskRequestRecord)
                    .where(RobotTaskRequestRecord.robot_id == robot_id)
                )
                or 0
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to count robot task requests.") from exc

    def _require(self, robot_id: str) -> Robot:
        robot = self._session.get(Robot, robot_id)
        if robot is None:
            raise RobotNotFoundError()
        return robot

    def _find(self, adapter_id: str, external_id: str) -> Robot | None:
        return self._session.scalars(
            select(Robot)
            .where(Robot.adapter_id == adapter_id, Robot.external_id == external_id)
            .limit(1)
        ).first()

    def _replace_capabilities(
        self,
        robot: Robot,
        capabilities: list[RobotCapability],
    ) -> None:
        robot.capabilities.clear()
        self._session.flush()
        for capability in capabilities:
            robot.capabilities.append(
                RobotCapabilityRecord(
                    id=str(uuid4()),
                    capability=capability.capability.value,
                    schema_version=capability.schema_version,
                    verification_status=capability.verification_status,
                    runtime_enabled=capability.runtime_enabled,
                    risk_level=capability.risk_level,
                    requires_confirmation=capability.requires_confirmation,
                    requires_consents=capability.requires_consents,
                    min_battery_percent=capability.min_battery_percent,
                    input_schema=capability.input_schema,
                    output_schema=capability.output_schema,
                    safety_envelope=capability.safety_envelope,
                    evidence=capability.evidence,
                )
            )

    def _apply_state(
        self,
        robot: Robot,
        snapshot: RobotStateSnapshot,
    ) -> RobotStateSnapshotRecord:
        robot.connection_state = snapshot.connection_state.value
        robot.is_online = snapshot.is_online
        robot.motion_safety_state = snapshot.motion_safety_state.value
        robot.emergency_stop = snapshot.emergency_stop
        robot.manual_takeover = snapshot.manual_takeover
        robot.battery_percent = snapshot.battery_percent
        robot.device_states = snapshot.device_states.model_dump(mode="json")
        robot.location = snapshot.location.model_dump(mode="json")
        robot.last_seen_at = snapshot.observed_at if snapshot.is_online else None
        robot.updated_at = utc_now()
        return RobotStateSnapshotRecord(
            id=snapshot.id,
            robot_id=robot.id,
            connection_state=snapshot.connection_state.value,
            is_online=snapshot.is_online,
            motion_safety_state=snapshot.motion_safety_state.value,
            emergency_stop=snapshot.emergency_stop,
            manual_takeover=snapshot.manual_takeover,
            battery_percent=snapshot.battery_percent,
            device_states=snapshot.device_states.model_dump(mode="json"),
            location=snapshot.location.model_dump(mode="json"),
            source=snapshot.source,
            observed_at=snapshot.observed_at,
            received_at=snapshot.received_at,
            schema_version=snapshot.schema_version,
        )


def _robot(robot: Robot) -> RegisteredRobot:
    return RegisteredRobot(
        id=robot.id,
        adapter_id=robot.adapter_id,
        external_id=robot.external_id,
        name=robot.name,
        vendor=robot.vendor,
        model=robot.model,
        hardware_version=robot.hardware_version,
        firmware_version=robot.firmware_version,
        edge_runtime_version=robot.edge_runtime_version,
        is_enabled=robot.is_enabled,
        space_id=robot.space_id,
        metadata=robot.metadata_summary,
        connection_state=robot.connection_state,  # type: ignore[arg-type]
        is_online=robot.is_online,
        motion_safety_state=robot.motion_safety_state,  # type: ignore[arg-type]
        emergency_stop=robot.emergency_stop,
        manual_takeover=robot.manual_takeover,
        battery_percent=robot.battery_percent,
        low_battery_percent=robot.low_battery_percent,
        device_states=RobotDeviceStates.model_validate(robot.device_states),
        location=RobotLocation.model_validate(robot.location),
        last_seen_at=robot.last_seen_at,
        created_at=robot.created_at,
        updated_at=robot.updated_at,
    )


def _capability(record: RobotCapabilityRecord) -> RobotCapability:
    return RobotCapability(
        robot_id=record.robot_id,
        capability=RobotCapabilityName(record.capability),
        schema_version=record.schema_version,
        verification_status=record.verification_status,  # type: ignore[arg-type]
        runtime_enabled=record.runtime_enabled,
        risk_level=record.risk_level,  # type: ignore[arg-type]
        requires_confirmation=record.requires_confirmation,
        requires_consents=record.requires_consents,  # type: ignore[arg-type]
        min_battery_percent=record.min_battery_percent,
        input_schema=record.input_schema,
        output_schema=record.output_schema,
        safety_envelope=record.safety_envelope,
        evidence=record.evidence,
    )


def _task(record: RobotTaskRequestRecord) -> RegisteredRobotTaskRequest:
    return RegisteredRobotTaskRequest(
        id=record.id,
        robot_id=record.robot_id,
        capability=RobotCapabilityName(record.capability),
        status=RobotTaskStatus(record.status),
        parameters=record.parameters,
        requested_by=record.requested_by,
        origin_type=record.origin_type,
        task_id=record.task_id,
        idempotency_key=record.idempotency_key,
        confirmed_by_user=record.confirmed_by_user,
        requires_confirmation=record.requires_confirmation,
        result=record.result,
        error=record.error,
        timeout_seconds=record.timeout_seconds,
        correlation_id=record.correlation_id,
        created_at=record.created_at,
        submitted_at=record.submitted_at,
        completed_at=record.completed_at,
        updated_at=record.updated_at,
    )


def _event(record: RobotEventRecord) -> RobotEvent:
    return RobotEvent(
        id=record.id,
        robot_id=record.robot_id,
        task_request_id=record.task_request_id,
        event_type=record.event_type,  # type: ignore[arg-type]
        severity=record.severity,  # type: ignore[arg-type]
        source=record.source,
        payload=record.payload,
        occurred_at=record.occurred_at,
        received_at=record.received_at,
        processed_at=record.processed_at,
        late_arrival=record.late_arrival,
        correlation_id=record.correlation_id,
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["RobotRepository", "_utc"]
