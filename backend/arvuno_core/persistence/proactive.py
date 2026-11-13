from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import (
    Environment,
    ProactiveSuggestion,
    UserPreference,
)


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def stored_datetime(value: datetime) -> datetime:
    normalized = utc(value) or datetime.now(UTC)
    return normalized.replace(tzinfo=None)


def _scope_digest(environment_id: str, dedupe_key: str) -> str:
    scope = f"{environment_id}\0{dedupe_key}".encode()
    return sha256(scope).hexdigest()


class ProactiveRepository:
    """Persistence boundary for proactive suggestions and rate-limit decisions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def environment(self, environment_id: str | None, name: str) -> Environment | None:
        try:
            statement = select(Environment)
            if environment_id is not None:
                statement = statement.where(Environment.id == environment_id)
            else:
                statement = statement.where(
                    Environment.name == name,
                    Environment.is_default.is_(True),
                )
            return self._session.scalars(
                statement.order_by(Environment.created_at).limit(1)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read the proactive environment.") from exc

    def add(self, suggestion: ProactiveSuggestion) -> ProactiveSuggestion:
        try:
            self._session.add(suggestion)
            self._session.flush()
            return suggestion
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a proactive suggestion.") from exc

    def get(self, suggestion_id: str) -> ProactiveSuggestion | None:
        try:
            return self._session.get(ProactiveSuggestion, suggestion_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a proactive suggestion.") from exc

    def list(
        self,
        *,
        environment_id: str | None = None,
        status: str | None = None,
        trigger_type: str | None = None,
        importance: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ProactiveSuggestion], int]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("Page must be positive and page_size must be between 1 and 100")
        filters: list[Any] = []
        if environment_id is not None:
            filters.append(ProactiveSuggestion.environment_id == environment_id)
        if status is not None:
            filters.append(ProactiveSuggestion.status == status)
        if trigger_type is not None:
            filters.append(ProactiveSuggestion.trigger_type == trigger_type)
        if importance is not None:
            filters.append(ProactiveSuggestion.importance == importance)
        try:
            count = int(
                self._session.scalar(
                    select(func.count()).select_from(ProactiveSuggestion).where(*filters)
                )
                or 0
            )
            rows = list(
                self._session.scalars(
                    select(ProactiveSuggestion)
                    .where(*filters)
                    .order_by(
                        ProactiveSuggestion.created_at.desc(),
                        ProactiveSuggestion.id.desc(),
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            return rows, count
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list proactive suggestions.") from exc

    def active_in_cooldown(
        self,
        *,
        environment_id: str,
        dedupe_key: str,
        now: datetime,
    ) -> ProactiveSuggestion | None:
        active_statuses = ("evaluated", "queued", "delivered", "opened")
        try:
            return self._session.scalars(
                select(ProactiveSuggestion)
                .where(
                    ProactiveSuggestion.environment_id == environment_id,
                    ProactiveSuggestion.dedupe_key == dedupe_key,
                    ProactiveSuggestion.status.in_(active_statuses),
                    or_(
                        ProactiveSuggestion.cooldown_until.is_(None),
                        ProactiveSuggestion.cooldown_until > stored_datetime(now),
                    ),
                )
                .order_by(ProactiveSuggestion.created_at.desc())
                .limit(1)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to check active proactive suggestions.") from exc

    def suppression_preference(
        self,
        *,
        environment_id: str,
        dedupe_key: str,
        now: datetime,
    ) -> UserPreference | None:
        try:
            scoped_key = f"proactive_suppression:{_scope_digest(environment_id, dedupe_key)}"
            legacy_key = f"proactive_suppression:{dedupe_key}"
            preferences = list(
                self._session.scalars(
                    select(UserPreference).where(
                        UserPreference.status == "active",
                        UserPreference.category == "proactive_suppression",
                        UserPreference.key.in_([scoped_key, legacy_key]),
                    )
                )
            )
            for preference in preferences:
                if preference.value.get("environment_id") != environment_id:
                    continue
                if preference.expires_at is not None and preference.expires_at <= stored_datetime(
                    now
                ):
                    continue
                return preference
            return None
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read proactive suppression preference.") from exc

    def preference_for_key(self, key: str) -> UserPreference | None:
        try:
            return self._session.scalars(
                select(UserPreference)
                .where(
                    UserPreference.category == "proactive_suppression",
                    UserPreference.key == key,
                )
                .order_by(UserPreference.created_at.desc())
                .limit(1)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read proactive suppression preference.") from exc

    def delivered_count_since(
        self,
        *,
        environment_id: str,
        since: datetime,
    ) -> int:
        try:
            return int(
                self._session.scalar(
                    select(func.count())
                    .select_from(ProactiveSuggestion)
                    .where(
                        ProactiveSuggestion.environment_id == environment_id,
                        ProactiveSuggestion.delivered_at.isnot(None),
                        ProactiveSuggestion.delivered_at >= stored_datetime(since),
                    )
                )
                or 0
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to count delivered suggestions.") from exc

    def trigger_quality(
        self,
        *,
        environment_id: str,
        trigger_type: str,
    ) -> dict[str, int]:
        try:
            rows = self._session.execute(
                select(ProactiveSuggestion.status, func.count())
                .where(
                    ProactiveSuggestion.environment_id == environment_id,
                    ProactiveSuggestion.trigger_type == trigger_type,
                )
                .group_by(ProactiveSuggestion.status)
            ).all()
            return {status: int(count) for status, count in rows}
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to calculate proactive suggestion quality.") from exc

    def mark(self, suggestion: ProactiveSuggestion) -> ProactiveSuggestion:
        try:
            self._session.flush()
            return suggestion
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to update a proactive suggestion.") from exc

    def delete(self, suggestion: ProactiveSuggestion) -> None:
        try:
            self._session.delete(suggestion)
            self._session.flush()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to delete a proactive suggestion.") from exc

    def expire_stale(self, *, now: datetime, limit: int | None = None) -> int:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        try:
            stale_statuses = ("evaluated", "queued", "delivered", "opened")
            statement = (
                select(ProactiveSuggestion)
                .where(
                    ProactiveSuggestion.status.in_(stale_statuses),
                    ProactiveSuggestion.expires_at.isnot(None),
                    ProactiveSuggestion.expires_at <= stored_datetime(now),
                )
                .order_by(ProactiveSuggestion.expires_at, ProactiveSuggestion.id)
            )
            if limit is not None:
                statement = statement.limit(limit)
            result = self._session.execute(statement)
            count = 0
            for suggestion in result.scalars():
                suggestion.status = "expired"
                count += 1
            self._session.flush()
            return count
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to expire proactive suggestions.") from exc


__all__ = ["ProactiveRepository", "utc"]
