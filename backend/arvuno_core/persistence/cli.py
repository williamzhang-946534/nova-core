import argparse
import json
import logging
from pathlib import Path

from pydantic import ValidationError

from arvuno_core.config import Settings
from arvuno_core.logging_config import configure_logging
from arvuno_core.persistence.backup import SqliteBackupService
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.exceptions import PersistenceError

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="arvuno-persistence", description="Manage Arvuno storage")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Create local directories and upgrade to head")
    subparsers.add_parser("status", help="Show the current Alembic revision")
    subparsers.add_parser("backup", help="Create a SQLite backup")

    restore = subparsers.add_parser("restore", help="Restore a SQLite backup")
    restore.add_argument("backup_file", type=Path)
    restore.add_argument(
        "--replace-existing",
        action="store_true",
        help="Replace the current database after an integrity check",
    )
    return parser.parse_args()


def run_cli(settings: Settings | None = None) -> int:
    try:
        app_settings = settings or Settings()
    except ValidationError as exc:
        print(f"Configuration is invalid: {exc.error_count()} setting error(s).", flush=True)
        return 1

    configure_logging(app_settings.log_level, app_settings.resolved_log_file)
    args = _parse_args()
    manager = DatabaseManager(app_settings)

    try:
        if args.command == "init":
            status = manager.initialize_database()
            result = {"operation": "init", **status.__dict__}
        elif args.command == "status":
            manager.ensure_local_directories()
            status = manager.status()
            result = {"operation": "status", **status.__dict__}
        elif args.command == "backup":
            manager.ensure_local_directories()
            manager.verify_connection()
            backup_path = SqliteBackupService(app_settings).create_backup()
            result = {"operation": "backup", "backup_file": str(backup_path)}
        else:
            manager.ensure_local_directories()
            restored_path = SqliteBackupService(app_settings).restore_backup(
                args.backup_file,
                replace_existing=args.replace_existing,
            )
            status = manager.initialize_database()
            result = {
                "operation": "restore",
                "database_file": str(restored_path),
                **status.__dict__,
            }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except PersistenceError as exc:
        logger.error("persistence_operation_failed", extra={"payload": {"reason": str(exc)}})
        print(f"Operation failed: {exc}", flush=True)
        return 1
    finally:
        manager.dispose()


def main() -> None:
    raise SystemExit(run_cli())
