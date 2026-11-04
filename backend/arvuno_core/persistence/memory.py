from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import (
    ConversationMessage,
    EnvironmentSnapshot,
    Event,
    Memory,
    MemoryAccessLog,
    MemoryConsent,
    MemoryEvidence,
    MemoryProcedureValidation,
    MemoryProcedureVersion,
    MemoryRevision,
    Observation,
    Task,
    UserPreference,
)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class MemoryRepository:
    """Persistence boundary for durable memories, preferences, and evidence."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_memory(self, memory: Memory) -> Memory:
        try:
            self._session.add(memory)
            self._session.flush()
            return memory
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a memory.") from exc

    def get_memory(self, memory_id: str) -> Memory | None:
        try:
            statement = (
                select(Memory).where(Memory.id == memory_id).options(selectinload(Memory.evidence))
            )
            return self._session.scalars(statement).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a memory.") from exc

    def list_memories(
        self,
        *,
        memory_type: str | None = None,
        status: str | None = "current",
        source_type: str | None = None,
        keyword: str | None = None,
        environment_id: str | None = None,
        space_id: str | None = None,
        entity_id: str | None = None,
        include_expired: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Memory], int]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("Page must be positive and page_size must be between 1 and 100")
        filters = []
        if memory_type is not None:
            filters.append(Memory.memory_type == memory_type)
        if status is not None and status != "current":
            filters.append(Memory.status == status)
        if source_type is not None:
            filters.append(Memory.source_type == source_type)
        if environment_id is not None:
            filters.append(Memory.environment_id == environment_id)
        if space_id is not None:
            filters.append(Memory.space_id == space_id)
        if entity_id is not None:
            filters.append(Memory.entity_id == entity_id)
        if status == "current":
            filters.append(Memory.status.in_(["active", "corrected"]))
        if not include_expired:
            filters.append(
                or_(Memory.expires_at.is_(None), Memory.expires_at > utc(datetime.now(UTC)))
            )
        if keyword:
            needle = f"%{keyword.casefold()}%"
            filters.append(
                or_(
                    func.lower(Memory.title).like(needle),
                    func.lower(Memory.content).like(needle),
                    func.lower(Memory.summary).like(needle),
                    func.lower(Memory.subject_type).like(needle),
                    func.lower(Memory.subject_id).like(needle),
                    func.lower(Memory.predicate).like(needle),
                )
            )
        try:
            count = int(
                self._session.scalar(select(func.count()).select_from(Memory).where(*filters)) or 0
            )
            statement = (
                select(Memory)
                .where(*filters)
                .options(selectinload(Memory.evidence))
                .order_by(Memory.importance.desc(), Memory.updated_at.desc(), Memory.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return list(self._session.scalars(statement)), count
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list memories.") from exc

    def semantic_conflicts(
        self,
        *,
        subject_type: str,
        subject_id: str,
        predicate: str,
    ) -> list[Memory]:
        try:
            return list(
                self._session.scalars(
                    select(Memory).where(
                        Memory.memory_type == "semantic",
                        Memory.status.in_(["active", "corrected"]),
                        Memory.subject_type == subject_type,
                        Memory.subject_id == subject_id,
                        Memory.predicate == predicate,
                    )
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to check semantic conflicts.") from exc

    def record_exists(self, evidence_type: str, record_id: str) -> bool:
        model = {
            "observation": Observation,
            "observation_id": Observation,
        }.get(evidence_type)
        column = Observation.observation_id if model is Observation else None
        if model is None:
            model = {
                "event": Event,
                "task": Task,
                "conversation": ConversationMessage,
                "environment_snapshot": EnvironmentSnapshot,
                "procedure_execution": None,
            }.get(evidence_type)
            if model is None:
                if evidence_type == "procedure_execution":
                    from arvuno_core.persistence.models import ToolExecution

                    model = ToolExecution
                else:
                    return False
        try:
            if column is None:
                column = model.id  # type: ignore[union-attr]
            return self._session.scalar(select(column == record_id).limit(1)) is True  # type: ignore[arg-type]
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to validate memory evidence.") from exc

    def add_evidence(self, evidence: MemoryEvidence) -> MemoryEvidence:
        try:
            self._session.add(evidence)
            self._session.flush()
            return evidence
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save memory evidence.") from exc

    def evidence_for(self, memory_id: str) -> list[MemoryEvidence]:
        try:
            return list(
                self._session.scalars(
                    select(MemoryEvidence)
                    .where(MemoryEvidence.memory_id == memory_id)
                    .order_by(MemoryEvidence.created_at, MemoryEvidence.id)
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read memory evidence.") from exc

    def add_revision(self, revision: MemoryRevision) -> MemoryRevision:
        try:
            self._session.add(revision)
            self._session.flush()
            return revision
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a memory revision.") from exc

    def revisions_for(self, memory_id: str) -> list[MemoryRevision]:
        try:
            return list(
                self._session.scalars(
                    select(MemoryRevision)
                    .where(MemoryRevision.memory_id == memory_id)
                    .order_by(MemoryRevision.created_at.desc(), MemoryRevision.id.desc())
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read memory revisions.") from exc

    def add_access_log(self, entry: MemoryAccessLog) -> MemoryAccessLog:
        try:
            self._session.add(entry)
            self._session.flush()
            return entry
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save memory access.") from exc

    def delete_memory(self, memory: Memory) -> None:
        try:
            self._session.execute(
                sa_delete(MemoryAccessLog).where(MemoryAccessLog.memory_id == memory.id)
            )
            self._session.delete(memory)
            self._session.flush()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to delete a memory.") from exc

    def memories_for_cleanup(self, now: datetime) -> tuple[list[Memory], list[Memory]]:
        try:
            expired = list(
                self._session.scalars(
                    select(Memory).where(
                        Memory.status.in_(["active", "corrected", "candidate"]),
                        Memory.expires_at.is_not(None),
                        Memory.expires_at <= now,
                    )
                )
            )
            retention = list(
                self._session.scalars(
                    select(Memory).where(
                        Memory.status.in_(["expired", "archived"]),
                        Memory.retention_until.is_not(None),
                        Memory.retention_until <= now,
                    )
                )
            )
            return expired, retention
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to load memories for cleanup.") from exc

    def preferences_for_cleanup(
        self,
        now: datetime,
    ) -> tuple[list[UserPreference], list[UserPreference]]:
        try:
            expired = list(
                self._session.scalars(
                    select(UserPreference).where(
                        UserPreference.status == "active",
                        UserPreference.expires_at.is_not(None),
                        UserPreference.expires_at <= now,
                    )
                )
            )
            retention = list(
                self._session.scalars(
                    select(UserPreference).where(
                        UserPreference.status == "revoked",
                        UserPreference.retention_until.is_not(None),
                        UserPreference.retention_until <= now,
                    )
                )
            )
            return expired, retention
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to load preferences for cleanup.") from exc

    def procedure_version(
        self,
        memory_id: str,
        *,
        version: str | None = None,
    ) -> MemoryProcedureVersion | None:
        try:
            statement = select(MemoryProcedureVersion).where(
                MemoryProcedureVersion.memory_id == memory_id
            )
            if version is not None:
                statement = statement.where(MemoryProcedureVersion.version == version)
            else:
                statement = statement.where(MemoryProcedureVersion.status != "retired")
            return self._session.scalars(
                statement.order_by(MemoryProcedureVersion.created_at.desc()).limit(1)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a procedure version.") from exc

    def add_procedure_version(
        self,
        version: MemoryProcedureVersion,
    ) -> MemoryProcedureVersion:
        try:
            self._session.add(version)
            self._session.flush()
            return version
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a procedure version.") from exc

    def add_procedure_validation(
        self,
        validation: MemoryProcedureValidation,
    ) -> MemoryProcedureValidation:
        try:
            self._session.add(validation)
            self._session.flush()
            return validation
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a procedure validation.") from exc

    def add_consent(self, consent: MemoryConsent) -> MemoryConsent:
        try:
            self._session.add(consent)
            self._session.flush()
            return consent
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a consent record.") from exc

    def add_preference(self, preference: UserPreference) -> UserPreference:
        try:
            self._session.add(preference)
            self._session.flush()
            return preference
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a user preference.") from exc

    def get_preference(self, preference_id: str) -> UserPreference | None:
        try:
            return self._session.get(UserPreference, preference_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a user preference.") from exc

    def active_preference_key(self, key: str) -> UserPreference | None:
        try:
            return self._session.scalars(
                select(UserPreference).where(
                    UserPreference.key == key,
                    UserPreference.status.in_(["draft", "active"]),
                )
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to check a user preference key.") from exc

    def list_preferences(
        self,
        *,
        status: str | None = "active",
        category: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[UserPreference], int]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("Page must be positive and page_size must be between 1 and 100")
        filters = []
        if status is not None:
            filters.append(UserPreference.status == status)
        if category is not None:
            filters.append(UserPreference.category == category)
        if keyword:
            needle = f"%{keyword.casefold()}%"
            filters.append(
                or_(
                    func.lower(UserPreference.key).like(needle),
                    func.lower(UserPreference.description).like(needle),
                )
            )
        try:
            count = int(
                self._session.scalar(
                    select(func.count()).select_from(UserPreference).where(*filters)
                )
                or 0
            )
            rows = list(
                self._session.scalars(
                    select(UserPreference)
                    .where(*filters)
                    .order_by(UserPreference.updated_at.desc(), UserPreference.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            return rows, count
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list user preferences.") from exc

    def delete_preference(self, preference: UserPreference) -> None:
        try:
            self._session.execute(
                sa_delete(MemoryAccessLog).where(MemoryAccessLog.preference_id == preference.id)
            )
            self._session.delete(preference)
            self._session.flush()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to delete a user preference.") from exc

    def related_history(self, memory: Memory) -> list[tuple[MemoryEvidence, Any]]:
        rows: list[tuple[MemoryEvidence, Any]] = []
        for evidence in self.evidence_for(memory.id):
            record_id = evidence.evidence_id
            if record_id is None:
                rows.append((evidence, None))
                continue
            record: Any | None = None
            if evidence.evidence_type == "observation":
                record = self._session.get(Observation, record_id)
            elif evidence.evidence_type == "event":
                record = self._session.get(Event, record_id)
            elif evidence.evidence_type == "task":
                record = self._session.get(Task, record_id)
            elif evidence.evidence_type == "conversation":
                record = self._session.get(ConversationMessage, record_id)
            elif evidence.evidence_type == "environment_snapshot":
                record = self._session.get(EnvironmentSnapshot, record_id)
            elif evidence.evidence_type == "procedure_execution":
                from arvuno_core.persistence.models import ToolExecution

                record = self._session.get(ToolExecution, record_id)
            rows.append((evidence, record))
        return rows


__all__ = ["MemoryRepository", "utc"]
