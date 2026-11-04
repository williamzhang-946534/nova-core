"""create the ARS-03 memory system

Revision ID: a3f9c02e7714
Revises: d41d8acd98a0
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3f9c02e7714"
down_revision: str | None = "d41d8acd98a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MEMORY_COLUMNS = [
    sa.Column(
        "status",
        sa.String(length=30),
        nullable=False,
        server_default=sa.text("'active'"),
    ),
    sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0.5")),
    sa.Column(
        "verification_status",
        sa.String(length=30),
        nullable=False,
        server_default=sa.text("'unverified'"),
    ),
    sa.Column(
        "owner_id",
        sa.String(length=100),
        nullable=False,
        server_default=sa.text("'local_user'"),
    ),
    sa.Column(
        "access_level",
        sa.String(length=30),
        nullable=False,
        server_default=sa.text("'owner_only'"),
    ),
    sa.Column("scope", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    sa.Column("environment_id", sa.String(length=36), nullable=True),
    sa.Column("space_id", sa.String(length=36), nullable=True),
    sa.Column("entity_id", sa.String(length=36), nullable=True),
    sa.Column("conversation_id", sa.String(length=36), nullable=True),
    sa.Column("task_id", sa.String(length=36), nullable=True),
    sa.Column("subject_type", sa.String(length=100), nullable=True),
    sa.Column("subject_id", sa.String(length=255), nullable=True),
    sa.Column("predicate", sa.String(length=255), nullable=True),
    sa.Column("object_value", sa.JSON(), nullable=True),
    sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
    sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
    sa.Column("superseded_by_id", sa.String(length=36), nullable=True),
    sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("correction_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
]


PREFERENCE_COLUMNS = [
    sa.Column(
        "source_type",
        sa.String(length=50),
        nullable=False,
        server_default=sa.text("'user'"),
    ),
    sa.Column("source_record_id", sa.String(length=255), nullable=True),
    sa.Column(
        "status",
        sa.String(length=30),
        nullable=False,
        server_default=sa.text("'draft'"),
    ),
    sa.Column("scope", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    sa.Column("conversation_id", sa.String(length=36), nullable=True),
    sa.Column("consent_id", sa.String(length=36), nullable=True),
    sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
    sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
]


def upgrade() -> None:
    op.execute(
        "UPDATE memories SET memory_type = CASE "
        "WHEN memory_type = 'fact' THEN 'semantic' "
        "WHEN memory_type = 'preference' THEN 'episodic' "
        "ELSE 'episodic' END"
    )
    with op.batch_alter_table("memories", schema=None) as batch_op:
        for column in MEMORY_COLUMNS:
            batch_op.add_column(column)
    op.execute("UPDATE memories SET status = 'active'")
    op.execute("UPDATE memories SET verification_status = 'verified'")
    op.execute("UPDATE memories SET valid_from = created_at WHERE valid_from IS NULL")
    memory_constraints = {
        "ck_memories_type": "memory_type IN ('episodic', 'semantic', 'procedural')",
        "ck_memories_status": (
            "status IN ('active', 'candidate', 'corrected', 'superseded', 'expired', 'archived')"
        ),
        "ck_memories_verification": (
            "verification_status IN ('unverified', 'verified', 'rejected')"
        ),
        "ck_memories_importance": "importance BETWEEN 1 AND 5",
        "ck_memories_ai_inference_candidate": (
            "source_type != 'ai_inference' OR (status = 'candidate' AND "
            "user_confirmed = 0 AND verification_status = 'unverified' "
            "AND expires_at IS NOT NULL)"
        ),
        "ck_memories_procedure_subject": ("memory_type != 'procedural' OR subject_id IS NOT NULL"),
    }
    with op.batch_alter_table("memories", schema=None) as batch_op:
        for name, expression in memory_constraints.items():
            batch_op.create_check_constraint(name, expression)
        batch_op.create_index("ix_memories_status_type", ["status", "memory_type"])
        batch_op.create_index("ix_memories_scope", ["environment_id", "space_id", "entity_id"])
        batch_op.create_index(
            "ix_memories_subject_predicate", ["subject_type", "subject_id", "predicate"]
        )
        batch_op.create_index("ix_memories_valid_until", ["expires_at"])
        batch_op.create_index("ix_memories_retention", ["retention_until"])
        batch_op.create_foreign_key(
            "fk_memories_environment", "environments", ["environment_id"], ["id"]
        )
        batch_op.create_foreign_key("fk_memories_space", "spaces", ["space_id"], ["id"])
        batch_op.create_foreign_key("fk_memories_entity", "entities", ["entity_id"], ["id"])
        batch_op.create_foreign_key(
            "fk_memories_conversation", "conversations", ["conversation_id"], ["id"]
        )
        batch_op.create_foreign_key("fk_memories_task", "tasks", ["task_id"], ["id"])
        batch_op.create_foreign_key(
            "fk_memories_superseded_by", "memories", ["superseded_by_id"], ["id"]
        )
    with op.batch_alter_table("memories", schema=None) as batch_op:
        batch_op.alter_column(
            "valid_from", existing_type=sa.DateTime(timezone=True), nullable=False
        )

    op.create_table(
        "memory_consents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=100), nullable=False),
        sa.Column("grant_type", sa.String(length=50), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_type", sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_memory_consents"),
        sa.CheckConstraint(
            "grant_type IN ('memory_store', 'preference_store', 'retrieval')",
            name="ck_memory_consents_grant_type",
        ),
    )
    with op.batch_alter_table("memory_consents", schema=None) as batch_op:
        batch_op.create_index(
            "ix_memory_consents_subject",
            ["subject_id", "grant_type", "granted_at"],
        )

    with op.batch_alter_table("user_preferences", schema=None) as batch_op:
        for column in PREFERENCE_COLUMNS:
            batch_op.add_column(column)
    op.execute("UPDATE user_preferences SET source_type = 'user'")
    op.execute(
        "UPDATE user_preferences SET source_record_id = COALESCE(source, id) "
        "WHERE source_record_id IS NULL"
    )
    op.execute(
        "UPDATE user_preferences SET status = CASE WHEN confirmed = 1 "
        "THEN 'active' ELSE 'draft' END"
    )
    op.execute(
        "UPDATE user_preferences SET confirmed_at = updated_at "
        "WHERE confirmed = 1 AND confirmed_at IS NULL"
    )
    op.execute("UPDATE user_preferences SET valid_from = created_at WHERE valid_from IS NULL")
    with op.batch_alter_table("user_preferences", schema=None) as batch_op:
        batch_op.create_check_constraint(
            "ck_user_preferences_status", "status IN ('draft', 'active', 'revoked')"
        )
        batch_op.create_check_constraint(
            "ck_user_preferences_confirmation",
            "(confirmed = 0 AND confirmed_at IS NULL) "
            "OR (confirmed = 1 AND confirmed_at IS NOT NULL)",
        )
        batch_op.create_check_constraint(
            "ck_user_preferences_user_source",
            "source_type = 'user' AND source_record_id IS NOT NULL",
        )
        batch_op.create_index("ix_user_preferences_status_key", ["status", "key"])
        batch_op.create_foreign_key(
            "fk_user_preferences_conversation", "conversations", ["conversation_id"], ["id"]
        )
        batch_op.create_foreign_key(
            "fk_user_preferences_consent", "memory_consents", ["consent_id"], ["id"]
        )
    with op.batch_alter_table("user_preferences", schema=None) as batch_op:
        batch_op.alter_column(
            "source_record_id", existing_type=sa.String(length=255), nullable=False
        )
        batch_op.alter_column(
            "valid_from", existing_type=sa.DateTime(timezone=True), nullable=False
        )

    op.create_table(
        "memory_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.Column("evidence_id", sa.String(length=255), nullable=True),
        sa.Column("source_type", sa.String(length=100), nullable=False),
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
        sa.Column("trust_level", sa.Float(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name="fk_memory_evidence_memory",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memory_evidence"),
        sa.CheckConstraint(
            "evidence_type IN ('observation', 'event', 'task', 'conversation', "
            "'procedure_execution', 'user_statement', 'environment_snapshot')",
            name="ck_memory_evidence_type",
        ),
        sa.CheckConstraint(
            "evidence_type IN ('user_statement', 'ai_inference') OR evidence_id IS NOT NULL",
            name="ck_memory_evidence_record",
        ),
        sa.UniqueConstraint(
            "memory_id",
            "evidence_type",
            "evidence_id",
            name="uq_memory_evidence_record",
        ),
    )
    with op.batch_alter_table("memory_evidence", schema=None) as batch_op:
        batch_op.create_index("ix_memory_evidence_memory", ["memory_id"])
        batch_op.create_index("ix_memory_evidence_record", ["evidence_type", "evidence_id"])

    op.create_table(
        "memory_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("revision_type", sa.String(length=30), nullable=False),
        sa.Column("previous_content", sa.Text(), nullable=False),
        sa.Column("previous_summary", sa.Text(), nullable=True),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("actor_type", sa.String(length=50), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name="fk_memory_revisions_memory",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memory_revisions"),
        sa.CheckConstraint(
            "revision_type IN ('create', 'update', 'correct', 'confirm', "
            "'expire', 'archive', 'validate')",
            name="ck_memory_revisions_type",
        ),
    )
    with op.batch_alter_table("memory_revisions", schema=None) as batch_op:
        batch_op.create_index("ix_memory_revisions_memory_created", ["memory_id", "created_at"])

    op.create_table(
        "memory_procedure_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("risk_level", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("required_successes", sa.Integer(), nullable=False),
        sa.Column("successful_validations", sa.Integer(), nullable=False),
        sa.Column("failed_validations", sa.Integer(), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name="fk_memory_procedure_versions_memory",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memory_procedure_versions"),
        sa.UniqueConstraint("memory_id", "version", name="uq_memory_procedure_versions_version"),
        sa.CheckConstraint(
            "status IN ('testing', 'validated', 'retired')",
            name="ck_memory_procedure_versions_status",
        ),
        sa.CheckConstraint("required_successes > 0", name="ck_memory_procedure_versions_required"),
    )
    with op.batch_alter_table("memory_procedure_versions", schema=None) as batch_op:
        batch_op.create_index("ix_memory_procedure_versions_memory_status", ["memory_id", "status"])

    op.create_table(
        "memory_procedure_validations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("procedure_version_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("tool_execution_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("validator_type", sa.String(length=50), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["procedure_version_id"],
            ["memory_procedure_versions.id"],
            name="fk_memory_procedure_validations_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name="fk_memory_procedure_validations_task"
        ),
        sa.ForeignKeyConstraint(
            ["tool_execution_id"],
            ["tool_executions.id"],
            name="fk_memory_procedure_validations_tool_execution",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memory_procedure_validations"),
        sa.CheckConstraint(
            "status IN ('passed', 'failed')", name="ck_memory_procedure_validations_status"
        ),
    )
    with op.batch_alter_table("memory_procedure_validations", schema=None) as batch_op:
        batch_op.create_index(
            "ix_memory_procedure_validations_version",
            ["procedure_version_id", "validated_at"],
        )

    op.create_table(
        "memory_access_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("memory_id", sa.String(length=36), nullable=True),
        sa.Column("preference_id", sa.String(length=36), nullable=True),
        sa.Column("access_type", sa.String(length=30), nullable=False),
        sa.Column("actor_type", sa.String(length=50), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("authorized", sa.Boolean(), nullable=False),
        sa.Column("query", sa.JSON(), nullable=True),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name="fk_memory_access_logs_memory",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["preference_id"],
            ["user_preferences.id"],
            name="fk_memory_access_logs_preference",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memory_access_logs"),
        sa.CheckConstraint(
            "access_type IN ('create', 'read', 'retrieve', 'update', 'confirm', "
            "'correct', 'delete', 'expire')",
            name="ck_memory_access_logs_type",
        ),
        sa.CheckConstraint(
            "memory_id IS NOT NULL OR preference_id IS NOT NULL",
            name="ck_memory_access_logs_target",
        ),
    )
    with op.batch_alter_table("memory_access_logs", schema=None) as batch_op:
        batch_op.create_index("ix_memory_access_logs_memory", ["memory_id", "accessed_at"])
        batch_op.create_index("ix_memory_access_logs_preference", ["preference_id", "accessed_at"])


def downgrade() -> None:
    op.drop_table("memory_access_logs")
    op.drop_table("memory_procedure_validations")
    op.drop_table("memory_procedure_versions")
    op.drop_table("memory_revisions")
    op.drop_table("memory_evidence")
    with op.batch_alter_table("user_preferences", schema=None) as batch_op:
        batch_op.drop_index("ix_user_preferences_status_key")
        batch_op.drop_constraint("fk_user_preferences_consent", type_="foreignkey")
        batch_op.drop_constraint("fk_user_preferences_conversation", type_="foreignkey")
        batch_op.drop_constraint("ck_user_preferences_user_source", type_="check")
        batch_op.drop_constraint("ck_user_preferences_confirmation", type_="check")
        batch_op.drop_constraint("ck_user_preferences_status", type_="check")
        for column in reversed(PREFERENCE_COLUMNS):
            batch_op.drop_column(column.name)
    op.drop_table("memory_consents")
    op.execute(
        "UPDATE memories SET memory_type = CASE WHEN memory_type = 'semantic' "
        "THEN 'fact' ELSE 'event' END"
    )
    with op.batch_alter_table("memories", schema=None) as batch_op:
        batch_op.drop_index("ix_memories_retention")
        batch_op.drop_index("ix_memories_valid_until")
        batch_op.drop_index("ix_memories_subject_predicate")
        batch_op.drop_index("ix_memories_scope")
        batch_op.drop_index("ix_memories_status_type")
        batch_op.drop_constraint("ck_memories_procedure_subject", type_="check")
        batch_op.drop_constraint("ck_memories_ai_inference_candidate", type_="check")
        batch_op.drop_constraint("ck_memories_importance", type_="check")
        batch_op.drop_constraint("ck_memories_verification", type_="check")
        batch_op.drop_constraint("ck_memories_status", type_="check")
        batch_op.drop_constraint("ck_memories_type", type_="check")
        batch_op.drop_constraint("fk_memories_superseded_by", type_="foreignkey")
        batch_op.drop_constraint("fk_memories_task", type_="foreignkey")
        batch_op.drop_constraint("fk_memories_conversation", type_="foreignkey")
        batch_op.drop_constraint("fk_memories_entity", type_="foreignkey")
        batch_op.drop_constraint("fk_memories_space", type_="foreignkey")
        batch_op.drop_constraint("fk_memories_environment", type_="foreignkey")
        for column in reversed(MEMORY_COLUMNS):
            batch_op.drop_column(column.name)
