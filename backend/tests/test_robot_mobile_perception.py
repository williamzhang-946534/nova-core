import asyncio
import itertools
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.perception.robot_mobile import (
    RobotMobilePerceptionError,
    RobotMobilePerceptionService,
)
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import (
    ActivePerceptionRequest,
    Observation,
    RobotTaskRequestRecord,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.robots.errors import RobotExecutionLockedError
from arvuno_core.robots.models import (
    RobotCapabilityName,
)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
HEADERS = {"Authorization": "Bearer test-api-token"}


@dataclass
class FixedClock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now


@dataclass
class MobileEnvironment:
    manager: DatabaseManager
    client: TestClient
    service: RobotMobilePerceptionService
    robot_id: str
    clock: FixedClock


def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        robot_profile="legacy_mock_mobile",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


def mobile_environment(tmp_path: Path) -> MobileEnvironment:
    manager = DatabaseManager(settings(tmp_path))
    manager.initialize_database()
    app = create_app(
        settings(tmp_path),
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
    )
    clock = FixedClock()
    counter = itertools.count(1)
    app.state.perception_service._clock = clock
    app.state.perception_service._request_id_factory = lambda: f"mobile-{next(counter)}"
    service = RobotMobilePerceptionService(
        app.state.perception_service,
        app.state.robot_service,
        app.state.observation_service,
        lambda: SqlAlchemyUnitOfWork(manager.session_factory),
        environment_name="home",
        clock=clock,
    )
    app.state.robot_mobile_perception_service = service
    client = TestClient(app)
    robot_id = prepare_robot(app.state.mock_robot_adapter, app.state.robot_service)
    return MobileEnvironment(manager, client, service, robot_id, clock)


def prepare_robot(adapter: Any, robot_service: Any) -> str:
    adapter.set_emergency_stop(active=False)
    for capability in (RobotCapabilityName.NAVIGATE_TO, RobotCapabilityName.OBSERVE):
        adapter.set_capability(
            capability,
            runtime_enabled=True,
            verification_status="bench_verified",
        )
    asyncio.run(robot_service.sync_robot(adapter, adapter.external_id))
    robots = asyncio.run(robot_service.list_robots())
    asyncio.run(robot_service.enable_robot(robots[0].id, enabled=True))
    for capability in (RobotCapabilityName.NAVIGATE_TO, RobotCapabilityName.OBSERVE):
        asyncio.run(
            robot_service.set_capability_governance(
                robots[0].id,
                capability,
                enabled=True,
                approved=True,
                consent_granted=True,
                approved_by="test-admin",
            )
        )
    return asyncio.run(robot_service.list_robots(enabled_only=True))[0].id


def create_room(environment: MobileEnvironment, name: str) -> str:
    spatial = environment.client.app.state.spatial_service
    root = asyncio.run(spatial.ensure_root())
    return asyncio.run(
        spatial.create_space(
            parent_id=root.id,
            name=f"Mobile Perception {name}",
            space_type="room",
        )
    ).id


def evaluate(
    environment: MobileEnvironment,
    *,
    space_id: str,
    attribute: str = "scene_label",
    **overrides: Any,
) -> Any:
    return asyncio.run(
        environment.service.evaluate(
            _request(space_id=space_id, attribute=attribute, **overrides),
            robot_id=environment.robot_id,
        )
    )


def _request(
    *,
    space_id: str,
    attribute: str,
    question: str = "What is in this room now?",
    **overrides: Any,
) -> Any:
    from arvuno_core.schemas.perception import ActivePerceptionEvaluateRequest

    return ActivePerceptionEvaluateRequest(
        question=question,
        space_id=space_id,
        attribute=attribute,
        start_time=NOW - timedelta(minutes=5),
        end_time=NOW,
        now=NOW,
        **overrides,
    )


def authorize(
    environment: MobileEnvironment,
    request_id: str,
    *,
    navigation: bool = True,
    camera: bool = True,
) -> Any:
    return asyncio.run(
        environment.service.authorize(
            request_id,
            confirmed_navigation=navigation,
            confirmed_camera_capture=camera,
        )
    )


def execute(environment: MobileEnvironment, request_id: str) -> Any:
    return asyncio.run(environment.service.execute(request_id))


def task_count(environment: MobileEnvironment) -> int:
    with environment.manager.session_factory() as session:
        return int(session.scalar(select(func.count()).select_from(RobotTaskRequestRecord)) or 0)


def observation_count(environment: MobileEnvironment) -> int:
    with environment.manager.session_factory() as session:
        return int(session.scalar(select(func.count()).select_from(Observation)) or 0)


def refresh(environment: MobileEnvironment, request_id: str) -> Any:
    with environment.manager.session_factory() as session:
        return session.get(ActivePerceptionRequest, request_id)


def test_mobile_perception_fulfills_exact_space_request_with_sources_and_trace(
    tmp_path: Path,
) -> None:
    environment = mobile_environment(tmp_path)
    try:
        room_id = create_room(environment, "closed loop")
        request = evaluate(environment, space_id=room_id)

        assert request.status == "awaiting_consent"
        assert request.privacy_level == "sensitive"
        plan = request.proposed_input["mobile_plan"]
        assert plan == {
            "robot_id": environment.robot_id,
            "source_id": plan["source_id"],
            "source_type": "robot_mobile",
            "target_space_id": room_id,
            "target_location": {
                "reference_frame": "room",
                "x": 1.0,
                "y": 1.0,
                "yaw": 0,
                "position_confidence": 0.8,
                "space_id": room_id,
            },
            "steps": ["navigate_to", "observe"],
            "requires_exact_scope": True,
        }
        assert request.execution_trace["origin"] == "robot_mobile_perception"
        assert request.execution_trace["mock_only"] is True

        with pytest.raises(RobotMobilePerceptionError, match="explicit confirmation"):
            authorize(environment, request.id, navigation=True, camera=False)
        assert task_count(environment) == 0

        authorized = authorize(environment, request.id)
        assert authorized.status == "proposed"
        assert authorized.authorization_scope["robot_id"] == environment.robot_id
        assert authorized.authorization_scope["target_space_id"] == room_id
        assert authorized.authorization_scope["confirmed_camera_capture"] is True

        with pytest.raises(RobotExecutionLockedError):
            execute(environment, request.id)
        assert refresh(environment, request.id).status == "proposed"
        assert task_count(environment) == 0
        assert observation_count(environment) == 0
    finally:
        environment.manager.dispose()


def test_navigation_failure_cannot_be_reached_while_execution_is_locked(
    tmp_path: Path,
) -> None:
    environment = mobile_environment(tmp_path)
    try:
        environment.client.app.state.mock_robot_adapter.set_navigation_failure(enabled=True)
        room_id = create_room(environment, "navigation failure")
        request = evaluate(environment, space_id=room_id)
        authorize(environment, request.id)

        with pytest.raises(RobotExecutionLockedError):
            execute(environment, request.id)

        unavailable = refresh(environment, request.id)
        assert unavailable is not None
        assert unavailable.status == "proposed"
        assert task_count(environment) == 0
        assert observation_count(environment) == 0
    finally:
        environment.manager.dispose()


@pytest.mark.parametrize(
    "configure",
    [
        lambda adapter: adapter.set_offline(offline=True),
        lambda adapter: adapter.set_emergency_stop(active=True),
        lambda adapter: adapter.set_manual_takeover(active=True),
        lambda adapter: adapter.set_localization_lost(lost=True),
        lambda adapter: adapter.set_battery_percent(10),
    ],
)
def test_unsafe_robot_state_blocks_evaluation_before_any_motion(
    tmp_path: Path,
    configure: Any,
) -> None:
    environment = mobile_environment(tmp_path)
    try:
        configure(environment.client.app.state.mock_robot_adapter)
        room_id = create_room(environment, "unsafe")
        with pytest.raises(RobotMobilePerceptionError, match="robot"):
            evaluate(environment, space_id=room_id)
        assert task_count(environment) == 0
    finally:
        environment.manager.dispose()


def test_unverified_capability_blocks_evaluation(
    tmp_path: Path,
) -> None:
    environment = mobile_environment(tmp_path)
    try:
        adapter = environment.client.app.state.mock_robot_adapter
        adapter.set_capability(
            RobotCapabilityName.NAVIGATE_TO,
            runtime_enabled=True,
            verification_status="concept",
        )
        asyncio.run(
            environment.client.app.state.robot_service.sync_robot(
                adapter,
                adapter.external_id,
            )
        )
        room_id = create_room(environment, "unverified")
        with pytest.raises(
            RobotMobilePerceptionError,
            match="Verified and enabled navigate_to",
        ):
            evaluate(environment, space_id=room_id)
        assert task_count(environment) == 0
    finally:
        environment.manager.dispose()


def test_room_allowlist_blocks_motion_into_unauthorized_space(tmp_path: Path) -> None:
    environment = mobile_environment(tmp_path)
    try:
        allowed_room = create_room(environment, "allowed")
        private_room = create_room(environment, "private")
        evaluate(environment, space_id=allowed_room)
        with environment.manager.session_factory() as session:
            from arvuno_core.persistence.models import ObservationSource

            source = session.scalars(
                select(ObservationSource).where(ObservationSource.source_type == "robot_mobile")
            ).one()
            source.config = {**source.config, "allowed_space_ids": [allowed_room]}
            session.commit()

        with pytest.raises(RobotMobilePerceptionError, match="allowlist"):
            evaluate(environment, space_id=private_room)
        assert task_count(environment) == 0
    finally:
        environment.manager.dispose()


def test_execution_lock_precedes_mobile_authorization_validation(tmp_path: Path) -> None:
    environment = mobile_environment(tmp_path)
    try:
        room_id = create_room(environment, "authorization")
        request = evaluate(environment, space_id=room_id)
        with pytest.raises(RobotExecutionLockedError):
            execute(environment, request.id)
        assert task_count(environment) == 0

        authorize(environment, request.id)
        with environment.manager.session_factory() as session:
            row = session.get(ActivePerceptionRequest, request.id)
            assert row is not None
            row.authorization_scope = {
                **row.authorization_scope,
                "target_space_id": "another-space",
            }
            session.commit()

        with pytest.raises(RobotExecutionLockedError):
            execute(environment, request.id)
        assert task_count(environment) == 0
    finally:
        environment.manager.dispose()


def test_entity_scope_is_rejected_even_when_a_robot_is_ready(tmp_path: Path) -> None:
    environment = mobile_environment(tmp_path)
    try:
        with pytest.raises(RobotMobilePerceptionError, match="exact target space"):
            asyncio.run(
                environment.service.evaluate(
                    _request(space_id="unused", attribute="temperature", entity_id="entity-1"),
                    robot_id=environment.robot_id,
                )
            )
        assert task_count(environment) == 0
    finally:
        environment.manager.dispose()


def test_mobile_perception_api_requires_token_and_blocks_execution(tmp_path: Path) -> None:
    environment = mobile_environment(tmp_path)
    try:
        room_id = create_room(environment, "api")
        assert (
            environment.client.post(
                "/api/robot-perception/requests/evaluate",
                json={"request": {}, "robot_id": environment.robot_id},
            ).status_code
            == 401
        )

        response = environment.client.post(
            "/api/robot-perception/requests/evaluate",
            headers=HEADERS,
            json={
                "robot_id": environment.robot_id,
                "request": {
                    "question": "What is in this room now?",
                    "space_id": room_id,
                    "attribute": "scene_label",
                    "start_time": (NOW - timedelta(minutes=5)).isoformat(),
                    "end_time": NOW.isoformat(),
                    "now": NOW.isoformat(),
                },
            },
        )
        assert response.status_code == 201
        request_id = response.json()["data"]["id"]

        authorized = environment.client.post(
            f"/api/robot-perception/requests/{request_id}/authorize",
            headers=HEADERS,
            json={
                "confirmed_navigation": True,
                "confirmed_camera_capture": True,
            },
        )
        assert authorized.status_code == 200

        executed = environment.client.post(
            f"/api/robot-perception/requests/{request_id}/execute",
            headers=HEADERS,
        )
        assert executed.status_code == 403
        assert executed.json()["error"]["code"] == "ROBOT_EXECUTION_LOCKED"

        fetched = environment.client.get(
            f"/api/robot-perception/requests/{request_id}",
            headers=HEADERS,
        )
        assert fetched.status_code == 200
        assert fetched.json()["data"]["status"] == "proposed"
        assert fetched.json()["data"]["execution_trace"]["mock_only"] is True
    finally:
        environment.manager.dispose()


def test_mobile_perception_uses_only_the_robot_application_boundary() -> None:
    source = (
        Path(__file__).parents[1] / "arvuno_core" / "perception" / "robot_mobile.py"
    ).read_text(encoding="utf-8")
    assert "RobotAdapter" not in source
    assert "adapter.execute_task" not in source
    assert "RobotRegistry" not in source
    assert "joint" not in source.lower()
    assert "motor" not in source.lower()
