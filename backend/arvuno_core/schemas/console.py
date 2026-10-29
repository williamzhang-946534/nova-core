from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from arvuno_core.devices.models import AdapterHealth
from arvuno_core.devices.registry import RegisteredDevice, RegisteredDeviceState
from arvuno_core.environment.context import EnvironmentContextState
from arvuno_core.schemas.events import EventItem


class DeviceListData(BaseModel):
    data: list[RegisteredDevice]
    page: int
    page_size: int
    total: int


class DeviceDetailData(BaseModel):
    device: RegisteredDevice
    latest_state: RegisteredDeviceState | None = None
    recent_events: list[EventItem] = Field(default_factory=list)


class DeviceDetailDataWrapper(BaseModel):
    data: DeviceDetailData


class DeviceStateData(BaseModel):
    device_id: str
    external_id: str
    state: str
    attributes: dict[str, Any]
    raw_state: str | None = None
    observed_at: datetime
    verified: bool
    from_cache: bool = False


class DeviceStateDataWrapper(BaseModel):
    data: DeviceStateData


class EnvironmentSummary(BaseModel):
    environment: EnvironmentContextState
    areas: dict[str, dict[str, int | list[str]]]
    online_device_count: int
    unavailable_device_ids: list[str]
    active_task_count: int
    recent_events: list[EventItem]


class EnvironmentDataWrapper(BaseModel):
    data: EnvironmentSummary


class EnvironmentSnapshotItem(BaseModel):
    id: str
    environment_id: str
    context: dict[str, Any]
    active_task_ids: list[str]
    anomaly_count: int
    created_at: datetime


class EnvironmentSnapshotListData(BaseModel):
    data: list[EnvironmentSnapshotItem]
    page: int
    page_size: int
    total: int


class SystemStatusData(BaseModel):
    version: str
    environment: str
    database: Literal["ok", "error"]
    adapters: list[AdapterHealth]
    device_count: int
    online_device_count: int
    active_task_count: int
    recent_error_events: list[EventItem]
    checked_at: datetime


class SystemStatusDataWrapper(BaseModel):
    data: SystemStatusData


class RuntimeSettingsData(BaseModel):
    app_name: str
    environment: str
    ai_provider: Literal["mock", "openai_compatible"]
    home_assistant_configured: bool
    home_assistant_write_enabled: bool
    home_assistant_entity_limit: int
    device_poll_interval_seconds: int
    event_retention_days: int
    diagnostic_event_retention_days: int
    default_environment_name: str


class WebConsoleSettingsData(BaseModel):
    event_poll_interval_seconds: int = Field(default=10, ge=2, le=300)


class SystemSettingsData(BaseModel):
    runtime: RuntimeSettingsData
    web_console: WebConsoleSettingsData


class SystemSettingsDataWrapper(BaseModel):
    data: SystemSettingsData


class SystemSettingsUpdateRequest(BaseModel):
    web_console: WebConsoleSettingsData


__all__ = [
    "DeviceDetailData",
    "DeviceDetailDataWrapper",
    "DeviceListData",
    "DeviceStateData",
    "DeviceStateDataWrapper",
    "EnvironmentDataWrapper",
    "EnvironmentSnapshotItem",
    "EnvironmentSnapshotListData",
    "EnvironmentSummary",
    "RuntimeSettingsData",
    "SystemSettingsData",
    "SystemSettingsDataWrapper",
    "SystemSettingsUpdateRequest",
    "SystemStatusData",
    "SystemStatusDataWrapper",
    "WebConsoleSettingsData",
]
