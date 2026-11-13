"""add persistent device availability state

Revision ID: e9f0a1b2c3d4
Revises: d2e6f8a1b4c7
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e9f0a1b2c3d4"
down_revision: str | None = "d2e6f8a1b4c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "availability_state",
                sa.String(length=20),
                nullable=False,
                server_default="online",
            )
        )
        batch_op.add_column(
            sa.Column("availability_failure_scope", sa.String(length=20), nullable=True)
        )
        batch_op.add_column(
            sa.Column("availability_error_code", sa.String(length=100), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "availability_last_success_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "availability_last_failure_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "availability_transitioned_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.create_check_constraint(
            "ck_devices_availability_state",
            "availability_state IN ('online', 'unavailable')",
        )
        batch_op.create_check_constraint(
            "ck_devices_availability_failure_scope",
            "availability_failure_scope IN ('none', 'adapter', 'device', 'entity')",
        )

    op.execute(
        sa.text(
            """
            UPDATE devices
            SET availability_state = CASE WHEN is_online = 0 THEN 'unavailable' ELSE 'online' END,
                availability_last_success_at = COALESCE(
                    availability_last_success_at,
                    last_seen_at
                )
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.drop_constraint("ck_devices_availability_failure_scope", type_="check")
        batch_op.drop_constraint("ck_devices_availability_state", type_="check")
        batch_op.drop_column("availability_transitioned_at")
        batch_op.drop_column("availability_last_failure_at")
        batch_op.drop_column("availability_last_success_at")
        batch_op.drop_column("availability_error_code")
        batch_op.drop_column("availability_failure_scope")
        batch_op.drop_column("availability_state")
