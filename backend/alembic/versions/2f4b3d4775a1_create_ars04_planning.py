"""create the ARS-04 planning and goal model

Revision ID: 2f4b3d4775a1
Revises: c7a8d9e21b46
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2f4b3d4775a1"
down_revision: str | None = "c7a8d9e21b46"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("origin_type", sa.String(length=30), nullable=False, server_default="'user'"),
        sa.Column("origin_record_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="'candidate'"),
        sa.Column("goal_type", sa.String(length=30), nullable=False, server_default="'other'"),
        sa.Column("scope", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("desired_state", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("constraints", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("prohibitions", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("clarifications", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("unknowns", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("success_conditions", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("failure_conditions", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="'normal'"),
        sa.Column(
            "authorization_scope",
            sa.JSON(),
            nullable=False,
            server_default=('\'{"max_risk_level": "read_only", "automatic_execution": "none"}\''),
        ),
        sa.Column("time_window", sa.JSON(), nullable=True),
        sa.Column("reasoning_session_id", sa.String(length=36), nullable=True),
        sa.Column("parent_goal_id", sa.String(length=36), nullable=True),
        sa.Column("confirmed_by_user", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name="fk_goals_environment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reasoning_session_id"],
            ["reasoning_sessions.id"],
            name="fk_goals_reasoning_session",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_goal_id"], ["goals.id"], name="fk_goals_parent", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_goals"),
        sa.CheckConstraint(
            "origin_type IN ('user', 'model', 'automation', 'system')",
            name="ck_goals_origin",
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'active', 'paused', 'completed', 'failed', "
            "'cancelled', 'expired')",
            name="ck_goals_status",
        ),
        sa.CheckConstraint(
            "goal_type IN ('comfort', 'energy', 'device_state', 'routine', "
            "'diagnosis', 'safety_check', 'other')",
            name="ck_goals_type",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'critical')",
            name="ck_goals_priority",
        ),
    )
    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.create_index("ix_goals_environment_status", ["environment_id", "status"])
        batch_op.create_index("ix_goals_origin", ["origin_type", "origin_record_id"])

    op.create_table(
        "goal_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("goal_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.String(length=30), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["goal_id"], ["goals.id"], name="fk_goal_revisions_goal", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_goal_revisions"),
        sa.UniqueConstraint("goal_id", "revision", name="uq_goal_revisions_goal_revision"),
        sa.CheckConstraint(
            "change_type IN ('create', 'clarify', 'rescope', 'confirm', 'pause', "
            "'resume', 'close')",
            name="ck_goal_revisions_change_type",
        ),
    )
    with op.batch_alter_table("goal_revisions", schema=None) as batch_op:
        batch_op.create_index("ix_goal_revisions_goal", ["goal_id", "revision"])

    op.create_table(
        "plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("goal_id", sa.String(length=36), nullable=False),
        sa.Column("reasoning_session_id", sa.String(length=36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="'draft'"),
        sa.Column("planner_type", sa.String(length=20), nullable=False, server_default="'rule'"),
        sa.Column(
            "run_mode",
            sa.String(length=30),
            nullable=False,
            server_default="'awaiting_confirmation'",
        ),
        sa.Column("strategy", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("constraints", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column(
            "max_risk_level", sa.String(length=20), nullable=False, server_default="'read_only'"
        ),
        sa.Column("estimated_duration", sa.JSON(), nullable=True),
        sa.Column("resource_requirements", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("validation_errors", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("success_criteria", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("failure_policy", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("submitted_task_id", sa.String(length=36), nullable=True),
        sa.Column("superseded_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name="fk_plans_environment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["goal_id"], ["goals.id"], name="fk_plans_goal", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reasoning_session_id"],
            ["reasoning_sessions.id"],
            name="fk_plans_reasoning_session",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_task_id"], ["tasks.id"], name="fk_plans_task", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"], ["plans.id"], name="fk_plans_superseded_by", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plans"),
        sa.UniqueConstraint("goal_id", "version", name="uq_plans_goal_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'validated', 'awaiting_confirmation', 'approved', "
            "'submitted', 'superseded', 'cancelled', 'rejected')",
            name="ck_plans_status",
        ),
        sa.CheckConstraint(
            "planner_type IN ('rule', 'model', 'hybrid', 'template', 'user')",
            name="ck_plans_planner_type",
        ),
        sa.CheckConstraint(
            "run_mode IN ('analyze_only', 'suggest_only', 'awaiting_confirmation', "
            "'confirm_then_execute', 'limited_auto_execute')",
            name="ck_plans_run_mode",
        ),
        sa.CheckConstraint(
            "max_risk_level IN ('read_only', 'low_risk', 'medium_risk', 'high_risk')",
            name="ck_plans_max_risk",
        ),
    )
    with op.batch_alter_table("plans", schema=None) as batch_op:
        batch_op.create_index("ix_plans_goal_version", ["goal_id", "version"])
        batch_op.create_index("ix_plans_environment_status", ["environment_id", "status"])
        batch_op.create_index("ix_plans_submitted_task", ["submitted_task_id"])

    op.create_table(
        "plan_steps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("tool_version", sa.String(length=50), nullable=True),
        sa.Column("input", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("preconditions", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("expected_effect", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("postconditions", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("verification", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("retry_policy", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("on_failure", sa.String(length=40), nullable=False, server_default="'stop'"),
        sa.Column("depends_on", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name="fk_plan_steps_plan", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plan_steps"),
        sa.UniqueConstraint("plan_id", "step_index", name="uq_plan_steps_plan_index"),
        sa.CheckConstraint(
            "risk_level IN ('read_only', 'low_risk', 'medium_risk', 'high_risk')",
            name="ck_plan_steps_risk",
        ),
        sa.CheckConstraint(
            "on_failure IN ('stop', 'request_user_confirmation', 'request_replan')",
            name="ck_plan_steps_on_failure",
        ),
    )
    with op.batch_alter_table("plan_steps", schema=None) as batch_op:
        batch_op.create_index("ix_plan_steps_plan", ["plan_id", "step_index"])
        batch_op.create_index("ix_plan_steps_tool", ["tool_name"])

    op.create_table(
        "plan_replanning_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("old_plan_id", sa.String(length=36), nullable=False),
        sa.Column("new_plan_id", sa.String(length=36), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("trigger_type", sa.String(length=50), nullable=False),
        sa.Column("trigger_record_type", sa.String(length=50), nullable=True),
        sa.Column("trigger_record_id", sa.String(length=255), nullable=True),
        sa.Column("change_summary", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("risk_delta", sa.JSON(), nullable=False, server_default="'{}'"),
        sa.Column("already_executed_steps", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("reversible_steps", sa.JSON(), nullable=False, server_default="'[]'"),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name="fk_plan_replanning_environment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["old_plan_id"], ["plans.id"], name="fk_plan_replanning_old_plan", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["new_plan_id"], ["plans.id"], name="fk_plan_replanning_new_plan", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name="fk_plan_replanning_task", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plan_replanning_records"),
        sa.CheckConstraint(
            "trigger_type IN ('precondition_failed', 'tool_failed', 'verification_failed', "
            "'goal_changed', 'environment_changed', 'user_cancelled', "
            "'priority_preempted', 'timeout')",
            name="ck_plan_replanning_trigger",
        ),
        sa.CheckConstraint(
            "decision IN ('replan', 'stop', 'wait_user_confirmation', 'reject')",
            name="ck_plan_replanning_decision",
        ),
    )
    with op.batch_alter_table("plan_replanning_records", schema=None) as batch_op:
        batch_op.create_index("ix_plan_replanning_old_plan", ["old_plan_id", "created_at"])
        batch_op.create_index("ix_plan_replanning_task", ["task_id"])


def downgrade() -> None:
    op.drop_table("plan_replanning_records")
    op.drop_table("plan_steps")
    op.drop_table("plans")
    op.drop_table("goal_revisions")
    op.drop_table("goals")
