import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request

from arvuno_core import __version__
from arvuno_core.api.security import require_api_token
from arvuno_core.config import Settings
from arvuno_core.devices.interface import DeviceAdapter
from arvuno_core.devices.models import AdapterHealth
from arvuno_core.events.service import EventQueryService
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.schemas.console import SystemStatusData, SystemStatusDataWrapper
from arvuno_core.schemas.events import EventItem

router = APIRouter(prefix="/api/system", tags=["System"], dependencies=[Depends(require_api_token)])


def get_console_settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        raise RuntimeError("The application settings are unavailable.")
    return settings


def _event_item(payload: object) -> EventItem:
    event = payload  # type: ignore[assignment]
    return EventItem(
        id=event.id,
        event_type=event.event_type.value,
        source=event.source.value,
        subject_type=event.subject_type,
        subject_id=event.subject_id,
        payload=event.payload.model_dump(mode="json"),
        correlation_id=event.correlation_id,
        occurred_at=event.occurred_at,
        created_at=event.created_at,
    )


def _database_available(factory: Callable[[], SqlAlchemyUnitOfWork]) -> bool:
    try:
        with factory() as unit_of_work:
            if unit_of_work.system_settings is None:
                return False
            unit_of_work.system_settings.get_by_key("web_console")
            return True
    except Exception:
        return False


def _active_task_count(factory: Callable[[], SqlAlchemyUnitOfWork]) -> int:
    with factory() as unit_of_work:
        if unit_of_work.tasks is None:
            raise RuntimeError("The task repository is unavailable.")
        return unit_of_work.tasks.count_active()


async def _adapter_health(adapter: DeviceAdapter | None) -> AdapterHealth:
    if adapter is None:
        return AdapterHealth(
            status="disconnected",
            adapter_id="home_assistant",
            detail="Home Assistant is not configured.",
        )
    try:
        return await adapter.health_check()
    except Exception:
        return AdapterHealth(
            status="degraded",
            adapter_id=adapter.adapter_id,
            detail="The adapter health check failed.",
        )


@router.get("/status", response_model=SystemStatusDataWrapper)
async def get_system_status(request: Request) -> SystemStatusDataWrapper:
    settings = request.app.state.settings
    factory = request.app.state.unit_of_work_factory
    if not isinstance(settings, Settings) or not callable(factory):
        raise RuntimeError("The system status dependencies are unavailable.")

    database_ok, active_task_count = await asyncio.gather(
        asyncio.to_thread(_database_available, factory),
        asyncio.to_thread(_active_task_count, factory),
    )
    adapters = [
        await _adapter_health(getattr(request.app.state, "mock_device_adapter", None)),
        await _adapter_health(getattr(request.app.state, "home_assistant_adapter", None)),
    ]
    device_service = request.app.state.device_service
    devices = await device_service.list_devices()
    recent_errors = await EventQueryService(factory).list(
        event_type="task_failed",
        page=1,
        page_size=5,
    )
    return SystemStatusDataWrapper(
        data=SystemStatusData(
            version=__version__,
            environment=settings.environment,
            database="ok" if database_ok else "error",
            adapters=adapters,
            device_count=len(devices),
            online_device_count=sum(device.is_online for device in devices),
            active_task_count=active_task_count,
            recent_error_events=[_event_item(event) for event in recent_errors.items],
            checked_at=datetime.now(UTC),
        )
    )


__all__ = ["router"]
