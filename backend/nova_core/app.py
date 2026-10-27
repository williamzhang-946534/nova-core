import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nova_core import __version__
from nova_core.api.events import router as events_router
from nova_core.api.health import router as health_router
from nova_core.config import Settings, get_settings
from nova_core.environment.context import EnvironmentContextService
from nova_core.errors import ErrorResponse, NovaError
from nova_core.events.bus import EventBus
from nova_core.events.models import NovaEventType
from nova_core.logging_config import correlation_id_var
from nova_core.persistence.database import DatabaseManager
from nova_core.persistence.unit_of_work import SqlAlchemyUnitOfWork

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("nova_backend_started", extra={"version": __version__})
    if getattr(app.state, "initialize_event_runtime", False):
        environment_context = app.state.environment_context
        await environment_context.initialize()
    yield
    manager = getattr(app.state, "database_manager", None)
    if manager is not None:
        manager.dispose()
    logger.info("nova_backend_stopped")


def create_app(
    settings: Settings | None = None,
    *,
    unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork] | None = None,
    initialize_event_runtime: bool = False,
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
    )
    app.include_router(health_router)
    app.include_router(events_router)

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
