"""create the ARS-02 spatial model

Revision ID: 7c2a9f10d48d
Revises: 07b82937bedb
Create Date: 2026-11-02
"""

from collections.abc import Sequence
from datetime import datetime, timezone
import json
import re
import uuid

import sqlalchemy as sa

from alembic import op

revision: str = "7c2a9f10d48d"
down_revision: str | None = "07b82937bedb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _slug(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", value.strip()).strip("-").lower()
    return normalized[:100] or "space"


def _unique_slug(conn: sa.Connection, parent_id: str | None, desired: str) -> str:
    if parent_id is None:
        parent_condition = "parent_id IS NULL"
        parameters: dict[str, object] = {"slug": desired}
    else:
        parent_condition = "parent_id = :parent_id"
        parameters = {"slug": desired, "parent_id": parent_id}
    existing = conn.execute(
        sa.text(f"SELECT slug FROM spaces WHERE {parent_condition} AND slug = :slug"),
        parameters,
    ).scalar()
    if existing is None:
        return desired
    suffix = 2
    while True:
        candidate = f"{desired[:96]}-{suffix}"
        parameters["slug"] = candidate
        existing = conn.execute(
            sa.text(f"SELECT slug FROM spaces WHERE {parent_condition} AND slug = :slug"),
            parameters,
        ).scalar()
        if existing is None:
            return candidate
        suffix += 1


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _entity_type(device_type: object) -> str:
    value = str(device_type or "")
    if value.startswith("sensor_") or value == "sensor":
        return "sensor"
    if value in {"light", "switch", "climate", "media_player", "actuator"}:
        return "actuator"
    return "device"


def _insert_space(
    conn: sa.Connection,
    *,
    parent_id: str | None,
    space_type: str,
    name: str,
    path: str,
) -> str:
    space_id = _uuid()
    slug = _unique_slug(conn, parent_id, _slug(name))
    conn.execute(
        sa.text(
            """
            INSERT INTO spaces (
                id, parent_id, space_type, name, normalized_name, slug, path,
                sort_order, external_space_id, external_source, status, geometry,
                metadata, created_at, updated_at, archived_at
            ) VALUES (
                :id, :parent_id, :space_type, :name, :normalized_name, :slug, :path,
                :sort_order, NULL, NULL, 'active', NULL, :metadata,
                :created_at, :created_at, NULL
            )
            """
        ),
        {
            "id": space_id,
            "parent_id": parent_id,
            "space_type": space_type,
            "name": name[:255],
            "normalized_name": name[:255].casefold(),
            "slug": slug,
            "path": path[:1024],
            "sort_order": 0,
            "metadata": json.dumps({"migration": "ars02_spatial_model"}, ensure_ascii=False),
            "created_at": _now(),
        },
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO space_paths (ancestor_id, descendant_id, depth, path_version, created_at)
            VALUES (:ancestor_id, :descendant_id, 0, :path_version, :created_at)
            """
        ),
        {
            "ancestor_id": space_id,
            "descendant_id": space_id,
            "path_version": _uuid(),
            "created_at": _now(),
        },
    )
    if parent_id is not None:
        conn.execute(
            sa.text(
                """
                INSERT INTO space_paths (
                    ancestor_id, descendant_id, depth, path_version, created_at
                )
                SELECT ancestor_id, :descendant_id, depth + 1, :path_version, :created_at
                FROM space_paths
                WHERE descendant_id = :parent_id
                """
            ),
            {
                "descendant_id": space_id,
                "parent_id": parent_id,
                "path_version": _uuid(),
                "created_at": _now(),
            },
        )
    return space_id


def _migrate_existing_data(conn: sa.Connection) -> None:
    environments = list(conn.execute(sa.text("SELECT id, name FROM environments")).mappings())
    if not environments:
        environment_id = _uuid()
        conn.execute(
            sa.text(
                """
                INSERT INTO environments (id, name, description, is_default, created_at)
                VALUES (:id, 'home', NULL, 1, :created_at)
                """
            ),
            {"id": environment_id, "created_at": _now()},
        )
        environments = [{"id": environment_id, "name": "home"}]

    roots: dict[str, str] = {}
    room_ids_by_root_and_area: dict[tuple[str, str], str] = {}
    for environment in environments:
        root_id = _insert_space(
            conn,
            parent_id=None,
            space_type="home",
            name=str(environment["name"]),
            path="",
        )
        roots[str(environment["id"])] = root_id
        root_path = _slug(str(environment["name"]))
        conn.execute(
            sa.text("UPDATE spaces SET path = :path WHERE id = :space_id"),
            {"path": root_path, "space_id": root_id},
        )
        conn.execute(
            sa.text("UPDATE environments SET root_space_id = :root_id WHERE id = :environment_id"),
            {"root_id": root_id, "environment_id": environment["id"]},
        )

    devices = list(
        conn.execute(
            sa.text("SELECT id, area, created_at, device_type, name FROM devices")
        ).mappings()
    )
    default_environment_id = str(environments[0]["id"])
    for device in devices:
        environment_id = default_environment_id
        entity_id = _uuid()
        name = str(device["name"])
        conn.execute(
            sa.text(
                """
                INSERT INTO entities (
                    id, environment_id, entity_type, name, normalized_name, description,
                    status, semantic_tags, capabilities_ref, metadata, created_at,
                    updated_at, retired_at
                ) VALUES (
                    :id, :environment_id, :entity_type, :name, :normalized_name, NULL,
                    'active', :semantic_tags, NULL, :metadata, :created_at, :created_at, NULL
                )
                """
            ),
            {
                "id": entity_id,
                "environment_id": environment_id,
                "entity_type": _entity_type(device["device_type"]),
                "name": name[:255],
                "normalized_name": name[:255].casefold(),
                "semantic_tags": json.dumps(
                    ["device", str(device["device_type"])], ensure_ascii=False
                ),
                "metadata": json.dumps(
                    {"created_by": "ars02_migration", "device_id": str(device["id"])},
                    ensure_ascii=False,
                ),
                "created_at": _now(),
            },
        )
        conn.execute(
            sa.text("UPDATE devices SET entity_id = :entity_id WHERE id = :device_id"),
            {"entity_id": entity_id, "device_id": device["id"]},
        )

        area = str(device["area"] or "").strip()
        if not area:
            continue
        root_id = roots[environment_id]
        room_key = (root_id, area.casefold())
        room_id = room_ids_by_root_and_area.get(room_key)
        if room_id is None:
            root_path = conn.execute(
                sa.text("SELECT path FROM spaces WHERE id = :root_id"),
                {"root_id": root_id},
            ).scalar_one()
            room_id = _insert_space(
                conn,
                parent_id=root_id,
                space_type="room",
                name=area,
                path=f"{root_path}/{_slug(area)}",
            )
            room_ids_by_root_and_area[room_key] = room_id

        conn.execute(
            sa.text(
                """
                INSERT INTO entity_space_assignments (
                    id, entity_id, space_id, assignment_type, valid_from, valid_until,
                    confidence, source_type, source_id, source_observation_id, reason,
                    created_at, updated_at
                ) VALUES (
                    :id, :entity_id, :space_id, 'fixed_installation', :valid_from, NULL,
                    0.8, 'migration', :source_id, NULL, :reason, :created_at, :created_at
                )
                """
            ),
            {
                "id": _uuid(),
                "entity_id": entity_id,
                "space_id": room_id,
                "valid_from": _datetime(device["created_at"]).isoformat(),
                "source_id": str(device["id"]),
                "reason": "Imported from the legacy devices.area compatibility field.",
                "created_at": _now(),
            },
        )


def upgrade() -> None:
    op.create_table(
        "spaces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("space_type", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("external_space_id", sa.String(length=255), nullable=True),
        sa.Column("external_source", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("geometry", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["spaces.id"],
            name=op.f("fk_spaces_parent_id_spaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spaces")),
        sa.UniqueConstraint("parent_id", "slug", name="uq_spaces_parent_slug"),
    )
    with op.batch_alter_table("spaces", schema=None) as batch_op:
        batch_op.create_index("ix_spaces_parent", ["parent_id"], unique=False)
        batch_op.create_index("ix_spaces_path", ["path"], unique=False)
        batch_op.create_index("ix_spaces_type", ["space_type"], unique=False)
        batch_op.create_index("ix_spaces_status", ["status"], unique=False)
        batch_op.create_index(
            "ix_spaces_external", ["external_source", "external_space_id"], unique=False
        )

    op.create_table(
        "space_paths",
        sa.Column("ancestor_id", sa.String(length=36), nullable=False),
        sa.Column("descendant_id", sa.String(length=36), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("path_version", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ancestor_id"],
            ["spaces.id"],
            name=op.f("fk_space_paths_ancestor_id_spaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["descendant_id"],
            ["spaces.id"],
            name=op.f("fk_space_paths_descendant_id_spaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ancestor_id", "descendant_id", name=op.f("pk_space_paths")),
    )
    with op.batch_alter_table("space_paths", schema=None) as batch_op:
        batch_op.create_index("ix_space_paths_descendant", ["descendant_id"], unique=False)

    op.create_table(
        "entities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("semantic_tags", sa.JSON(), nullable=False),
        sa.Column("capabilities_ref", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environments.id"],
            name=op.f("fk_entities_environment_id_environments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entities")),
    )
    with op.batch_alter_table("entities", schema=None) as batch_op:
        batch_op.create_index(
            "ix_entities_environment_type", ["environment_id", "entity_type"], unique=False
        )
        batch_op.create_index("ix_entities_normalized_name", ["normalized_name"], unique=False)

    with op.batch_alter_table("environments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("root_space_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_environments_root_space_id_spaces",
            "spaces",
            ["root_space_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_unique_constraint("uq_environments_root_space_id", ["root_space_id"])
        batch_op.create_index("ix_environments_root_space", ["root_space_id"], unique=False)

    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.add_column(sa.Column("entity_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_devices_entity_id_entities",
            "entities",
            ["entity_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_unique_constraint("uq_devices_entity_id", ["entity_id"])
        batch_op.create_index("ix_devices_entity", ["entity_id"], unique=False)

    op.create_table(
        "entity_space_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("assignment_type", sa.String(length=50), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=True),
        sa.Column("source_observation_id", sa.String(length=36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_entity_space_assignments_entity_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            name=op.f("fk_entity_space_assignments_space_id_spaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_space_assignments")),
    )
    with op.batch_alter_table("entity_space_assignments", schema=None) as batch_op:
        batch_op.create_index(
            "ix_entity_space_assignments_entity_from",
            ["entity_id", "valid_from"],
            unique=False,
        )
        batch_op.create_index(
            "ix_entity_space_assignments_space_from",
            ["space_id", "valid_from"],
            unique=False,
        )
        batch_op.create_index(
            "ix_entity_space_assignments_type", ["assignment_type"], unique=False
        )

    _migrate_existing_data(op.get_bind())


def downgrade() -> None:
    # Intended for rollback before ARS-02 placement history becomes authoritative.
    # Legacy devices, device_states, and events are never modified.
    op.drop_table("entity_space_assignments")
    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.drop_index("ix_devices_entity")
        batch_op.drop_constraint("uq_devices_entity_id", type_="unique")
        batch_op.drop_constraint("fk_devices_entity_id_entities", type_="foreignkey")
        batch_op.drop_column("entity_id")
    with op.batch_alter_table("environments", schema=None) as batch_op:
        batch_op.drop_index("ix_environments_root_space")
        batch_op.drop_constraint("uq_environments_root_space_id", type_="unique")
        batch_op.drop_constraint("fk_environments_root_space_id_spaces", type_="foreignkey")
        batch_op.drop_column("root_space_id")
    op.drop_table("entities")
    with op.batch_alter_table("space_paths", schema=None) as batch_op:
        batch_op.drop_index("ix_space_paths_descendant")
    op.drop_table("space_paths")
    with op.batch_alter_table("spaces", schema=None) as batch_op:
        batch_op.drop_index("ix_spaces_external")
        batch_op.drop_index("ix_spaces_status")
        batch_op.drop_index("ix_spaces_type")
        batch_op.drop_index("ix_spaces_path")
        batch_op.drop_index("ix_spaces_parent")
    op.drop_table("spaces")
