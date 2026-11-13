import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.multimodal.service import MultimodalService
from arvuno_core.observations.pipeline import ObservationPipeline
from arvuno_core.observations.service import ObservationService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import (
    Environment,
    EnvironmentSnapshot,
    Event,
    MultimodalConsent,
    MultimodalMediaAsset,
    Observation,
    ObservationAttributeDefinition,
    ObservationIngestionBatch,
    ObservationSource,
    ProactiveSuggestion,
    ProviderLog,
    RetentionRun,
)
from arvuno_core.persistence.provider_logs import SqlProviderLogStore
from arvuno_core.persistence.retention import SqlRetentionRunStore
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.proactive.service import ProactiveService
from arvuno_core.retention.models import RetentionPolicy
from arvuno_core.retention.scheduler import RetentionConflictError, RetentionScheduler
from arvuno_core.retention.service import build_retention_scheduler

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
JOB_NAMES = [
    "event",
    "observation",
    "multimodal_media",
    "proactive",
    "environment_snapshot",
    "provider_log",
]


@dataclass
class FixedClock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now


@dataclass
class RetentionTestContext:
    settings: Settings
    manager: DatabaseManager
    factory: Any
    scheduler: RetentionScheduler
    clock: FixedClock
    media_root: Path


def retention_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "api_token": "test-api-token",
        "data_dir": tmp_path / "data",
        "log_dir": tmp_path / "logs",
        "backup_dir": tmp_path / "backups",
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def build_context(
    tmp_path: Path,
    *,
    settings: Settings | None = None,
) -> RetentionTestContext:
    app_settings = settings or retention_settings(tmp_path)
    manager = DatabaseManager(app_settings)
    manager.initialize_database()

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(manager.session_factory)

    observation_service = ObservationService(factory)
    observation_pipeline = ObservationPipeline(factory, observation_service)
    multimodal_service = MultimodalService(factory, observation_service, app_settings)
    proactive_service = ProactiveService(factory, environment_name="home")
    provider_store = SqlProviderLogStore(factory)
    clock = FixedClock()
    scheduler = build_retention_scheduler(
        settings=app_settings,
        unit_of_work_factory=factory,
        observation_pipeline=observation_pipeline,
        multimodal_service=multimodal_service,
        proactive_service=proactive_service,
        provider_log_store=provider_store,
        clock=clock,
    )
    return RetentionTestContext(
        settings=app_settings,
        manager=manager,
        factory=factory,
        scheduler=scheduler,
        clock=clock,
        media_root=multimodal_service.media_root,
    )


def seed_retention_data(context: RetentionTestContext) -> None:
    media_root = context.media_root
    media_root.mkdir(parents=True, exist_ok=True)
    expired_media = b"expired private audio"
    active_media = b"active private audio"
    (media_root / "expired-media.wav").write_bytes(expired_media)
    (media_root / "active-media.wav").write_bytes(active_media)

    source = ObservationSource(
        id="retention-source",
        source_type="device",
        adapter_id="retention-adapter",
        name="Retention test source",
        status="active",
        trust_level=1.0,
        time_trust="poll_clock",
        config={},
        privacy_scope={},
    )
    environment = Environment(id="retention-env", name="home", is_default=True)

    with context.manager.session_factory() as session:
        session.add_all([source, environment])
        session.flush()
        attribute = session.get(ObservationAttributeDefinition, "temperature")
        if attribute is None:
            attribute = ObservationAttributeDefinition(
                attribute="temperature",
                display_name="Temperature",
                value_type="number",
                canonical_unit="C",
                normalization_rule_version="1",
                valid_range={},
                quality_policy={},
                freshness_policy={},
                sampling_policy={},
                retention_policy={"days": 30},
                sensitivity="normal",
            )
            session.add(attribute)
            session.flush()
        session.add_all(
            [
                Event(
                    id="expired-event",
                    event_type="device_state_changed",
                    source="mock_adapter",
                    subject_type="device",
                    subject_id="device-1",
                    payload={},
                    occurred_at=NOW - timedelta(days=181),
                ),
                Event(
                    id="current-event",
                    event_type="device_state_changed",
                    source="mock_adapter",
                    subject_type="device",
                    subject_id="device-1",
                    payload={},
                    occurred_at=NOW - timedelta(days=100),
                ),
                Event(
                    id="long-term-event",
                    event_type="task_started",
                    source="task",
                    subject_type=None,
                    subject_id=None,
                    payload={},
                    occurred_at=NOW - timedelta(days=400),
                ),
                Observation(
                    observation_id="expired-observation",
                    source_id=source.id,
                    source_type="device",
                    subject_type="environment",
                    subject_id="global",
                    attribute=attribute.attribute,
                    raw_value=20,
                    normalized_value=20,
                    value_type="number",
                    received_at=NOW - timedelta(days=31),
                    quality_status="valid",
                    quality_issues=[],
                    dedupe_key="expired-observation",
                    payload_hash="expired-observation",
                    retention_class="standard_30d",
                    retention_until=NOW - timedelta(days=1),
                ),
                Observation(
                    observation_id="current-observation",
                    source_id=source.id,
                    source_type="device",
                    subject_type="environment",
                    subject_id="global",
                    attribute=attribute.attribute,
                    raw_value=21,
                    normalized_value=21,
                    value_type="number",
                    received_at=NOW,
                    quality_status="valid",
                    quality_issues=[],
                    dedupe_key="current-observation",
                    payload_hash="current-observation",
                    retention_class="standard_30d",
                    retention_until=NOW + timedelta(days=1),
                ),
                ObservationIngestionBatch(
                    id="expired-batch",
                    source_id=source.id,
                    source_type="device",
                    adapter_id="retention-adapter",
                    received_at=NOW - timedelta(days=31),
                    status="completed",
                    errors=[],
                ),
                EnvironmentSnapshot(
                    id="expired-snapshot",
                    environment_id=environment.id,
                    context={},
                    active_task_ids=[],
                    anomaly_count=0,
                    created_at=NOW - timedelta(days=31),
                ),
                EnvironmentSnapshot(
                    id="current-snapshot",
                    environment_id=environment.id,
                    context={},
                    active_task_ids=[],
                    anomaly_count=0,
                    created_at=NOW,
                ),
                ProactiveSuggestion(
                    id="expired-suggestion",
                    environment_id=environment.id,
                    trigger_type="anomaly",
                    title="Expired",
                    message="Expired",
                    dedupe_key="expired",
                    status="evaluated",
                    expires_at=NOW - timedelta(minutes=1),
                ),
                ProactiveSuggestion(
                    id="current-suggestion",
                    environment_id=environment.id,
                    trigger_type="anomaly",
                    title="Current",
                    message="Current",
                    dedupe_key="current",
                    status="evaluated",
                    expires_at=NOW + timedelta(minutes=1),
                ),
                ProviderLog(
                    id="expired-provider-log",
                    provider="mock",
                    model="mock-agent",
                    request_kind="agent_intent_plan",
                    input_summary={"schema_version": 2, "message_count": 1},
                    output_summary={},
                    status="succeeded",
                    created_at=NOW - timedelta(days=91),
                ),
                ProviderLog(
                    id="debug-provider-log",
                    provider="mock",
                    model="mock-agent",
                    request_kind="agent_intent_plan",
                    input_summary={
                        "schema_version": 2,
                        "message_count": 1,
                        "debug": {
                            "purpose": "temporary_provider_request_debug",
                            "expires_at": (NOW + timedelta(seconds=60)).isoformat(),
                        },
                    },
                    output_summary={},
                    status="succeeded",
                    created_at=NOW,
                ),
            ]
        )
        consent = MultimodalConsent(
            id="retention-consent",
            environment_id=environment.id,
            user_id="user-1",
            consent_type="capture",
            modality="audio",
            purpose="user_query",
            processing_locations=["local"],
            space_ids=[],
            granted_at=NOW,
            status="granted",
            scope={},
        )
        session.add(consent)
        session.flush()
        session.add_all(
            [
                MultimodalMediaAsset(
                    id="expired-media",
                    environment_id=environment.id,
                    media_kind="audio_clip",
                    mime_type="audio/wav",
                    size_bytes=len(expired_media),
                    sha256=hashlib.sha256(expired_media).hexdigest(),
                    storage_backend="local_private_file",
                    storage_key="expired-media.wav",
                    content_available=True,
                    validation_status="valid",
                    purpose="user_query",
                    consent_id=consent.id,
                    retention_class="process_then_delete_24h",
                    retention_until=NOW - timedelta(minutes=1),
                    purge_status="pending",
                    received_at=NOW,
                    metadata_summary={},
                ),
                MultimodalMediaAsset(
                    id="current-media",
                    environment_id=environment.id,
                    media_kind="audio_clip",
                    mime_type="audio/wav",
                    size_bytes=len(active_media),
                    sha256=hashlib.sha256(active_media).hexdigest(),
                    storage_backend="local_private_file",
                    storage_key="active-media.wav",
                    content_available=True,
                    validation_status="valid",
                    purpose="user_query",
                    consent_id=consent.id,
                    retention_class="process_then_delete_24h",
                    retention_until=NOW + timedelta(hours=1),
                    purge_status="pending",
                    received_at=NOW,
                    metadata_summary={},
                ),
            ]
        )
        session.commit()


def test_retention_jobs_clean_expired_data_and_are_idempotent(tmp_path: Path) -> None:
    context = build_context(
        tmp_path,
        settings=retention_settings(tmp_path, retention_manual_cooldown_seconds=1),
    )
    try:
        seed_retention_data(context)

        assert asyncio.run(context.scheduler.run_manual(JOB_NAMES)) == JOB_NAMES

        with context.manager.session_factory() as session:
            assert session.scalars(select(Event.id).order_by(Event.occurred_at)).all() == [
                "long-term-event",
                "current-event",
            ]
            assert session.scalars(select(Observation.observation_id)).all() == [
                "current-observation"
            ]
            assert session.get(ObservationIngestionBatch, "expired-batch") is None
            assert session.get(EnvironmentSnapshot, "expired-snapshot") is None
            assert session.get(ProactiveSuggestion, "expired-suggestion").status == "expired"
            assert session.get(MultimodalMediaAsset, "expired-media").purge_status == "purged"
            assert session.get(ProviderLog, "expired-provider-log") is None
            debug_record = session.get(ProviderLog, "debug-provider-log")
            assert debug_record is not None
            assert "debug" in debug_record.input_summary
            assert not (context.media_root / "expired-media.wav").exists()
            assert (context.media_root / "active-media.wav").exists()
            latest = {run.job_name: run for run in session.scalars(select(RetentionRun)).all()}
            assert set(latest) == set(JOB_NAMES)
            assert all(run.status == "succeeded" for run in latest.values())

        context.clock.now += timedelta(seconds=1)
        assert asyncio.run(context.scheduler.run_manual(JOB_NAMES)) == JOB_NAMES
        with context.manager.session_factory() as session:
            assert [
                run.affected_count
                for run in session.scalars(select(RetentionRun)).all()
                if run.status == "succeeded"
            ].count(0) == len(JOB_NAMES)

        context.clock.now += timedelta(seconds=61)
        assert asyncio.run(context.scheduler.run_manual(["provider_log"])) == ["provider_log"]
        with context.manager.session_factory() as session:
            debug_record = session.get(ProviderLog, "debug-provider-log")
            assert debug_record is not None
            assert "debug" not in debug_record.input_summary
    finally:
        context.manager.dispose()


def test_module_policies_are_independent_and_can_be_disabled(tmp_path: Path) -> None:
    settings = retention_settings(
        tmp_path,
        event_retention_interval_seconds=10,
        observation_retention_interval_seconds=20,
        observation_retention_cleanup_enabled=False,
        multimodal_media_retention_interval_seconds=100,
        proactive_retention_interval_seconds=100,
        environment_snapshot_retention_interval_seconds=100,
        provider_log_retention_interval_seconds=100,
    )
    context = build_context(tmp_path, settings=settings)
    try:
        assert context.clock.now == NOW
        assert asyncio.run(context.scheduler.run_due(now=NOW)) == []
        assert asyncio.run(context.scheduler.run_due(now=NOW + timedelta(seconds=10))) == ["event"]
        assert asyncio.run(context.scheduler.run_due(now=NOW + timedelta(seconds=20))) == ["event"]

        policies = {item["name"]: item for item in context.scheduler.policies()}
        assert set(policies) == set(JOB_NAMES)
        assert policies["observation"]["enabled"] is False
        assert policies["event"]["interval_seconds"] == 10
        assert policies["provider_log"]["rules"]["debug_capture"] != "metadata_retention"
    finally:
        context.manager.dispose()


@dataclass
class FakeJob:
    name: str
    enabled: bool = True
    interval_seconds: int = 60
    fail: bool = False
    affected: int = 1

    async def run(self, *, now: datetime) -> int:
        if self.fail:
            raise RuntimeError("simulated cleanup failure")
        return self.affected

    def policy(self) -> RetentionPolicy:
        return RetentionPolicy(
            name=self.name,
            label=self.name,
            enabled=self.enabled,
            interval_seconds=self.interval_seconds,
            batch_size=10,
            rules={},
        )


def test_scheduler_isolates_failures_and_reports_them(tmp_path: Path) -> None:
    context = build_context(tmp_path)
    try:
        scheduler = RetentionScheduler(
            jobs=[FakeJob("failing", fail=True), FakeJob("successful")],
            run_store=SqlRetentionRunStore(context.factory),
            tick_seconds=60,
            manual_cooldown_seconds=60,
            clock=context.clock,
        )
        executed = asyncio.run(scheduler.run_due(now=NOW + timedelta(seconds=60)))
        assert sorted(executed) == ["failing", "successful"]
        failures = asyncio.run(scheduler.failures())
        assert [item["job_name"] for item in failures] == ["failing"]
        assert failures[0]["error_code"] == "RuntimeError"
        status = asyncio.run(scheduler.status())
        by_name = {item["name"]: item["last_run"] for item in status["jobs"]}
        assert by_name["failing"]["status"] == "failed"
        assert by_name["successful"]["status"] == "succeeded"
    finally:
        context.manager.dispose()


@dataclass
class BlockingJob:
    name: str = "blocking"
    started: Any = None
    release: Any = None

    async def run(self, *, now: datetime) -> int:
        if self.started is None:
            self.started = asyncio.Event()
        if self.release is None:
            self.release = asyncio.Event()
        self.started.set()
        await self.release.wait()
        return 1

    async def wait_until_started(self) -> None:
        while self.started is None:
            await asyncio.sleep(0)
        await self.started.wait()

    def policy(self) -> RetentionPolicy:
        return RetentionPolicy(
            name=self.name,
            label=self.name,
            enabled=True,
            interval_seconds=60,
            batch_size=1,
            rules={},
        )


def test_cancelled_job_is_audited_and_a_new_run_can_complete(tmp_path: Path) -> None:
    context = build_context(tmp_path)
    try:

        async def scenario() -> None:
            job = BlockingJob()
            scheduler = RetentionScheduler(
                jobs=[job],
                run_store=SqlRetentionRunStore(context.factory),
                tick_seconds=60,
                manual_cooldown_seconds=1,
                clock=context.clock,
            )
            task = asyncio.create_task(scheduler.run_manual([job.name]))
            await asyncio.wait_for(job.wait_until_started(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            context.clock.now += timedelta(seconds=1)
            job.release.set()
            assert await scheduler.run_manual([job.name]) == [job.name]

        asyncio.run(scenario())
        with context.manager.session_factory() as session:
            statuses = list(
                session.scalars(select(RetentionRun.status).order_by(RetentionRun.started_at))
            )
            assert statuses == ["failed", "succeeded"]
    finally:
        context.manager.dispose()


def test_manual_execution_rejects_overlap_and_cooldown(tmp_path: Path) -> None:
    context = build_context(tmp_path)
    try:

        async def scenario() -> None:
            job = BlockingJob()
            scheduler = RetentionScheduler(
                jobs=[job],
                run_store=SqlRetentionRunStore(context.factory),
                tick_seconds=60,
                manual_cooldown_seconds=1,
                clock=context.clock,
            )
            first = asyncio.create_task(scheduler.run_manual([job.name]))
            await asyncio.wait_for(job.wait_until_started(), timeout=1)
            with pytest.raises(RetentionConflictError, match="already running"):
                await scheduler.run_manual([job.name])
            job.release.set()
            assert await first == [job.name]

            context.clock.now += timedelta(seconds=1)
            assert await scheduler.run_manual([job.name]) == [job.name]
            with pytest.raises(RetentionConflictError, match="cooling down"):
                await scheduler.run_manual([job.name])

        asyncio.run(scenario())
    finally:
        context.manager.dispose()


def test_retention_api_requires_authentication_and_reports_status(tmp_path: Path) -> None:
    settings = retention_settings(
        tmp_path,
        retention_scheduler_enabled=False,
        retention_manual_cooldown_seconds=60,
    )
    context = build_context(tmp_path, settings=settings)
    app = create_app(settings, unit_of_work_factory=context.factory)
    headers = {"Authorization": "Bearer test-api-token"}
    try:
        with TestClient(app) as client:
            assert client.get("/api/retention/policies").status_code == 401
            assert client.get("/api/retention/status").status_code == 401
            assert client.post("/api/retention/run", headers=headers).status_code == 200

            policies = client.get("/api/retention/policies", headers=headers).json()["data"]
            assert {item["name"] for item in policies["policies"]} == set(JOB_NAMES)
            status = client.get("/api/retention/status", headers=headers).json()["data"]
            assert status["single_process_only"] is True

            second_run = client.post("/api/retention/run", headers=headers)
            assert second_run.status_code == 409
            assert second_run.json()["error"]["code"] == "RETENTION_MANUAL_COOLDOWN"

            unknown = client.post(
                "/api/retention/run",
                headers=headers,
                json={"jobs": ["unknown"]},
            )
            assert unknown.status_code == 409
            assert unknown.json()["error"]["code"] == "RETENTION_JOB_NOT_FOUND"
            assert client.get("/api/retention/failures", headers=headers).status_code == 200
    finally:
        context.manager.dispose()


def test_retention_scheduler_lifespan_is_explicitly_controlled(tmp_path: Path) -> None:
    enabled_context = build_context(tmp_path)
    disabled_context = build_context(
        tmp_path / "disabled",
        settings=retention_settings(tmp_path / "disabled", retention_scheduler_enabled=False),
    )
    enabled_app = create_app(
        enabled_context.settings,
        unit_of_work_factory=enabled_context.factory,
    )
    disabled_app = create_app(
        disabled_context.settings,
        unit_of_work_factory=disabled_context.factory,
    )
    try:
        with TestClient(enabled_app):
            assert enabled_app.state.retention_scheduler.is_running is True
        assert enabled_app.state.retention_scheduler.is_running is False

        with TestClient(disabled_app):
            assert disabled_app.state.retention_scheduler.is_running is False
    finally:
        enabled_context.manager.dispose()
        disabled_context.manager.dispose()
