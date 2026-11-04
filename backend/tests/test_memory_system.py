from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from arvuno_core.app import create_app
from arvuno_core.config import Settings
from arvuno_core.persistence.database import DatabaseManager
from arvuno_core.persistence.models import (
    Conversation,
    ConversationMessage,
    Event,
    MemoryAccessLog,
    MemoryEvidence,
    Task,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork


def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        api_token="test-api-token",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


@pytest.fixture
def manager(tmp_path: Path) -> DatabaseManager:
    test_manager = DatabaseManager(settings(tmp_path))
    test_manager.initialize_database()
    yield test_manager
    test_manager.dispose()


def client_for(manager: DatabaseManager, tmp_path: Path) -> TestClient:
    app = create_app(
        settings(tmp_path),
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(manager.session_factory),
    )
    return TestClient(app)


def session(manager: DatabaseManager) -> Session:
    return manager.session_factory()


def memory_payload(**overrides: object) -> dict[str, object]:
    value = {
        "memory_type": "semantic",
        "title": "Living room light location",
        "content": "The living room ceiling light is above the sofa.",
        "keywords": ["living room", "light"],
        "importance": 3,
        "source_type": "user",
        "source_id": "chat-statement-1",
        "user_confirmed": True,
        "subject_type": "space_object",
        "subject_id": "living-room-ceiling-light",
        "predicate": "located_above",
        "object_value": {"space_id": "sofa"},
    }
    value.update(overrides)
    return value


def preference_payload(**overrides: object) -> dict[str, object]:
    value = {
        "key": "temperature.unit",
        "value": {"unit": "C"},
        "category": "environment",
        "description": "Preferred temperature unit",
        "source_record_id": "conversation-message-1",
        "consent_statement": "Save my temperature unit preference.",
        "confirmed": False,
    }
    value.update(overrides)
    return value


def test_memory_api_requires_authorization(manager: DatabaseManager, tmp_path: Path) -> None:
    client = client_for(manager, tmp_path)

    missing = client.get("/api/memories")
    rejected = client.get("/api/memories", headers={"Authorization": "Bearer wrong-token"})

    assert missing.status_code == 401
    assert rejected.status_code == 401


def test_create_memory_tracks_source_evidence_and_access(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    occurred_at = datetime.now(UTC) - timedelta(hours=1)
    with manager.session_factory() as db:
        db.add(
            Event(
                id="event-1",
                event_type="device_state_changed",
                source="mock",
                payload={"state": "on"},
                occurred_at=occurred_at,
            )
        )
        db.commit()

    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    response = client.post(
        "/api/memories",
        headers=headers,
        json=memory_payload(
            source_type="observation",
            user_confirmed=False,
            evidence=[
                {
                    "evidence_type": "event",
                    "evidence_id": "event-1",
                    "source_type": "event",
                    "source_record_id": "event-1",
                    "trust_level": 0.9,
                    "snapshot": {"state": "on"},
                    "occurred_at": occurred_at.isoformat(),
                }
            ],
        ),
    )

    assert response.status_code == 201
    memory = response.json()["data"]
    assert memory["status"] == "candidate"
    assert memory["verification_status"] == "unverified"
    assert memory["user_confirmed"] is False

    detail = client.get(f"/api/memories/{memory['id']}", headers=headers)
    history = client.get(f"/api/memories/{memory['id']}/history", headers=headers)

    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == memory["id"]
    assert history.status_code == 200
    reference = history.json()["data"][0]
    assert reference["evidence"]["evidence_type"] == "event"
    assert reference["evidence"]["evidence_id"] == "event-1"
    assert reference["evidence"]["source_record_id"] == "event-1"
    assert reference["record"]["record_type"] == "event"

    with manager.session_factory() as db:
        evidence_count = len(list(db.scalars(select(MemoryEvidence))))
        access_types = set(db.scalars(select(MemoryAccessLog.access_type)))

    assert evidence_count == 1
    assert {"create", "read"} <= access_types


def test_create_memory_rejects_missing_history_evidence(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    response = client.post(
        "/api/memories",
        headers=headers,
        json=memory_payload(
            evidence=[
                {
                    "evidence_type": "event",
                    "evidence_id": "missing-event",
                    "source_type": "event",
                }
            ]
        ),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MEMORY_VALIDATION_ERROR"


def test_memory_list_filters_and_retrieval_includes_sources(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    semantic = client.post("/api/memories", headers=headers, json=memory_payload()).json()["data"]
    client.post(
        "/api/memories",
        headers=headers,
        json=memory_payload(
            memory_type="episodic",
            title="Guest visit",
            content="A guest arrived at 7 pm.",
            source_type="event",
            source_id="event-visit",
            user_confirmed=False,
            subject_type=None,
            subject_id=None,
            predicate=None,
            object_value=None,
        ),
    )

    semantic_list = client.get(
        "/api/memories",
        headers=headers,
        params={"memory_type": "semantic", "keyword": "ceiling"},
    )
    episodic_list = client.get(
        "/api/memories",
        headers=headers,
        params={"memory_type": "episodic", "status": "candidate"},
    )
    retrieval = client.post(
        "/api/memory-retrieval",
        headers=headers,
        json={"question_type": "semantic_fact", "query": "living room"},
    )

    assert semantic_list.status_code == 200
    assert semantic_list.json()["total"] == 1
    assert semantic_list.json()["data"][0]["id"] == semantic["id"]
    assert episodic_list.status_code == 200
    assert episodic_list.json()["total"] == 1
    assert retrieval.status_code == 200
    result = retrieval.json()["data"]
    assert [item["id"] for item in result["memories"]] == [semantic["id"]]
    assert result["source_references"] == []


def test_ai_inference_stays_an_expiring_candidate(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    created = client.post(
        "/api/memories",
        headers=headers,
        json=memory_payload(
            source_type="ai_inference",
            source_id="inference-1",
            user_confirmed=False,
        ),
    )
    confirmed = client.post(
        f"/api/memories/{created.json()['data']['id']}/confirm", headers=headers
    )

    assert created.status_code == 201
    assert created.json()["data"]["status"] == "candidate"
    assert created.json()["data"]["expires_at"] is not None
    assert confirmed.status_code == 400


def test_user_correction_promotes_ai_inference_to_user_source(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    memory = client.post(
        "/api/memories",
        headers=headers,
        json=memory_payload(
            source_type="ai_inference",
            source_id="inference-1",
            user_confirmed=False,
        ),
    ).json()["data"]
    response = client.post(
        f"/api/memories/{memory['id']}/correct",
        headers=headers,
        json={"content": "The user corrected this statement.", "reason": "User correction"},
    )

    assert response.status_code == 200
    corrected = response.json()["data"]
    assert corrected["status"] == "corrected"
    assert corrected["source_type"] == "user"
    assert corrected["source_id"] == "local_user"
    assert corrected["expires_at"] is None
    assert corrected["verification_status"] == "verified"
    revisions = client.get(f"/api/memories/{memory['id']}/revisions", headers=headers)
    correction = revisions.json()["data"][0]
    assert correction["changed_fields"]["source_type"] == "user"


def test_update_memory_records_revision(manager: DatabaseManager, tmp_path: Path) -> None:
    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    memory = client.post("/api/memories", headers=headers, json=memory_payload()).json()["data"]
    response = client.patch(
        f"/api/memories/{memory['id']}",
        headers=headers,
        json={"importance": 5, "reason": "User asked to retain this."},
    )
    revisions = client.get(f"/api/memories/{memory['id']}/revisions", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"]["importance"] == 5
    assert revisions.status_code == 200
    assert [item["revision_type"] for item in revisions.json()["data"]][:2] == [
        "update",
        "create",
    ]


def test_confirmed_semantic_conflict_is_rejected(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    first = client.post("/api/memories", headers=headers, json=memory_payload())
    conflict = client.post(
        "/api/memories",
        headers=headers,
        json=memory_payload(
            title="Different location",
            content="The living room ceiling light is above the table.",
            object_value={"space_id": "table"},
        ),
    )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "MEMORY_CONFLICT"


def test_user_correction_updates_status_and_revisions(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    memory = client.post("/api/memories", headers=headers, json=memory_payload()).json()["data"]
    response = client.post(
        f"/api/memories/{memory['id']}/correct",
        headers=headers,
        json={
            "content": "The light is above the reading chair.",
            "reason": "User correction",
        },
    )

    assert response.status_code == 200
    corrected = response.json()["data"]
    assert corrected["status"] == "corrected"
    assert corrected["correction_count"] == 1
    assert corrected["verification_status"] == "verified"


def test_only_user_statements_can_be_confirmed(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    memory = client.post(
        "/api/memories",
        headers=headers,
        json=memory_payload(
            source_type="observation",
            source_id="observation-1",
            user_confirmed=False,
        ),
    ).json()["data"]
    response = client.post(f"/api/memories/{memory['id']}/confirm", headers=headers)

    assert response.status_code == 400


def test_procedure_requires_validations_before_retrieval(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    procedure = client.post(
        "/api/memories",
        headers=headers,
        json=memory_payload(
            memory_type="procedural",
            title="Evening shutdown routine",
            content="Turn off downstairs lights and lock the door.",
            source_type="task",
            source_id="task-1",
            user_confirmed=False,
            subject_type="procedure",
            subject_id="evening_shutdown",
            predicate=None,
            object_value=None,
        ),
    ).json()["data"]
    version_response = client.post(
        f"/api/memories/{procedure['id']}/procedure-versions",
        headers=headers,
        json={
            "version": "1.0",
            "steps": [{"action": "turn_off"}, {"action": "lock"}],
            "required_successes": 2,
        },
    )
    first_pass = client.post(
        f"/api/memories/{procedure['id']}/procedure-validations",
        headers=headers,
        json={"version": "1.0", "status": "passed", "result": {"ok": True}},
    )
    first_retrieval = client.post(
        "/api/memory-retrieval",
        headers=headers,
        json={"question_type": "procedure", "query": "shutdown"},
    )
    second_pass = client.post(
        f"/api/memories/{procedure['id']}/procedure-validations",
        headers=headers,
        json={"version": "1.0", "status": "passed", "result": {"ok": True}},
    )
    validated_retrieval = client.post(
        "/api/memory-retrieval",
        headers=headers,
        json={"question_type": "procedure", "query": "shutdown"},
    )

    assert procedure["verification_status"] == "unverified"
    assert version_response.status_code == 201
    assert first_pass.status_code == 200
    assert first_pass.json()["data"]["successful_validations"] == 1
    assert first_retrieval.json()["data"]["memories"] == []
    assert second_pass.json()["data"]["status"] == "validated"
    assert len(validated_retrieval.json()["data"]["memories"]) == 1


def test_expired_memory_is_hidden_and_cleanup_expires_it(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    memory = client.post(
        "/api/memories",
        headers=headers,
        json=memory_payload(expires_at=(datetime.now(UTC) + timedelta(days=1)).isoformat()),
    ).json()["data"]

    response = client.patch(
        f"/api/memories/{memory['id']}",
        headers=headers,
        json={"expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()},
    )
    listing = client.get("/api/memories", headers=headers)
    retrieval = client.post(
        "/api/memory-retrieval",
        headers=headers,
        json={"question_type": "semantic_fact", "query": "light"},
    )
    cleanup = client.post("/api/memories/cleanup", headers=headers)
    expired_listing = client.get(
        "/api/memories",
        headers=headers,
        params={"status": "expired", "include_expired": True},
    )

    assert response.status_code == 200
    assert listing.json()["total"] == 0
    assert retrieval.json()["data"]["memories"] == []
    assert cleanup.json()["data"]["expired"] == 1
    assert expired_listing.json()["total"] == 1
    assert expired_listing.json()["data"][0]["status"] == "expired"


def test_delete_memory_removes_it_and_related_evidence(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    memory = client.post(
        "/api/memories",
        headers=headers,
        json=memory_payload(
            evidence=[
                {
                    "evidence_type": "user_statement",
                    "source_type": "user",
                    "source_record_id": "chat-statement-1",
                }
            ]
        ),
    ).json()["data"]
    response = client.delete(f"/api/memories/{memory['id']}", headers=headers)
    detail = client.get(f"/api/memories/{memory['id']}", headers=headers)

    with manager.session_factory() as db:
        evidence = list(db.scalars(select(MemoryEvidence)))

    assert response.status_code == 200
    assert response.json()["data"]["deleted"] is True
    assert detail.status_code == 404
    assert evidence == []


def test_preference_requires_explicit_confirmation_before_retrieval(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    created = client.post("/api/memory-preferences", headers=headers, json=preference_payload())
    draft_retrieval = client.post(
        "/api/memory-retrieval",
        headers=headers,
        json={"question_type": "preference", "query": "temperature"},
    )
    memory_id = created.json()["data"]["id"]
    confirmed = client.post(f"/api/memory-preferences/{memory_id}/confirm", headers=headers)
    active_retrieval = client.post(
        "/api/memory-retrieval",
        headers=headers,
        json={"question_type": "preference", "query": "temperature"},
    )

    assert created.status_code == 201
    assert created.json()["data"]["status"] == "draft"
    assert created.json()["data"]["consent_id"] is not None
    assert draft_retrieval.json()["data"]["preferences"] == []
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "active"
    preferences = active_retrieval.json()["data"]["preferences"]
    assert len(preferences) == 1
    assert preferences[0]["source_record_id"] == "conversation-message-1"


def test_preference_update_conflict_delete_and_cleanup(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    first = client.post(
        "/api/memory-preferences",
        headers=headers,
        json=preference_payload(confirmed=True),
    ).json()["data"]
    duplicate = client.post(
        "/api/memory-preferences",
        headers=headers,
        json=preference_payload(
            key="temperature.unit",
            source_record_id="conversation-message-2",
            confirmed=True,
        ),
    )
    updated = client.patch(
        f"/api/memory-preferences/{first['id']}",
        headers=headers,
        json={"value": {"unit": "F"}},
    )
    deleted = client.delete(f"/api/memory-preferences/{first['id']}", headers=headers)
    recreated = client.post(
        "/api/memory-preferences",
        headers=headers,
        json=preference_payload(
            source_record_id="conversation-message-2",
            confirmed=True,
            retention_until=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            expires_at=(datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
        ),
    )
    cleanup = client.post("/api/memories/cleanup", headers=headers)
    revoked_list = client.get(
        "/api/memory-preferences", headers=headers, params={"status": "revoked"}
    )

    assert first["status"] == "active"
    assert duplicate.status_code == 409
    assert updated.json()["data"]["value"] == {"unit": "F"}
    assert deleted.status_code == 200
    assert recreated.status_code == 201
    assert cleanup.json()["data"]["expired"] >= 1
    assert revoked_list.json()["total"] == 1


def test_expired_preference_is_not_retrieved(manager: DatabaseManager, tmp_path: Path) -> None:
    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    preference = client.post(
        "/api/memory-preferences",
        headers=headers,
        json=preference_payload(
            confirmed=True,
            expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        ),
    ).json()["data"]
    retrieval = client.post(
        "/api/memory-retrieval",
        headers=headers,
        json={"question_type": "preference", "query": "temperature"},
    )

    assert preference["status"] == "active"
    assert retrieval.json()["data"]["preferences"] == []


def test_related_history_links_event_task_and_conversation(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    with manager.session_factory() as db:
        conversation = Conversation(id="conversation-1", title="Setup", status="active")
        message = ConversationMessage(
            id="message-1",
            conversation_id="conversation-1",
            role="user",
            content="Remember the guest routine.",
        )
        task = Task(
            id="task-1",
            task_type="routine",
            title="Guest routine",
            status="completed",
            origin="user",
            plan={},
            created_at=now,
        )
        db.add_all([conversation, message, task])
        db.commit()

    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    memory = client.post(
        "/api/memories",
        headers=headers,
        json=memory_payload(
            memory_type="episodic",
            title="Guest setup",
            content="The guest routine was completed.",
            source_type="task",
            source_id="task-1",
            user_confirmed=False,
            task_id="task-1",
            conversation_id="conversation-1",
            subject_type=None,
            subject_id=None,
            predicate=None,
            object_value=None,
            evidence=[
                {
                    "evidence_type": "task",
                    "evidence_id": "task-1",
                    "source_type": "task",
                },
                {
                    "evidence_type": "conversation",
                    "evidence_id": "message-1",
                    "source_type": "conversation",
                },
            ],
        ),
    ).json()["data"]
    history = client.get(f"/api/memories/{memory['id']}/history", headers=headers)

    assert history.status_code == 200
    records = {item["record"]["record_type"] for item in history.json()["data"]}
    assert records == {"task", "conversation_message"}


def test_memory_permission_is_owner_scoped_by_api_contract(
    manager: DatabaseManager,
    tmp_path: Path,
) -> None:
    client = client_for(manager, tmp_path)
    headers = {"Authorization": "Bearer test-api-token"}
    memory = client.post(
        "/api/memories",
        headers=headers,
        json=memory_payload(owner_id="another_user"),
    ).json()["data"]

    assert memory["owner_id"] == "another_user"
    assert memory["access_level"] == "owner_only"
    assert client.get(f"/api/memories/{memory['id']}", headers=headers).status_code == 200
