import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from arvuno_core.config import Settings
from arvuno_core.persistence.backup import SqliteBackupService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.exceptions import BackupError
from arvuno_core.persistence.models import (
    Environment,
    MultimodalConsent,
    MultimodalMediaAsset,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork


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


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_private_media(settings: Settings, name: str, content: bytes) -> None:
    media_path = settings.resolved_data_dir / "media" / "multimodal" / name
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(content)


def seed_media_reference(
    manager: DatabaseManager,
    *,
    storage_key: str,
    content: bytes | None,
) -> str:
    now = datetime.now(UTC)
    with manager.session_factory() as session:
        environment = Environment(
            id=f"backup-env-{storage_key}",
            name=f"backup-{storage_key}",
            is_default=False,
        )
        consent = MultimodalConsent(
            id=f"backup-consent-{storage_key}",
            environment_id=environment.id,
            user_id="backup-user",
            consent_type="capture",
            modality="audio",
            purpose="user_query",
            processing_locations=["local"],
            space_ids=[],
            granted_at=now,
            status="granted",
            scope={},
        )
        asset = MultimodalMediaAsset(
            id=f"backup-asset-{storage_key}",
            environment_id=environment.id,
            media_kind="audio_clip",
            mime_type="audio/wav",
            size_bytes=len(content) if content is not None else 0,
            sha256=hashlib.sha256(content).hexdigest() if content is not None else None,
            storage_backend="local_private_file",
            storage_key=storage_key,
            content_available=content is not None,
            validation_status="valid" if content is not None else "pending",
            purpose="user_query",
            consent_id=consent.id,
            retention_class="process_then_delete_24h",
            retention_until=now + timedelta(hours=24),
            purge_status="pending",
            received_at=now,
            metadata_summary={},
        )
        session.add_all([environment, consent, asset])
        session.commit()
        return asset.id


def test_backup_and_restore_round_trip(tmp_path: Path) -> None:
    settings = phase_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    seed_setting(manager, True)
    manager.dispose()


def test_backup_set_contains_manifest_media_hashes_and_orphan_report(tmp_path: Path) -> None:
    settings = phase_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    seed_setting(manager, True)
    referenced = b"referenced private media"
    orphan = b"orphan private media"
    write_private_media(settings, "referenced.wav", referenced)
    write_private_media(settings, "orphan.wav", orphan)
    seed_media_reference(manager, storage_key="referenced.wav", content=referenced)
    manager.dispose()

    service = SqliteBackupService(settings)
    backup_path = service.create_backup()
    manifest_path = backup_path.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    media_root = backup_path.parent / "media"
    files = {item["relative_path"]: item for item in manifest["media"]["files"]}

    assert manifest["schema_version"] == 1
    assert manifest["database"]["sha256"] == file_hash(backup_path)
    assert files["referenced.wav"]["sha256"] == file_hash(media_root / "referenced.wav")
    assert files["orphan.wav"]["sha256"] == file_hash(media_root / "orphan.wav")
    assert [item["asset_id"] for item in manifest["media"]["references"]] == [
        "backup-asset-referenced.wav"
    ]
    assert manifest["consistency"]["media_missing_reference_count"] == 0
    assert manifest["consistency"]["orphan_media_count"] == 1

    status = service.inspect_backup(backup_path)
    assert status.database_valid is True
    assert status.media_complete is True
    assert status.media_scope == "media_and_metadata"
    assert status.orphan_media_files == ["orphan.wav"]

    write_private_media(settings, "referenced.wav", b"changed")
    (settings.resolved_data_dir / "media" / "multimodal" / "orphan.wav").unlink()
    restored = service.restore_backup_set(backup_path, replace_existing=True)
    assert restored.metadata_restored is True
    assert restored.media_restored_count == 2
    assert restored.media_complete is True
    assert file_hash(media_root / "referenced.wav") == hashlib.sha256(referenced).hexdigest()
    assert (settings.resolved_data_dir / "media" / "multimodal" / "orphan.wav").exists()

    manager = DatabaseManager(settings)
    assert read_setting(manager) is True
    manager.dispose()


def test_missing_media_reference_is_not_reported_as_complete_restore(tmp_path: Path) -> None:
    settings = phase_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    orphan = b"present but unreferenced"
    write_private_media(settings, "orphan.wav", orphan)
    seed_media_reference(manager, storage_key="missing.wav", content=None)
    manager.dispose()

    service = SqliteBackupService(settings)
    backup_path = service.create_backup()
    status = service.inspect_backup(backup_path)
    assert status.database_valid is True
    assert status.media_scope == "media_and_metadata"
    assert status.media_missing_references == [
        {"asset_id": "backup-asset-missing.wav", "relative_path": "missing.wav"}
    ]
    assert status.media_complete is False

    restored = service.restore_backup_set(backup_path, replace_existing=True)
    assert restored.metadata_restored is True
    assert restored.media_restored_count == 1
    assert restored.media_missing_references == status.media_missing_references
    assert restored.media_complete is False


def test_backup_inspection_detects_tampering_and_legacy_database_backups(tmp_path: Path) -> None:
    settings = phase_settings(tmp_path)
    manager = DatabaseManager(settings)
    manager.initialize_database()
    seed_setting(manager, True)
    referenced = b"media that must not silently change"
    write_private_media(settings, "referenced.wav", referenced)
    seed_media_reference(manager, storage_key="referenced.wav", content=referenced)
    manager.dispose()

    service = SqliteBackupService(settings)
    backup_path = service.create_backup()
    media_path = backup_path.parent / "media" / "referenced.wav"
    media_path.write_bytes(b"tampered media")
    status = service.inspect_backup(backup_path)
    assert status.media_invalid_files == ["referenced.wav"]
    assert status.media_complete is False
    restored = service.restore_backup_set(backup_path, replace_existing=True)
    assert restored.metadata_restored is True
    assert restored.media_restored_count == 0
    assert restored.media_invalid_files == ["referenced.wav"]
    assert restored.media_complete is False

    manifest_path = backup_path.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["database"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BackupError, match="database hash does not match"):
        service.inspect_backup(backup_path)

    legacy_path = settings.resolved_backup_dir / "legacy" / "database.sqlite3"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(backup_path.read_bytes())
    legacy_status = service.inspect_backup(legacy_path)
    assert legacy_status.database_valid is True
    assert legacy_status.media_scope == "legacy_database_only"
    assert legacy_status.media_complete is False
    legacy_restored = service.restore_backup_set(legacy_path, replace_existing=True)
    assert legacy_restored.metadata_restored is True
    assert legacy_restored.media_restored_count == 0
    assert legacy_restored.media_complete is False

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
    assert not first_backup.parent.exists()
    assert second_backup.exists()
    assert (second_backup.parent / "manifest.json").is_file()
