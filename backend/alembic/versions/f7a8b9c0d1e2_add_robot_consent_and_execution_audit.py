"""add robot consent and unified execution audit

Revision ID: f7a8b9c0d1e2
Revises: b1c2d3e4f5a6
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "robot_consents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("robot_id", sa.String(length=36), nullable=False),
        sa.Column("capability", sa.String(length=100), nullable=False),
        sa.Column("data_category", sa.String(length=50), nullable=False),
        sa.Column("space_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="granted"),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grant_source", sa.String(length=50), nullable=False),
        sa.Column("granted_by", sa.String(length=255), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_robot_consents"),
        sa.ForeignKeyConstraint(
            ["robot_id"],
            ["robots.id"],
            name="fk_robot_consents_robot",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('granted', 'revoked', 'expired')",
            name="ck_robot_consents_status",
        ),
        sa.CheckConstraint(
            "data_category IN ('camera', 'microphone', 'speaker', 'motion')",
            name="ck_robot_consents_data_category",
        ),
    )
    op.create_index(
        "ix_robot_consents_active",
        "robot_consents",
        ["robot_id", "capability", "data_category", "status"],
    )
    op.create_index(
        "ix_robot_consents_robot_space",
        "robot_consents",
        ["robot_id", "space_id"],
    )

    with op.batch_alter_table("robot_task_requests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("task_step_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("tool_execution_id", sa.String(length=36), nullable=True))
        batch_op.create_index(
            "ix_robot_task_requests_task_step",
            ["task_step_id"],
        )
        batch_op.create_index(
            "ix_robot_task_requests_tool_execution",
            ["tool_execution_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("robot_task_requests", schema=None) as batch_op:
        batch_op.drop_index("ix_robot_task_requests_tool_execution")
        batch_op.drop_index("ix_robot_task_requests_task_step")
        batch_op.drop_column("tool_execution_id")
        batch_op.drop_column("task_step_id")
    op.drop_index("ix_robot_consents_robot_space", table_name="robot_consents")
    op.drop_index("ix_robot_consents_active", table_name="robot_consents")
    op.drop_table("robot_consents")
