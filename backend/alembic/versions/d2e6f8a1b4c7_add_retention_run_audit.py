"""add retention scheduler run audit

Revision ID: d2e6f8a1b4c7
Revises: c9d5e7f8a9b0
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2e6f8a1b4c7"
down_revision: str | None = "c9d5e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "retention_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_name", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("affected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_retention_runs"),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_retention_runs_status",
        ),
    )
    op.create_index(
        "ix_retention_runs_job_started",
        "retention_runs",
        ["job_name", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_retention_runs_job_started", table_name="retention_runs")
    op.drop_table("retention_runs")
