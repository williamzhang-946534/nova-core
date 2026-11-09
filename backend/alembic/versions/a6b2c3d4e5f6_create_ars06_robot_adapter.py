"""create ARS-06 robot adapter projections

Revision ID: a6b2c3d4e5f6
Revises: e5f1a2b3c4d5
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a6b2c3d4e5f6"
down_revision: str | None = "e5f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "robots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("adapter_id", sa.String(length=100), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("vendor", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("hardware_version", sa.String(length=100), nullable=True),
        sa.Column("firmware_version", sa.String(length=100), nullable=True),
        sa.Column("edge_runtime_version", sa.String(length=100), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("space_id", sa.String(length=36), nullable=True),
        sa.Column("connection_state", sa.String(length=30), nullable=False),
        sa.Column("is_online", sa.Boolean(), nullable=False),
        sa.Column("motion_safety_state", sa.String(length=50), nullable=False),
        sa.Column("emergency_stop", sa.Boolean(), nullable=False),
        sa.Column("manual_takeover", sa.Boolean(), nullable=False),
        sa.Column("battery_percent", sa.Float(), nullable=True),
        sa.Column("low_battery_percent", sa.Float(), nullable=False),
        sa.Column("device_states", sa.JSON(), nullable=False),
        sa.Column("location", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_robots"),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            name="fk_robots_space",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("adapter_id", "external_id", name="uq_robots_adapter_external"),
        sa.CheckConstraint(
            "connection_state IN ('disconnected', 'connecting', 'connected', 'degraded')",
            name="ck_robots_connection_state",
        ),
        sa.CheckConstraint(
            "motion_safety_state IN ('normal', 'stopped', 'manual_takeover', "
            "'limit_reached', 'stalled', 'over_current', 'tilt_detected', 'unknown')",
            name="ck_robots_motion_safety_state",
        ),
        sa.CheckConstraint(
            "battery_percent IS NULL OR battery_percent BETWEEN 0 AND 100",
            name="ck_robots_battery_range",
        ),
    )
    op.create_index("ix_robots_connection", "robots", ["connection_state", "is_online"])

    op.create_table(
        "robot_capabilities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("robot_id", sa.String(length=36), nullable=False),
        sa.Column("capability", sa.String(length=100), nullable=False),
        sa.Column("schema_version", sa.String(length=30), nullable=False),
        sa.Column("verification_status", sa.String(length=40), nullable=False),
        sa.Column("runtime_enabled", sa.Boolean(), nullable=False),
        sa.Column("risk_level", sa.String(length=30), nullable=False),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False),
        sa.Column("requires_consents", sa.JSON(), nullable=False),
        sa.Column("min_battery_percent", sa.Float(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("safety_envelope", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_robot_capabilities"),
        sa.ForeignKeyConstraint(
            ["robot_id"],
            ["robots.id"],
            name="fk_robot_capabilities_robot",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "robot_id",
            "capability",
            name="uq_robot_capabilities_capability",
        ),
        sa.CheckConstraint(
            "verification_status IN ('concept', 'specified', 'bench_verified', "
            "'integration_verified', 'safety_approved')",
            name="ck_robot_capabilities_verification",
        ),
        sa.CheckConstraint(
            "risk_level IN ('read_only', 'low_risk', 'medium_risk', 'high_risk')",
            name="ck_robot_capabilities_risk",
        ),
    )
    op.create_index(
        "ix_robot_capabilities_robot_enabled",
        "robot_capabilities",
        ["robot_id", "runtime_enabled"],
    )

    op.create_table(
        "robot_state_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("robot_id", sa.String(length=36), nullable=False),
        sa.Column("connection_state", sa.String(length=30), nullable=False),
        sa.Column("is_online", sa.Boolean(), nullable=False),
        sa.Column("motion_safety_state", sa.String(length=50), nullable=False),
        sa.Column("emergency_stop", sa.Boolean(), nullable=False),
        sa.Column("manual_takeover", sa.Boolean(), nullable=False),
        sa.Column("battery_percent", sa.Float(), nullable=True),
        sa.Column("device_states", sa.JSON(), nullable=False),
        sa.Column("location", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(length=30), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_robot_state_snapshots"),
        sa.ForeignKeyConstraint(
            ["robot_id"],
            ["robots.id"],
            name="fk_robot_state_snapshots_robot",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "source IN ('firmware_reported', 'edge_observed', 'adapter_derived', 'mock')",
            name="ck_robot_state_snapshots_source",
        ),
    )
    op.create_index(
        "ix_robot_state_snapshots_robot_observed",
        "robot_state_snapshots",
        ["robot_id", "observed_at"],
    )
    op.create_index(
        "ix_robot_state_snapshots_safety",
        "robot_state_snapshots",
        ["robot_id", "motion_safety_state"],
    )

    op.create_table(
        "robot_task_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("robot_id", sa.String(length=36), nullable=False),
        sa.Column("capability", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("origin_type", sa.String(length=50), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("confirmed_by_user", sa.Boolean(), nullable=False),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_robot_task_requests"),
        sa.ForeignKeyConstraint(
            ["robot_id"],
            ["robots.id"],
            name="fk_robot_task_requests_robot",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "robot_id",
            "idempotency_key",
            name="uq_robot_task_idempotency",
        ),
        sa.CheckConstraint(
            "status IN ('created', 'awaiting_confirmation', 'rejected', 'submitted', "
            "'accepted', 'running', 'waiting_result', 'succeeded', 'failed', "
            "'timeout', 'cancelled', 'safe_stopped', 'unavailable')",
            name="ck_robot_task_requests_status",
        ),
        sa.CheckConstraint(
            "origin_type IN ('user', 'task_system', 'active_perception', 'system')",
            name="ck_robot_task_requests_origin",
        ),
        sa.CheckConstraint(
            "timeout_seconds > 0",
            name="ck_robot_task_requests_timeout",
        ),
    )
    op.create_index(
        "ix_robot_task_requests_robot_status",
        "robot_task_requests",
        ["robot_id", "status"],
    )
    op.create_index(
        "ix_robot_task_requests_task",
        "robot_task_requests",
        ["task_id"],
    )
    op.create_index(
        "ix_robot_task_requests_correlation",
        "robot_task_requests",
        ["correlation_id"],
    )

    op.create_table(
        "robot_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("robot_id", sa.String(length=36), nullable=False),
        sa.Column("task_request_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("late_arrival", sa.Boolean(), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_robot_events"),
        sa.ForeignKeyConstraint(
            ["robot_id"],
            ["robots.id"],
            name="fk_robot_events_robot",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_request_id"],
            ["robot_task_requests.id"],
            name="fk_robot_events_task_request",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "event_type IN ('connection_changed', 'state_changed', 'safety_changed', "
            "'task_accepted', 'task_running', 'task_succeeded', 'task_failed', "
            "'task_cancelled', 'task_safe_stopped', 'task_unavailable')",
            name="ck_robot_events_type",
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name="ck_robot_events_severity",
        ),
    )
    op.create_index(
        "ix_robot_events_robot_occurred",
        "robot_events",
        ["robot_id", "occurred_at"],
    )
    op.create_index(
        "ix_robot_events_request_occurred",
        "robot_events",
        ["task_request_id", "occurred_at"],
    )
    op.create_index(
        "ix_robot_events_type_occurred",
        "robot_events",
        ["event_type", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_robot_events_type_occurred", table_name="robot_events")
    op.drop_index("ix_robot_events_request_occurred", table_name="robot_events")
    op.drop_index("ix_robot_events_robot_occurred", table_name="robot_events")
    op.drop_table("robot_events")

    op.drop_index("ix_robot_task_requests_correlation", table_name="robot_task_requests")
    op.drop_index("ix_robot_task_requests_task", table_name="robot_task_requests")
    op.drop_index("ix_robot_task_requests_robot_status", table_name="robot_task_requests")
    op.drop_table("robot_task_requests")

    op.drop_index(
        "ix_robot_state_snapshots_safety",
        table_name="robot_state_snapshots",
    )
    op.drop_index(
        "ix_robot_state_snapshots_robot_observed",
        table_name="robot_state_snapshots",
    )
    op.drop_table("robot_state_snapshots")

    op.drop_index(
        "ix_robot_capabilities_robot_enabled",
        table_name="robot_capabilities",
    )
    op.drop_table("robot_capabilities")

    op.drop_index("ix_robots_connection", table_name="robots")
    op.drop_table("robots")
