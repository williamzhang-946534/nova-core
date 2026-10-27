from collections.abc import Awaitable, Callable
from typing import Protocol

from nova_core.devices.models import (
    ActionResult,
    AdapterHealth,
    Device,
    DeviceAction,
    DeviceEvent,
    DeviceState,
)

DeviceEventSubscriber = Callable[[DeviceEvent], Awaitable[None]]


class SubscriptionHandle:
    """Removes a subscriber when the adapter subscription is closed."""

    def __init__(self, close_callback: Callable[[], None]) -> None:
        self._close_callback = close_callback
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._close_callback()


class DeviceAdapter(Protocol):
    adapter_id: str
    version: str

    async def health_check(self) -> AdapterHealth: ...

    async def get_devices(self) -> list[Device]: ...

    async def get_device(self, external_id: str) -> Device: ...

    async def get_state(self, external_id: str) -> DeviceState: ...

    async def execute_action(
        self,
        external_id: str,
        action: DeviceAction,
    ) -> ActionResult: ...

    async def subscribe_events(
        self,
        subscriber: DeviceEventSubscriber,
    ) -> SubscriptionHandle: ...
