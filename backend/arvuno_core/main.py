import uvicorn

from arvuno_core.app import create_app
from arvuno_core.config import get_settings
from arvuno_core.logging_config import configure_logging
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork

settings = get_settings()
configure_logging(settings.log_level, settings.resolved_log_file)
database_manager = DatabaseManager(settings)
database_manager.initialize_database()


def unit_of_work() -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(database_manager.session_factory)


app = create_app(
    settings,
    unit_of_work_factory=unit_of_work,
    initialize_event_runtime=True,
    initialize_tool_runtime=True,
)
app.state.database_manager = database_manager


def run() -> None:
    uvicorn.run(
        "arvuno_core.main:app",
        host=settings.host,
        port=settings.port,
        log_config=None,
    )


if __name__ == "__main__":
    run()
