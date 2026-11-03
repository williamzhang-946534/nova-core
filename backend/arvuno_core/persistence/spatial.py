import re
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arvuno_core.persistence.exceptions import RepositoryError
from arvuno_core.persistence.models import (
    Device,
    Entity,
    EntitySpaceAssignment,
    Environment,
    Space,
    SpacePath,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_space_name(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", value.strip()).strip("-").lower()
    return normalized[:100] or "space"


def _device_entity_type(device_type: str) -> str:
    if device_type.startswith("sensor_") or device_type == "sensor":
        return "sensor"
    if device_type in {"light", "switch", "climate", "media_player", "actuator"}:
        return "actuator"
    return "device"


class SpaceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, space_id: str) -> Space | None:
        try:
            return self._session.get(Space, space_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a space.") from exc

    def get_by_slug(self, parent_id: str | None, slug: str) -> Space | None:
        try:
            parent_condition = (
                Space.parent_id.is_(None) if parent_id is None else Space.parent_id == parent_id
            )
            return self._session.scalars(
                select(Space).where(parent_condition, Space.slug == slug)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a space slug.") from exc

    def list_spaces(
        self,
        *,
        root_id: str | None = None,
        parent_id: str | None = None,
        space_type: str | None = None,
        status: str | None = None,
    ) -> list[Space]:
        try:
            statement = select(Space)
            if root_id is not None:
                statement = statement.where(
                    Space.id.in_(
                        select(SpacePath.descendant_id).where(SpacePath.ancestor_id == root_id)
                    )
                )
            if parent_id is not None:
                statement = statement.where(Space.parent_id == parent_id)
            if space_type is not None:
                statement = statement.where(Space.space_type == space_type)
            if status is not None:
                statement = statement.where(Space.status == status)
            return list(
                self._session.scalars(
                    statement.order_by(Space.path, Space.sort_order, Space.normalized_name)
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list spaces.") from exc

    def root_of(self, space: Space) -> Space:
        try:
            current = space
            visited: set[str] = set()
            while current.parent_id is not None:
                if current.id in visited:
                    raise RepositoryError("The space tree contains a cycle.")
                visited.add(current.id)
                parent = self._session.get(Space, current.parent_id)
                if parent is None:
                    raise RepositoryError("The space parent does not exist.")
                current = parent
            return current
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to resolve the space root.") from exc

    def add(self, space: Space) -> Space:
        self._session.add(space)
        return space

    def flush(self) -> None:
        try:
            self._session.flush()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a space.") from exc

    def rebuild_paths(self, root: Space) -> None:
        try:
            spaces: list[Space] = []
            pending = [root]
            visited: set[str] = set()
            while pending:
                current = pending.pop(0)
                if current.id in visited:
                    raise RepositoryError("The space tree contains a cycle.")
                visited.add(current.id)
                spaces.append(current)
                pending.extend(self.list_spaces(parent_id=current.id))
            if not spaces or spaces[0].id != root.id:
                raise RepositoryError("The space tree root is incomplete.")
            by_id = {space.id: space for space in spaces}
            children: dict[str | None, list[Space]] = {}
            for space in spaces:
                children.setdefault(space.parent_id, []).append(space)

            version = str(uuid4())
            self._session.execute(
                delete(SpacePath).where(SpacePath.descendant_id.in_([space.id for space in spaces]))
            )

            def visit(space: Space, path: str, ancestors: list[str]) -> None:
                space.path = path[:1024]
                for distance, ancestor_id in enumerate(reversed(ancestors), start=1):
                    self._session.add(
                        SpacePath(
                            ancestor_id=ancestor_id,
                            descendant_id=space.id,
                            depth=distance,
                            path_version=version,
                        )
                    )
                self._session.add(
                    SpacePath(
                        ancestor_id=space.id,
                        descendant_id=space.id,
                        depth=0,
                        path_version=version,
                    )
                )

            def walk(space: Space, path: str, ancestors: list[str]) -> None:
                visit(space, path, ancestors)
                for child in sorted(
                    children.get(space.id, []),
                    key=lambda item: (item.sort_order, item.normalized_name, item.id),
                ):
                    walk(child, f"{path}/{child.slug}", [*ancestors, space.id])

            if root.parent_id is not None or root.id not in by_id:
                raise RepositoryError("The supplied space is not a tree root.")
            walk(root, root.slug, [])
            self._session.flush()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to rebuild space paths.") from exc

    def has_active_children(self, space_id: str) -> bool:
        try:
            return (
                self._session.scalar(
                    select(func.count())
                    .select_from(Space)
                    .where(Space.parent_id == space_id, Space.status != "archived")
                )
                or 0
            ) > 0
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read child spaces.") from exc


class EntityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, entity_id: str) -> Entity | None:
        try:
            return self._session.get(Entity, entity_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read an entity.") from exc

    def ensure_device_entity(
        self,
        device: Device,
        environment: Environment,
    ) -> Entity:
        try:
            if device.entity_id is not None:
                entity = self._session.get(Entity, device.entity_id)
                if entity is not None:
                    return entity
            entity = Entity(
                environment_id=environment.id,
                entity_type=_device_entity_type(device.device_type),
                name=device.name,
                normalized_name=device.name.casefold(),
                status="active" if device.is_enabled else "inactive",
                semantic_tags=["device", device.device_type],
                metadata_summary={"device_id": device.id},
            )
            self._session.add(entity)
            self._session.flush()
            device.entity_id = entity.id
            self._session.flush()
            return entity
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to ensure a device entity.") from exc

    def add(self, entity: Entity) -> Entity:
        self._session.add(entity)
        return entity


class EntitySpaceAssignmentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, assignment_id: str) -> EntitySpaceAssignment | None:
        try:
            return self._session.get(EntitySpaceAssignment, assignment_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a space assignment.") from exc

    def list_for_entity(self, entity_id: str) -> list[EntitySpaceAssignment]:
        try:
            return list(
                self._session.scalars(
                    select(EntitySpaceAssignment)
                    .where(EntitySpaceAssignment.entity_id == entity_id)
                    .order_by(
                        EntitySpaceAssignment.valid_from.desc(),
                        EntitySpaceAssignment.created_at.desc(),
                    )
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list space assignments.") from exc

    def current_for_entity(
        self,
        entity_id: str,
        *,
        assignment_type: str | None = None,
    ) -> list[EntitySpaceAssignment]:
        try:
            statement = select(EntitySpaceAssignment).where(
                EntitySpaceAssignment.entity_id == entity_id,
                EntitySpaceAssignment.valid_until.is_(None),
            )
            if assignment_type is not None:
                statement = statement.where(
                    EntitySpaceAssignment.assignment_type == assignment_type
                )
            return list(
                self._session.scalars(statement.order_by(EntitySpaceAssignment.valid_from.desc()))
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read current space assignments.") from exc

    def current_for_tree(self, root_id: str) -> list[EntitySpaceAssignment]:
        try:
            descendants = select(SpacePath.descendant_id).where(SpacePath.ancestor_id == root_id)
            return list(
                self._session.scalars(
                    select(EntitySpaceAssignment)
                    .where(
                        EntitySpaceAssignment.space_id.in_(descendants),
                        EntitySpaceAssignment.valid_until.is_(None),
                    )
                    .order_by(
                        EntitySpaceAssignment.space_id,
                        EntitySpaceAssignment.valid_from.desc(),
                    )
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read space assignments.") from exc

    def overlapping(
        self,
        *,
        entity_id: str,
        assignment_type: str,
        valid_from: datetime,
        valid_until: datetime | None,
    ) -> list[EntitySpaceAssignment]:
        try:
            end_condition = (
                EntitySpaceAssignment.valid_until.is_(None)
                if valid_until is None
                else (
                    (EntitySpaceAssignment.valid_until.is_(None))
                    | (EntitySpaceAssignment.valid_until > valid_from)
                )
            )
            return list(
                self._session.scalars(
                    select(EntitySpaceAssignment).where(
                        EntitySpaceAssignment.entity_id == entity_id,
                        EntitySpaceAssignment.assignment_type == assignment_type,
                        EntitySpaceAssignment.valid_from <= valid_from,
                        end_condition,
                    )
                )
            )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to validate space assignment intervals.") from exc

    def devices_in_space(
        self,
        space_id: str,
        *,
        include_descendants: bool,
    ) -> list[tuple[Device, EntitySpaceAssignment]]:
        try:
            if include_descendants:
                space_ids = select(SpacePath.descendant_id).where(SpacePath.ancestor_id == space_id)
            else:
                space_ids = select(Space.__table__.c.id).where(Space.id == space_id)
            rows = self._session.execute(
                select(Device, EntitySpaceAssignment)
                .join(EntitySpaceAssignment, Device.entity_id == EntitySpaceAssignment.entity_id)
                .where(
                    EntitySpaceAssignment.space_id.in_(space_ids),
                    EntitySpaceAssignment.valid_until.is_(None),
                )
                .order_by(Device.normalized_name, Device.id)
            ).all()
            return [(row[0], row[1]) for row in rows]
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list devices in a space tree.") from exc

    def add(self, assignment: EntitySpaceAssignment) -> EntitySpaceAssignment:
        self._session.add(assignment)
        return assignment


__all__ = [
    "EntityRepository",
    "EntitySpaceAssignmentRepository",
    "SpaceRepository",
    "normalize_space_name",
    "utc_now",
]
