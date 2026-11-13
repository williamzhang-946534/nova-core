"""add robot failsafe and cancellation states

Revision ID: 8a9b0c1d2e3f
Revises: f7a8b9c0d1e2
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "8a9b0c1d2e3f"
down_revision: str | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("robot_task_requests", schema=None) as batch_op:
        batch_op.drop_constraint("ck_robot_task_requests_status", type_="check")
        batch_op.create_check_constraint(
            "ck_robot_task_requests_status",
            "status IN ('created', 'awaiting_confirmation', 'rejected', 'submitted', "
            "'accepted', 'running', 'waiting_result', 'succeeded', 'failed', "
            "'timeout', 'cancelled', 'cancel_requested', 'stopping', "
            "'cancel_failed', 'execution_state_unknown', 'safe_stopped', "
            "'unavailable')",
        )

    with op.batch_alter_table("robot_events", schema=None) as batch_op:
        batch_op.drop_constraint("ck_robot_events_type", type_="check")
        batch_op.create_check_constraint(
            "ck_robot_events_type",
            "event_type IN ('connection_changed', 'state_changed', 'safety_changed', "
            "'task_accepted', 'task_running', 'task_succeeded', 'task_failed', "
            "'task_cancelled', 'task_cancel_requested', 'task_stopping', "
            "'task_cancel_failed', 'task_execution_unknown', "
            "'task_safe_stopped', 'task_unavailable')",
        )


def downgrade() -> None:
    # A downgrade is only safe for records still using the pre-failsafe status set.
    with op.batch_alter_table("robot_events", schema=None) as batch_op:
        batch_op.drop_constraint("ck_robot_events_type", type_="check")
        batch_op.create_check_constraint(
            "ck_robot_events_type",
            "event_type IN ('connection_changed', 'state_changed', 'safety_changed', "
            "'task_accepted', 'task_running', 'task_succeeded', 'task_failed', "
            "'task_cancelled', 'task_safe_stopped', 'task_unavailable')",
        )

    with op.batch_alter_table("robot_task_requests", schema=None) as batch_op:
        batch_op.drop_constraint("ck_robot_task_requests_status", type_="check")
        batch_op.create_check_constraint(
            "ck_robot_task_requests_status",
            "status IN ('created', 'awaiting_confirmation', 'rejected', 'submitted', "
            "'accepted', 'running', 'waiting_result', 'succeeded', 'failed', "
            "'timeout', 'cancelled', 'safe_stopped', 'unavailable')",
        )
