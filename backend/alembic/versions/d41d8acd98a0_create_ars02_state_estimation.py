"""create the ARS-02 state estimation model

Revision ID: d41d8acd98a0
Revises: b7d4e6c9a210
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d41d8acd98a0"
down_revision: str | None = "b7d4e6c9a210"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "estimation_targets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.Column("space_id", sa.String(length=36), nullable=True),
        sa.Column("attribute", sa.String(length=50), nullable=False),
        sa.Column("strategy_id", sa.String(length=100), nullable=False),
        sa.Column("strategy_version", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("validity_policy", sa.JSON(), nullable=False),
        sa.Column("conflict_policy", sa.JSON(), nullable=False),
        sa.Column("coverage_policy", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["environment_id"], ["environments.id"], name="fk_estimation_targets_environment"
        ),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], name="fk_estimation_targets_entity"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], name="fk_estimation_targets_space"),
        sa.ForeignKeyConstraint(
            ["attribute"],
            ["observation_attribute_definitions.attribute"],
            name="fk_estimation_targets_attribute",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_estimation_targets"),
        sa.CheckConstraint(
            "(target_type = 'entity' AND entity_id IS NOT NULL AND space_id IS NULL) "
            "OR (target_type = 'space' AND entity_id IS NULL AND space_id IS NOT NULL) "
            "OR (target_type = 'environment' AND entity_id IS NULL AND space_id IS NULL)",
            name="ck_estimation_targets_scope",
        ),
    )
    with op.batch_alter_table("estimation_targets", schema=None) as batch_op:
        batch_op.create_index(
            "uq_estimation_targets_entity",
            ["environment_id", "entity_id", "attribute"],
            unique=True,
            sqlite_where=sa.text("target_type = 'entity' AND entity_id IS NOT NULL"),
        )
        batch_op.create_index(
            "uq_estimation_targets_space",
            ["environment_id", "space_id", "attribute"],
            unique=True,
            sqlite_where=sa.text("target_type = 'space' AND space_id IS NOT NULL"),
        )
        batch_op.create_index(
            "uq_estimation_targets_environment",
            ["environment_id", "attribute"],
            unique=True,
            sqlite_where=sa.text("target_type = 'environment'"),
        )
        batch_op.create_index(
            "ix_estimation_targets_environment_type", ["environment_id", "target_type"]
        )
        batch_op.create_index("ix_estimation_targets_attribute", ["attribute"])

    op.create_table(
        "state_estimates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence_summary", sa.JSON(), nullable=False),
        sa.Column("conflict_details", sa.JSON(), nullable=True),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("rule_version", sa.String(length=50), nullable=False),
        sa.Column("input_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["target_id"], ["estimation_targets.id"], name="fk_state_estimates_target"
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"], ["environments.id"], name="fk_state_estimates_environment"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_state_estimates"),
        sa.CheckConstraint(
            "status IN ('observed', 'derived', 'inferred', 'unknown', 'stale', "
            "'unavailable', 'conflict')",
            name="ck_state_estimates_status",
        ),
    )
    with op.batch_alter_table("state_estimates", schema=None) as batch_op:
        batch_op.create_index(
            "ix_state_estimates_target_generated", ["target_id", "generated_at"]
        )
        batch_op.create_index(
            "ix_state_estimates_environment_status_generated",
            ["environment_id", "status", "generated_at"],
        )

    op.create_table(
        "state_estimate_observations",
        sa.Column("estimate_id", sa.String(length=36), nullable=False),
        sa.Column("observation_id", sa.String(length=36), nullable=False),
        sa.Column("contribution", sa.String(length=30), nullable=False),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("exclusion_reason", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["estimate_id"],
            ["state_estimates.id"],
            name="fk_state_estimate_observations_estimate",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["observations.observation_id"],
            name="fk_state_estimate_observations_observation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("estimate_id", "observation_id", name="pk_state_estimate_observations"),
        sa.CheckConstraint(
            "contribution IN ('direct', 'candidate', 'context', 'negative_evidence')",
            name="ck_state_estimate_observations_contribution",
        ),
    )
    with op.batch_alter_table("state_estimate_observations", schema=None) as batch_op:
        batch_op.create_index(
            "ix_state_estimate_observations_observation", ["observation_id"]
        )

    op.create_table(
        "current_state_estimates",
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("latest_estimate_id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("projection_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.ForeignKeyConstraint(
            ["target_id"], ["estimation_targets.id"], name="fk_current_state_estimates_target"
        ),
        sa.ForeignKeyConstraint(
            ["latest_estimate_id"],
            ["state_estimates.id"],
            name="fk_current_state_estimates_latest_estimate",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name="fk_current_state_estimates_environment",
        ),
        sa.PrimaryKeyConstraint("target_id", name="pk_current_state_estimates"),
        sa.CheckConstraint(
            "status IN ('observed', 'derived', 'inferred', 'unknown', 'stale', "
            "'unavailable', 'conflict')",
            name="ck_current_state_estimates_status",
        ),
    )
    with op.batch_alter_table("current_state_estimates", schema=None) as batch_op:
        batch_op.create_index(
            "ix_current_state_estimates_environment_status", ["environment_id", "status"]
        )
        batch_op.create_index("ix_current_state_estimates_valid_until", ["valid_until"])

    with op.batch_alter_table("environment_snapshots", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "context_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        batch_op.add_column(sa.Column("state_generated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("environment_snapshots", schema=None) as batch_op:
        batch_op.drop_column("state_generated_at")
        batch_op.drop_column("context_version")
    op.drop_table("current_state_estimates")
    op.drop_table("state_estimate_observations")
    op.drop_table("state_estimates")
    with op.batch_alter_table("estimation_targets", schema=None) as batch_op:
        batch_op.drop_index("ix_estimation_targets_attribute")
        batch_op.drop_index("ix_estimation_targets_environment_type")
        batch_op.drop_index("uq_estimation_targets_environment")
        batch_op.drop_index("uq_estimation_targets_space")
        batch_op.drop_index("uq_estimation_targets_entity")
    op.drop_table("estimation_targets")
