"""create the ARS-04 active perception request model

Revision ID: a7d4f83c1092
Revises: 6d4b8f9c2e31
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7d4f83c1092"
down_revision: str | None = "6d4b8f9c2e31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "active_perception_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("reasoning_session_id", sa.String(length=36), nullable=False),
        sa.Column("hypothesis_id", sa.String(length=36), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("gap_type", sa.String(length=50), nullable=False),
        sa.Column("subject_type", sa.String(length=50), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("space_id", sa.String(length=36), nullable=True),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.Column("attribute", sa.String(length=50), nullable=True),
        sa.Column("needed_time_range", sa.JSON(), nullable=False),
        sa.Column("current_coverage", sa.JSON(), nullable=False),
        sa.Column("expected_value", sa.JSON(), nullable=False),
        sa.Column("would_resolve", sa.JSON(), nullable=False),
        sa.Column("proposed_capability", sa.String(length=100), nullable=True),
        sa.Column("proposed_input", sa.JSON(), nullable=False),
        sa.Column("privacy_level", sa.String(length=20), nullable=False),
        sa.Column("requires_user_consent", sa.Boolean(), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorization_scope", sa.JSON(), nullable=True),
        sa.Column("cost_estimate", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("fulfilled_by_type", sa.String(length=50), nullable=True),
        sa.Column("fulfilled_by_id", sa.String(length=255), nullable=True),
        sa.Column(
            "follow_up_reasoning_session_id",
            sa.String(length=36),
            nullable=True,
        ),
        sa.Column("unavailable_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name="fk_active_perception_environment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reasoning_session_id"],
            ["reasoning_sessions.id"],
            name="fk_active_perception_reasoning",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["hypothesis_id"],
            ["hypotheses.id"],
            name="fk_active_perception_hypothesis",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            name="fk_active_perception_space",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name="fk_active_perception_entity",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["follow_up_reasoning_session_id"],
            ["reasoning_sessions.id"],
            name="fk_active_perception_follow_up",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_active_perception_requests"),
        sa.CheckConstraint(
            "gap_type IN ('space_coverage', 'time_coverage', 'quality', "
            "'entity_identity', 'post_action_verification', 'procedure')",
            name="ck_active_perception_gap_type",
        ),
        sa.CheckConstraint(
            "subject_type IN ('space', 'entity')",
            name="ck_active_perception_subject_type",
        ),
        sa.CheckConstraint(
            "privacy_level IN ('normal', 'sensitive')",
            name="ck_active_perception_privacy",
        ),
        sa.CheckConstraint(
            "privacy_level != 'sensitive' OR requires_user_consent = 1",
            name="ck_active_perception_sensitive_consent",
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'awaiting_consent', 'rejected', 'queued', "
            "'executed', 'fulfilled', 'unavailable', 'expired')",
            name="ck_active_perception_status",
        ),
        sa.CheckConstraint(
            "status != 'fulfilled' OR (fulfilled_by_type IS NOT NULL "
            "AND fulfilled_by_id IS NOT NULL)",
            name="ck_active_perception_fulfilled_source",
        ),
    )
    with op.batch_alter_table("active_perception_requests", schema=None) as batch_op:
        batch_op.create_index(
            "ix_active_perception_environment_status",
            ["environment_id", "status"],
        )
        batch_op.create_index(
            "ix_active_perception_subject",
            ["subject_type", "subject_id", "attribute"],
        )
        batch_op.create_index("ix_active_perception_expires", ["expires_at"])


def downgrade() -> None:
    with op.batch_alter_table("active_perception_requests", schema=None) as batch_op:
        batch_op.drop_index("ix_active_perception_expires")
        batch_op.drop_index("ix_active_perception_subject")
        batch_op.drop_index("ix_active_perception_environment_status")
    op.drop_table("active_perception_requests")
