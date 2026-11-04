"""create the ARS-04 reasoning evidence model

Revision ID: c7a8d9e21b46
Revises: a3f9c02e7714
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7a8d9e21b46"
down_revision: str | None = "a3f9c02e7714"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reasoning_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("trigger", sa.String(length=50), nullable=False, server_default="'user'"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="'running'"),
        sa.Column("scope", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("diagnosis", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("analyzer_versions", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("actor_type", sa.String(length=50), nullable=False, server_default="'user'"),
        sa.Column("actor_id", sa.String(length=100), nullable=False, server_default="'local_user'"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name="fk_reasoning_sessions_environment",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reasoning_sessions"),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_reasoning_sessions_status",
        ),
        sa.CheckConstraint(
            "trigger IN ('user', 'system', 'automation')",
            name="ck_reasoning_sessions_trigger",
        ),
    )
    with op.batch_alter_table("reasoning_sessions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_reasoning_sessions_environment_created",
            ["environment_id", "created_at"],
        )
        batch_op.create_index(
            "ix_reasoning_sessions_status_created",
            ["status", "created_at"],
        )

    op.create_table(
        "evidence_bundles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("selection_basis", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("coverage", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["reasoning_sessions.id"],
            name="fk_evidence_bundles_session",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name="fk_evidence_bundles_environment",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_bundles"),
    )
    with op.batch_alter_table("evidence_bundles", schema=None) as batch_op:
        batch_op.create_index("ix_evidence_bundles_session", ["session_id"])
        batch_op.create_index("ix_evidence_bundles_environment", ["environment_id"])

    op.create_table(
        "evidence_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("bundle_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_record_id", sa.String(length=255), nullable=False),
        sa.Column("classification", sa.String(length=30), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("scope", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("source_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quality_status", sa.String(length=30), nullable=False, server_default="'valid'"),
        sa.Column("quality_issues", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("trust_level", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("source_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["bundle_id"],
            ["evidence_bundles.id"],
            name="fk_evidence_items_bundle",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_items"),
        sa.CheckConstraint(
            "source_type IN ('observation', 'state_estimate', 'event', 'task', 'memory')",
            name="ck_evidence_items_source_type",
        ),
        sa.CheckConstraint(
            "classification IN ('observed', 'derived', 'inferred_candidate', "
            "'verified_cause', 'unknown')",
            name="ck_evidence_items_classification",
        ),
        sa.CheckConstraint(
            "quality_status IN ('valid', 'suspect', 'invalid', 'unavailable')",
            name="ck_evidence_items_quality",
        ),
        sa.CheckConstraint("trust_level BETWEEN 0 AND 1", name="ck_evidence_items_trust"),
        sa.UniqueConstraint(
            "bundle_id", "source_type", "source_record_id", name="uq_evidence_items_source"
        ),
    )
    with op.batch_alter_table("evidence_items", schema=None) as batch_op:
        batch_op.create_index("ix_evidence_items_bundle_class", ["bundle_id", "classification"])
        batch_op.create_index("ix_evidence_items_source", ["source_type", "source_record_id"])

    op.create_table(
        "hypotheses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("hypothesis_type", sa.String(length=50), nullable=False),
        sa.Column("origin_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="'unsupported'"),
        sa.Column(
            "confidence_level", sa.String(length=20), nullable=False, server_default="'unknown'"
        ),
        sa.Column("causal_claim", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("unknowns", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("rule_id", sa.String(length=100), nullable=True),
        sa.Column("rule_version", sa.String(length=50), nullable=True),
        sa.Column("superseded_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["reasoning_sessions.id"],
            name="fk_hypotheses_session",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name="fk_hypotheses_environment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["hypotheses.id"],
            name="fk_hypotheses_superseded_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_hypotheses"),
        sa.CheckConstraint(
            "hypothesis_type IN ('deterministic_rule', 'correlation', 'ai_candidate', "
            "'verified_cause', 'data_quality', 'unknown')",
            name="ck_hypotheses_type",
        ),
        sa.CheckConstraint(
            "origin_type IN ('rule', 'model', 'user', 'system')",
            name="ck_hypotheses_origin",
        ),
        sa.CheckConstraint(
            "status IN ('unsupported', 'plausible', 'supported', 'conflicted', "
            "'refuted', 'expired', 'superseded')",
            name="ck_hypotheses_status",
        ),
        sa.CheckConstraint(
            "confidence_level IN ('unknown', 'low', 'medium', 'high')",
            name="ck_hypotheses_confidence",
        ),
        sa.CheckConstraint(
            "origin_type != 'model' OR (status IN ('unsupported', 'plausible') "
            "AND causal_claim = 0)",
            name="ck_hypotheses_model_candidate",
        ),
    )
    with op.batch_alter_table("hypotheses", schema=None) as batch_op:
        batch_op.create_index("ix_hypotheses_session_type", ["session_id", "hypothesis_type"])
        batch_op.create_index("ix_hypotheses_environment_status", ["environment_id", "status"])

    op.create_table(
        "hypothesis_evidence",
        sa.Column("hypothesis_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("relationship", sa.String(length=30), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["hypothesis_id"],
            ["hypotheses.id"],
            name="fk_hypothesis_evidence_hypothesis",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_items.id"],
            name="fk_hypothesis_evidence_evidence",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("hypothesis_id", "evidence_id", name="pk_hypothesis_evidence"),
        sa.CheckConstraint(
            "relationship IN ('supports', 'contradicts', 'context')",
            name="ck_hypothesis_evidence_relationship",
        ),
        sa.CheckConstraint("weight BETWEEN 0 AND 1", name="ck_hypothesis_evidence_weight"),
    )
    with op.batch_alter_table("hypothesis_evidence", schema=None) as batch_op:
        batch_op.create_index("ix_hypothesis_evidence_evidence", ["evidence_id"])


def downgrade() -> None:
    op.drop_table("hypothesis_evidence")
    op.drop_table("hypotheses")
    op.drop_table("evidence_items")
    op.drop_table("evidence_bundles")
    op.drop_table("reasoning_sessions")
