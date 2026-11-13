"""bind memory procedures to executable tools

Revision ID: 9c0d1e2f3a4b
Revises: 8a9b0c1d2e3f
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from sqlalchemy import Column, String

from alembic import op

revision: str = "9c0d1e2f3a4b"
down_revision: str | None = "8a9b0c1d2e3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("memory_procedure_versions", schema=None) as batch_op:
        batch_op.add_column(Column("tool_name", String(length=255), nullable=True))
        batch_op.create_index(
            "ix_memory_procedure_versions_tool_status",
            ["tool_name", "status"],
        )


def downgrade() -> None:
    with op.batch_alter_table("memory_procedure_versions", schema=None) as batch_op:
        batch_op.drop_index("ix_memory_procedure_versions_tool_status")
        batch_op.drop_column("tool_name")
