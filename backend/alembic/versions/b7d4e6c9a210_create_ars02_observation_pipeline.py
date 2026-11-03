"""create the ARS-02 observation pipeline

Revision ID: b7d4e6c9a210
Revises: f3d2c8a67b01
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7d4e6c9a210"
down_revision: str | None = "f3d2c8a67b01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("device_states", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("0"))
        )

    # Preserve every historical row while marking one current projection per device.
    op.execute(
        sa.text(
            """
            UPDATE device_states SET is_current = 1
            WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY device_id
                        ORDER BY observed_at DESC, created_at DESC, id DESC
                    ) AS row_number
                    FROM device_states
                ) WHERE row_number = 1
            )
            """
        )
    )
    op.create_index(
        "uq_device_states_current",
        "device_states",
        ["device_id"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
    )

    op.create_table(
        "observation_ingestion_batches",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("adapter_id", sa.String(length=100), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("accepted", sa.Integer(), nullable=False),
        sa.Column("deduplicated", sa.Integer(), nullable=False),
        sa.Column("sampled", sa.Integer(), nullable=False),
        sa.Column("invalid", sa.Integer(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["observation_sources.id"],
            name="fk_observation_ingestion_batches_source_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_observation_ingestion_batches"),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_observation_ingestion_batches_status",
        ),
    )
    with op.batch_alter_table("observation_ingestion_batches", schema=None) as batch_op:
        batch_op.create_index(
            "ix_observation_ingestion_batches_source_received",
            ["source_id", "received_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_observation_ingestion_batches_status_received",
            ["status", "received_at"],
            unique=False,
        )

    op.create_table(
        "observation_source_heartbeats",
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("last_batch_id", sa.String(length=100), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["observation_sources.id"],
            name="fk_observation_source_heartbeats_source_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("source_id", name="pk_observation_source_heartbeats"),
        sa.CheckConstraint(
            "status IN ('healthy', 'degraded', 'failed')",
            name="ck_observation_source_heartbeats_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("observation_source_heartbeats")
    op.drop_table("observation_ingestion_batches")
    op.drop_index("uq_device_states_current", table_name="device_states")
    with op.batch_alter_table("device_states", schema=None) as batch_op:
        batch_op.drop_column("is_current")
