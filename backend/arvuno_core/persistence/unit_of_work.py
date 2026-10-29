from types import TracebackType

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from arvuno_core.persistence.automations import (
    AutomationRepository,
    AutomationRunRepository,
    NotificationRepository,
)
from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.provider_logs import ProviderLogRepository
from arvuno_core.persistence.repositories import (
    DeviceRepository,
    EnvironmentRepository,
    EventRepository,
    SystemSettingRepository,
    ToolExecutionRepository,
    ToolRepository,
)
from arvuno_core.persistence.tasks import TaskRepository


class SqlAlchemyUnitOfWork:
    """Owns one transaction and prevents callers from using the raw session."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self.devices: DeviceRepository | None = None
        self.events: EventRepository | None = None
        self.environments: EnvironmentRepository | None = None
        self.system_settings: SystemSettingRepository | None = None
        self.tools: ToolRepository | None = None
        self.tool_executions: ToolExecutionRepository | None = None
        self.tasks: TaskRepository | None = None
        self.provider_logs: ProviderLogRepository | None = None
        self.automations: AutomationRepository | None = None
        self.automation_runs: AutomationRunRepository | None = None
        self.notifications: NotificationRepository | None = None

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self._session = self._session_factory()
        self.devices = DeviceRepository(self._session)
        self.events = EventRepository(self._session)
        self.environments = EnvironmentRepository(self._session)
        self.system_settings = SystemSettingRepository(self._session)
        self.tools = ToolRepository(self._session)
        self.tool_executions = ToolExecutionRepository(self._session)
        self.tasks = TaskRepository(self._session)
        self.provider_logs = ProviderLogRepository(self._session)
        self.automations = AutomationRepository(self._session)
        self.automation_runs = AutomationRunRepository(self._session)
        self.notifications = NotificationRepository(self._session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self.rollback()
        self.close()

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("The unit of work is not open.")
        try:
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise RepositoryError("Failed to commit the unit of work.") from exc

    def rollback(self) -> None:
        if self._session is not None:
            self._session.rollback()

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
            self.devices = None
            self.events = None
            self.environments = None
            self.system_settings = None
            self.tools = None
            self.tool_executions = None
            self.tasks = None
            self.provider_logs = None
            self.automations = None
            self.automation_runs = None
            self.notifications = None
