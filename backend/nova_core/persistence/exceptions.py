class PersistenceError(Exception):
    """Base exception for the persistence boundary."""


class DatabaseConnectionError(PersistenceError):
    """The configured database could not be opened or queried."""


class MigrationError(PersistenceError):
    """An Alembic migration operation failed."""


class RepositoryError(PersistenceError):
    """A repository operation failed."""


class BackupError(PersistenceError):
    """A database backup or restore operation failed."""
