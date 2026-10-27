from collections.abc import Callable

from nova_core.persistence.exceptions import RepositoryError
from nova_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from nova_core.tools.storage import (
    StoredToolExecution,
    ToolDefinitionRecord,
    ToolExecutionCreate,
    ToolExecutionUpdate,
)


class SqlToolExecutionStore:
    """Admits tool audit records through the normal transaction boundary."""

    def __init__(self, unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def register_definition(self, record: ToolDefinitionRecord) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            if unit_of_work.tools is None:
                raise RepositoryError("The tool repository is unavailable.")
            unit_of_work.tools.upsert_definition(record)
            unit_of_work.commit()

    def create_execution(self, record: ToolExecutionCreate) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            if unit_of_work.tool_executions is None:
                raise RepositoryError("The tool execution repository is unavailable.")
            unit_of_work.tool_executions.create_execution(record)
            unit_of_work.commit()

    def update_execution(self, execution_id: str, record: ToolExecutionUpdate) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            if unit_of_work.tool_executions is None:
                raise RepositoryError("The tool execution repository is unavailable.")
            unit_of_work.tool_executions.update_execution(execution_id, record)
            unit_of_work.commit()

    def get_execution(self, execution_id: str) -> StoredToolExecution | None:
        with self._unit_of_work_factory() as unit_of_work:
            if unit_of_work.tool_executions is None:
                raise RepositoryError("The tool execution repository is unavailable.")
            return unit_of_work.tool_executions.get_execution(execution_id)


__all__ = ["SqlToolExecutionStore"]
