from datetime import datetime
from typing import Protocol

from arvuno_core.persistence.memory import MemoryRepository
from arvuno_core.persistence.models import (
    Memory,
    MemoryAccessLog,
    MemoryConsent,
    MemoryEvidence,
    MemoryProcedureValidation,
    MemoryProcedureVersion,
    MemoryRevision,
    UserPreference,
)


class MemoryStore(Protocol):
    """Durable memory boundary; callers never receive the SQLAlchemy session."""

    def add_memory(self, memory: Memory) -> Memory: ...
    def get_memory(self, memory_id: str) -> Memory | None: ...
    def list_memories(self, **filters: object) -> tuple[list[Memory], int]: ...
    def semantic_conflicts(
        self, *, subject_type: str, subject_id: str, predicate: str
    ) -> list[Memory]: ...
    def record_exists(self, evidence_type: str, record_id: str) -> bool: ...
    def add_evidence(self, evidence: MemoryEvidence) -> MemoryEvidence: ...
    def evidence_for(self, memory_id: str) -> list[MemoryEvidence]: ...
    def add_revision(self, revision: MemoryRevision) -> MemoryRevision: ...
    def revisions_for(self, memory_id: str) -> list[MemoryRevision]: ...
    def add_access_log(self, entry: MemoryAccessLog) -> MemoryAccessLog: ...
    def delete_memory(self, memory: Memory) -> None: ...
    def memories_for_cleanup(self, now: datetime) -> tuple[list[Memory], list[Memory]]: ...
    def preferences_for_cleanup(
        self, now: datetime
    ) -> tuple[list[UserPreference], list[UserPreference]]: ...
    def procedure_version(
        self, memory_id: str, *, version: str | None = None
    ) -> MemoryProcedureVersion | None: ...
    def add_procedure_version(self, version: MemoryProcedureVersion) -> MemoryProcedureVersion: ...
    def procedure_versions_for_tool(self, tool_name: str) -> list[MemoryProcedureVersion]: ...
    def add_procedure_validation(
        self, validation: MemoryProcedureValidation
    ) -> MemoryProcedureValidation: ...
    def add_consent(self, consent: MemoryConsent) -> MemoryConsent: ...
    def add_preference(self, preference: UserPreference) -> UserPreference: ...
    def get_preference(self, preference_id: str) -> UserPreference | None: ...
    def active_preference_key(self, key: str) -> UserPreference | None: ...
    def list_preferences(self, **filters: object) -> tuple[list[UserPreference], int]: ...
    def delete_preference(self, preference: UserPreference) -> None: ...
    def related_history(self, memory: Memory) -> list[tuple[MemoryEvidence, object]]: ...


class SqlAlchemyMemoryStore:
    """Adapter that exposes the repository through the MemoryStore contract."""

    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    def add_memory(self, memory: Memory) -> Memory:
        return self._repository.add_memory(memory)

    def get_memory(self, memory_id: str) -> Memory | None:
        return self._repository.get_memory(memory_id)

    def list_memories(self, **filters: object) -> tuple[list[Memory], int]:
        return self._repository.list_memories(**filters)  # type: ignore[arg-type]

    def semantic_conflicts(
        self, *, subject_type: str, subject_id: str, predicate: str
    ) -> list[Memory]:
        return self._repository.semantic_conflicts(
            subject_type=subject_type,
            subject_id=subject_id,
            predicate=predicate,
        )

    def record_exists(self, evidence_type: str, record_id: str) -> bool:
        return self._repository.record_exists(evidence_type, record_id)

    def add_evidence(self, evidence: MemoryEvidence) -> MemoryEvidence:
        return self._repository.add_evidence(evidence)

    def evidence_for(self, memory_id: str) -> list[MemoryEvidence]:
        return self._repository.evidence_for(memory_id)

    def add_revision(self, revision: MemoryRevision) -> MemoryRevision:
        return self._repository.add_revision(revision)

    def revisions_for(self, memory_id: str) -> list[MemoryRevision]:
        return self._repository.revisions_for(memory_id)

    def add_access_log(self, entry: MemoryAccessLog) -> MemoryAccessLog:
        return self._repository.add_access_log(entry)

    def delete_memory(self, memory: Memory) -> None:
        self._repository.delete_memory(memory)

    def memories_for_cleanup(self, now: datetime) -> tuple[list[Memory], list[Memory]]:
        return self._repository.memories_for_cleanup(now)

    def preferences_for_cleanup(
        self,
        now: datetime,
    ) -> tuple[list[UserPreference], list[UserPreference]]:
        return self._repository.preferences_for_cleanup(now)

    def procedure_version(
        self, memory_id: str, *, version: str | None = None
    ) -> MemoryProcedureVersion | None:
        return self._repository.procedure_version(memory_id, version=version)

    def add_procedure_version(self, version: MemoryProcedureVersion) -> MemoryProcedureVersion:
        return self._repository.add_procedure_version(version)

    def procedure_versions_for_tool(self, tool_name: str) -> list[MemoryProcedureVersion]:
        return self._repository.procedure_versions_for_tool(tool_name)

    def add_procedure_validation(
        self, validation: MemoryProcedureValidation
    ) -> MemoryProcedureValidation:
        return self._repository.add_procedure_validation(validation)

    def add_consent(self, consent: MemoryConsent) -> MemoryConsent:
        return self._repository.add_consent(consent)

    def add_preference(self, preference: UserPreference) -> UserPreference:
        return self._repository.add_preference(preference)

    def get_preference(self, preference_id: str) -> UserPreference | None:
        return self._repository.get_preference(preference_id)

    def active_preference_key(self, key: str) -> UserPreference | None:
        return self._repository.active_preference_key(key)

    def list_preferences(self, **filters: object) -> tuple[list[UserPreference], int]:
        return self._repository.list_preferences(**filters)  # type: ignore[arg-type]

    def delete_preference(self, preference: UserPreference) -> None:
        self._repository.delete_preference(preference)

    def related_history(self, memory: Memory) -> list[tuple[MemoryEvidence, object]]:
        return self._repository.related_history(memory)


__all__ = ["MemoryStore", "SqlAlchemyMemoryStore"]
