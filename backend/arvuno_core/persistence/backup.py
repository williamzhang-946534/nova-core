import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arvuno_core.config import Settings
from arvuno_core.persistence.exceptions import BackupError


@dataclass(frozen=True)
class BackupSetStatus:
    database_valid: bool = False
    media_scope: str = "unknown"
    media_missing_references: list[dict[str, Any]] = field(default_factory=list)
    media_invalid_files: list[str] = field(default_factory=list)
    orphan_media_files: list[str] = field(default_factory=list)

    @property
    def media_complete(self) -> bool:
        if self.media_scope != "media_and_metadata":
            return False
        return not self.media_missing_references and not self.media_invalid_files

    def view(self) -> dict[str, Any]:
        return {
            "database_valid": self.database_valid,
            "media_complete": self.media_complete,
            "media_scope": self.media_scope,
            "media_missing_references": self.media_missing_references,
            "media_invalid_files": self.media_invalid_files,
            "orphan_media_files": self.orphan_media_files,
        }


@dataclass(frozen=True)
class BackupRestoreResult(BackupSetStatus):
    database_path: Path | None = None
    metadata_restored: bool = False
    media_restored_count: int = 0


class SqliteBackupService:
    """Creates a local database and private-media backup set."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_backup(self) -> Path:
        source_path = self._settings.resolved_database_path
        backup_dir = self._settings.resolved_backup_dir
        if not source_path.is_file():
            raise BackupError("Database file does not exist.")

        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        backup_root = backup_dir / f"arvuno-{timestamp}-{uuid.uuid4().hex[:8]}"
        backup_path = backup_root / "database.sqlite3"
        try:
            backup_root.mkdir()
            with (
                closing(sqlite3.connect(source_path)) as source,
                closing(sqlite3.connect(backup_path)) as destination,
            ):
                source.backup(destination)
            self._check_integrity(backup_path)
            copied_media = self._copy_private_media(backup_root / "media")
            manifest = self._build_manifest(backup_path, copied_media)
            (backup_root / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._apply_retention()
            return backup_path
        except BackupError:
            self._remove_path(backup_root)
            raise
        except (sqlite3.Error, OSError, ValueError) as exc:
            self._remove_path(backup_root)
            raise BackupError("Failed to create the backup set.") from exc

    def inspect_backup(self, backup_path: Path) -> BackupSetStatus:
        source_path = self._resolve_backup_path(backup_path)
        self._check_integrity(source_path)
        manifest_path = self._manifest_path(source_path)
        if manifest_path is None:
            return BackupSetStatus(
                database_valid=True,
                media_scope="legacy_database_only",
            )
        manifest = _read_manifest(manifest_path)
        database_record = manifest.get("database")
        if not isinstance(database_record, dict):
            raise BackupError("The backup manifest has no database record.")
        if database_record.get("sha256") != _hash_file(source_path):
            raise BackupError("The backup database hash does not match the manifest.")

        media_record = manifest.get("media")
        if not isinstance(media_record, dict):
            raise BackupError("The backup manifest media records are invalid.")
        files = media_record.get("files", [])
        references = media_record.get("references", [])
        if not isinstance(files, list) or not isinstance(references, list):
            raise BackupError("The backup manifest media records are invalid.")
        media_root = self._backup_media_root(source_path)
        files_by_path = {
            record.get("relative_path"): record
            for record in files
            if isinstance(record, dict) and isinstance(record.get("relative_path"), str)
        }
        invalid = {
            record["relative_path"]
            for record in files_by_path.values()
            if not _media_file_valid(media_root, record)
        }
        missing: list[dict[str, Any]] = []
        referenced_paths: set[str] = set()
        for reference in references:
            if not isinstance(reference, dict):
                raise BackupError("The backup manifest media reference is invalid.")
            relative_path = reference.get("relative_path")
            if not isinstance(relative_path, str) or relative_path not in files_by_path:
                missing.append(
                    {
                        "asset_id": reference.get("asset_id"),
                        "relative_path": relative_path,
                    }
                )
                continue
            record = files_by_path[relative_path]
            if (
                record.get("sha256") != reference.get("sha256")
                or record.get("size_bytes") != reference.get("size_bytes")
                or not _media_file_valid(media_root, record)
            ):
                invalid.add(relative_path)
            referenced_paths.add(relative_path)
        return BackupSetStatus(
            database_valid=True,
            media_scope="media_and_metadata",
            media_missing_references=missing,
            media_invalid_files=sorted(invalid),
            orphan_media_files=sorted(set(files_by_path) - referenced_paths),
        )

    def restore_backup_set(
        self,
        backup_path: Path,
        *,
        replace_existing: bool = False,
    ) -> BackupRestoreResult:
        source_path = self._resolve_backup_path(backup_path)
        status = self.inspect_backup(source_path)
        destination_path = self._restore_database(
            source_path,
            replace_existing=replace_existing,
        )
        restored_media = 0
        invalid_files = list(status.media_invalid_files)
        if status.media_scope == "media_and_metadata":
            source_media_root = self._backup_media_root(source_path)
            destination_media_root = self._private_media_root()
            destination_media_root.mkdir(parents=True, exist_ok=True)
            manifest = _read_manifest(self._manifest_path(source_path))
            for record in manifest.get("media", {}).get("files", []):
                if not isinstance(record, dict) or not _media_file_valid(
                    source_media_root,
                    record,
                ):
                    continue
                relative_path = record["relative_path"]
                source_file = _safe_media_path(source_media_root, relative_path)
                destination_file = _safe_media_path(destination_media_root, relative_path)
                destination_file.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination_file.with_name(
                    f".{destination_file.name}.restore-{uuid.uuid4().hex}.tmp"
                )
                shutil.copy2(source_file, temporary)
                if _hash_file(temporary) != record["sha256"]:
                    temporary.unlink(missing_ok=True)
                    invalid_files.append(relative_path)
                    continue
                os.replace(temporary, destination_file)
                restored_media += 1
        return BackupRestoreResult(
            database_valid=True,
            media_scope=status.media_scope,
            media_missing_references=status.media_missing_references,
            media_invalid_files=sorted(set(invalid_files)),
            orphan_media_files=status.orphan_media_files,
            database_path=destination_path,
            metadata_restored=True,
            media_restored_count=restored_media,
        )

    def restore_backup(self, backup_path: Path, *, replace_existing: bool = False) -> Path:
        return self.restore_backup_set(
            backup_path,
            replace_existing=replace_existing,
        ).database_path

    def _restore_database(
        self,
        source_path: Path,
        *,
        replace_existing: bool,
    ) -> Path:
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

    def _manifest_path(self, database_path: Path) -> Path | None:
        candidate = database_path.parent / "manifest.json"
        return candidate if candidate.is_file() else None

    def _backup_media_root(self, database_path: Path) -> Path:
        return database_path.parent / "media"

    def _private_media_root(self) -> Path:
        return self._settings.resolved_data_dir / "media" / "multimodal"

    def _copy_private_media(self, destination: Path) -> list[dict[str, Any]]:
        source_root = self._private_media_root()
        if not source_root.exists():
            return []
        records: list[dict[str, Any]] = []
        backup_dir = self._settings.resolved_backup_dir
        for path in source_root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                path.resolve().relative_to(backup_dir)
                continue
            except ValueError:
                pass
            relative = path.relative_to(source_root).as_posix()
            target = _safe_media_path(destination, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            records.append(
                {
                    "relative_path": relative,
                    "sha256": _hash_file(target),
                    "size_bytes": target.stat().st_size,
                }
            )
        return records

    def _build_manifest(
        self,
        database_path: Path,
        copied_media: list[dict[str, Any]],
    ) -> dict[str, Any]:
        references = _media_references(database_path)
        records_by_path = {record["relative_path"]: record for record in copied_media}
        manifest_references: list[dict[str, Any]] = []
        for reference in references:
            relative_path = reference["relative_path"]
            copied = records_by_path.get(relative_path)
            copied_record = copied or {}
            manifest_references.append(
                {
                    "asset_id": reference["asset_id"],
                    "relative_path": relative_path,
                    "sha256": reference["sha256"] or copied_record.get("sha256"),
                    "size_bytes": reference["size_bytes"],
                }
            )
        referenced_paths = {reference["relative_path"] for reference in manifest_references}
        return {
            "schema_version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "database": {
                "filename": database_path.name,
                "sha256": _hash_file(database_path),
                "size_bytes": database_path.stat().st_size,
                "integrity": "verified",
            },
            "media": {
                "files": copied_media,
                "references": manifest_references,
                "orphan_files": [
                    record["relative_path"]
                    for record in copied_media
                    if record["relative_path"] not in referenced_paths
                ],
            },
            "consistency": {
                "database_verified": True,
                "media_missing_reference_count": sum(
                    reference["relative_path"] not in records_by_path
                    for reference in manifest_references
                ),
                "orphan_media_count": sum(
                    record["relative_path"] not in referenced_paths for record in copied_media
                ),
            },
            "limitations": {
                "single_process_sqlite_snapshot": True,
                "media_files_copied_after_database_snapshot": True,
            },
        }

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
        entries: list[Path] = []
        for path in backup_dir.iterdir():
            if (
                path.is_dir()
                and path.name.startswith("arvuno-")
                and any(child.name == "database.sqlite3" for child in path.iterdir())
            ) or (
                path.is_file()
                and path.name.startswith("arvuno-")
                and path.name.endswith(".sqlite3")
            ):
                entries.append(path)
        entries.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        for path in entries[self._settings.backup_retention_count :]:
            self._remove_path(path)

    def _remove_path(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            resolved.relative_to(self._settings.resolved_backup_dir)
        except (OSError, ValueError):
            return
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def _media_references(database_path: Path) -> list[dict[str, Any]]:
    try:
        with closing(sqlite3.connect(database_path)) as connection:
            connection.row_factory = sqlite3.Row
            table_exists = connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'multimodal_media_assets'
                """
            ).fetchone()
            if table_exists is None:
                return []
            rows = connection.execute(
                """
                SELECT id, storage_key, sha256, size_bytes
                FROM multimodal_media_assets
                WHERE purge_status != 'purged' AND storage_key IS NOT NULL
                """
            ).fetchall()
    except sqlite3.Error as exc:
        raise BackupError("Failed to read multimodal references from the backup.") from exc
    references: list[dict[str, Any]] = []
    for row in rows:
        storage_key = row["storage_key"]
        if not isinstance(storage_key, str) or not storage_key:
            continue
        relative_path = Path(storage_key).as_posix()
        if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
            continue
        references.append(
            {
                "asset_id": row["id"],
                "relative_path": relative_path,
                "sha256": row["sha256"],
                "size_bytes": row["size_bytes"],
            }
        )
    return references


def _read_manifest(path: Path | None) -> dict[str, Any]:
    if path is None:
        raise BackupError("The backup manifest does not exist.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError("The backup manifest is invalid.") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise BackupError("The backup manifest schema is unsupported.")
    return value


def _safe_media_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise BackupError("A media path escapes the private media directory.") from exc
    return candidate


def _media_file_valid(root: Path, record: dict[str, Any]) -> bool:
    relative_path = record.get("relative_path")
    if not isinstance(relative_path, str):
        return False
    try:
        path = _safe_media_path(root, relative_path)
    except BackupError:
        return False
    return (
        path.is_file()
        and path.stat().st_size == record.get("size_bytes")
        and _hash_file(path) == record.get("sha256")
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
