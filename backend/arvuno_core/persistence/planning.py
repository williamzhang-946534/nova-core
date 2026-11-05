from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import (
    Environment,
    Goal,
    GoalRevision,
    Plan,
    PlanReplanningRecord,
    ReasoningSession,
    Task,
)


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, datetime):
        return (utc(value) or value).isoformat()
    return value


def _stored(value: datetime) -> datetime:
    return (utc(value) or datetime.now(UTC)).replace(tzinfo=None)


class PlanningRepository:
    """Persistence boundary for goals, plan versions, and replanning audits."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def environment(self, environment_id: str | None, name: str) -> Environment | None:
        statement = select(Environment)
        if environment_id is not None:
            statement = statement.where(Environment.id == environment_id)
        else:
            statement = statement.where(
                Environment.name == name,
                Environment.is_default.is_(True),
            )
        try:
            return self._session.scalars(
                statement.order_by(Environment.created_at).limit(1)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a planning environment.") from exc

    def reasoning_session(self, session_id: str, environment_id: str) -> ReasoningSession | None:
        try:
            return self._session.scalars(
                select(ReasoningSession).where(
                    ReasoningSession.id == session_id,
                    ReasoningSession.environment_id == environment_id,
                )
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a planning reasoning source.") from exc

    def task(self, task_id: str, environment_id: str) -> Task | None:
        try:
            return self._session.get(Task, task_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a planning task source.") from exc

    def add_goal(self, goal: Goal, revision: GoalRevision) -> Goal:
        try:
            self._apply_json(goal)
            self._session.add(goal)
            self._session.flush()
            revision.goal_id = goal.id
            revision.after = json_safe(revision.after)
            self._session.add(revision)
            self._session.flush()
            return goal
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a goal.") from exc

    def get_goal(self, goal_id: str) -> Goal | None:
        try:
            return self._session.scalars(
                select(Goal)
                .where(Goal.id == goal_id)
                .options(
                    selectinload(Goal.revisions),
                    selectinload(Goal.plans).selectinload(Plan.steps),
                )
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a goal.") from exc

    def list_goals(
        self,
        *,
        environment_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Goal], int]:
        self._validate_page(page, page_size, 100)
        filters = []
        if environment_id is not None:
            filters.append(Goal.environment_id == environment_id)
        if status is not None:
            filters.append(Goal.status == status)
        try:
            count = int(
                self._session.scalar(select(func.count()).select_from(Goal).where(*filters)) or 0
            )
            rows = list(
                self._session.scalars(
                    select(Goal)
                    .where(*filters)
                    .order_by(Goal.created_at.desc(), Goal.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            return rows, count
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list goals.") from exc

    def add_revision(self, revision: GoalRevision) -> GoalRevision:
        try:
            revision.before = json_safe(revision.before)
            revision.after = json_safe(revision.after)
            self._session.add(revision)
            self._session.flush()
            return revision
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a goal revision.") from exc

    def next_goal_revision(self, goal_id: str) -> int:
        try:
            value = self._session.scalar(
                select(func.max(GoalRevision.revision)).where(GoalRevision.goal_id == goal_id)
            )
            return int(value or 0) + 1
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to allocate a goal revision.") from exc

    def add_plan(self, plan: Plan) -> Plan:
        try:
            self._apply_json(plan)
            self._session.add(plan)
            self._session.flush()
            for step in plan.steps:
                self._apply_json(step)
                self._session.add(step)
            self._session.flush()
            return plan
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a plan.") from exc

    def next_plan_version(self, goal_id: str) -> int:
        try:
            value = self._session.scalar(
                select(func.max(Plan.version)).where(Plan.goal_id == goal_id)
            )
            return int(value or 0) + 1
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to allocate a plan version.") from exc

    def get_plan(self, plan_id: str) -> Plan | None:
        try:
            return self._session.scalars(
                select(Plan)
                .where(Plan.id == plan_id)
                .options(selectinload(Plan.steps), selectinload(Plan.replanning_records))
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a plan.") from exc

    def list_plans(
        self,
        *,
        goal_id: str | None = None,
        environment_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Plan], int]:
        self._validate_page(page, page_size, 100)
        filters = []
        if goal_id is not None:
            filters.append(Plan.goal_id == goal_id)
        if environment_id is not None:
            filters.append(Plan.environment_id == environment_id)
        if status is not None:
            filters.append(Plan.status == status)
        try:
            count = int(
                self._session.scalar(select(func.count()).select_from(Plan).where(*filters)) or 0
            )
            rows = list(
                self._session.scalars(
                    select(Plan)
                    .where(*filters)
                    .options(selectinload(Plan.steps), selectinload(Plan.replanning_records))
                    .order_by(Plan.created_at.desc(), Plan.version.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            return rows, count
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list plans.") from exc

    def latest_plan(self, goal_id: str) -> Plan | None:
        try:
            return self._session.scalars(
                select(Plan)
                .where(Plan.goal_id == goal_id)
                .options(selectinload(Plan.steps), selectinload(Plan.replanning_records))
                .order_by(Plan.version.desc())
                .limit(1)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read the latest plan.") from exc

    def add_replanning_record(self, record: PlanReplanningRecord) -> PlanReplanningRecord:
        try:
            self._apply_json(record)
            self._session.add(record)
            self._session.flush()
            return record
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a replanning record.") from exc

    def _apply_json(self, row: Any) -> None:
        for key, value in list(vars(row).items()):
            if key.startswith("_") or not isinstance(value, dict | list):
                continue
            setattr(row, key, json_safe(value))

    @staticmethod
    def _validate_page(page: int, page_size: int, maximum: int) -> None:
        if page < 1 or page_size < 1 or page_size > maximum:
            raise ValueError("Page must be positive and page_size is out of range")


__all__ = ["PlanningRepository", "json_safe", "utc"]
