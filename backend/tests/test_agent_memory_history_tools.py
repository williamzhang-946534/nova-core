import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from arvuno_core.agent_runtime.models import AgentEnvironmentSnapshot, AgentSpaceSummary
from arvuno_core.agent_runtime.runtime import AgentRuntime
from arvuno_core.ai.mock import MockAIProvider
from arvuno_core.ai.storage import ProviderLogFinish, ProviderLogStart
from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.history.models import (
    HistoryQueryResult,
    HistoryRecord,
    HistoryTimeRange,
    TimeGap,
    TimeSemantics,
)
from arvuno_core.memory.models import (
    MemoryEvidenceView,
    MemoryRetrievalResult,
    MemoryView,
    PreferenceView,
)
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import EnvironmentSnapshot, Event
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.tasks.models import (
    StoredTaskDetail,
    StoredTaskStep,
    TaskCreate,
    TaskRunResult,
    TaskStatus,
    TaskStepStatus,
)
from arvuno_core.tools.catalog import RegistryToolCatalog
from arvuno_core.tools.confirmation import ConfirmationService
from arvuno_core.tools.errors import ToolPermissionDeniedError
from arvuno_core.tools.executor import ToolExecutor
from arvuno_core.tools.models import (
    HistoryQueryInput,
    HistoryQueryOperation,
    HistoryQueryOutput,
    MemoryRetrievalInput,
    MemoryRetrievalOutput,
    ToolExecutionContext,
    ToolPermission,
    ToolRiskLevel,
)
from arvuno_core.tools.registry import build_default_tool_registry
from arvuno_core.tools.safety import SafetyPolicy
from arvuno_core.tools.storage import ToolExecutionCreate, ToolExecutionUpdate

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
HEADERS = {"Authorization": "Bearer test-api-token"}


@dataclass
class IdleDeviceService:
    async def list_devices(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        return []


@dataclass
class ProviderLogStore:
    starts: list[ProviderLogStart] = field(default_factory=list)
    finishes: dict[str, ProviderLogFinish] = field(default_factory=dict)

    async def start(self, record: ProviderLogStart) -> None:
        self.starts.append(record)

    async def finish(self, log_id: str, record: ProviderLogFinish) -> None:
        self.finishes[log_id] = record


def memory_view() -> MemoryView:
    return MemoryView(
        id="memory-tool-1",
        memory_type="semantic",
        title="User stated fact",
        content="The user prefers Celsius.",
        keywords=["temperature"],
        importance=4,
        source_type="user",
        source_id="conversation-message-1",
        user_confirmed=True,
        status="active",
        confidence=1.0,
        verification_status="verified",
        owner_id="local_user",
        access_level="owner",
        scope={"environment": "home"},
        valid_from=NOW,
        correction_count=0,
        created_at=NOW,
        updated_at=NOW,
    )


def preference_view() -> PreferenceView:
    return PreferenceView(
        id="preference-tool-1",
        key="temperature.unit",
        value={"unit": "C"},
        category="environment",
        description="Use Celsius.",
        source="conversation",
        source_type="conversation",
        source_record_id="conversation-message-1",
        status="active",
        scope={"environment": "home"},
        confirmed=True,
        confirmed_at=NOW,
        valid_from=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def evidence_view() -> MemoryEvidenceView:
    return MemoryEvidenceView(
        id="evidence-tool-1",
        evidence_type="event",
        evidence_id="event-tool-source",
        source_type="event",
        source_record_id="event-tool-source",
        trust_level=0.9,
        snapshot={"state": "on"},
        occurred_at=NOW,
        created_at=NOW,
    )


@dataclass
class MemoryProvider:
    inputs: list[MemoryRetrievalInput] = field(default_factory=list)

    async def __call__(self, raw_input: MemoryRetrievalInput) -> MemoryRetrievalResult:
        self.inputs.append(raw_input)
        return MemoryRetrievalResult(
            question_type=raw_input.question_type,
            query=raw_input.query,
            memories=[memory_view()],
            preferences=[preference_view()],
            source_references=[evidence_view()],
            retrieved_at=NOW,
        )


@dataclass
class HistoryProvider:
    inputs: list[HistoryQueryInput] = field(default_factory=list)

    async def __call__(self, raw_input: HistoryQueryInput) -> HistoryQueryOutput:
        self.inputs.append(raw_input)
        record = HistoryRecord(
            record_type="event",
            record_id="event-tool-source",
            occurred_at=NOW,
            local_time="2026-11-03T20:00:00+08:00",
            source="mock",
            data={"state": "on"},
        )
        return HistoryQueryOutput(
            service_available=True,
            operation=raw_input.operation,
            time_range=HistoryQueryResult(
                range=HistoryTimeRange(
                    start_time=NOW - timedelta(hours=2),
                    end_time=NOW,
                    local_start_time="2026-11-03T18:00:00+08:00",
                    local_end_time="2026-11-03T20:00:00+08:00",
                ),
                time_semantics=TimeSemantics(
                    local_timezone=raw_input.timezone,
                    query_time_basis="occurred_at",
                ),
                records=[record],
                counts={"event": 1},
                missing_ranges=[
                    TimeGap(
                        start_time=NOW - timedelta(hours=1),
                        end_time=NOW - timedelta(minutes=30),
                        duration_seconds=1800,
                        reason="no matching history records",
                    )
                ],
                generated_at=NOW,
            ),
        )


@dataclass
class MemoryToolStore:
    records: dict[str, ToolExecutionCreate | ToolExecutionUpdate] = field(default_factory=dict)

    def register_definition(self, record: Any) -> None:
        return None

    def create_execution(self, record: ToolExecutionCreate) -> None:
        self.records[record.id] = record

    def update_execution(self, execution_id: str, record: ToolExecutionUpdate) -> None:
        self.records[execution_id] = record

    def get_execution(self, execution_id: str) -> Any:
        return self.records.get(execution_id)


@dataclass
class RecordingTaskSystem:
    result: TaskRunResult
    requests: list[TaskCreate] = field(default_factory=list)

    async def create_and_run(
        self,
        request: TaskCreate,
        *,
        correlation_id: str | None = None,
    ) -> TaskRunResult:
        self.requests.append(request)
        return self.result


def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


@pytest.fixture
def manager(tmp_path: Path) -> DatabaseManager:
    test_manager = DatabaseManager(settings(tmp_path))
    test_manager.initialize_database()
    yield test_manager
    test_manager.dispose()


def unit_factory(manager: DatabaseManager) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(manager.session_factory)


def execution_context() -> ToolExecutionContext:
    return ToolExecutionContext(correlation_id="correlation-memory-history-tool")


def task_result(tool_name: str, output: dict[str, Any]) -> TaskRunResult:
    return TaskRunResult(
        StoredTaskDetail(
            id="task-memory-history",
            task_type="memory_query",
            title="Read records",
            description="Test task.",
            status=TaskStatus.COMPLETED,
            origin="user",
            conversation_id=None,
            plan={},
            result=None,
            error=None,
            correlation_id="correlation-agent-memory",
            created_at=NOW,
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=1),
            steps=[
                StoredTaskStep(
                    id=f"step-{tool_name}",
                    task_id="task-memory-history",
                    step_index=0,
                    name="Query",
                    description="Query real records.",
                    tool_name=tool_name,
                    input={},
                    status=TaskStepStatus.COMPLETED,
                    started_at=NOW,
                    completed_at=NOW + timedelta(seconds=1),
                    output=output,
                    error=None,
                )
            ],
        )
    )


def agent_for(
    result: TaskRunResult | None = None,
    outputs: list[dict[str, Any]] | None = None,
) -> tuple[AgentRuntime, MockAIProvider, RecordingTaskSystem]:
    provider = MockAIProvider(ProviderLogStore(), outputs=outputs)
    tasks = RecordingTaskSystem(
        result=result
        or task_result(
            "retrieve_memory",
            MemoryRetrievalOutput(
                service_available=True,
                question_type="preference",
                query="temperature unit",
                memories=[memory_view()],
                source_references=[evidence_view().model_dump(mode="json")],
                retrieved_at=NOW,
            ).model_dump(mode="json"),
        )
    )
    registry = build_default_tool_registry(
        IdleDeviceService(),
        memory_retrieval_provider=MemoryProvider(),
        history_query_provider=HistoryProvider(),
    )

    async def environment() -> AgentEnvironmentSnapshot:
        return AgentEnvironmentSnapshot(
            environment_name="home",
            updated_at=NOW,
            spaces=[
                AgentSpaceSummary(
                    space_id="space-living",
                    space_type="room",
                    name="Living Room",
                    path="home/living-room",
                    status="active",
                )
            ],
        )

    runtime = AgentRuntime(
        provider=provider,
        task_system=tasks,
        tool_catalog=RegistryToolCatalog(registry, permissions={}),
        environment_provider=environment,
    )
    return runtime, provider, tasks


def candidate(intent_type: str, tool_name: str, raw_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent": {"type": intent_type, "confidence": 0.95},
        "requires_tool": True,
        "plan": [{"name": "Read real record", "tool_name": tool_name, "input": raw_input}],
        "reply_to_user": "The model will not invent records.",
    }


def test_default_tools_are_read_only_and_have_service_boundaries() -> None:
    registry = build_default_tool_registry(IdleDeviceService())

    assert {item["name"] for item in registry.catalog()} == {
        "list_devices",
        "get_environment_state",
        "retrieve_memory",
        "query_history",
        "get_device_state",
        "control_device",
    }
    for name in ("retrieve_memory", "query_history"):
        definition = registry.get(name)
        assert definition is not None
        assert definition.risk_level is ToolRiskLevel.READ_ONLY
        assert definition.default_permission is ToolPermission.ALLOW
        assert definition.requires_confirmation is False


def test_memory_and_history_tools_delegate_to_service_providers() -> None:
    memory_provider = MemoryProvider()
    history_provider = HistoryProvider()
    registry = build_default_tool_registry(
        IdleDeviceService(),
        memory_retrieval_provider=memory_provider,
        history_query_provider=history_provider,
    )
    memory_definition = registry.get("retrieve_memory")
    history_definition = registry.get("query_history")
    assert memory_definition is not None
    assert history_definition is not None

    memory = asyncio.run(
        memory_definition.handler(
            execution_context(),
            MemoryRetrievalInput(question_type="preference", query="temperature"),
        )
    )
    history = asyncio.run(
        history_definition.handler(
            execution_context(),
            HistoryQueryInput(
                operation=HistoryQueryOperation.TIME_RANGE,
                start_time=NOW - timedelta(hours=2),
                end_time=NOW,
            ),
        )
    )

    assert isinstance(memory, MemoryRetrievalOutput)
    assert memory.service_available is True
    assert memory.source_references[0]["source_record_id"] == "event-tool-source"
    assert isinstance(history, HistoryQueryOutput)
    assert history.time_range is not None
    assert history.time_range.records[0].record_id == "event-tool-source"
    assert memory_provider.inputs[0].query == "temperature"
    assert history_provider.inputs[0].operation is HistoryQueryOperation.TIME_RANGE


def test_unavailable_services_return_explicit_tool_output() -> None:
    registry = build_default_tool_registry(IdleDeviceService())
    memory_definition = registry.get("retrieve_memory")
    history_definition = registry.get("query_history")
    assert memory_definition is not None
    assert history_definition is not None

    memory = asyncio.run(memory_definition.handler(execution_context(), MemoryRetrievalInput()))
    history = asyncio.run(
        history_definition.handler(
            execution_context(),
            HistoryQueryInput(operation=HistoryQueryOperation.SNAPSHOT_AT, at_time=NOW),
        )
    )

    assert memory.service_available is False
    assert memory.memories == []
    assert memory.preferences == []
    assert history.service_available is False
    assert history.snapshot is None


@pytest.mark.parametrize(
    "raw_input",
    [
        {"operation": "ask"},
        {"operation": "time_range", "start_time": NOW},
        {"operation": "spatial_history", "space_id": "space-1", "start_time": NOW},
        {
            "operation": "entity_history",
            "entity_id": "entity-1",
            "start_time": NOW,
        },
        {"operation": "trends", "attribute": "temperature", "start_time": NOW},
        {"operation": "snapshot_at"},
        {"operation": "snapshot_diff", "baseline_id": "snapshot-1"},
        {"operation": "correlate", "record_type": "event"},
    ],
)
def test_history_operation_schemas_require_complete_selectors(raw_input: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        HistoryQueryInput.model_validate(raw_input)


def test_tool_executor_allows_read_only_and_enforces_permission() -> None:
    registry = build_default_tool_registry(
        IdleDeviceService(),
        memory_retrieval_provider=MemoryProvider(),
    )
    store = MemoryToolStore()
    executor = ToolExecutor(
        registry=registry,
        safety_policy=SafetyPolicy(
            IdleDeviceService(),
            tool_permissions={"retrieve_memory": "allow_read_only", "query_history": "deny"},
        ),
        confirmation_service=ConfirmationService(ttl_seconds=300),
        execution_store=store,
    )

    result = asyncio.run(
        executor.execute(
            "retrieve_memory",
            {"question_type": "semantic_fact", "query": "temperature"},
            context=execution_context(),
        )
    )
    with pytest.raises(ToolPermissionDeniedError):
        asyncio.run(
            executor.execute(
                "query_history",
                {"operation": "ask", "query": "What happened?"},
                context=execution_context(),
            )
        )

    assert result.status == "completed"
    assert result.verified is True
    assert result.permission_result.name == "ALLOWED"
    assert result.output is not None
    assert result.output["source_references"][0]["source_record_id"] == "event-tool-source"
    finished = store.get_execution(result.execution_id)
    assert isinstance(finished, ToolExecutionUpdate)
    assert finished.status == "completed"


def test_agent_memory_intent_uses_only_the_read_only_tool_and_summarizes_sources() -> None:
    raw_input = {"question_type": "preference", "query": "temperature unit"}
    output = candidate("memory_query", "retrieve_memory", raw_input)
    runtime, provider, tasks = agent_for(outputs=[output])

    result = asyncio.run(
        runtime.chat(
            "What temperature unit do I prefer?",
            correlation_id="correlation-agent-memory",
        )
    )

    assert result.status == "completed"
    assert result.intent == "memory_query"
    assert tasks.requests[0].steps[0].tool_name == "retrieve_memory"
    assert tasks.requests[0].steps[0].input == raw_input
    assert "Celsius" in result.reply
    assert "conversation-message-1" in result.reply
    assert "retrieve_memory" in provider.requests[0].messages[0].content


def test_agent_history_intent_returns_record_count_and_missing_range() -> None:
    raw_input = {
        "operation": "time_range",
        "start_time": (NOW - timedelta(hours=2)).isoformat(),
        "end_time": NOW.isoformat(),
    }
    history_output = HistoryQueryOutput(
        service_available=True,
        operation=HistoryQueryOperation.TIME_RANGE,
        time_range=HistoryQueryResult(
            range=HistoryTimeRange(
                start_time=NOW - timedelta(hours=2),
                end_time=NOW,
                local_start_time="2026-11-03T18:00:00+08:00",
                local_end_time="2026-11-03T20:00:00+08:00",
            ),
            time_semantics=TimeSemantics(
                local_timezone="Asia/Shanghai",
                query_time_basis="occurred_at",
            ),
            records=[
                HistoryRecord(
                    record_type="event",
                    record_id="event-tool-source",
                    occurred_at=NOW,
                )
            ],
            missing_ranges=[
                TimeGap(
                    start_time=NOW - timedelta(hours=1),
                    end_time=NOW - timedelta(minutes=30),
                    duration_seconds=1800,
                    reason="no matching history records",
                )
            ],
            generated_at=NOW,
        ),
    )
    runtime, provider, tasks = agent_for(
        task_result("query_history", history_output.model_dump(mode="json")),
        outputs=[candidate("history_query", "query_history", raw_input)],
    )

    result = asyncio.run(
        runtime.chat("What happened recently?", correlation_id="correlation-agent-history")
    )

    assert result.status == "completed"
    assert result.intent == "history_query"
    assert tasks.requests[0].steps[0].tool_name == "query_history"
    assert tasks.requests[0].steps[0].input == HistoryQueryInput.model_validate(
        raw_input
    ).model_dump(mode="json")
    assert "1 条" in result.reply
    assert "缺失区间 1 个" in result.reply


def test_app_tools_use_memory_and_history_services_without_repositories(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    with manager.session_factory() as session:
        session.add(
            Event(
                id="event-tool-source",
                event_type="device_state_changed",
                source="mock",
                payload={"state": "on"},
                occurred_at=NOW - timedelta(minutes=1),
            )
        )
        session.commit()
    with unit_factory(manager) as unit_of_work:
        assert unit_of_work.environments is not None
        environment_id = unit_of_work.environments.ensure_default("home").id
    with manager.session_factory() as session:
        session.add_all(
            [
                EnvironmentSnapshot(
                    id="snapshot-before",
                    environment_id=environment_id,
                    context={"devices": {"ac": {"name": "Air conditioner", "state": "on"}}},
                    active_task_ids=[],
                    anomaly_count=0,
                    context_version=1,
                    state_generated_at=NOW - timedelta(minutes=31),
                    created_at=NOW - timedelta(minutes=30),
                ),
                EnvironmentSnapshot(
                    id="snapshot-after",
                    environment_id=environment_id,
                    context={"devices": {"ac": {"name": "Air conditioner", "state": "off"}}},
                    active_task_ids=[],
                    anomaly_count=0,
                    context_version=1,
                    state_generated_at=NOW - timedelta(seconds=1),
                    created_at=NOW,
                ),
            ]
        )
        session.commit()

    app = create_app(
        settings(tmp_path),
        unit_of_work_factory=lambda: unit_factory(manager),
        initialize_tool_runtime=True,
    )
    with TestClient(app) as client:
        catalog = client.get("/api/tools", headers=HEADERS)
        memory = client.post(
            "/api/memories",
            headers=HEADERS,
            json={
                "memory_type": "semantic",
                "title": "User stated fact",
                "content": "The user prefers Celsius.",
                "keywords": ["temperature"],
                "importance": 4,
                "source_type": "user",
                "source_id": "conversation-message-1",
                "user_confirmed": True,
                "evidence": [
                    {
                        "evidence_type": "event",
                        "evidence_id": "event-tool-source",
                        "source_type": "event",
                        "source_record_id": "event-tool-source",
                        "trust_level": 0.9,
                        "snapshot": {"state": "on"},
                    }
                ],
            },
        )
        preference = client.post(
            "/api/memory-preferences",
            headers=HEADERS,
            json={
                "key": "temperature.unit",
                "value": {"unit": "C"},
                "category": "environment",
                "description": "Use Celsius.",
                "source_record_id": "conversation-message-1",
                "consent_statement": "Save my temperature unit preference.",
                "confirmed": True,
            },
        )
        memory_id = memory.json()["data"]["id"]
        memory_confirmation = client.post(
            f"/api/memories/{memory_id}/confirm",
            headers=HEADERS,
        )
        confirmed_memory = client.get(f"/api/memories/{memory_id}", headers=HEADERS)
        retrieval = client.post(
            "/api/tools/retrieve_memory/execute",
            headers=HEADERS,
            json={"input": {"question_type": "any", "query": "temperature"}},
        )
        history = client.post(
            "/api/tools/query_history/execute",
            headers=HEADERS,
            json={
                "input": {
                    "operation": "time_range",
                    "start_time": (NOW - timedelta(hours=2)).isoformat(),
                    "end_time": NOW.isoformat(),
                }
            },
        )
        snapshot_diff = client.post(
            "/api/tools/query_history/execute",
            headers=HEADERS,
            json={
                "input": {
                    "operation": "snapshot_diff",
                    "baseline_id": "snapshot-before",
                    "target_id": "snapshot-after",
                }
            },
        )

    assert memory.status_code == 201
    assert memory_confirmation.status_code == 200
    assert confirmed_memory.status_code == 200
    assert confirmed_memory.json()["data"]["status"] == "active"
    assert preference.status_code == 201
    assert [item["name"] for item in catalog.json()["data"]] == [
        "list_devices",
        "get_environment_state",
        "retrieve_memory",
        "query_history",
        "get_device_state",
        "control_device",
    ]

    retrieval_data = retrieval.json()["data"]
    assert retrieval.status_code == 200
    assert retrieval_data["status"] == "completed"
    output = retrieval_data["output"]
    assert [item["id"] for item in output["memories"]] == [memory.json()["data"]["id"]]
    assert [item["id"] for item in output["preferences"]] == [preference.json()["data"]["id"]]
    assert output["source_references"][0]["source_record_id"] == "event-tool-source"

    history_data = history.json()["data"]
    assert history.status_code == 200
    assert history_data["status"] == "completed"
    history_output = history_data["output"]
    assert history_output["service_available"] is True
    assert any(
        record["record_id"] == "event-tool-source"
        for record in history_output["time_range"]["records"]
    )

    diff_data = snapshot_diff.json()["data"]
    assert diff_data["status"] == "completed"
    diff_output = diff_data["output"]["snapshot_diff"]
    assert diff_output["changes"][0]["path"] == "/devices/ac/state"
    assert diff_output["changes"][0]["recoverable_by_device"] is True
    assert diff_output["physical_change_paths"] == []
