from types import TracebackType

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from arvuno_core.persistence.automations import (
    AutomationRepository,
    AutomationRunRepository,
    NotificationRepository,
)
from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.history import HistoryRepository
from arvuno_core.persistence.memory import MemoryRepository
from arvuno_core.persistence.multimodal import MultimodalRepository
from arvuno_core.persistence.observations import (
    ObservationAttributeRepository,
    ObservationConsentRepository,
    ObservationIngestionBatchRepository,
    ObservationRepository,
    ObservationSourceHeartbeatRepository,
    ObservationSourceRepository,
)
from arvuno_core.persistence.perception import PerceptionRepository
from arvuno_core.persistence.planning import PlanningRepository
from arvuno_core.persistence.proactive import ProactiveRepository
from arvuno_core.persistence.provider_logs import ProviderLogRepository
from arvuno_core.persistence.reasoning import ReasoningRepository
from arvuno_core.persistence.repositories import (
    DeviceRepository,
    EnvironmentRepository,
    EventRepository,
    SystemSettingRepository,
    ToolExecutionRepository,
    ToolRepository,
)
from arvuno_core.persistence.retention import RetentionRunRepository
from arvuno_core.persistence.robots import RobotRepository
from arvuno_core.persistence.spatial import (
    EntityRepository,
    EntitySpaceAssignmentRepository,
    SpaceRepository,
)
from arvuno_core.persistence.state_estimates import StateEstimateRepository
from arvuno_core.persistence.tasks import TaskRepository


class SqlAlchemyUnitOfWork:
    """Owns one transaction and prevents callers from using the raw session."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self.devices: DeviceRepository | None = None
        self.events: EventRepository | None = None
        self.environments: EnvironmentRepository | None = None
        self.spaces: SpaceRepository | None = None
        self.entities: EntityRepository | None = None
        self.space_assignments: EntitySpaceAssignmentRepository | None = None
        self.observation_sources: ObservationSourceRepository | None = None
        self.observation_attributes: ObservationAttributeRepository | None = None
        self.observation_consents: ObservationConsentRepository | None = None
        self.observations: ObservationRepository | None = None
        self.observation_batches: ObservationIngestionBatchRepository | None = None
        self.observation_heartbeats: ObservationSourceHeartbeatRepository | None = None
        self.system_settings: SystemSettingRepository | None = None
        self.tools: ToolRepository | None = None
        self.tool_executions: ToolExecutionRepository | None = None
        self.tasks: TaskRepository | None = None
        self.provider_logs: ProviderLogRepository | None = None
        self.automations: AutomationRepository | None = None
        self.automation_runs: AutomationRunRepository | None = None
        self.notifications: NotificationRepository | None = None
        self.state_estimates: StateEstimateRepository | None = None
        self.memories: MemoryRepository | None = None
        self.history: HistoryRepository | None = None
        self.reasoning: ReasoningRepository | None = None
        self.planning: PlanningRepository | None = None
        self.proactive: ProactiveRepository | None = None
        self.perception: PerceptionRepository | None = None
        self.multimodal: MultimodalRepository | None = None
        self.robots: RobotRepository | None = None
        self.retention_runs: RetentionRunRepository | None = None

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self._session = self._session_factory()
        self.devices = DeviceRepository(self._session)
        self.events = EventRepository(self._session)
        self.environments = EnvironmentRepository(self._session)
        self.spaces = SpaceRepository(self._session)
        self.entities = EntityRepository(self._session)
        self.space_assignments = EntitySpaceAssignmentRepository(self._session)
        self.observation_sources = ObservationSourceRepository(self._session)
        self.observation_attributes = ObservationAttributeRepository(self._session)
        self.observation_consents = ObservationConsentRepository(self._session)
        self.observations = ObservationRepository(self._session)
        self.observation_batches = ObservationIngestionBatchRepository(self._session)
        self.observation_heartbeats = ObservationSourceHeartbeatRepository(self._session)
        self.system_settings = SystemSettingRepository(self._session)
        self.tools = ToolRepository(self._session)
        self.tool_executions = ToolExecutionRepository(self._session)
        self.tasks = TaskRepository(self._session)
        self.provider_logs = ProviderLogRepository(self._session)
        self.automations = AutomationRepository(self._session)
        self.automation_runs = AutomationRunRepository(self._session)
        self.notifications = NotificationRepository(self._session)
        self.state_estimates = StateEstimateRepository(self._session)
        self.memories = MemoryRepository(self._session)
        self.history = HistoryRepository(self._session)
        self.reasoning = ReasoningRepository(self._session)
        self.planning = PlanningRepository(self._session)
        self.proactive = ProactiveRepository(self._session)
        self.perception = PerceptionRepository(self._session)
        self.multimodal = MultimodalRepository(self._session)
        self.robots = RobotRepository(self._session)
        self.retention_runs = RetentionRunRepository(self._session)
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
            self.spaces = None
            self.entities = None
            self.space_assignments = None
            self.observation_sources = None
            self.observation_attributes = None
            self.observation_consents = None
            self.observations = None
            self.observation_batches = None
            self.observation_heartbeats = None
            self.system_settings = None
            self.tools = None
            self.tool_executions = None
            self.tasks = None
            self.provider_logs = None
            self.automations = None
            self.automation_runs = None
            self.notifications = None
            self.state_estimates = None
            self.memories = None
            self.history = None
            self.reasoning = None
            self.planning = None
            self.proactive = None
            self.perception = None
            self.multimodal = None
            self.robots = None
            self.retention_runs = None
