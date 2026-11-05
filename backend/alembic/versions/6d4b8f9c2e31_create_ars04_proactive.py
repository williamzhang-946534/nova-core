"""create the ARS-04 proactive suggestion model

Revision ID: 6d4b8f9c2e31
Revises: 2f4b3d4775a1
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6d4b8f9c2e31"
down_revision: str | None = "2f4b3d4775a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "proactive_suggestions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("reasoning_session_id", sa.String(length=36), nullable=True),
        sa.Column("hypothesis_id", sa.String(length=36), nullable=True),
        sa.Column("goal_id", sa.String(length=36), nullable=True),
        sa.Column("trigger_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("importance", sa.String(length=20), nullable=False, server_default="'normal'"),
        sa.Column("autonomy_level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("candidate_action", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="'evaluated'"),
        sa.Column("suppression_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_feedback", sa.JSON(), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name="fk_proactive_suggestions_environment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reasoning_session_id"],
            ["reasoning_sessions.id"],
            name="fk_proactive_suggestions_reasoning_session",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["hypothesis_id"],
            ["hypotheses.id"],
            name="fk_proactive_suggestions_hypothesis",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["goal_id"], ["goals.id"], name="fk_proactive_suggestions_goal", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_proactive_suggestions"),
        sa.CheckConstraint(
            "trigger_type IN ('trend', 'anomaly', 'goal_deviation', 'task_failure', "
            "'coverage_gap', 'device_fault', 'cost_risk')",
            name="ck_proactive_suggestions_trigger_type",
        ),
        sa.CheckConstraint(
            "importance IN ('low', 'normal', 'high')",
            name="ck_proactive_suggestions_importance",
        ),
        sa.CheckConstraint(
            "autonomy_level BETWEEN 0 AND 4",
            name="ck_proactive_suggestions_autonomy_level",
        ),
        sa.CheckConstraint(
            "status IN ('evaluated', 'suppressed', 'queued', 'delivered', 'opened', "
            "'accepted', 'dismissed', 'expired')",
            name="ck_proactive_suggestions_status",
        ),
    )
    op.create_index(
        "ix_proactive_suggestions_environment_dedupe",
        "proactive_suggestions",
        ["environment_id", "dedupe_key"],
    )
    op.create_index(
        "ix_proactive_suggestions_status",
        "proactive_suggestions",
        ["status"],
    )
    op.create_index(
        "ix_proactive_suggestions_cooldown",
        "proactive_suggestions",
        ["cooldown_until"],
    )
    op.create_index(
        "ix_proactive_suggestions_delivered",
        "proactive_suggestions",
        ["delivered_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_proactive_suggestions_delivered", table_name="proactive_suggestions")
    op.drop_index("ix_proactive_suggestions_cooldown", table_name="proactive_suggestions")
    op.drop_index("ix_proactive_suggestions_status", table_name="proactive_suggestions")
    op.drop_index(
        "ix_proactive_suggestions_environment_dedupe",
        table_name="proactive_suggestions",
    )
    op.drop_table("proactive_suggestions")
