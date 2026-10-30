import asyncio
import contextlib
import logging

from arvuno_core.devices.interface import DeviceAdapter
from arvuno_core.environment.reconciliation import EnvironmentReconciler

logger = logging.getLogger(__name__)


class DevicePollingRuntime:
    """Runs periodic state reconciliation so device events exist outside tests."""

    def __init__(
        self,
        reconciler: EnvironmentReconciler,
        adapters: dict[str, DeviceAdapter],
        external_ids: dict[str, list[str]],
        *,
        interval_seconds: float,
    ) -> None:
        self._reconciler = reconciler
        self._adapters = dict(adapters)
        self._external_ids = {key: list(value) for key, value in external_ids.items()}
        self._interval = max(0.1, float(interval_seconds))
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def poll_once(self) -> None:
        for adapter_id, adapter in self._adapters.items():
            external_ids = self._external_ids.get(adapter_id) or []
            if not external_ids:
                continue
            try:
                result = await self._reconciler.reconcile(adapter, external_ids)
            except Exception:  # pragma: no cover - defensive boundary around external adapters
                logger.exception(
                    "device_poll_failed",
                    extra={"payload": {"adapter_id": adapter_id}},
                )
                continue
            logger.info(
                "device_poll_completed",
                extra={
                    "payload": {
                        "adapter_id": adapter_id,
                        "checked": result.checked,
                        "events_published": result.events_published,
                        "failures": result.failures,
                    }
                },
            )

    async def _run(self) -> None:
        while not self._stop.is_set():
            await self.poll_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                continue

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task


__all__ = ["DevicePollingRuntime"]
