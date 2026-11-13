import asyncio
from collections.abc import Callable
from datetime import datetime

from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.robots.interface import RobotAdapter
from arvuno_core.robots.models import (
    RobotCapability,
    RobotCapabilityName,
    RobotConsent,
    RobotConsentGrant,
    RobotPolicySnapshot,
    RobotStateSnapshot,
    utc_now,
)


class RobotRegistry:
    """Project high-level robot facts into the normal application boundary."""

    def __init__(self, unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def sync_robot(
        self,
        adapter: RobotAdapter,
        external_id: str,
    ) -> None:
        robot = await adapter.get_robot(external_id)
        capabilities = await adapter.get_capabilities(external_id)
        state = await adapter.get_state(external_id)

        def execute() -> None:
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                unit_of_work.robots.upsert_robot(robot, capabilities, state)
                unit_of_work.commit()

        await asyncio.to_thread(execute)

    async def list_robots(self, *, enabled_only: bool = False):
        def execute():
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                return unit_of_work.robots.list(enabled_only=enabled_only)

        return await asyncio.to_thread(execute)

    async def get_robot(self, robot_id: str):
        def execute():
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                return unit_of_work.robots.get(robot_id)

        return await asyncio.to_thread(execute)

    async def set_enabled(self, robot_id: str, *, enabled: bool):
        def execute():
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                robot = unit_of_work.robots.set_enabled(robot_id, enabled=enabled)
                unit_of_work.commit()
                return robot

        return await asyncio.to_thread(execute)

    async def set_capability_governance(
        self,
        robot_id: str,
        capability: RobotCapabilityName,
        *,
        enabled: bool | None = None,
        approved: bool | None = None,
        consent_granted: bool | None = None,
        approved_by: str | None = None,
    ) -> RobotCapability:
        def execute():
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                result = unit_of_work.robots.set_capability_governance(
                    robot_id,
                    capability,
                    enabled=enabled,
                    approved=approved,
                    consent_granted=consent_granted,
                    approved_by=approved_by,
                )
                unit_of_work.commit()
                return result

        return await asyncio.to_thread(execute)

    async def capabilities(self, robot_id: str):
        def execute():
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                return unit_of_work.robots.capabilities(robot_id)

        return await asyncio.to_thread(execute)

    async def find_policy_snapshot(self, robot_id: str) -> RobotPolicySnapshot | None:
        def execute():
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                return unit_of_work.robots.policy_snapshot(robot_id)

        return await asyncio.to_thread(execute)

    async def grant_consent(
        self,
        robot_id: str,
        grant: RobotConsentGrant,
    ) -> RobotConsent:
        def execute():
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                result = unit_of_work.robots.create_consent(robot_id, grant)
                unit_of_work.commit()
                return result

        return await asyncio.to_thread(execute)

    async def revoke_consent(
        self,
        robot_id: str,
        consent_id: str,
        *,
        revoked_by: str,
    ) -> RobotConsent:
        def execute():
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                result = unit_of_work.robots.revoke_consent(
                    robot_id,
                    consent_id,
                    revoked_by=revoked_by,
                )
                unit_of_work.commit()
                return result

        return await asyncio.to_thread(execute)

    async def list_consents(
        self,
        robot_id: str,
        *,
        capability: RobotCapabilityName | None = None,
        active_only: bool = False,
    ) -> list[RobotConsent]:
        def execute():
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                return unit_of_work.robots.list_consents(
                    robot_id,
                    capability=capability,
                    active_only=active_only,
                )

        return await asyncio.to_thread(execute)

    async def record_state(self, snapshot: RobotStateSnapshot):
        def execute():
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                persisted = unit_of_work.robots.add_state(snapshot)
                robot = unit_of_work.robots.get(persisted.robot_id)
                unit_of_work.commit()
                return robot

        return await asyncio.to_thread(execute)

    async def mark_unavailable(
        self,
        adapter_id: str,
        external_id: str,
        *,
        reason: str,
        occurred_at: datetime | None = None,
    ):
        def execute():
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                robot = unit_of_work.robots.mark_unavailable(
                    adapter_id,
                    external_id,
                    reason=reason,
                    occurred_at=occurred_at or utc_now(),
                )
                unit_of_work.commit()
                return robot

        return await asyncio.to_thread(execute)

    async def _read(self, reader: Callable[..., object]):
        def execute():
            with self._unit_of_work_factory() as unit_of_work:
                assert unit_of_work.robots is not None
                return reader(unit_of_work.robots)

        return await asyncio.to_thread(execute)


__all__ = ["RobotRegistry"]
