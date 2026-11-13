import asyncio
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from arvuno_core.memory.errors import (
    MemoryConflictError,
    MemoryNotFoundError,
    MemoryValidationError,
    PreferenceNotFoundError,
)
from arvuno_core.memory.models import (
    HistoryReference,
    MemoryEvidenceView,
    MemoryGraph,
    MemoryGraphEdge,
    MemoryGraphNode,
    MemoryRetrievalResult,
    MemoryRevisionView,
    MemoryView,
    PreferenceView,
)
from arvuno_core.memory.store import MemoryStore, SqlAlchemyMemoryStore
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
    ToolExecution,
    UserPreference,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork


class MemoryService:
    """Owns durable memory lifecycle, authorization, and retrieval semantics."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def create_memory(
        self,
        request: Any,
        *,
        actor_type: str = "user",
        actor_id: str = "local_user",
    ) -> MemoryView:
        return await asyncio.to_thread(self._create_memory, request, actor_type, actor_id)

    async def list_memories(self, **filters: object) -> tuple[list[MemoryView], int]:
        def execute() -> tuple[list[MemoryView], int]:
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                rows, total = store.list_memories(**filters)
                now = datetime.now(UTC)
                views = []
                expired_count = 0
                for row in rows:
                    if self._expire_if_needed(store, row, now):
                        expired_count += 1
                        continue
                    views.append(_memory_view(row))
                if expired_count:
                    unit_of_work.commit()
                    return views, max(total - expired_count, 0)
                return views, total

        return await asyncio.to_thread(execute)

    async def get_memory(self, memory_id: str) -> MemoryView:
        def execute() -> MemoryView:
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                memory = self._get(store, memory_id)
                self._expire_if_needed(store, memory, datetime.now(UTC))
                unit_of_work.commit()
                return _memory_view(memory)

        return await asyncio.to_thread(execute)

    async def update_memory(
        self,
        memory_id: str,
        request: Any,
        *,
        actor_type: str = "user",
        actor_id: str = "local_user",
    ) -> MemoryView:
        return await asyncio.to_thread(
            self._update_memory, memory_id, request, actor_type, actor_id
        )

    async def correct_memory(
        self,
        memory_id: str,
        request: Any,
        *,
        actor_type: str = "user",
        actor_id: str = "local_user",
    ) -> MemoryView:
        return await asyncio.to_thread(
            self._correct_memory, memory_id, request, actor_type, actor_id
        )

    async def confirm_memory(self, memory_id: str) -> MemoryView:
        def execute() -> MemoryView:
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                memory = self._get(store, memory_id)
                now = datetime.now(UTC)
                if memory.status not in {"active", "corrected", "candidate"}:
                    raise MemoryValidationError("Only a current memory can be confirmed.")
                if memory.source_type != "user":
                    raise MemoryValidationError("Only user statements can be user confirmed.")
                memory.status = "active"
                memory.user_confirmed = True
                memory.verification_status = "verified"
                memory.last_reviewed_at = now
                if memory.source_type == "ai_inference":
                    memory.expires_at = None
                store.add_revision(
                    MemoryRevision(
                        memory_id=memory.id,
                        revision_type="confirm",
                        previous_content=memory.content,
                        changed_fields={"status": "active", "user_confirmed": True},
                        actor_type="user",
                        actor_id="local_user",
                        reason="Explicit user confirmation",
                    )
                )
                store.add_access_log(
                    MemoryAccessLog(
                        memory_id=memory.id,
                        access_type="confirm",
                        query={"memory_id": memory.id},
                    )
                )
                unit_of_work.commit()
                return _memory_view(memory)

        return await asyncio.to_thread(execute)

    async def delete_memory(self, memory_id: str) -> dict[str, str]:
        def execute() -> dict[str, str]:
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                memory = self._get(store, memory_id)
                store.add_access_log(
                    MemoryAccessLog(
                        memory_id=memory.id,
                        access_type="delete",
                        query={"memory_id": memory.id},
                    )
                )
                store.delete_memory(memory)
                unit_of_work.commit()
                return {"id": memory_id, "deleted": "true"}

        return await asyncio.to_thread(execute)

    async def cleanup(self) -> dict[str, int]:
        def execute() -> dict[str, int]:
            now = datetime.now(UTC)
            expired_count = 0
            deleted_count = 0
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                expired, retention = store.memories_for_cleanup(now)
                expired_preferences, retention_preferences = store.preferences_for_cleanup(now)
                for memory in expired:
                    self._expire_if_needed(store, memory, now)
                    expired_count += 1
                for preference in expired_preferences:
                    preference.status = "revoked"
                    preference.superseded_at = now
                    store.add_access_log(
                        MemoryAccessLog(
                            preference_id=preference.id,
                            access_type="expire",
                            query={"reason": "expired"},
                        )
                    )
                    expired_count += 1
                for memory in retention:
                    store.add_access_log(
                        MemoryAccessLog(
                            memory_id=memory.id,
                            access_type="delete",
                            query={"reason": "retention_expired"},
                        )
                    )
                    store.delete_memory(memory)
                    deleted_count += 1
                for preference in retention_preferences:
                    store.delete_preference(preference)
                    deleted_count += 1
                unit_of_work.commit()
            return {"expired": expired_count, "deleted": deleted_count}

        return await asyncio.to_thread(execute)

    async def create_procedure_version(self, memory_id: str, request: Any) -> dict[str, Any]:
        def execute() -> dict[str, Any]:
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                memory = self._get(store, memory_id)
                if memory.memory_type != "procedural":
                    raise MemoryValidationError("Procedure versions require procedural memory.")
                if store.procedure_version(memory.id, version=request.version) is not None:
                    raise MemoryValidationError("The procedure version already exists.")
                version = MemoryProcedureVersion(
                    memory_id=memory.id,
                    version=request.version,
                    tool_name=request.tool_name,
                    steps=request.steps,
                    input_schema=request.input_schema,
                    output_schema=request.output_schema,
                    risk_level=request.risk_level,
                    status="testing",
                    required_successes=request.required_successes,
                )
                result = store.add_procedure_version(version)
                unit_of_work.commit()
                return _procedure_version_data(result)

        return await asyncio.to_thread(execute)

    async def record_tool_procedure_validation(
        self,
        *,
        tool_name: str,
        task_id: str | None,
        tool_execution_id: str,
        passed: bool,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        def execute() -> dict[str, Any] | None:
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                candidates = store.procedure_versions_for_tool(tool_name)
                if len(candidates) != 1:
                    return None
                version = candidates[0]
                validation = MemoryProcedureValidation(
                    procedure_version_id=version.id,
                    task_id=task_id,
                    tool_execution_id=tool_execution_id,
                    status="passed" if passed else "failed",
                    result=result,
                    validator_type="tool_executor",
                )
                store.add_procedure_validation(validation)
                if validation.status == "passed":
                    version.successful_validations += 1
                    if (
                        version.status != "validated"
                        and version.successful_validations >= version.required_successes
                    ):
                        version.status = "validated"
                        version.validated_at = datetime.now(UTC)
                        memory = self._get(store, version.memory_id)
                        memory.verification_status = "verified"
                        memory.last_reviewed_at = version.validated_at
                        if memory.status == "candidate":
                            memory.status = "active"
                else:
                    version.failed_validations += 1
                unit_of_work.commit()
                return _procedure_version_data(version)

        return await asyncio.to_thread(execute)

    async def validate_procedure(self, memory_id: str, request: Any) -> dict[str, Any]:
        def execute() -> dict[str, Any]:
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                memory = self._get(store, memory_id)
                version = store.procedure_version(memory.id, version=request.version)
                if version is None or version.status == "retired":
                    raise MemoryValidationError("The procedure version is unavailable.")
                validation = MemoryProcedureValidation(
                    procedure_version_id=version.id,
                    task_id=request.task_id,
                    tool_execution_id=request.tool_execution_id,
                    status=request.status,
                    result=request.result,
                    validator_type=request.validator_type,
                )
                store.add_procedure_validation(validation)
                if validation.status == "passed":
                    version.successful_validations += 1
                    if (
                        version.status != "validated"
                        and version.successful_validations >= version.required_successes
                    ):
                        version.status = "validated"
                        version.validated_at = datetime.now(UTC)
                        memory.verification_status = "verified"
                        memory.last_reviewed_at = version.validated_at
                        if memory.status == "candidate":
                            memory.status = "active"
                        store.add_revision(
                            MemoryRevision(
                                memory_id=memory.id,
                                revision_type="validate",
                                previous_content=memory.content,
                                changed_fields={
                                    "procedure_version": version.version,
                                    "status": memory.status,
                                },
                                actor_type=request.validator_type,
                                actor_id="local_user",
                                reason="Procedure passed the required validations",
                            )
                        )
                else:
                    version.failed_validations += 1
                unit_of_work.commit()
                return _procedure_version_data(version)

        return await asyncio.to_thread(execute)

    async def create_preference(
        self,
        request: Any,
        *,
        actor_type: str = "user",
        actor_id: str = "local_user",
    ) -> PreferenceView:
        return await asyncio.to_thread(self._create_preference, request, actor_type, actor_id)

    async def list_preferences(self, **filters: object) -> tuple[list[PreferenceView], int]:
        def execute() -> tuple[list[PreferenceView], int]:
            with self._unit_of_work_factory() as unit_of_work:
                rows, total = self._store(unit_of_work).list_preferences(**filters)
                return [_preference_view(row) for row in rows], total

        return await asyncio.to_thread(execute)

    async def get_preference(self, preference_id: str) -> PreferenceView:
        def execute() -> PreferenceView:
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                preference = self._preference(store, preference_id)
                store.add_access_log(
                    MemoryAccessLog(
                        preference_id=preference.id,
                        access_type="read",
                        query={"preference_id": preference.id},
                    )
                )
                unit_of_work.commit()
                return _preference_view(preference)

        return await asyncio.to_thread(execute)

    async def update_preference(self, preference_id: str, request: Any) -> PreferenceView:
        def execute() -> PreferenceView:
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                preference = self._preference(store, preference_id)
                if preference.status == "revoked":
                    raise MemoryValidationError("A revoked preference cannot be updated.")
                changed: dict[str, Any] = {}
                for field in ("value", "category", "description", "scope"):
                    incoming = getattr(request, field)
                    if incoming is not None and incoming != getattr(preference, field):
                        changed[field] = incoming
                        setattr(preference, field, incoming)
                if request.expires_at is not None:
                    changed["expires_at"] = request.expires_at
                    preference.expires_at = request.expires_at
                if changed:
                    store.add_access_log(
                        MemoryAccessLog(
                            preference_id=preference.id,
                            access_type="update",
                            query={"changed_fields": sorted(changed)},
                        )
                    )
                unit_of_work.commit()
                return _preference_view(preference)

        return await asyncio.to_thread(execute)

    async def confirm_preference(self, preference_id: str) -> PreferenceView:
        def execute() -> PreferenceView:
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                preference = self._preference(store, preference_id)
                if preference.status == "revoked":
                    raise MemoryValidationError("A revoked preference cannot be confirmed.")
                if not preference.confirmed:
                    preference.confirmed = True
                    preference.confirmed_at = datetime.now(UTC)
                    preference.status = "active"
                    store.add_access_log(
                        MemoryAccessLog(
                            preference_id=preference.id,
                            access_type="confirm",
                            query={"preference_id": preference.id},
                        )
                    )
                unit_of_work.commit()
                return _preference_view(preference)

        return await asyncio.to_thread(execute)

    async def delete_preference(self, preference_id: str) -> dict[str, str]:
        def execute() -> dict[str, str]:
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                preference = self._preference(store, preference_id)
                store.add_access_log(
                    MemoryAccessLog(
                        preference_id=preference.id,
                        access_type="delete",
                        query={"preference_id": preference.id},
                    )
                )
                store.delete_preference(preference)
                unit_of_work.commit()
                return {"id": preference_id, "deleted": "true"}

        return await asyncio.to_thread(execute)

    async def retrieve(self, request: Any) -> MemoryRetrievalResult:
        def execute() -> MemoryRetrievalResult:
            now = datetime.now(UTC)
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                memories: list[Memory] = []
                preferences: list[UserPreference] = []
                if request.question_type in {"preference", "any"}:
                    preferences, _ = store.list_preferences(status="active")
                    preferences = self._live_preferences(preferences, now)
                    preferences = [
                        preference
                        for preference in preferences
                        if preference.retention_until is None or preference.retention_until > now
                    ]
                for memory_type in self._requested_types(request.question_type):
                    rows, _ = store.list_memories(
                        memory_type=memory_type,
                        status="current",
                        keyword=request.query or None,
                        page_size=100,
                    )
                    scored: list[tuple[float, Memory]] = []
                    for memory in rows:
                        if self._expire_if_needed(store, memory, now):
                            continue
                        if request.question_type == "procedure":
                            version = store.procedure_version(memory.id)
                            if version is None or version.status != "validated":
                                continue
                        if request.question_type == "task_record":
                            evidence_types = {
                                item.evidence_type for item in store.evidence_for(memory.id)
                            }
                            if memory.task_id is None and "task" not in evidence_types:
                                continue
                        score = self._score_memory(memory, request.query or "")
                        if score > 0:
                            scored.append((score, memory))
                    scored.sort(
                        key=lambda item: (-item[0], -item[1].importance, item[1].id),
                    )
                    memories.extend(memory for _, memory in scored)

                references: list[MemoryEvidenceView] = []
                for memory in memories:
                    store.add_access_log(
                        MemoryAccessLog(
                            memory_id=memory.id,
                            access_type="retrieve",
                            query={
                                "question_type": request.question_type,
                                "query": request.query,
                            },
                        )
                    )
                    references.extend(_evidence_views(store.evidence_for(memory.id)))
                unit_of_work.commit()
                return MemoryRetrievalResult(
                    question_type=request.question_type,
                    query=request.query,
                    memories=[_memory_view(item) for item in memories],
                    preferences=[_preference_view(item) for item in preferences],
                    source_references=references,
                    retrieved_at=now,
                )

        return await asyncio.to_thread(execute)

    async def compress_memories(self, request: Any) -> tuple[MemoryView, list[str]]:
        def execute() -> tuple[MemoryView, list[str]]:
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                memories = self._operation_sources(store, request.memory_ids, "episodic")
                now = datetime.now(UTC)
                summary = request.summary or "; ".join(
                    f"{memory.title}: {memory.summary or memory.content}"[:400]
                    for memory in memories
                )
                content = "Compressed episodic memory candidate.\n" + "\n".join(
                    f"- {memory.title}: {memory.content}"[:800] for memory in memories
                )
                candidate = self._candidate_from_sources(
                    memories,
                    memory_type="episodic",
                    title=request.title or f"Compressed: {memories[0].title}",
                    content=content,
                    summary=summary,
                    keywords={keyword for memory in memories for keyword in memory.keywords},
                    expires_at=now + timedelta(days=request.expires_in_days),
                    operation="compress",
                )
                added = store.add_memory(candidate)
                self._copy_operation_evidence(store, added, memories)
                self._record_operation(store, added, memories, "compress")
                unit_of_work.commit()
                return _memory_view(added), [memory.id for memory in memories]

        return await asyncio.to_thread(execute)

    async def distill_memories(self, request: Any) -> tuple[MemoryView, list[str]]:
        def execute() -> tuple[MemoryView, list[str]]:
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                memories = self._operation_sources(store, request.memory_ids, "episodic")
                unconfirmed = [
                    memory.id
                    for memory in memories
                    if not memory.user_confirmed or memory.verification_status != "verified"
                ]
                if unconfirmed:
                    raise MemoryValidationError(
                        "Knowledge distillation requires confirmed episodic memories.",
                        {"memory_ids": unconfirmed},
                    )
                statement_complete = all(
                    [
                        request.subject_type,
                        request.subject_id,
                        request.predicate,
                        request.object_value is not None,
                    ]
                )
                if not statement_complete:
                    raise MemoryValidationError(
                        "A distilled semantic candidate requires a complete "
                        "subject-predicate-object statement."
                    )
                now = datetime.now(UTC)
                content = (
                    f"{request.subject_type} {request.subject_id} {request.predicate} "
                    f"{request.object_value}. Derived from: "
                    + "; ".join(memory.title for memory in memories)
                )
                summary = request.summary or f"Derived from {len(memories)} confirmed records."
                candidate = self._candidate_from_sources(
                    memories,
                    memory_type="semantic",
                    title=request.title or f"Distilled: {request.subject_id}",
                    content=content,
                    summary=summary,
                    keywords={keyword for memory in memories for keyword in memory.keywords},
                    expires_at=now + timedelta(days=request.expires_in_days),
                    operation="distill",
                )
                candidate.subject_type = request.subject_type
                candidate.subject_id = request.subject_id
                candidate.predicate = request.predicate
                candidate.object_value = request.object_value
                conflicts = store.semantic_conflicts(
                    subject_type=request.subject_type,
                    subject_id=request.subject_id,
                    predicate=request.predicate,
                )
                conflicting = [
                    item.id
                    for item in conflicts
                    if item.id not in set(request.memory_ids)
                    and item.object_value != request.object_value
                ]
                if conflicting:
                    raise MemoryConflictError(conflicting)
                added = store.add_memory(candidate)
                self._copy_operation_evidence(store, added, memories)
                self._record_operation(store, added, memories, "distill")
                unit_of_work.commit()
                return _memory_view(added), [memory.id for memory in memories]

        return await asyncio.to_thread(execute)

    async def memory_graph(self, request: Any) -> MemoryGraph:
        def execute() -> MemoryGraph:
            now = datetime.now(UTC)
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                rows, total = store.list_memories(
                    memory_type=request.memory_type,
                    status="current",
                    keyword=request.keyword,
                    space_id=request.space_id,
                    entity_id=request.entity_id,
                    page_size=request.max_memories,
                )
                nodes: list[MemoryGraphNode] = []
                edges: list[MemoryGraphEdge] = []
                seen_nodes: set[str] = set()
                seen_edges: set[tuple[str, str, str]] = set()

                def add_node(node: MemoryGraphNode) -> None:
                    if node.id not in seen_nodes:
                        nodes.append(node)
                        seen_nodes.add(node.id)

                def add_edge(source: str, target: str, relation: str) -> None:
                    key = (source, target, relation)
                    if key not in seen_edges:
                        edges.append(
                            MemoryGraphEdge(source=source, target=target, relation=relation)
                        )
                        seen_edges.add(key)

                for memory in rows:
                    if self._expire_if_needed(store, memory, now):
                        continue
                    memory_key = f"memory:{memory.id}"
                    add_node(
                        MemoryGraphNode(
                            id=memory_key,
                            node_type="memory",
                            label=memory.title,
                            memory_type=memory.memory_type,
                            status=memory.status,
                        )
                    )
                    if memory.space_id:
                        space_key = f"space:{memory.space_id}"
                        add_node(
                            MemoryGraphNode(
                                id=space_key,
                                node_type="space",
                                label=memory.space_id,
                                status="reference",
                            )
                        )
                        add_edge(memory_key, space_key, "located_in")
                    if memory.entity_id:
                        entity_key = f"entity:{memory.entity_id}"
                        add_node(
                            MemoryGraphNode(
                                id=entity_key,
                                node_type="entity",
                                label=memory.entity_id,
                                status="reference",
                            )
                        )
                        add_edge(memory_key, entity_key, "about")
                    if memory.task_id:
                        task_key = f"task:{memory.task_id}"
                        add_node(
                            MemoryGraphNode(
                                id=task_key,
                                node_type="task",
                                label=memory.task_id,
                                status="reference",
                            )
                        )
                        add_edge(task_key, memory_key, "recorded_by")
                    store.add_access_log(
                        MemoryAccessLog(
                            memory_id=memory.id,
                            access_type="read",
                            query={"view": "graph"},
                        )
                    )
                unit_of_work.commit()
                return MemoryGraph(
                    nodes=nodes,
                    edges=edges,
                    truncated=total > len(rows),
                    generated_at=now,
                )

        return await asyncio.to_thread(execute)

    async def related_history(self, memory_id: str) -> list[HistoryReference]:
        def execute() -> list[HistoryReference]:
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                memory = self._get(store, memory_id)
                rows = store.related_history(memory)
                store.add_access_log(
                    MemoryAccessLog(
                        memory_id=memory.id,
                        access_type="read",
                        query={"related_history": True},
                    )
                )
                unit_of_work.commit()
                return [
                    HistoryReference(
                        evidence=_evidence_view(evidence),
                        record=_record_summary(record),
                    )
                    for evidence, record in rows
                ]

        return await asyncio.to_thread(execute)

    async def revisions(self, memory_id: str) -> list[MemoryRevisionView]:
        def execute() -> list[MemoryRevisionView]:
            with self._unit_of_work_factory() as unit_of_work:
                store = self._store(unit_of_work)
                memory = self._get(store, memory_id)
                return [
                    MemoryRevisionView.model_validate(item)
                    for item in store.revisions_for(memory.id)
                ]

        return await asyncio.to_thread(execute)

    @staticmethod
    def _store(unit_of_work: SqlAlchemyUnitOfWork) -> MemoryStore:
        if unit_of_work.memories is None:
            raise RuntimeError("The memory repository is unavailable.")
        return SqlAlchemyMemoryStore(unit_of_work.memories)

    @staticmethod
    def _operation_sources(
        store: MemoryStore,
        memory_ids: list[str],
        expected_type: str,
    ) -> list[Memory]:
        unique_ids = list(dict.fromkeys(memory_ids))
        memories: dict[str, Memory] = {}
        missing: list[str] = []
        invalid_ids: list[str] = []
        for memory_id in unique_ids:
            memory = store.get_memory(memory_id)
            if memory is None:
                missing.append(memory_id)
                continue
            if memory.memory_type != expected_type or memory.status not in {
                "active",
                "candidate",
                "corrected",
            }:
                invalid_ids.append(memory_id)
                continue
            memories[memory_id] = memory
        if missing:
            raise MemoryValidationError(
                "One or more operation source memories were not found.",
                {"memory_ids": missing},
            )
        if invalid_ids:
            raise MemoryValidationError(
                "One or more operation source memories are not usable.",
                {"memory_ids": invalid_ids},
            )
        return [memories[memory_id] for memory_id in unique_ids]

    @staticmethod
    def _candidate_from_sources(
        memories: list[Memory],
        *,
        memory_type: str,
        title: str,
        content: str,
        summary: str,
        keywords: set[str],
        expires_at: datetime,
        operation: str,
    ) -> Memory:
        first = memories[0]
        same_space = len({memory.space_id for memory in memories}) == 1
        same_entity = len({memory.entity_id for memory in memories}) == 1
        same_task = len({memory.task_id for memory in memories}) == 1
        same_owner = len({memory.owner_id for memory in memories}) == 1
        same_access = len({memory.access_level for memory in memories}) == 1
        return Memory(
            memory_type=memory_type,
            title=title[:255],
            content=content,
            summary=summary,
            keywords=sorted(keyword for keyword in keywords if keyword)[:30],
            importance=max(memory.importance for memory in memories),
            source_type="system",
            source_id=f"memory_{operation}:{first.id}",
            user_confirmed=False,
            status="candidate",
            confidence=0.5,
            verification_status="unverified",
            owner_id=first.owner_id if same_owner else "local_user",
            access_level=first.access_level if same_access else "owner_only",
            scope={"operation": operation, "source_memory_ids": [item.id for item in memories]},
            space_id=first.space_id if same_space else None,
            entity_id=first.entity_id if same_entity else None,
            task_id=first.task_id if same_task else None,
            valid_from=datetime.now(UTC),
            expires_at=expires_at,
        )

    @staticmethod
    def _copy_operation_evidence(
        store: MemoryStore,
        candidate: Memory,
        memories: list[Memory],
    ) -> None:
        added = 0
        for memory in memories:
            for evidence in store.evidence_for(memory.id):
                store.add_evidence(
                    MemoryEvidence(
                        memory_id=candidate.id,
                        evidence_type=evidence.evidence_type,
                        evidence_id=evidence.evidence_id,
                        source_type=evidence.source_type,
                        source_record_id=evidence.source_record_id,
                        trust_level=evidence.trust_level,
                        snapshot=dict(evidence.snapshot),
                        occurred_at=evidence.occurred_at,
                    )
                )
                added += 1
        candidate.scope["copied_evidence_count"] = added

    @staticmethod
    def _record_operation(
        store: MemoryStore,
        candidate: Memory,
        memories: list[Memory],
        operation: str,
    ) -> None:
        store.add_revision(
            MemoryRevision(
                memory_id=candidate.id,
                revision_type="create",
                previous_content=candidate.content,
                changed_fields={"status": candidate.status, "operation": operation},
                actor_type="system",
                actor_id="memory_governance",
                reason=f"{operation.capitalize()} generated a reviewable candidate.",
            )
        )
        for memory in memories:
            store.add_access_log(
                MemoryAccessLog(
                    memory_id=memory.id,
                    access_type="update",
                    query={"operation": operation, "candidate_memory_id": candidate.id},
                )
            )

    @staticmethod
    def _get(store: MemoryStore, memory_id: str) -> Memory:
        memory = store.get_memory(memory_id)
        if memory is None:
            raise MemoryNotFoundError()
        return memory

    @staticmethod
    def _preference(store: MemoryStore, preference_id: str) -> UserPreference:
        preference = store.get_preference(preference_id)
        if preference is None:
            raise PreferenceNotFoundError()
        return preference

    @staticmethod
    def _expire_if_needed(store: MemoryStore, memory: Memory, now: datetime) -> bool:
        if memory.expires_at is None or memory.status not in {"active", "candidate", "corrected"}:
            return False
        expires_at = memory.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at > now:
            return False
        memory.status = "expired"
        store.add_revision(
            MemoryRevision(
                memory_id=memory.id,
                revision_type="expire",
                previous_content=memory.content,
                changed_fields={"status": "expired"},
                actor_type="system",
                actor_id="lifecycle",
            )
        )
        store.add_access_log(
            MemoryAccessLog(
                memory_id=memory.id,
                access_type="expire",
                query={"reason": "expired"},
            )
        )
        return True

    @staticmethod
    def _score_memory(memory: Memory, query: str) -> float:
        """Return a bounded lexical relevance score for hybrid retrieval."""

        terms = [term.casefold() for term in re.split(r"\s+", query.strip()) if term]
        if not terms:
            return 1.0
        title = memory.title.casefold()
        content = memory.content.casefold()
        summary = (memory.summary or "").casefold()
        keywords = " ".join(memory.keywords).casefold()
        subject = (
            f"{memory.subject_type or ''} {memory.subject_id or ''} {memory.predicate or ''}"
        ).casefold()
        object_value = str(memory.object_value or "").casefold()
        score = 0.0
        for term in terms:
            term_score = 0.0
            if term == title:
                term_score += 5.0
            elif term in title:
                term_score += 3.0
            if term in content:
                term_score += 2.0
            if term in summary:
                term_score += 1.0
            if term in keywords:
                term_score += 1.5
            if term in subject:
                term_score += 1.0
            if term in object_value:
                term_score += 1.0
            if term_score == 0:
                return 0.0
            score += term_score
        return score * (1.0 + memory.importance / 100.0)

    @staticmethod
    def _requested_types(question_type: Any) -> list[str]:
        mapping = {
            "semantic_fact": ["semantic"],
            "spatial_fact": ["semantic"],
            "historical_event": ["episodic"],
            "task_record": ["episodic"],
            "procedure": ["procedural"],
        }
        if question_type == "any":
            return ["episodic", "semantic", "procedural"]
        return mapping.get(question_type, [])

    @staticmethod
    def _live_preferences(
        preferences: list[UserPreference],
        now: datetime,
    ) -> list[UserPreference]:
        result: list[UserPreference] = []
        for preference in preferences:
            if preference.expires_at is not None:
                expires_at = preference.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if expires_at <= now:
                    continue
            result.append(preference)
        return result

    def _create_memory(
        self,
        request: Any,
        actor_type: str,
        actor_id: str,
    ) -> MemoryView:
        now = datetime.now(UTC)
        if request.source_type == "ai_inference":
            if request.status not in {None, "candidate"}:
                raise MemoryValidationError("AI inference must start as a candidate.")
            if request.user_confirmed:
                raise MemoryValidationError("AI inference cannot be pre-confirmed.")
            expires_at = request.expires_at or now + timedelta(days=7)
            status = "candidate"
            verification_status = "unverified"
        else:
            if request.status == "candidate":
                status = "candidate"
                verification_status = "unverified"
            else:
                status = "active" if request.user_confirmed else "candidate"
                verification_status = "verified" if request.user_confirmed else "unverified"
            if request.user_confirmed and request.source_type != "user":
                raise MemoryValidationError("Only user statements can be user confirmed.")
            expires_at = request.expires_at

        if status == "active" and request.expires_at is not None:
            expires_at = request.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                raise MemoryValidationError("The expiration time must be in the future.")
        if request.memory_type == "procedural" and not request.subject_id:
            raise MemoryValidationError("Procedural memory requires a procedure subject.")

        with self._unit_of_work_factory() as unit_of_work:
            store = self._store(unit_of_work)
            if (
                request.memory_type == "semantic"
                and request.subject_type
                and request.subject_id
                and request.predicate
            ):
                conflicts = store.semantic_conflicts(
                    subject_type=request.subject_type,
                    subject_id=request.subject_id,
                    predicate=request.predicate,
                )
                conflicting = [
                    item.id for item in conflicts if item.object_value != request.object_value
                ]
                if conflicting:
                    raise MemoryConflictError(conflicting)

            memory = Memory(
                memory_type=request.memory_type,
                title=request.title,
                content=request.content,
                summary=request.summary,
                keywords=request.keywords,
                importance=request.importance,
                source_type=request.source_type,
                source_id=request.source_id,
                user_confirmed=request.user_confirmed,
                status=status,
                confidence=request.confidence,
                verification_status=verification_status,
                owner_id=request.owner_id,
                access_level=request.access_level,
                scope=request.scope,
                environment_id=request.environment_id,
                space_id=request.space_id,
                entity_id=request.entity_id,
                conversation_id=request.conversation_id,
                task_id=request.task_id,
                subject_type=request.subject_type,
                subject_id=request.subject_id,
                predicate=request.predicate,
                object_value=request.object_value,
                valid_from=request.valid_from or now,
                expires_at=expires_at,
                retention_until=request.retention_until,
            )
            store.add_memory(memory)
            for evidence in request.evidence:
                self._add_evidence(store, memory, evidence)
            store.add_revision(
                MemoryRevision(
                    memory_id=memory.id,
                    revision_type="create",
                    previous_content=request.content,
                    changed_fields={"status": status},
                    actor_type=actor_type,
                    actor_id=actor_id,
                )
            )
            store.add_access_log(
                MemoryAccessLog(
                    memory_id=memory.id,
                    access_type="create",
                    actor_type=actor_type,
                    actor_id=actor_id,
                    query={"source_type": request.source_type},
                )
            )
            unit_of_work.commit()
            return _memory_view(memory)

    def _add_evidence(self, store: MemoryStore, memory: Memory, evidence: Any) -> None:
        if evidence.evidence_id is not None and not store.record_exists(
            evidence.evidence_type,
            evidence.evidence_id,
        ):
            raise MemoryValidationError(
                "The referenced history record does not exist.",
                {"evidence_type": evidence.evidence_type, "evidence_id": evidence.evidence_id},
            )
        store.add_evidence(
            MemoryEvidence(
                memory_id=memory.id,
                evidence_type=evidence.evidence_type,
                evidence_id=evidence.evidence_id,
                source_type=evidence.source_type,
                source_record_id=evidence.source_record_id,
                trust_level=evidence.trust_level,
                snapshot=evidence.snapshot,
                occurred_at=evidence.occurred_at,
            )
        )

    def _update_memory(
        self,
        memory_id: str,
        request: Any,
        actor_type: str,
        actor_id: str,
    ) -> MemoryView:
        with self._unit_of_work_factory() as unit_of_work:
            store = self._store(unit_of_work)
            memory = self._get(store, memory_id)
            if memory.status not in {"active", "corrected", "candidate"}:
                raise MemoryValidationError("Only a current memory can be updated.")
            original_content = memory.content
            changed: dict[str, Any] = {}
            for field in (
                "title",
                "content",
                "summary",
                "keywords",
                "importance",
                "scope",
                "space_id",
                "entity_id",
                "retention_until",
            ):
                incoming = getattr(request, field)
                if incoming is not None and incoming != getattr(memory, field):
                    changed[field] = incoming
                    setattr(memory, field, incoming)
            if request.expires_at is not None:
                changed["expires_at"] = request.expires_at
                memory.expires_at = request.expires_at
            changed = _json_safe(changed)
            if request.status == "archived":
                changed["status"] = "archived"
                memory.status = "archived"
            if changed:
                memory.last_reviewed_at = datetime.now(UTC)
                store.add_revision(
                    MemoryRevision(
                        memory_id=memory.id,
                        revision_type="update",
                        previous_content=request.previous_content or original_content,
                        changed_fields=changed,
                        actor_type=actor_type,
                        actor_id=actor_id,
                        reason=request.reason,
                    )
                )
                store.add_access_log(
                    MemoryAccessLog(
                        memory_id=memory.id,
                        access_type="update",
                        query={"changed_fields": sorted(changed)},
                    )
                )
            unit_of_work.commit()
            return _memory_view(memory)

    def _correct_memory(
        self,
        memory_id: str,
        request: Any,
        actor_type: str,
        actor_id: str,
    ) -> MemoryView:
        with self._unit_of_work_factory() as unit_of_work:
            store = self._store(unit_of_work)
            memory = self._get(store, memory_id)
            if memory.status not in {"active", "corrected", "candidate"}:
                raise MemoryValidationError("Only a current memory can be corrected.")
            source_changed = False
            if memory.source_type == "ai_inference":
                if actor_type != "user":
                    raise MemoryValidationError("An AI inference can be corrected only by a user.")
                # The corrected statement now originates from the user; retain the
                # prior source in the revision while allowing the candidate to survive.
                memory.source_type = "user"
                memory.source_id = actor_id
                memory.expires_at = None
                source_changed = True
            previous_content = memory.content
            previous_summary = memory.summary
            memory.content = request.content
            memory.summary = request.summary
            memory.status = "corrected"
            memory.correction_count += 1
            memory.last_reviewed_at = datetime.now(UTC)
            if actor_type == "user":
                memory.verification_status = "verified"
                memory.user_confirmed = True
            changed_fields = {"content": request.content, "status": "corrected"}
            if source_changed:
                changed_fields.update(
                    {
                        "source_type": "user",
                        "source_id": actor_id,
                        "expires_at": None,
                    }
                )
            store.add_revision(
                MemoryRevision(
                    memory_id=memory.id,
                    revision_type="correct",
                    previous_content=previous_content,
                    previous_summary=previous_summary,
                    changed_fields=changed_fields,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason=request.reason,
                )
            )
            store.add_access_log(
                MemoryAccessLog(
                    memory_id=memory.id,
                    access_type="correct",
                    actor_type=actor_type,
                    actor_id=actor_id,
                )
            )
            unit_of_work.commit()
            return _memory_view(memory)

    def _create_preference(
        self,
        request: Any,
        actor_type: str,
        actor_id: str,
    ) -> PreferenceView:
        if request.source_type != "user":
            raise MemoryValidationError("Preferences require an explicit user source.")
        now = datetime.now(UTC)
        confirmed_at = request.confirmed_at
        confirmed = request.confirmed or confirmed_at is not None
        if confirmed and confirmed_at is None:
            confirmed_at = now
        status = "active" if confirmed else "draft"
        with self._unit_of_work_factory() as unit_of_work:
            store = self._store(unit_of_work)
            if store.active_preference_key(request.key) is not None:
                raise MemoryConflictError([])
            consent = MemoryConsent(
                subject_id=actor_id,
                grant_type="preference_store",
                statement=request.consent_statement,
                scope=request.scope,
                granted_at=confirmed_at or now,
                actor_type=actor_type,
            )
            store.add_consent(consent)
            preference = UserPreference(
                key=request.key,
                value=request.value,
                category=request.category,
                description=request.description,
                source=request.source_type,
                source_type=request.source_type,
                source_record_id=request.source_record_id,
                status=status,
                scope=request.scope,
                conversation_id=request.conversation_id,
                consent_id=consent.id,
                confirmed=confirmed,
                confirmed_at=confirmed_at,
                valid_from=request.valid_from or now,
                expires_at=request.expires_at,
                retention_until=request.retention_until,
            )
            store.add_preference(preference)
            store.add_access_log(
                MemoryAccessLog(
                    preference_id=preference.id,
                    access_type="create",
                    actor_type=actor_type,
                    actor_id=actor_id,
                    query={"status": status},
                )
            )
            unit_of_work.commit()
            return _preference_view(preference)


def _memory_view(memory: Memory) -> MemoryView:
    return MemoryView.model_validate(memory)


def _preference_view(preference: UserPreference) -> PreferenceView:
    return PreferenceView.model_validate(preference)


def _evidence_views(rows: list[MemoryEvidence]) -> list[MemoryEvidenceView]:
    return [_evidence_view(row) for row in rows]


def _evidence_view(evidence: MemoryEvidence) -> MemoryEvidenceView:
    return MemoryEvidenceView(
        id=evidence.id,
        evidence_type=evidence.evidence_type,
        evidence_id=evidence.evidence_id,
        source_type=evidence.source_type,
        source_record_id=evidence.source_record_id,
        trust_level=evidence.trust_level,
        snapshot=evidence.snapshot,
        occurred_at=evidence.occurred_at,
        created_at=evidence.created_at,
    )


def _procedure_version_data(version: MemoryProcedureVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "memory_id": version.memory_id,
        "version": version.version,
        "tool_name": version.tool_name,
        "status": version.status,
        "required_successes": version.required_successes,
        "successful_validations": version.successful_validations,
        "failed_validations": version.failed_validations,
        "validated_at": version.validated_at,
    }


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.isoformat() if isinstance(item, datetime) else item for key, item in value.items()
    }


def _record_summary(record: object | None) -> dict[str, Any] | None:
    if record is None:
        return None
    if isinstance(record, Observation):
        return {
            "record_type": "observation",
            "id": record.observation_id,
            "entity_id": record.entity_id,
            "space_id": record.space_id,
            "attribute": record.attribute,
            "value": record.normalized_value,
            "received_at": record.received_at,
        }
    if isinstance(record, Event):
        return {
            "record_type": "event",
            "id": record.id,
            "event_type": record.event_type,
            "subject_type": record.subject_type,
            "subject_id": record.subject_id,
            "occurred_at": record.occurred_at,
        }
    if isinstance(record, Task):
        return {
            "record_type": "task",
            "id": record.id,
            "title": record.title,
            "status": record.status,
            "created_at": record.created_at,
            "completed_at": record.completed_at,
        }
    if isinstance(record, ConversationMessage):
        return {
            "record_type": "conversation_message",
            "id": record.id,
            "conversation_id": record.conversation_id,
            "role": record.role,
            "created_at": record.created_at,
        }
    if isinstance(record, EnvironmentSnapshot):
        return {
            "record_type": "environment_snapshot",
            "id": record.id,
            "environment_id": record.environment_id,
            "created_at": record.created_at,
            "context_version": record.context_version,
        }
    if isinstance(record, ToolExecution):
        return {
            "record_type": "tool_execution",
            "id": record.id,
            "tool_id": record.tool_id,
            "task_id": record.task_id,
            "status": record.status,
            "started_at": record.started_at,
        }
    return {
        "record_type": record.__class__.__name__,
        "id": getattr(record, "id", None),
    }


__all__ = ["MemoryService"]
