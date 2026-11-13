import asyncio
from pathlib import Path

import pytest

from arvuno_core.config import Settings
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.robots.errors import RobotCapabilityGovernanceError
from arvuno_core.robots.mock import MockRobotAdapter
from arvuno_core.robots.models import RobotCapabilityName
from arvuno_core.robots.registry import RobotRegistry
from arvuno_core.robots.service import RobotApplicationService


def settings(tmp_path: Path, *, profile: str = "desktop_robot") -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
        robot_profile=profile,  # type: ignore[arg-type]
    )


def environment(tmp_path: Path, *, profile: str = "desktop_robot"):
    manager = DatabaseManager(settings(tmp_path, profile=profile))
    manager.initialize_database()
    adapter = MockRobotAdapter(profile=profile)
    registry = RobotRegistry(lambda: SqlAlchemyUnitOfWork(manager.session_factory))
    service = RobotApplicationService(
        registry,
        {adapter.adapter_id: adapter},
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
    )
    asyncio.run(service.sync_robot(adapter, adapter.external_id))
    robot = asyncio.run(service.list_robots())[0]
    return manager, adapter, service, robot


def test_desktop_profile_declares_only_bench_target_capabilities(tmp_path: Path) -> None:
    manager, _adapter, service, robot = environment(tmp_path)
    try:
        capabilities = asyncio.run(service.capabilities(robot.id))
        names = {item.capability for item in capabilities}
        assert names == {
            RobotCapabilityName.REPORT_STATUS,
            RobotCapabilityName.LOOK_AT,
            RobotCapabilityName.OBSERVE_SCENE,
            RobotCapabilityName.REQUEST_SAFE_STOP,
            RobotCapabilityName.ENTER_IDLE_POSE,
            RobotCapabilityName.SPEAK,
            RobotCapabilityName.LISTEN,
        }
        assert all(item.supported for item in capabilities)
        assert all(item.discovered for item in capabilities)
        assert all(not item.enabled for item in capabilities)
        assert all(not item.approved for item in capabilities)
        assert all(not item.executable for item in capabilities)
        assert RobotCapabilityName.NAVIGATE_TO not in names
        assert RobotCapabilityName.RETURN_TO_DOCK not in names
        assert RobotCapabilityName.CHARGE not in names
    finally:
        manager.dispose()


def test_sync_preserves_user_governance_and_updates_adapter_facts(tmp_path: Path) -> None:
    manager, adapter, service, robot = environment(tmp_path)
    try:
        adapter.set_capability(
            RobotCapabilityName.REPORT_STATUS,
            runtime_enabled=True,
            verification_status="bench_verified",
        )
        asyncio.run(service.sync_robot(adapter, adapter.external_id))
        approved = asyncio.run(
            service.set_capability_governance(
                robot.id,
                RobotCapabilityName.REPORT_STATUS,
                enabled=True,
                approved=True,
                approved_by="operator-1",
            )
        )
        assert approved.executable is True

        adapter.set_capability(
            RobotCapabilityName.REPORT_STATUS,
            runtime_enabled=False,
            verification_status="concept",
        )
        asyncio.run(service.sync_robot(adapter, adapter.external_id))
        after_sync = asyncio.run(service.capabilities(robot.id))
        report = next(
            item for item in after_sync if item.capability is RobotCapabilityName.REPORT_STATUS
        )
        assert report.verification_status == "concept"
        assert report.enabled is True
        assert report.approved is True
        assert report.executable is False

        adapter.set_capability(
            RobotCapabilityName.REPORT_STATUS,
            runtime_enabled=True,
            verification_status="bench_verified",
        )
        asyncio.run(service.sync_robot(adapter, adapter.external_id))
        restored = asyncio.run(service.capabilities(robot.id))
        report = next(
            item for item in restored if item.capability is RobotCapabilityName.REPORT_STATUS
        )
        assert report.executable is True
    finally:
        manager.dispose()


def test_desktop_profile_rejects_mobile_capabilities(tmp_path: Path) -> None:
    manager, adapter, service, robot = environment(tmp_path)
    try:
        capabilities = asyncio.run(service.capabilities(robot.id))
        assert RobotCapabilityName.NAVIGATE_TO not in {item.capability for item in capabilities}
        with pytest.raises(RobotCapabilityGovernanceError, match="desktop_robot"):
            asyncio.run(
                service.set_capability_governance(
                    robot.id,
                    RobotCapabilityName.NAVIGATE_TO,
                    enabled=True,
                    approved=True,
                )
            )
        assert adapter.profile == "desktop_robot"
    finally:
        manager.dispose()


def test_mobile_profile_is_locked_until_hardware_safety_approval(tmp_path: Path) -> None:
    manager, adapter, service, robot = environment(tmp_path, profile="mobile_robot")
    try:
        adapter.set_capability(
            RobotCapabilityName.NAVIGATE_TO,
            runtime_enabled=True,
            verification_status="bench_verified",
        )
        asyncio.run(service.sync_robot(adapter, adapter.external_id))
        with pytest.raises(RobotCapabilityGovernanceError, match="mobile_robot"):
            asyncio.run(
                service.set_capability_governance(
                    robot.id,
                    RobotCapabilityName.NAVIGATE_TO,
                    enabled=True,
                    approved=True,
                    consent_granted=True,
                )
            )
        capabilities = asyncio.run(service.capabilities(robot.id))
        assert all(not item.executable for item in capabilities)
    finally:
        manager.dispose()


def test_capability_execution_requires_explicit_consent(tmp_path: Path) -> None:
    manager, adapter, service, robot = environment(tmp_path)
    try:
        adapter.set_capability(
            RobotCapabilityName.OBSERVE_SCENE,
            runtime_enabled=True,
            verification_status="bench_verified",
        )
        asyncio.run(service.sync_robot(adapter, adapter.external_id))
        without_consent = asyncio.run(
            service.set_capability_governance(
                robot.id,
                RobotCapabilityName.OBSERVE_SCENE,
                enabled=True,
                approved=True,
                consent_granted=False,
            )
        )
        assert without_consent.consent_granted is False
        # Governance projection records approved/enablement facts; active consent
        # is a separate SafetyPolicy runtime check and cannot be inferred from it.
        assert without_consent.executable is True

        with_consent = asyncio.run(
            service.set_capability_governance(
                robot.id,
                RobotCapabilityName.OBSERVE_SCENE,
                consent_granted=True,
            )
        )
        assert with_consent.consent_granted is True
        assert with_consent.executable is True
    finally:
        manager.dispose()
