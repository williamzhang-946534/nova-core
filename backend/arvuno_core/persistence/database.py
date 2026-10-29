from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from arvuno_core.config import Settings
from arvuno_core.persistence.backup import SqliteBackupService
from arvuno_core.persistence.exceptions import DatabaseConnectionError, MigrationError

ALEMBIC_CONFIG_PATH = Path(__file__).resolve().parents[2] / "alembic.ini"


@dataclass(frozen=True)
class DatabaseMigrationStatus:
    current_revision: str | None
    head_revision: str | None
    migration_pending: bool


class DatabaseManager:
    """Creates the local SQLite engine and manages Alembic migrations."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            engine = create_engine(
                self._settings.database_url,
                connect_args={"check_same_thread": False},
                future=True,
            )
            event.listen(engine, "connect", self._enable_sqlite_foreign_keys)
            self._engine = engine
        return self._engine

    @property
    def session_factory(self) -> sessionmaker[Session]:
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine,
                expire_on_commit=False,
                future=True,
            )
        return self._session_factory

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def ensure_local_directories(self) -> None:
        self._settings.ensure_local_directories()

    def verify_connection(self) -> None:
        try:
            with self.engine.connect() as connection:
                connection.execute(select(1))
        except SQLAlchemyError as exc:
            raise DatabaseConnectionError(
                "Could not connect to the configured SQLite database."
            ) from exc

    def initialize_database(self) -> DatabaseMigrationStatus:
        self.ensure_local_directories()
        self.verify_connection()
        status = self.upgrade()
        self.verify_connection()
        return status

    def status(self) -> DatabaseMigrationStatus:
        config = self._alembic_config()
        script = ScriptDirectory.from_config(config)
        try:
            with self.engine.connect() as connection:
                current = MigrationContext.configure(connection).get_current_revision()
        except SQLAlchemyError as exc:
            raise DatabaseConnectionError("Could not read the database migration status.") from exc
        head = script.get_current_head()
        return DatabaseMigrationStatus(
            current_revision=current,
            head_revision=head,
            migration_pending=current != head,
        )

    def upgrade(self) -> DatabaseMigrationStatus:
        try:
            status = self.status()
            if status.migration_pending and self._settings.resolved_database_path.exists():
                SqliteBackupService(self._settings).create_backup()
            command.upgrade(self._alembic_config(), "head")
            return self.status()
        except MigrationError:
            raise
        except DatabaseConnectionError:
            raise
        except Exception as exc:
            raise MigrationError("Database upgrade failed.") from exc

    def downgrade(self, revision: str = "base") -> DatabaseMigrationStatus:
        if not self._settings.resolved_database_path.exists():
            raise MigrationError("Database file does not exist.")
        backup = SqliteBackupService(self._settings)
        try:
            backup.create_backup()
            command.downgrade(self._alembic_config(), revision)
            return self.status()
        except Exception as exc:
            raise MigrationError("Database downgrade failed.") from exc

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None

    def _alembic_config(self) -> Config:
        config = Config(str(ALEMBIC_CONFIG_PATH))
        config.set_main_option("script_location", str(ALEMBIC_CONFIG_PATH.parent / "alembic"))
        config.attributes["database_url"] = self._settings.database_url
        return config
