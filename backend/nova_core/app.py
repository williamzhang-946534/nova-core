import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import SecretStr

from nova_core import __version__
from nova_core.agent_runtime.models import AgentEnvironmentSnapshot
from nova_core.agent_runtime.runtime import AgentRuntime
from nova_core.ai.mock import MockAIProvider
from nova_core.ai.openai_compatible import (
    OpenAICompatibleProvider,
    OpenAICompatibleProviderConfig,
)
from nova_core.ai.provider import AIProvider
from nova_core.api.agent import router as agent_router
from nova_core.api.events import router as events_router
from nova_core.api.health import router as health_router
from nova_core.api.tasks import router as tasks_router
from nova_core.api.tools import router as tools_router
from nova_core.config import Settings, get_settings
from nova_core.devices.home_assistant import HomeAssistantAdapter
from nova_core.devices.mock import MockDeviceAdapter
from nova_core.devices.registry import DeviceRegistry
from nova_core.devices.service import DeviceApplicationService
from nova_core.environment.context import EnvironmentContextService, area_summary
from nova_core.errors import ErrorResponse, NovaError
from nova_core.events.bus import EventBus
from nova_core.events.models import NovaEventType
from nova_core.logging_config import correlation_id_var
from nova_core.persistence.database import DatabaseManager
from nova_core.persistence.provider_logs import SqlProviderLogStore
from nova_core.persistence.tools import SqlToolExecutionStore
from nova_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from nova_core.tasks.service import TaskService
from nova_core.tools.catalog import RegistryToolCatalog
from nova_core.tools.confirmation import ConfirmationService
from nova_core.tools.executor import ToolExecutor
from nova_core.tools.registry import build_default_tool_registry
from nova_core.tools.safety import SafetyPolicy

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("nova_backend_started", extra={"version": __version__})
    if getattr(app.state, "initialize_event_runtime", False):
        environment_context = app.state.environment_context
        await environment_context.initialize()
    if getattr(app.state, "initialize_tool_runtime", False):
        device_registry = app.state.device_registry
        mock_adapter = app.state.mock_device_adapter
        await device_registry.sync_devices(mock_adapter)
        home_assistant_adapter = getattr(app.state, "home_assistant_adapter", None)
        if home_assistant_adapter is not None:
            try:
                await device_registry.sync_devices(home_assistant_adapter)
            except Exception:
                logger.exception("home_assistant_projection_sync_failed")
    yield
    provider = getattr(app.state, "ai_provider", None)
    if provider is not None:
        await provider.aclose()
    home_assistant_adapter = getattr(app.state, "home_assistant_adapter", None)
    if home_assistant_adapter is not None:
        await home_assistant_adapter.close()
    manager = getattr(app.state, "database_manager", None)
    if manager is not None:
        manager.dispose()
    logger.info("nova_backend_stopped")


def create_app(
    settings: Settings | None = None,
    *,
    unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork] | None = None,
    ai_provider: AIProvider | None = None,
    initialize_event_runtime: bool = False,
    initialize_tool_runtime: bool = False,
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
    event_bus = EventBus(unit_of_work_factory)
    environment_context = EnvironmentContextService(
        unit_of_work_factory,
        environment_name=app_settings.default_environment_name,
    )
    event_bus.subscribe(
        environment_context.handle_event,
        event_types={
            NovaEventType.DEVICE_STATE_CHANGED.value,
            NovaEventType.SENSOR_UPDATED.value,
            NovaEventType.DEVICE_UNAVAILABLE.value,
        },
    )
    app.state.event_bus = event_bus
    app.state.environment_context = environment_context
    app.state.initialize_event_runtime = initialize_event_runtime
    mock_adapter = MockDeviceAdapter()
    device_registry = DeviceRegistry(unit_of_work_factory)
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
    )
    tool_registry = build_default_tool_registry(
        device_service,
        environment_state_provider=lambda: environment_context.state,
    )
    tool_executor = ToolExecutor(
        registry=tool_registry,
        safety_policy=SafetyPolicy(
            device_service,
            tool_permissions=app_settings.tool_permissions,
        ),
        confirmation_service=ConfirmationService(
            ttl_seconds=app_settings.tool_confirmation_ttl_seconds,
        ),
        execution_store=SqlToolExecutionStore(unit_of_work_factory),
        event_publisher=event_bus,
    )
    app.state.mock_device_adapter = mock_adapter
    app.state.home_assistant_adapter = home_assistant_adapter
    app.state.device_registry = device_registry
    app.state.device_service = device_service
    app.state.tool_registry = tool_registry
    app.state.tool_executor = tool_executor
    app.state.task_service = TaskService(unit_of_work_factory, tool_executor, event_bus)
    app.state.initialize_tool_runtime = initialize_tool_runtime
    provider_log_store = SqlProviderLogStore(unit_of_work_factory)
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
                ),
                provider_log_store,
            )
        else:
            ai_provider = MockAIProvider(provider_log_store)
    else:
        ai_provider = ai_provider

    async def environment_snapshot() -> AgentEnvironmentSnapshot:
        state = environment_context.state
        return AgentEnvironmentSnapshot(
            environment_name=state.environment_name,
            updated_at=state.updated_at,
            devices=[device.model_dump(mode="json") for device in state.devices.values()],
            sensors=[sensor.model_dump(mode="json") for sensor in state.sensors.values()],
            areas=area_summary(state),
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
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
    )
    app.include_router(health_router)
    app.include_router(events_router)
    app.include_router(tools_router)
    app.include_router(tasks_router)
    app.include_router(agent_router)

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

    @app.exception_handler(NovaError)
    async def handle_nova_error(request: Request, exc: NovaError) -> JSONResponse:
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
