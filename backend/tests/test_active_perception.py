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
from arvuno_core.estimation.service import StateEstimationService
from arvuno_core.observations.models import ObservationInput
from arvuno_core.observations.service import ObservationService
from arvuno_core.perception.errors import (
    PerceptionRequestNotFoundError,
    PerceptionStateError,
)
from arvuno_core.perception.service import ActivePerceptionService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import Observation, ObservationConsent, ObservationSource
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.reasoning.service import ReasoningService
from arvuno_core.schemas.perception import ActivePerceptionEvaluateRequest
from arvuno_core.spatial.service import SpatialService

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
HEADERS = {"Authorization": "Bearer test-api-token"}


@dataclass
class FixedClock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now


@dataclass
class MockObserver:
    observation: ObservationInput | None
    calls: list[str]

    async def observe(self, request: Any) -> ObservationInput | None:
        self.calls.append(request.id)
        return self.observation


@dataclass
class PerceptionEnvironment:
    manager: DatabaseManager
    factory: Any
    service: ActivePerceptionService
    observation_service: ObservationService
    clock: FixedClock


def phase_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


def perception_environment(tmp_path: Path) -> PerceptionEnvironment:
    manager = DatabaseManager(phase_settings(tmp_path))
    manager.initialize_database()

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(manager.session_factory)

    observation_service = ObservationService(factory)
    clock = FixedClock()
    counter = itertools.count(1)
    service = ActivePerceptionService(
        factory,
        observation_service,
        StateEstimationService(factory, environment_name="home"),
        ReasoningService(factory, environment_name="home"),
        environment_name="home",
        clock=clock,
        request_id_factory=lambda: f"perception-{next(counter)}",
    )
    return PerceptionEnvironment(manager, factory, service, observation_service, clock)


def create_room(environment: PerceptionEnvironment, name: str) -> str:
    spatial = SpatialService(environment.factory, environment_name="home")
    root = asyncio.run(spatial.ensure_root())
    room = asyncio.run(
        spatial.create_space(
            parent_id=root.id,
            name=f"Active Perception {name}",
            space_type="room",
        )
    )
    return room.id


def configure_home_assistant_source(
    environment: PerceptionEnvironment,
    *,
    attribute: str,
    cost: float = 2.0,
) -> str:
    with environment.manager.session_factory() as session:
        source = session.scalars(
            select(ObservationSource).where(ObservationSource.adapter_id == "home_assistant")
        ).one()
        source.config = {
            "kind": "home_assistant",
            "supported_attributes": [attribute],
            "perception_cost": cost,
        }
        session.commit()
        return source.id


def add_compared_source(
    environment: PerceptionEnvironment,
    *,
    name: str,
    attribute: str,
    trust_level: float,
    cost: float,
) -> str:
    with environment.manager.session_factory() as session:
        source = ObservationSource(
            source_type="user_report",
            name=name,
            status="active",
            trust_level=trust_level,
            time_trust="user_asserted",
            config={
                "supported_attributes": [attribute],
                "perception_cost": cost,
            },
            privacy_scope={},
        )
        session.add(source)
        session.commit()
        session.refresh(source)
        return source.id


def evaluate(
    environment: PerceptionEnvironment,
    *,
    question: str,
    space_id: str,
    attribute: str,
    **overrides: Any,
) -> Any:
    return asyncio.run(
        environment.service.evaluate_gap(
            ActivePerceptionEvaluateRequest(
                question=question,
                space_id=space_id,
                attribute=attribute,
                start_time=NOW - timedelta(minutes=5),
                end_time=NOW,
                now=NOW,
                **overrides,
            )
        )
    )


def observation(
    *,
    source_id: str,
    space_id: str,
    attribute: str,
    value: Any,
    external_id: str,
) -> ObservationInput:
    return ObservationInput(
        source_id=source_id,
        subject_type="space",
        subject_id=space_id,
        space_id=space_id,
        attribute=attribute,
        raw_value=value,
        raw_unit="°C" if attribute == "temperature" else None,
        observed_at=NOW,
        observed_at_source="gateway_state_clock",
        received_at=NOW,
        correlation_id="active-perception-test",
        external_id=external_id,
    )


def observation_count(environment: PerceptionEnvironment) -> int:
    with environment.manager.session_factory() as session:
        return int(session.scalar(select(func.count()).select_from(Observation)) or 0)


def test_gap_selects_comparable_sources_by_trust_and_records_cost(
    tmp_path: Path,
) -> None:
    environment = perception_environment(tmp_path)
    try:
        room_id = create_room(environment, "source comparison")
        home_assistant_id = configure_home_assistant_source(
            environment,
            attribute="temperature",
            cost=2.0,
        )
        add_compared_source(
            environment,
            name="Cheaper user report",
            attribute="temperature",
            trust_level=0.8,
            cost=1.0,
        )

        request = evaluate(
            environment,
            question="What is the current room temperature?",
            space_id=room_id,
            attribute="temperature",
        )

        assert request.status == "proposed"
        assert request.proposed_input["source_id"] == home_assistant_id
        assert request.cost_estimate == {
            "score": 2.0,
            "basis": "source.config.perception_cost or conservative source-type default",
            "worthwhile": True,
        }
        candidates = request.current_coverage["candidate_sources"]
        assert [item["source_type"] for item in candidates] == ["adapter", "user_report"]
        assert candidates[0]["trust_level"] == 0.9
        assert candidates[0]["cost_score"] == 2.0
        assert {item["capability_basis"] for item in candidates} == {"declared"}
        assert request.current_coverage["rejected_sources"] == []
    finally:
        environment.manager.dispose()


def test_over_cost_source_is_rejected_as_not_worthwhile(tmp_path: Path) -> None:
    environment = perception_environment(tmp_path)
    try:
        room_id = create_room(environment, "expensive source")
        configure_home_assistant_source(environment, attribute="temperature", cost=50.0)

        request = evaluate(
            environment,
            question="Is an expensive extra reading worthwhile?",
            space_id=room_id,
            attribute="temperature",
            max_cost_score=1.0,
        )

        assert request.status == "unavailable"
        assert request.proposed_capability is None
        assert request.proposed_input == {}
        assert request.cost_estimate == {"score": None, "worthwhile": False}
        rejected = request.current_coverage["rejected_sources"]
        assert len(rejected) == 1
        assert rejected[0]["reason"] == "cost_above_limit"
        assert rejected[0]["cost_score"] == 50.0
    finally:
        environment.manager.dispose()


def test_historical_attribute_use_discovers_a_source_for_a_new_space(
    tmp_path: Path,
) -> None:
    environment = perception_environment(tmp_path)
    try:
        known_room = create_room(environment, "known space")
        new_room = create_room(environment, "new space")
        with environment.manager.session_factory() as session:
            source = session.scalars(
                select(ObservationSource).where(ObservationSource.adapter_id == "home_assistant")
            ).one()
            home_assistant_id = source.id

        asyncio.run(
            environment.observation_service.record(
                observation(
                    source_id=home_assistant_id,
                    space_id=known_room,
                    attribute="temperature",
                    value=22.0,
                    external_id="prior-room-reading",
                )
            )
        )

        request = evaluate(
            environment,
            question="What is the temperature in the new room?",
            space_id=new_room,
            attribute="temperature",
        )
        assert request.status == "proposed"
        assert request.proposed_input["source_id"] == home_assistant_id
        assert request.current_coverage["candidate_sources"][0]["capability_basis"] == (
            "historical_use"
        )
    finally:
        environment.manager.dispose()


def test_no_observer_or_no_result_is_unavailable_and_never_fabricates_an_observation(
    tmp_path: Path,
) -> None:
    environment = perception_environment(tmp_path)
    try:
        room_id = create_room(environment, "no hardware")
        source_id = configure_home_assistant_source(environment, attribute="temperature")
        no_observer = evaluate(
            environment,
            question="Can the current deployment read this room?",
            space_id=room_id,
            attribute="temperature",
        )
        unavailable = asyncio.run(environment.service.execute(no_observer.id, None, now=NOW))
        assert unavailable.status == "unavailable"
        assert "No read-only observer is configured" in unavailable.unavailable_reason
        assert observation_count(environment) == 0

        none_result = evaluate(
            environment,
            question="Can this observer read this room?",
            space_id=room_id,
            attribute="temperature",
        )
        asyncio.run(
            environment.service.execute(
                none_result.id,
                MockObserver(None, []),
                now=NOW,
            )
        )
        refreshed = asyncio.run(environment.service.get_request(none_result.id))
        assert refreshed.status == "unavailable"
        assert "No read-only observer is available" in refreshed.unavailable_reason
        assert observation_count(environment) == 0
        assert source_id
    finally:
        environment.manager.dispose()


def test_mock_observer_records_real_observation_updates_state_and_reruns_reasoning(
    tmp_path: Path,
) -> None:
    environment = perception_environment(tmp_path)
    try:
        room_id = create_room(environment, "closed loop")
        source_id = configure_home_assistant_source(environment, attribute="temperature")
        request = evaluate(
            environment,
            question="What is the current room temperature?",
            space_id=room_id,
            attribute="temperature",
        )
        mock = MockObserver(
            observation(
                source_id=source_id,
                space_id=room_id,
                attribute="temperature",
                value=23.0,
                external_id="active-perception-real-result",
            ),
            [],
        )

        fulfilled = asyncio.run(environment.service.execute(request.id, mock, now=NOW))

        assert mock.calls == [request.id]
        assert fulfilled.status == "fulfilled"
        assert fulfilled.fulfilled_by_type == "observation"
        assert fulfilled.follow_up_reasoning_session_id != request.reasoning_session_id
        assert observation_count(environment) == 1
        with environment.manager.session_factory() as session:
            stored = session.get(Observation, fulfilled.fulfilled_by_id)
            assert stored is not None
            assert stored.normalized_value == 23.0
            assert stored.quality_status == "valid"
        estimates = asyncio.run(
            StateEstimationService(environment.factory, environment_name="home").list(
                space_id=room_id,
                attribute="temperature",
                now=NOW,
            )
        )
        assert estimates[0][0].status == "observed"
        assert estimates[0][0].value == 23.0
    finally:
        environment.manager.dispose()


def test_sensitive_gap_requires_scoped_consent_before_observation(
    tmp_path: Path,
) -> None:
    environment = perception_environment(tmp_path)
    try:
        room_id = create_room(environment, "sensitive gap")
        source_id = configure_home_assistant_source(environment, attribute="motion")
        request = evaluate(
            environment,
            question="Is anyone in this room?",
            space_id=room_id,
            attribute="motion",
        )

        assert request.status == "awaiting_consent"
        assert request.privacy_level == "sensitive"
        assert request.requires_user_consent is True
        with pytest.raises(PerceptionStateError, match="status 'awaiting_consent'"):
            asyncio.run(
                environment.service.execute(
                    request.id,
                    MockObserver(None, []),
                    now=NOW,
                )
            )
        assert observation_count(environment) == 0

        authorized = asyncio.run(environment.service.authorize(request.id))
        assert authorized.status == "proposed"
        assert authorized.authorized_at == NOW
        with environment.manager.session_factory() as session:
            consent_id = authorized.authorization_scope["consent_id"]
            consent = session.get(ObservationConsent, consent_id)
            assert consent is not None
            assert consent.status == "granted"
            assert consent.scope["active_perception_request_id"] == request.id
            assert consent.attribute == "motion"

        fulfilled = asyncio.run(
            environment.service.execute(
                request.id,
                MockObserver(
                    observation(
                        source_id=source_id,
                        space_id=room_id,
                        attribute="motion",
                        value=True,
                        external_id="authorized-motion-reading",
                    ),
                    [],
                ),
                now=NOW,
            )
        )
        assert fulfilled.status == "fulfilled"
        assert observation_count(environment) == 1
    finally:
        environment.manager.dispose()


def test_reject_and_delete_revoke_consent_and_do_not_duplicate_requests(
    tmp_path: Path,
) -> None:
    environment = perception_environment(tmp_path)
    try:
        room_id = create_room(environment, "rejection")
        configure_home_assistant_source(environment, attribute="motion")
        request = evaluate(
            environment,
            question="May I observe motion?",
            space_id=room_id,
            attribute="motion",
        )
        authorized = asyncio.run(environment.service.authorize(request.id))
        consent_id = authorized.authorization_scope["consent_id"]
        rejected = asyncio.run(environment.service.reject(request.id, reason="Not now"))
        assert rejected.status == "rejected"
        assert rejected.unavailable_reason == "Not now"
        with environment.manager.session_factory() as session:
            assert session.get(ObservationConsent, consent_id).status == "revoked"

        repeat = evaluate(
            environment,
            question="May I observe motion again?",
            space_id=room_id,
            attribute="motion",
        )
        assert repeat.id == request.id
        assert repeat.status == "rejected"

        asyncio.run(environment.service.delete_request(request.id))
        with pytest.raises(PerceptionRequestNotFoundError):
            asyncio.run(environment.service.get_request(request.id))
        assert observation_count(environment) == 0
    finally:
        environment.manager.dispose()


def test_expired_authorization_blocks_observation_and_expiry_is_auditable(
    tmp_path: Path,
) -> None:
    environment = perception_environment(tmp_path)
    try:
        room_id = create_room(environment, "expiry")
        configure_home_assistant_source(environment, attribute="motion")
        request = evaluate(
            environment,
            question="Is this authorization still valid?",
            space_id=room_id,
            attribute="motion",
            time_limit_seconds=600,
        )
        asyncio.run(
            environment.service.authorize(
                request.id,
                authorization_seconds=60,
            )
        )
        with pytest.raises(PerceptionStateError, match="authorization has expired"):
            asyncio.run(
                environment.service.execute(
                    request.id,
                    MockObserver(None, []),
                    now=NOW + timedelta(seconds=61),
                )
            )
        blocked = asyncio.run(environment.service.get_request(request.id))
        assert blocked.status == "unavailable"
        assert blocked.unavailable_reason == "The observation authorization has expired."

        second = evaluate(
            environment,
            question="Does another request expire?",
            space_id=room_id,
            attribute="temperature",
        )
        expired_count = asyncio.run(
            environment.service.expire_stale(now=NOW + timedelta(seconds=301))
        )
        assert expired_count == 1
        assert asyncio.run(environment.service.get_request(second.id)).status == "expired"
    finally:
        environment.manager.dispose()


def test_procedure_gap_does_not_claim_an_observation_can_solve_it(
    tmp_path: Path,
) -> None:
    environment = perception_environment(tmp_path)
    try:
        room_id = create_room(environment, "procedure")
        configure_home_assistant_source(environment, attribute="temperature")
        request = evaluate(
            environment,
            question="Which validated procedure should run?",
            space_id=room_id,
            attribute="temperature",
            gap_type="procedure",
        )
        assert request.status == "unavailable"
        assert request.unavailable_reason == (
            "Procedure gaps require a validated procedure, not an observation."
        )
        assert request.proposed_capability is None
    finally:
        environment.manager.dispose()


def test_active_perception_api_requires_authorization_and_uses_design_path(
    tmp_path: Path,
) -> None:
    environment = perception_environment(tmp_path)
    app = create_app(
        phase_settings(tmp_path),
        unit_of_work_factory=environment.factory,
    )
    app.state.perception_service = environment.service
    client = TestClient(app)
    try:
        room_id = create_room(environment, "api")
        configure_home_assistant_source(environment, attribute="temperature")
        assert client.get("/api/active-perception/requests").status_code == 401

        response = client.post(
            "/api/active-perception/requests/evaluate",
            headers=HEADERS,
            json={
                "question": "What is the API room temperature?",
                "space_id": room_id,
                "attribute": "temperature",
                "start_time": (NOW - timedelta(minutes=5)).isoformat(),
                "end_time": NOW.isoformat(),
                "now": NOW.isoformat(),
            },
        )
        assert response.status_code == 201
        request_id = response.json()["data"]["id"]
        listed = client.get(
            "/api/active-perception/requests",
            headers=HEADERS,
            params={"status": "proposed"},
        )
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["data"][0]["id"] == request_id
    finally:
        environment.manager.dispose()


def test_active_perception_does_not_import_device_or_tool_execution_paths() -> None:
    source = (Path(__file__).parents[1] / "arvuno_core" / "perception" / "service.py").read_text(
        encoding="utf-8"
    )
    assert "ToolExecutor" not in source
    assert "DeviceAdapter" not in source
    assert "HomeAssistantAdapter" not in source
    assert "control_device" not in source
