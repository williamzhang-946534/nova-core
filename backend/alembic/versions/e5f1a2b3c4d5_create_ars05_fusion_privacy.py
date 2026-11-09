"""create ARS-05 fusion privacy governance

Revision ID: e5f1a2b3c4d5
Revises: bc51e7a90f4d
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f1a2b3c4d5"
down_revision: str | None = "bc51e7a90f4d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "multimodal_data_access_grants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("modalities", sa.JSON(), nullable=False),
        sa.Column("space_ids", sa.JSON(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_multimodal_access_grants"),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name="fk_multimodal_access_grants_environment",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('granted', 'revoked', 'expired')",
            name="ck_multimodal_access_grants_status",
        ),
    )
    op.create_index(
        "ix_multimodal_access_grants_subject",
        "multimodal_data_access_grants",
        ["environment_id", "user_id", "status"],
    )

    op.create_table(
        "multimodal_audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=True),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("subject_type", sa.String(length=50), nullable=True),
        sa.Column("subject_id", sa.String(length=255), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_multimodal_audit_events"),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name="fk_multimodal_audit_events_environment",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "action IN ('asset_uploaded', 'asset_read', 'asset_analyzed', "
            "'asset_purged', 'consent_revoked', 'grant_created', 'grant_revoked', "
            "'fusion_queried', 'speech_synthesized')",
            name="ck_multimodal_audit_events_action",
        ),
    )
    op.create_index(
        "ix_multimodal_audit_events_environment_time",
        "multimodal_audit_events",
        ["environment_id", "occurred_at"],
    )
    op.create_index(
        "ix_multimodal_audit_events_action_time",
        "multimodal_audit_events",
        ["action", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_multimodal_audit_events_action_time",
        table_name="multimodal_audit_events",
    )
    op.drop_index(
        "ix_multimodal_audit_events_environment_time",
        table_name="multimodal_audit_events",
    )
    op.drop_table("multimodal_audit_events")
    op.drop_index(
        "ix_multimodal_access_grants_subject",
        table_name="multimodal_data_access_grants",
    )
    op.drop_table("multimodal_data_access_grants")
