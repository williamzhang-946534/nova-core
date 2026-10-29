import asyncio
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from arvuno_core.api.security import require_api_token
from arvuno_core.api.system import get_console_settings
from arvuno_core.config import Settings
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.schemas.console import (
    RuntimeSettingsData,
    SystemSettingsData,
    SystemSettingsDataWrapper,
    SystemSettingsUpdateRequest,
    WebConsoleSettingsData,
)


def get_unit_of_work_factory(request: Request) -> Callable[[], SqlAlchemyUnitOfWork]:
    factory = getattr(request.app.state, "unit_of_work_factory", None)
    if not callable(factory):
        raise RuntimeError("The database unit-of-work factory is unavailable.")
    return factory


router = APIRouter(
    prefix="/api/settings",
    tags=["Settings"],
    dependencies=[Depends(require_api_token)],
)


def _runtime(settings: Settings) -> RuntimeSettingsData:
    return RuntimeSettingsData(
        app_name=settings.app_name,
        environment=settings.environment,
        ai_provider=settings.ai_provider,
        home_assistant_configured=(
            settings.home_assistant_url is not None
            and settings.home_assistant_token is not None
            and bool(settings.home_assistant_allowed_entity_ids)
        ),
        home_assistant_write_enabled=settings.home_assistant_write_enabled,
        home_assistant_entity_limit=len(settings.home_assistant_allowed_entity_ids),
        device_poll_interval_seconds=settings.device_poll_interval_seconds,
        event_retention_days=settings.event_retention_days,
        diagnostic_event_retention_days=settings.diagnostic_event_retention_days,
        default_environment_name=settings.default_environment_name,
    )


def _read_console_settings(
    factory: Callable[[], SqlAlchemyUnitOfWork],
) -> WebConsoleSettingsData:
    with factory() as unit_of_work:
        if unit_of_work.system_settings is None:
            raise RuntimeError("The system setting repository is unavailable.")
        setting = unit_of_work.system_settings.get_by_key("web_console")
        if setting is None:
            return WebConsoleSettingsData()
        return WebConsoleSettingsData.model_validate(setting.value)


@router.get("", response_model=SystemSettingsDataWrapper)
async def get_settings(
    request: Request,
    settings: Annotated[Settings, Depends(get_console_settings)],
    unit_of_work_factory: Annotated[
        Callable[[], SqlAlchemyUnitOfWork], Depends(get_unit_of_work_factory)
    ],
) -> SystemSettingsDataWrapper:
    console = await asyncio.to_thread(_read_console_settings, unit_of_work_factory)
    return SystemSettingsDataWrapper(
        data=SystemSettingsData(runtime=_runtime(settings), web_console=console)
    )


@router.patch("", response_model=SystemSettingsDataWrapper)
async def update_settings(
    request: SystemSettingsUpdateRequest,
    raw_request: Request,
    settings: Annotated[Settings, Depends(get_console_settings)],
    unit_of_work_factory: Annotated[
        Callable[[], SqlAlchemyUnitOfWork], Depends(get_unit_of_work_factory)
    ],
) -> SystemSettingsDataWrapper:
    def persist() -> None:
        with unit_of_work_factory() as unit_of_work:
            if unit_of_work.system_settings is None:
                raise RuntimeError("The system setting repository is unavailable.")
            unit_of_work.system_settings.upsert_non_sensitive(
                key="web_console",
                value=request.web_console.model_dump(mode="json"),
                value_type="object",
                description="Non-sensitive Web console display preferences.",
            )
            unit_of_work.commit()

    await asyncio.to_thread(persist)
    console = await asyncio.to_thread(_read_console_settings, unit_of_work_factory)
    return SystemSettingsDataWrapper(
        data=SystemSettingsData(runtime=_runtime(settings), web_console=console)
    )


__all__ = ["router"]
