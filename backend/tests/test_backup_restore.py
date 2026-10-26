from pathlib import Path

import pytest

from nova_core.config import Settings
from nova_core.persistence.backup import SqliteBackupService
from nova_core.persistence.database import DatabaseManager
from nova_core.persistence.exceptions import BackupError
from nova_core.persistence.unit_of_work import SqlAlchemyUnitOfWork


def phase_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "data_dir": tmp_path / "data",
        "log_dir": tmp_path / "logs",
        "backup_dir": tmp_path / "backups",
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def seed_setting(manager: DatabaseManager, enabled: bool) -> None:
    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        uow.system_settings.upsert_non_sensitive(
            key="backup.test",
            value={"enabled": enabled},
            value_type="object",
        )
        uow.commit()


def read_setting(manager: DatabaseManager) -> bool:
    with SqlAlchemyUnitOfWork(manager.session_factory) as uow:
        setting = uow.system_settings.get_by_key("backup.test")
        assert setting is not None
        return bool(setting.value["enabled"])


def test_backup_and_restore_round_trip(tmp_path: Path) -> None:
    settings = phase_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    seed_setting(manager, True)
    manager.dispose()

    backup_path = SqliteBackupService(settings).create_backup()
    assert backup_path.is_file()

    manager = DatabaseManager(settings)
    seed_setting(manager, False)
    manager.dispose()

    service = SqliteBackupService(settings)
    with pytest.raises(BackupError, match="explicit replacement"):
        service.restore_backup(backup_path)

    restored_path = service.restore_backup(backup_path, replace_existing=True)
    assert restored_path == settings.resolved_database_path

    manager = DatabaseManager(settings)
    assert read_setting(manager) is True
    manager.dispose()


def test_restore_rejects_outside_and_invalid_backups(tmp_path: Path) -> None:
    settings = phase_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    seed_setting(manager, True)
    manager.dispose()

    outside_path = tmp_path / "outside.sqlite3"
    outside_path.write_bytes(b"not sqlite")
    invalid_backup = settings.resolved_backup_dir / "invalid.sqlite3"
    invalid_backup.parent.mkdir(parents=True, exist_ok=True)
    invalid_backup.write_bytes(b"not sqlite")

    service = SqliteBackupService(settings)
    with pytest.raises(BackupError, match="inside the configured backup directory"):
        service.restore_backup(outside_path, replace_existing=True)
    with pytest.raises(BackupError, match="integrity check failed"):
        service.restore_backup(invalid_backup, replace_existing=True)

    manager = DatabaseManager(settings)
    assert read_setting(manager) is True
    manager.dispose()


def test_backup_requires_an_existing_database_file(tmp_path: Path) -> None:
    settings = phase_settings(tmp_path)

    with pytest.raises(BackupError, match="Database file does not exist."):
        SqliteBackupService(settings).create_backup()


def test_backup_retention_keeps_the_newest_backup(tmp_path: Path) -> None:
    settings = phase_settings(tmp_path, backup_retention_count=1)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    manager.dispose()

    service = SqliteBackupService(settings)
    first_backup = service.create_backup()
    second_backup = service.create_backup()

    assert not first_backup.exists()
    assert second_backup.exists()
