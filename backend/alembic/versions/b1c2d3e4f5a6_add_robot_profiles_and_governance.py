"""add robot profiles and capability governance

Revision ID: b1c2d3e4f5a6
Revises: e9f0a1b2c3d4
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "e9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("robots", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "profile",
                sa.String(length=50),
                nullable=False,
                server_default="desktop_robot",
            )
        )
    op.execute(
        sa.text(
            """
            UPDATE robots
            SET profile = CASE
                WHEN lower(model) LIKE '%desktop%' OR adapter_id = 'mock_robot'
                    THEN 'desktop_robot'
                ELSE 'mobile_robot'
            END
            """
        )
    )
    with op.batch_alter_table("robots", schema=None) as batch_op:
        batch_op.create_check_constraint(
            "ck_robots_profile",
            "profile IN ('desktop_robot', 'mobile_robot', 'legacy_mock_mobile')",
        )

    op.create_table(
        "robot_capability_governance",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("robot_id", sa.String(length=36), nullable=False),
        sa.Column("capability", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "consent_granted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_robot_capability_governance"),
        sa.ForeignKeyConstraint(
            ["robot_id"],
            ["robots.id"],
            name="fk_robot_capability_governance_robot",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "robot_id",
            "capability",
            name="uq_robot_capability_governance",
        ),
    )
    op.create_index(
        "ix_robot_capability_governance_robot",
        "robot_capability_governance",
        ["robot_id", "capability"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_robot_capability_governance_robot",
        table_name="robot_capability_governance",
    )
    op.drop_table("robot_capability_governance")
    with op.batch_alter_table("robots", schema=None) as batch_op:
        batch_op.drop_constraint("ck_robots_profile", type_="check")
        batch_op.drop_column("profile")
