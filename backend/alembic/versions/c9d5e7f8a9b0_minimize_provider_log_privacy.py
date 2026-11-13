"""minimize provider log privacy exposure

Revision ID: c9d5e7f8a9b0
Revises: b8c3d4e5f6a7
Create Date: 2026-11-11
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "c9d5e7f8a9b0"
down_revision: str | None = "b8c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, input_summary, error FROM provider_logs")
    ).mappings()
    for row in rows:
        old_input = _object(row["input_summary"])
        messages = old_input.get("messages")
        role_distribution: dict[str, int] = {}
        if isinstance(messages, list):
            for message in messages:
                if isinstance(message, dict) and isinstance(message.get("role"), str):
                    role_distribution[message["role"]] = (
                        role_distribution.get(message["role"], 0) + 1
                    )
        input_summary: dict[str, Any] = {
            "schema_version": 2,
            "request_id": row["id"],
            "correlation_id": old_input.get("correlation_id"),
            "message_count": len(messages) if isinstance(messages, list) else None,
            "role_distribution": dict(sorted(role_distribution.items())),
        }
        old_error = _object(row["error"])
        error = {"code": old_error.get("code", "PROVIDER_ERROR")}
        if not isinstance(error["code"], str):
            error["code"] = "PROVIDER_ERROR"
        connection.execute(
            sa.text(
                """
                UPDATE provider_logs
                SET input_summary = :input_summary, output_summary = '{}', error = :error
                WHERE id = :id
                """
            ),
            {
                "input_summary": json.dumps(input_summary, ensure_ascii=False),
                "error": json.dumps(error, ensure_ascii=False),
                "id": row["id"],
            },
        )


def downgrade() -> None:
    # Full conversation content was intentionally removed and cannot be restored.
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, input_summary FROM provider_logs")).mappings()
    for row in rows:
        input_summary = _object(row["input_summary"])
        input_summary["schema_version"] = 1
        connection.execute(
            sa.text("UPDATE provider_logs SET input_summary = :input_summary WHERE id = :id"),
            {
                "input_summary": json.dumps(input_summary, ensure_ascii=False),
                "id": row["id"],
            },
        )


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, bytes)):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}
