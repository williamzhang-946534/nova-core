import os
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from nova_core.config import Settings
from nova_core.persistence.exceptions import BackupError


class SqliteBackupService:
    """Safe SQLite backup and restore operations for the local Nova database."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_backup(self) -> Path:
        source_path = self._settings.resolved_database_path
        backup_dir = self._settings.resolved_backup_dir
        if not source_path.is_file():
            raise BackupError("Database file does not exist.")

        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        backup_path = backup_dir / f"nova-{timestamp}-{uuid.uuid4().hex[:8]}.sqlite3"
        try:
            with (
                closing(sqlite3.connect(source_path)) as source,
                closing(sqlite3.connect(backup_path)) as destination,
            ):
                source.backup(destination)
            self._check_integrity(backup_path)
            self._apply_retention()
            return backup_path
        except BackupError:
            backup_path.unlink(missing_ok=True)
            raise
        except (sqlite3.Error, OSError) as exc:
            backup_path.unlink(missing_ok=True)
            raise BackupError("Failed to create the database backup.") from exc

    def restore_backup(self, backup_path: Path, *, replace_existing: bool = False) -> Path:
        source_path = self._resolve_backup_path(backup_path)
        destination_path = self._settings.resolved_database_path
        if destination_path.exists() and not replace_existing:
            raise BackupError("Destination database exists; explicit replacement is required.")

        self._check_integrity(source_path)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = destination_path.with_name(
            f".{destination_path.name}.restore-{uuid.uuid4().hex}.tmp"
        )
        safety_path = destination_path.with_name(
            f".{destination_path.name}.before-restore-{uuid.uuid4().hex}.sqlite3"
        )
        moved_existing = False

        try:
            with (
                closing(sqlite3.connect(source_path)) as source,
                closing(sqlite3.connect(temporary_path)) as destination,
            ):
                source.backup(destination)
            self._check_integrity(temporary_path)

            if destination_path.exists():
                os.replace(destination_path, safety_path)
                moved_existing = True
            os.replace(temporary_path, destination_path)
            self._check_integrity(destination_path)
            if moved_existing:
                safety_path.unlink(missing_ok=True)
            return destination_path
        except BackupError:
            temporary_path.unlink(missing_ok=True)
            if moved_existing and safety_path.exists() and not destination_path.exists():
                os.replace(safety_path, destination_path)
            raise
        except (sqlite3.Error, OSError) as exc:
            temporary_path.unlink(missing_ok=True)
            if moved_existing and safety_path.exists() and not destination_path.exists():
                os.replace(safety_path, destination_path)
            raise BackupError("Failed to restore the database backup.") from exc

    def _resolve_backup_path(self, backup_path: Path) -> Path:
        resolved = backup_path.expanduser().resolve()
        backup_dir = self._settings.resolved_backup_dir
        try:
            resolved.relative_to(backup_dir)
        except ValueError as exc:
            raise BackupError(
                "Backup file must be inside the configured backup directory."
            ) from exc
        if not resolved.is_file():
            raise BackupError("Backup file does not exist.")
        return resolved

    def _check_integrity(self, path: Path) -> None:
        try:
            with closing(sqlite3.connect(path)) as connection:
                result = connection.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise BackupError("SQLite integrity check failed.")
        except sqlite3.Error as exc:
            raise BackupError("SQLite integrity check failed.") from exc

    def _apply_retention(self) -> None:
        backup_dir = self._settings.resolved_backup_dir
        backups = sorted(
            (
                path
                for path in backup_dir.iterdir()
                if path.is_file()
                and path.name.startswith("nova-")
                and path.name.endswith(".sqlite3")
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in backups[self._settings.backup_retention_count :]:
            path.unlink(missing_ok=True)
