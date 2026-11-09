"""add robot mobile perception execution trace

Revision ID: b8c3d4e5f6a7
Revises: a6b2c3d4e5f6
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8c3d4e5f6a7"
down_revision: str | None = "a6b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("active_perception_requests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("execution_trace", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("active_perception_requests", schema=None) as batch_op:
        batch_op.drop_column("execution_trace")
