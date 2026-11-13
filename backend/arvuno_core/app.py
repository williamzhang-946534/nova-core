import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import SecretStr

from arvuno_core import __version__
from arvuno_core.agent_runtime.models import AgentEnvironmentSnapshot, AgentSpaceSummary
from arvuno_core.agent_runtime.runtime import AgentRuntime
from arvuno_core.ai.mock import MockAIProvider
from arvuno_core.ai.openai_compatible import (
    OpenAICompatibleProvider,
    OpenAICompatibleProviderConfig,
)
from arvuno_core.ai.provider import AIProvider
from arvuno_core.api.agent import router as agent_router
from arvuno_core.api.automations import router as automations_router
from arvuno_core.api.devices import router as devices_router
from arvuno_core.api.environment import router as environment_router
from arvuno_core.api.events import router as events_router
from arvuno_core.api.health import router as health_router
from arvuno_core.api.history import router as history_router
from arvuno_core.api.memory import (
    preference_router as memory_preference_router,
)
from arvuno_core.api.memory import (
    retrieval_router as memory_retrieval_router,
)
from arvuno_core.api.memory import (
    router as memory_router,
)
from arvuno_core.api.multimodal import router as multimodal_router
from arvuno_core.api.observations import router as observations_router
from arvuno_core.api.observations import source_router as observation_sources_router
from arvuno_core.api.perception import router as perception_router
from arvuno_core.api.planning import router as planning_router
from arvuno_core.api.privacy import router as privacy_router
from arvuno_core.api.proactive import router as proactive_router
from arvuno_core.api.reasoning import router as reasoning_router
from arvuno_core.api.retention import router as retention_router
from arvuno_core.api.robot_perception import router as robot_perception_router
from arvuno_core.api.robots import router as robots_router
from arvuno_core.api.settings import router as settings_router
from arvuno_core.api.spaces import device_router as space_device_router
from arvuno_core.api.spaces import router as spaces_router
from arvuno_core.api.state_estimates import router as state_estimates_router
from arvuno_core.api.system import router as system_router
from arvuno_core.api.tasks import router as tasks_router
from arvuno_core.api.tools import router as tools_router
from arvuno_core.api.voice import router as voice_router
from arvuno_core.automation.notifications import NotificationService
from arvuno_core.automation.service import AutomationService
from arvuno_core.config import Settings, get_settings
from arvuno_core.devices.errors import (
    AdapterTimeoutError,
    DeviceError,
    DeviceNotFoundError,
)
from arvuno_core.devices.home_assistant import HomeAssistantAdapter
from arvuno_core.devices.mock import MockDeviceAdapter
from arvuno_core.devices.polling_runtime import DevicePollingRuntime
from arvuno_core.devices.registry import DeviceRegistry
from arvuno_core.devices.service import DeviceApplicationService
from arvuno_core.environment.context import EnvironmentContextService
from arvuno_core.environment.context_v2 import EnvironmentContextV2Service
from arvuno_core.environment.query import EnvironmentQueryService
from arvuno_core.environment.reconciliation import EnvironmentReconciler
from arvuno_core.errors import ArvunoError, ErrorResponse
from arvuno_core.estimation.service import StateEstimationService
from arvuno_core.events.bus import EventBus
from arvuno_core.events.models import ArvunoEventType
from arvuno_core.events.service import DeviceEventService, EventQueryService
from arvuno_core.history.service import HistoryService
from arvuno_core.logging_config import correlation_id_var
from arvuno_core.memory.service import MemoryService
from arvuno_core.multimodal.service import MultimodalService
from arvuno_core.observations.pipeline import ObservationPipeline
from arvuno_core.observations.service import ObservationService
from arvuno_core.perception.robot_mobile import RobotMobilePerceptionService
from arvuno_core.perception.service import ActivePerceptionService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.provider_logs import SqlProviderLogStore
from arvuno_core.persistence.tools import SqlToolExecutionStore
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.planning.service import PlanningService
from arvuno_core.privacy.service import PrivacyService
from arvuno_core.proactive.service import ProactiveService
from arvuno_core.reasoning.service import ReasoningService
from arvuno_core.retention.service import build_retention_scheduler
from arvuno_core.robots.registry import RobotRegistry
from arvuno_core.robots.service import RobotApplicationService
from arvuno_core.robots.simulator import DesktopRobotFirmwareSimulatorAdapter
from arvuno_core.schemas.memory import MemoryRetrievalRequest
from arvuno_core.spatial.service import SpatialService
from arvuno_core.tasks.service import TaskService
from arvuno_core.tools.catalog import RegistryToolCatalog
from arvuno_core.tools.confirmation import ConfirmationService
from arvuno_core.tools.executor import ToolExecutor
from arvuno_core.tools.models import (
    HistoryQueryInput,
    HistoryQueryOperation,
    HistoryQueryOutput,
    MemoryRetrievalInput,
)
from arvuno_core.tools.registry import build_default_tool_registry
from arvuno_core.tools.safety import SafetyPolicy

logger = logging.getLogger(__name__)


async def _start_device_polling(
    app: FastAPI,
    device_registry: DeviceRegistry,
) -> DevicePollingRuntime:
    app_settings: Settings = app.state.settings
    adapters = app.state.device_polling_adapters
    external_ids: dict[str, list[str]] = {}
    for adapter_id, adapter in adapters.items():
        if adapter_id == "home_assistant":
            external_ids[adapter_id] = list(app_settings.home_assistant_allowed_entity_ids)
        else:
            external_ids[adapter_id] = [
                device.external_id for device in await adapter.get_devices()
            ]
    runtime = DevicePollingRuntime(
        EnvironmentReconciler(
            device_registry,
            DeviceEventService(device_registry, app.state.event_bus),
            app.state.observation_pipeline,
        ),
        adapters,
        external_ids,
        interval_seconds=float(app_settings.device_poll_interval_seconds),
    )
    runtime.start()
    logger.info(
        "device_polling_started",
        extra={
            "payload": {
                "adapters": sorted(adapters),
                "interval_seconds": app_settings.device_poll_interval_seconds,
            }
        },
    )
    return runtime


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("arvuno_backend_started", extra={"version": __version__})
    if getattr(app.state, "initialize_tool_runtime", False):
        device_registry = app.state.device_registry
        mock_adapter = app.state.mock_device_adapter
        await app.state.spatial_service.ensure_root()
        mock_sync = await device_registry.sync_devices(mock_adapter)
        try:
            await app.state.observation_pipeline.ingest_states(
                adapter_id=mock_adapter.adapter_id,
                states=list(mock_sync.states),
            )
        except Exception:
            logger.exception("mock_observation_ingestion_failed")
        home_assistant_adapter = getattr(app.state, "home_assistant_adapter", None)
        if home_assistant_adapter is not None:
            try:
                home_assistant_sync = await device_registry.sync_devices(home_assistant_adapter)
                await app.state.observation_pipeline.ingest_states(
                    adapter_id=home_assistant_adapter.adapter_id,
                    states=list(home_assistant_sync.states),
                )
            except Exception:
                logger.exception("home_assistant_projection_sync_failed")
        try:
            await app.state.state_estimation_service.rebuild()
        except Exception:
            logger.exception("startup_state_estimation_rebuild_failed")
        try:
            await app.state.robot_service.sync_robot(
                app.state.robot_simulator_adapter,
                app.state.robot_simulator_adapter.external_id,
            )
        except Exception:
            logger.exception("mock_robot_projection_sync_failed")
        if getattr(app.state, "start_device_polling", False):
            runtime = await _start_device_polling(app, device_registry)
            app.state.device_polling_runtime = runtime
    if getattr(app.state, "initialize_event_runtime", False):
        environment_context = app.state.environment_context
        await environment_context.initialize()
        await environment_context.synchronize_with_registry()
    try:
        recovery = await app.state.task_service.recover_tasks()
        logger.info(
            "task_startup_recovery_completed",
            extra={
                "payload": {
                    "resumed": len(recovery.resumed_task_ids),
                    "waiting_cancelled": len(recovery.waiting_cancelled_task_ids),
                    "unknown": len(recovery.unknown_task_ids),
                    "expired": len(recovery.timed_out_task_ids),
                }
            },
        )
    except Exception:
        logger.exception("task_startup_recovery_failed")
    try:
        await app.state.automation_service.recover_interrupted_runs()
    except Exception:
        logger.exception("automation_startup_recovery_failed")
    if getattr(app.state, "initialize_tool_runtime", False):
        await app.state.multimodal_service.initialize_catalog()
    retention_scheduler = getattr(app.state, "retention_scheduler", None)
    if retention_scheduler is not None and app.state.settings.retention_scheduler_enabled:
        retention_scheduler.start()
        logger.info("retention_scheduler_started")
    yield
    try:
        async with asyncio.timeout(app.state.settings.event_subscriber_timeout_seconds):
            await app.state.automation_service.wait_for_background_work()
    except TimeoutError:
        logger.warning("automation_background_work_cancelled_at_shutdown")
    retention_scheduler = getattr(app.state, "retention_scheduler", None)
    if retention_scheduler is not None:
        await retention_scheduler.stop()
    runtime = getattr(app.state, "device_polling_runtime", None)
    if runtime is not None:
        await runtime.stop()
    provider = getattr(app.state, "ai_provider", None)
    if provider is not None:
        await provider.aclose()
    home_assistant_adapter = getattr(app.state, "home_assistant_adapter", None)
    if home_assistant_adapter is not None:
        await home_assistant_adapter.close()
    manager = getattr(app.state, "database_manager", None)
    if manager is not None:
        manager.dispose()
    logger.info("arvuno_backend_stopped")


def create_app(
    settings: Settings | None = None,
    *,
    unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork] | None = None,
    ai_provider: AIProvider | None = None,
    initialize_event_runtime: bool = False,
    initialize_tool_runtime: bool = False,
    start_device_polling: bool = False,
) -> FastAPI:
    app_settings = settings or get_settings()
    database_manager: DatabaseManager | None = None
    if unit_of_work_factory is None:
        database_manager = DatabaseManager(app_settings)
        manager = database_manager

        def default_unit_of_work() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(manager.session_factory)

        unit_of_work_factory = default_unit_of_work

    app = FastAPI(
        title=app_settings.app_name,
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.unit_of_work_factory = unit_of_work_factory
    app.state.database_manager = database_manager
    event_bus = EventBus(
        unit_of_work_factory,
        subscriber_timeout_seconds=app_settings.event_subscriber_timeout_seconds,
    )
    app.state.event_bus = event_bus
    mock_adapter = MockDeviceAdapter()
    device_registry = DeviceRegistry(unit_of_work_factory)
    environment_context = EnvironmentContextService(
        unit_of_work_factory,
        registry=device_registry,
        environment_name=app_settings.default_environment_name,
    )
    event_bus.subscribe(
        environment_context.handle_event,
        event_types={
            ArvunoEventType.DEVICE_STATE_CHANGED.value,
            ArvunoEventType.SENSOR_UPDATED.value,
            ArvunoEventType.DEVICE_UNAVAILABLE.value,
        },
    )
    app.state.environment_context = environment_context
    spatial_service = SpatialService(
        unit_of_work_factory,
        environment_name=app_settings.default_environment_name,
    )
    app.state.spatial_service = spatial_service
    observation_service = ObservationService(unit_of_work_factory)
    app.state.observation_service = observation_service
    app.state.multimodal_service = MultimodalService(
        unit_of_work_factory,
        observation_service,
        app_settings,
    )
    state_estimation_service = StateEstimationService(
        unit_of_work_factory,
        environment_name=app_settings.default_environment_name,
    )
    app.state.state_estimation_service = state_estimation_service
    app.state.environment_context_v2 = EnvironmentContextV2Service(
        unit_of_work_factory,
        state_estimation_service,
    )
    environment_query_service = EnvironmentQueryService(
        unit_of_work_factory,
        state_estimation_service,
        environment_name=app_settings.default_environment_name,
    )
    app.state.environment_query_service = environment_query_service

    async def rebuild_after_observations(received_at: object) -> None:
        await state_estimation_service.rebuild(
            received_at if isinstance(received_at, datetime) else None
        )

    observation_pipeline = ObservationPipeline(
        unit_of_work_factory,
        observation_service,
        estimation_callback=rebuild_after_observations,
    )
    app.state.observation_pipeline = observation_pipeline
    app.state.initialize_event_runtime = initialize_event_runtime
    home_assistant_adapter: HomeAssistantAdapter | None = None
    if (
        app_settings.home_assistant_url is not None
        and app_settings.home_assistant_token is not None
        and app_settings.home_assistant_allowed_entity_ids
    ):
        home_assistant_adapter = HomeAssistantAdapter(app_settings)
    device_service = DeviceApplicationService(
        device_registry,
        {
            adapter.adapter_id: adapter
            for adapter in (mock_adapter, home_assistant_adapter)
            if adapter is not None
        },
        observation_pipeline,
    )
    memory_service = MemoryService(unit_of_work_factory)
    history_service = HistoryService(
        unit_of_work_factory,
        environment_name=app_settings.default_environment_name,
    )
    provider_log_store = SqlProviderLogStore(unit_of_work_factory)
    candidate_ai_provider = (
        ai_provider
        if ai_provider is not None or app_settings.ai_provider == "openai_compatible"
        else None
    )
    if ai_provider is None:
        if app_settings.ai_provider == "openai_compatible":
            ai_provider = OpenAICompatibleProvider(
                OpenAICompatibleProviderConfig(
                    base_url=app_settings.ai_base_url or "",
                    model=app_settings.ai_model or "",
                    api_key=app_settings.ai_api_key or SecretStr(""),
                    timeout_seconds=app_settings.ai_timeout_seconds,
                    max_retries=app_settings.ai_max_retries,
                    structured_output_mode=app_settings.ai_structured_output_mode,
                    retry_backoff_seconds=app_settings.ai_retry_backoff_seconds,
                    debug_logging=app_settings.ai_provider_debug_logging,
                    debug_logging_ttl_seconds=app_settings.ai_provider_debug_logging_ttl_seconds,
                ),
                provider_log_store,
            )
        else:
            ai_provider = MockAIProvider(
                provider_log_store,
                debug_logging=app_settings.ai_provider_debug_logging,
                debug_logging_ttl_seconds=app_settings.ai_provider_debug_logging_ttl_seconds,
            )
    reasoning_service = ReasoningService(
        unit_of_work_factory,
        environment_name=app_settings.default_environment_name,
        ai_provider=candidate_ai_provider,
    )
    app.state.memory_service = memory_service
    app.state.history_service = history_service
    app.state.reasoning_service = reasoning_service

    async def retrieve_memory(request: MemoryRetrievalInput):
        return await memory_service.retrieve(
            MemoryRetrievalRequest(
                question_type=request.question_type,
                query=request.query,
            )
        )

    async def query_history(request: HistoryQueryInput) -> HistoryQueryOutput:
        result: HistoryQueryOutput
        if request.operation is HistoryQueryOperation.ASK:
            assert request.query is not None
            result = HistoryQueryOutput(
                service_available=True,
                operation=request.operation,
                natural_history=await history_service.ask(
                    request.query,
                    timezone=request.timezone,
                    now=request.now,
                ),
            )
        elif request.operation is HistoryQueryOperation.TIME_RANGE:
            assert request.start_time is not None
            assert request.end_time is not None
            result = HistoryQueryOutput(
                service_available=True,
                operation=request.operation,
                time_range=await history_service.time_range(
                    start_time=request.start_time,
                    end_time=request.end_time,
                    timezone=request.timezone,
                    entity_id=request.entity_id,
                    space_id=request.space_id,
                    include_descendants=request.include_descendants,
                    attribute=request.attribute,
                    quality_status=request.quality_status,
                    expected_interval_seconds=request.expected_interval_seconds,
                    limit=request.limit,
                ),
            )
        elif request.operation is HistoryQueryOperation.SPATIAL_HISTORY:
            assert request.space_id is not None
            assert request.start_time is not None
            assert request.end_time is not None
            result = HistoryQueryOutput(
                service_available=True,
                operation=request.operation,
                spatial_history=await history_service.spatial_history(
                    request.space_id,
                    start_time=request.start_time,
                    end_time=request.end_time,
                    timezone=request.timezone,
                    include_descendants=request.include_descendants,
                    attribute=request.attribute,
                    expected_interval_seconds=request.expected_interval_seconds,
                    limit=request.limit,
                ),
            )
        elif request.operation is HistoryQueryOperation.ENTITY_HISTORY:
            assert request.entity_id is not None
            assert request.start_time is not None
            assert request.end_time is not None
            result = HistoryQueryOutput(
                service_available=True,
                operation=request.operation,
                entity_history=await history_service.entity_history(
                    request.entity_id,
                    start_time=request.start_time,
                    end_time=request.end_time,
                    timezone=request.timezone,
                    attribute=request.attribute,
                    expected_interval_seconds=request.expected_interval_seconds,
                    limit=request.limit,
                ),
            )
        elif request.operation is HistoryQueryOperation.TRENDS:
            assert request.attribute is not None
            assert request.start_time is not None
            assert request.end_time is not None
            result = HistoryQueryOutput(
                service_available=True,
                operation=request.operation,
                trends=await history_service.trends(
                    start_time=request.start_time,
                    end_time=request.end_time,
                    attribute=request.attribute,
                    timezone=request.timezone,
                    group_by=request.group_by,
                    space_id=request.space_id,
                    entity_id=request.entity_id,
                    include_descendants=request.include_descendants,
                    limit=request.limit,
                ),
            )
        elif request.operation is HistoryQueryOperation.SNAPSHOT_AT:
            assert request.at_time is not None
            result = HistoryQueryOutput(
                service_available=True,
                operation=request.operation,
                snapshot=await history_service.snapshot_at(
                    at_time=request.at_time,
                    timezone=request.timezone,
                    environment_id=request.environment_id,
                    nearest=request.nearest,
                ),
            )
        elif request.operation is HistoryQueryOperation.SNAPSHOT_DIFF:
            result = HistoryQueryOutput(
                service_available=True,
                operation=request.operation,
                snapshot_diff=await history_service.snapshot_diff(
                    baseline_id=request.baseline_id,
                    target_id=request.target_id,
                    baseline_at=request.baseline_at,
                    target_at=request.target_at,
                    timezone=request.timezone,
                ),
            )
        else:
            assert request.record_type is not None
            assert request.record_id is not None
            result = HistoryQueryOutput(
                service_available=True,
                operation=request.operation,
                correlation=await history_service.correlate(
                    record_type=request.record_type,
                    record_id=request.record_id,
                    timezone=request.timezone,
                ),
            )
        return result

    robot_simulator_adapter = DesktopRobotFirmwareSimulatorAdapter(
        profile=app_settings.robot_profile,
    )
    robot_registry = RobotRegistry(unit_of_work_factory)
    robot_service = RobotApplicationService(
        robot_registry,
        {robot_simulator_adapter.adapter_id: robot_simulator_adapter},
        unit_of_work_factory=unit_of_work_factory,
        event_publisher=event_bus,
        heartbeat_timeout_seconds=app_settings.robot_heartbeat_timeout_seconds,
    )
    tool_registry = build_default_tool_registry(
        device_service,
        environment_query_provider=environment_query_service.query,
        environment_state_sink=environment_context,
        memory_retrieval_provider=retrieve_memory,
        history_query_provider=query_history,
        event_query_provider=EventQueryService(unit_of_work_factory).query,
        robot_service=robot_service,
        perception_execution_provider=(
            lambda request_id: app.state.perception_service.execute(
                request_id,
                getattr(app.state, "perception_observer", None),
            )
        ),
    )
    tool_executor = ToolExecutor(
        registry=tool_registry,
        safety_policy=SafetyPolicy(
            device_service,
            tool_permissions=app_settings.tool_permissions,
            robot_reader=robot_service,
        ),
        confirmation_service=ConfirmationService(
            ttl_seconds=app_settings.tool_confirmation_ttl_seconds,
        ),
        execution_store=SqlToolExecutionStore(unit_of_work_factory),
        event_publisher=event_bus,
        procedure_validation_recorder=memory_service,
    )
    app.state.mock_device_adapter = mock_adapter
    app.state.home_assistant_adapter = home_assistant_adapter
    app.state.device_polling_adapters = {
        adapter.adapter_id: adapter
        for adapter in (mock_adapter, home_assistant_adapter)
        if adapter is not None
    }
    app.state.start_device_polling = start_device_polling
    app.state.device_registry = device_registry
    app.state.device_service = device_service
    app.state.tool_registry = tool_registry
    app.state.tool_executor = tool_executor
    app.state.task_service = TaskService(unit_of_work_factory, tool_executor, event_bus)
    notification_service = NotificationService(unit_of_work_factory)
    automation_service = AutomationService(
        unit_of_work_factory,
        app.state.task_service,
        event_bus,
    )
    app.state.task_service.lifecycle_observer = automation_service
    event_bus.subscribe(
        automation_service.handle_event_scheduled,
        event_types={
            ArvunoEventType.DEVICE_STATE_CHANGED.value,
            ArvunoEventType.SENSOR_UPDATED.value,
            ArvunoEventType.DEVICE_UNAVAILABLE.value,
        },
    )
    event_bus.subscribe(
        notification_service.handle_task_failed,
        event_types={ArvunoEventType.TASK_FAILED.value},
    )
    app.state.automation_service = automation_service
    app.state.notification_service = notification_service
    app.state.planning_service = PlanningService(
        unit_of_work_factory,
        RegistryToolCatalog(tool_registry, permissions=app_settings.tool_permissions),
        app.state.task_service,
        device_service,
        environment_name=app_settings.default_environment_name,
        ai_provider=candidate_ai_provider,
    )
    app.state.proactive_service = ProactiveService(
        unit_of_work_factory,
        notification_service,
        environment_name=app_settings.default_environment_name,
        default_autonomy_level=2,
        max_autonomy_level=2,
        planning_service=app.state.planning_service,
    )
    app.state.perception_service = ActivePerceptionService(
        unit_of_work_factory,
        observation_service,
        state_estimation_service,
        reasoning_service,
        environment_name=app_settings.default_environment_name,
    )
    app.state.perception_observer = None
    app.state.robot_simulator_adapter = robot_simulator_adapter
    # Compatibility alias for existing integration tests and local tooling.
    app.state.mock_robot_adapter = robot_simulator_adapter
    app.state.robot_registry = robot_registry
    app.state.robot_service = robot_service
    app.state.robot_mobile_perception_service = RobotMobilePerceptionService(
        app.state.perception_service,
        app.state.robot_service,
        observation_service,
        unit_of_work_factory,
        environment_name=app_settings.default_environment_name,
    )
    event_bus.subscribe(
        app.state.proactive_service.handle_event,
        event_types={
            ArvunoEventType.SENSOR_UPDATED.value,
            ArvunoEventType.DEVICE_UNAVAILABLE.value,
            ArvunoEventType.TASK_FAILED.value,
        },
    )
    app.state.initialize_tool_runtime = initialize_tool_runtime
    app.state.retention_scheduler = build_retention_scheduler(
        settings=app_settings,
        unit_of_work_factory=unit_of_work_factory,
        observation_pipeline=observation_pipeline,
        multimodal_service=app.state.multimodal_service,
        proactive_service=app.state.proactive_service,
        provider_log_store=provider_log_store,
    )
    app.state.privacy_service = PrivacyService(
        unit_of_work_factory,
        app_settings.resolved_data_dir / "media" / "multimodal",
        event_bus,
    )

    async def environment_snapshot() -> AgentEnvironmentSnapshot:
        state = environment_context.state
        try:
            spaces = await spatial_service.list_spaces(status="active")
            space_catalog = [
                AgentSpaceSummary(
                    space_id=space.id,
                    parent_id=space.parent_id,
                    space_type=space.space_type,
                    name=space.name,
                    path=space.path,
                    status=space.status,
                )
                for space in spaces
            ]
        except Exception:
            logger.exception("agent_space_catalog_unavailable")
            space_catalog = []
        return AgentEnvironmentSnapshot(
            environment_name=state.environment_name,
            updated_at=state.updated_at,
            spaces=space_catalog,
        )

    agent_runtime = AgentRuntime(
        provider=ai_provider,
        task_system=app.state.task_service,
        tool_catalog=RegistryToolCatalog(
            tool_registry,
            permissions=app_settings.tool_permissions,
        ),
        environment_provider=environment_snapshot,
        task_timeout_seconds=60.0,
    )
    app.state.ai_provider = ai_provider
    app.state.agent_runtime = agent_runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
    )
    app.include_router(health_router)
    app.include_router(system_router)
    app.include_router(devices_router)
    app.include_router(spaces_router)
    app.include_router(space_device_router)
    app.include_router(observations_router)
    app.include_router(observation_sources_router)
    app.include_router(state_estimates_router)
    app.include_router(environment_router)
    app.include_router(events_router)
    app.include_router(tools_router)
    app.include_router(tasks_router)
    app.include_router(agent_router)
    app.include_router(voice_router)
    app.include_router(settings_router)
    app.include_router(automations_router)
    app.include_router(memory_router)
    app.include_router(memory_retrieval_router)
    app.include_router(memory_preference_router)
    app.include_router(multimodal_router)
    app.include_router(history_router)
    app.include_router(reasoning_router)
    app.include_router(robots_router)
    app.include_router(robot_perception_router)
    app.include_router(retention_router)
    app.include_router(privacy_router)
    app.include_router(planning_router)
    app.include_router(proactive_router)
    app.include_router(perception_router)

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next: Any) -> Any:
        incoming_id = request.headers.get("X-Correlation-ID")
        request_id = incoming_id or str(uuid.uuid4())
        correlation_id_var.set(request_id)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request_id
        logger.info(
            "http_request",
            extra={
                "http_method": request.method,
                "http_path": request.url.path,
                "status_code": response.status_code,
            },
        )
        return response

    @app.exception_handler(ArvunoError)
    async def handle_arvuno_error(request: Request, exc: ArvunoError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error={
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "correlation_id": correlation_id_var.get(),
                }
            ).model_dump(),
        )

    @app.exception_handler(DeviceError)
    async def handle_device_error(request: Request, exc: DeviceError) -> JSONResponse:
        if isinstance(exc, DeviceNotFoundError):
            status_code = 404
            code = "NOT_FOUND"
        elif isinstance(exc, AdapterTimeoutError):
            status_code = 504
            code = "ADAPTER_TIMEOUT"
        else:
            status_code = 502
            code = "ADAPTER_ERROR"
        return JSONResponse(
            status_code=status_code,
            content=ErrorResponse(
                error={
                    "code": code,
                    "message": str(exc),
                    "details": {"device_code": exc.code, "detail": exc.detail},
                    "correlation_id": correlation_id_var.get(),
                }
            ).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors: list[dict[str, Any]] = []
        for error in exc.errors():
            errors.append(
                {
                    "location": list(error.get("loc", [])),
                    "message": error.get("msg", "Invalid request."),
                    "type": error.get("type", "value_error"),
                }
            )
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error={
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed.",
                    "details": {"errors": errors},
                    "correlation_id": correlation_id_var.get(),
                }
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception")
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error={
                    "code": "INTERNAL_ERROR",
                    "message": "An internal server error occurred.",
                    "details": {},
                    "correlation_id": correlation_id_var.get(),
                }
            ).model_dump(),
        )

    return app
