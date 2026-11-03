import asyncio
from collections import defaultdict
from collections.abc import Callable as CallableType
from typing import Any

from arvuno_core.errors import ArvunoError
from arvuno_core.persistence.models import Device, Environment, Space
from arvuno_core.persistence.spatial import normalize_space_name, utc_now
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork
from arvuno_core.spatial.errors import SpaceNotFoundError, SpatialError
from arvuno_core.spatial.models import (
    AssignedDevice,
    AssignmentHistoryItem,
    DeviceAssignmentResult,
    SpaceDetail,
    SpaceTreeNode,
)


class SpatialService:
    """Owns the reality-space tree and entity placement history."""

    def __init__(
        self,
        unit_of_work_factory: CallableType[[], SqlAlchemyUnitOfWork],
        *,
        environment_name: str = "home",
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._environment_name = environment_name

    async def ensure_root(self) -> SpaceDetail:
        return await asyncio.to_thread(self._ensure_root)

    async def list_spaces(
        self,
        *,
        space_type: str | None = None,
        status: str | None = None,
    ) -> list[SpaceDetail]:
        def execute() -> list[SpaceDetail]:
            with self._unit_of_work_factory() as uow:
                assert uow.spaces is not None
                root, _ = self._environment(uow)
                records = uow.spaces.list_spaces(
                    root_id=root.id,
                    space_type=space_type,
                    status=status,
                )
                return [_detail(item) for item in records]

        return await asyncio.to_thread(execute)

    async def tree(self) -> SpaceTreeNode:
        def execute() -> SpaceTreeNode:
            with self._unit_of_work_factory() as uow:
                assert uow.spaces is not None
                root, _ = self._environment(uow)
                return _tree(root, uow.spaces.list_spaces(root_id=root.id))

        return await asyncio.to_thread(execute)

    async def get_space(self, space_id: str) -> SpaceDetail:
        def execute() -> SpaceDetail:
            with self._unit_of_work_factory() as uow:
                assert uow.spaces is not None
                root, _ = self._environment(uow)
                space = self._space_in_tree(uow.spaces, root, space_id)
                return _detail(space)

        return await asyncio.to_thread(execute)

    async def create_space(
        self,
        *,
        parent_id: str,
        name: str,
        space_type: str,
        slug: str | None = None,
        sort_order: int = 0,
        external_space_id: str | None = None,
        external_source: str | None = None,
        geometry: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SpaceDetail:
        def execute() -> SpaceDetail:
            with self._unit_of_work_factory() as uow:
                assert uow.spaces is not None
                root, _ = self._environment(uow)
                parent = self._space_in_tree(uow.spaces, root, parent_id)
                if parent.status != "active":
                    raise SpatialError("An inactive or archived space cannot contain child spaces.")
                selected_slug = normalize_space_name(slug or name)
                if uow.spaces.get_by_slug(parent.id, selected_slug) is not None:
                    raise SpatialError(
                        "A sibling space already uses this slug.",
                        code="SPACE_SLUG_CONFLICT",
                    )
                space = Space(
                    parent_id=parent.id,
                    space_type=space_type,
                    name=name.strip(),
                    normalized_name=name.strip().casefold(),
                    slug=selected_slug,
                    path="pending",
                    sort_order=sort_order,
                    external_space_id=external_space_id,
                    external_source=external_source,
                    status="active",
                    geometry=geometry,
                    metadata_summary=metadata or {},
                )
                uow.spaces.add(space)
                uow.spaces.flush()
                uow.spaces.rebuild_paths(root)
                uow.commit()
                return _detail(space)

        return await asyncio.to_thread(execute)

    async def update_space(
        self,
        space_id: str,
        *,
        name: str | None = None,
        slug: str | None = None,
        sort_order: int | None = None,
        status: str | None = None,
        external_space_id: str | None = None,
        external_source: str | None = None,
        geometry: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SpaceDetail:
        def execute() -> SpaceDetail:
            with self._unit_of_work_factory() as uow:
                assert uow.space_assignments is not None
                assert uow.spaces is not None
                root, _ = self._environment(uow)
                space = self._space_in_tree(uow.spaces, root, space_id)
                if space.status == "archived":
                    raise SpatialError("An archived space cannot be updated.")

                next_slug = space.slug if slug is None else normalize_space_name(slug)
                if next_slug != space.slug:
                    conflict = uow.spaces.get_by_slug(space.parent_id, next_slug)
                    if conflict is not None and conflict.id != space.id:
                        raise SpatialError(
                            "A sibling space already uses this slug.",
                            code="SPACE_SLUG_CONFLICT",
                        )
                    space.slug = next_slug

                if name is not None:
                    space.name = name.strip()
                    space.normalized_name = space.name.casefold()
                if sort_order is not None:
                    space.sort_order = sort_order
                if external_space_id is not None:
                    space.external_space_id = external_space_id or None
                if external_source is not None:
                    space.external_source = external_source or None
                if geometry is not None:
                    space.geometry = geometry
                if metadata is not None:
                    space.metadata_summary = metadata

                if status is not None and status != space.status:
                    self._validate_status_transition(uow, root, space, status)
                    space.status = status

                uow.spaces.flush()
                uow.spaces.rebuild_paths(root)
                uow.commit()
                return _detail(space)

        return await asyncio.to_thread(execute)

    async def move_space(self, space_id: str, *, new_parent_id: str) -> SpaceDetail:
        def execute() -> SpaceDetail:
            with self._unit_of_work_factory() as uow:
                assert uow.spaces is not None
                root, _ = self._environment(uow)
                space = self._space_in_tree(uow.spaces, root, space_id)
                parent = self._space_in_tree(uow.spaces, root, new_parent_id)
                if space.parent_id is None:
                    raise SpatialError("A root space cannot be moved.")
                if space.status == "archived" or parent.status != "active":
                    raise SpatialError("Archived spaces cannot participate in a move.")
                if parent.id == space.id:
                    raise SpatialError("A space cannot be its own parent.")
                if self._is_descendant(uow.spaces, ancestor=space, descendant_id=parent.id):
                    raise SpatialError(
                        "A space cannot be moved below one of its descendants.",
                        code="SPACE_CYCLE",
                    )
                conflict = uow.spaces.get_by_slug(parent.id, space.slug)
                if conflict is not None and conflict.id != space.id:
                    raise SpatialError(
                        "The target parent already has a space with this slug.",
                        code="SPACE_SLUG_CONFLICT",
                    )
                space.parent_id = parent.id
                uow.spaces.flush()
                uow.spaces.rebuild_paths(root)
                uow.commit()
                return _detail(space)

        return await asyncio.to_thread(execute)

    async def archive_space(self, space_id: str) -> SpaceDetail:
        def execute() -> SpaceDetail:
            with self._unit_of_work_factory() as uow:
                assert uow.space_assignments is not None
                assert uow.spaces is not None
                root, _ = self._environment(uow)
                space = self._space_in_tree(uow.spaces, root, space_id)
                self._validate_status_transition(uow, root, space, "archived")
                space.status = "archived"
                space.archived_at = utc_now()
                uow.spaces.rebuild_paths(root)
                uow.commit()
                return _detail(space)

        return await asyncio.to_thread(execute)

    async def devices_in_space(
        self,
        space_id: str,
        *,
        include_descendants: bool = False,
    ) -> list[AssignedDevice]:
        def execute() -> list[AssignedDevice]:
            with self._unit_of_work_factory() as uow:
                assert uow.space_assignments is not None
                assert uow.spaces is not None
                root, _ = self._environment(uow)
                self._space_in_tree(uow.spaces, root, space_id)
                rows = uow.space_assignments.devices_in_space(
                    space_id,
                    include_descendants=include_descendants,
                )
                return [_assigned_device(device, assignment) for device, assignment in rows]

        return await asyncio.to_thread(execute)

    async def assign_device(
        self,
        device_id: str,
        *,
        space_id: str,
        assignment_type: str = "fixed_installation",
        confidence: float = 1.0,
        reason: str | None = None,
        source_type: str = "user",
        source_id: str | None = None,
    ) -> DeviceAssignmentResult:
        from arvuno_core.persistence.models import EntitySpaceAssignment

        def execute() -> DeviceAssignmentResult:
            with self._unit_of_work_factory() as uow:
                assert uow.devices is not None
                assert uow.entities is not None
                assert uow.environments is not None
                assert uow.space_assignments is not None
                assert uow.spaces is not None
                root, environment = self._environment(uow)
                space = self._space_in_tree(uow.spaces, root, space_id)
                if space.status != "active":
                    raise SpatialError("A device cannot be assigned to an inactive space.")
                device = uow.devices.get_by_id(device_id)
                if device is None:
                    raise ArvunoError(
                        code="NOT_FOUND",
                        message="The device does not exist.",
                        status_code=404,
                    )
                entity = uow.entities.ensure_device_entity(device, environment)
                current = uow.space_assignments.current_for_entity(
                    entity.id,
                    assignment_type=assignment_type,
                )
                if len(current) == 1 and current[0].space_id == space.id:
                    return _assignment_result(device, current[0], space)
                if len(current) > 1:
                    raise SpatialError("The entity has conflicting current assignments.")

                now = utc_now()
                for assignment in current:
                    assignment.valid_until = now
                    assignment.updated_at = now
                if uow.space_assignments.overlapping(
                    entity_id=entity.id,
                    assignment_type=assignment_type,
                    valid_from=now,
                    valid_until=None,
                ):
                    raise SpatialError("The new assignment overlaps an existing interval.")
                assignment = EntitySpaceAssignment(
                    entity_id=entity.id,
                    space_id=space.id,
                    assignment_type=assignment_type,
                    valid_from=now,
                    confidence=confidence,
                    source_type=source_type,
                    source_id=source_id or device.id,
                    reason=reason,
                )
                uow.space_assignments.add(assignment)
                uow.spaces.flush()
                device.area = space.name
                uow.commit()
                return _assignment_result(device, assignment, space)

        return await asyncio.to_thread(execute)

    async def device_history(self, device_id: str) -> list[AssignmentHistoryItem]:
        def execute() -> list[AssignmentHistoryItem]:
            with self._unit_of_work_factory() as uow:
                assert uow.devices is not None
                assert uow.space_assignments is not None
                assert uow.spaces is not None
                device = uow.devices.get_by_id(device_id)
                if device is None or device.entity_id is None:
                    raise ArvunoError(
                        code="NOT_FOUND",
                        message="The device does not exist or has no entity.",
                        status_code=404,
                    )
                assignments = uow.space_assignments.list_for_entity(device.entity_id)
                result: list[AssignmentHistoryItem] = []
                for assignment in assignments:
                    space = uow.spaces.get(assignment.space_id)
                    if space is not None:
                        result.append(_history_item(device, assignment, space))
                return result

        return await asyncio.to_thread(execute)

    def _ensure_root(self) -> SpaceDetail:
        with self._unit_of_work_factory() as uow:
            assert uow.spaces is not None
            root, _ = self._environment(uow, create_root=False)
            if root is None:
                environment = uow.environments.ensure_default(self._environment_name)
                slug = normalize_space_name(environment.name)
                if uow.spaces.get_by_slug(None, slug) is not None:
                    raise SpatialError("An unattached root space already uses this slug.")
                root = Space(
                    space_type="home",
                    name=environment.name,
                    normalized_name=environment.name.casefold(),
                    slug=slug,
                    path=slug,
                    sort_order=0,
                    status="active",
                    metadata_summary={},
                )
                uow.spaces.add(root)
                uow.spaces.flush()
                environment.root_space_id = root.id
                uow.spaces.rebuild_paths(root)
                uow.commit()
            return _detail(root)

    def _environment(
        self,
        uow: SqlAlchemyUnitOfWork,
        *,
        create_root: bool = True,
    ) -> tuple[Space, Environment]:
        if uow.environments is None or uow.spaces is None:
            raise RuntimeError("The spatial repositories are unavailable.")
        environment = uow.environments.ensure_default(self._environment_name)
        root = environment.root_space
        if root is None:
            if create_root:
                root = self._create_root(uow, environment)
            else:
                raise SpaceNotFoundError()
        return root, environment

    def _create_root(
        self,
        uow: SqlAlchemyUnitOfWork,
        environment: Environment,
    ) -> Space:
        assert uow.spaces is not None
        slug = normalize_space_name(environment.name)
        if uow.spaces.get_by_slug(None, slug) is not None:
            raise SpatialError("An unattached root space already uses this slug.")
        root = Space(
            space_type="home",
            name=environment.name,
            normalized_name=environment.name.casefold(),
            slug=slug,
            path=slug,
            sort_order=0,
            status="active",
            metadata_summary={},
        )
        uow.spaces.add(root)
        uow.spaces.flush()
        environment.root_space_id = root.id
        uow.spaces.rebuild_paths(root)
        return root

    def _space_in_tree(
        self,
        repository: Any,
        root: Space,
        space_id: str,
    ) -> Space:
        space = repository.get(space_id)
        if space is None or repository.root_of(space).id != root.id:
            raise SpaceNotFoundError()
        return space

    def _is_descendant(
        self,
        repository: Any,
        *,
        ancestor: Space,
        descendant_id: str,
    ) -> bool:
        current = repository.get(descendant_id)
        while current is not None and current.parent_id is not None:
            if current.parent_id == ancestor.id:
                return True
            current = repository.get(current.parent_id)
        return False

    def _validate_status_transition(
        self,
        uow: SqlAlchemyUnitOfWork,
        root: Space,
        space: Space,
        status: str,
    ) -> None:
        assert uow.space_assignments is not None
        assert uow.spaces is not None
        if status == "active":
            if space.parent_id is not None:
                parent = uow.spaces.get(space.parent_id)
                if parent is None or parent.status != "active":
                    raise SpatialError("A space can only be activated under an active parent.")
            return
        if status not in {"inactive", "archived"}:
            raise SpatialError("Unsupported space status.")
        if uow.spaces.has_active_children(space.id):
            raise SpatialError("Handle child spaces before deactivating this space.")
        current = uow.space_assignments.current_for_tree(root.id)
        space_ids = self._descendant_ids(uow.spaces, root, space.id)
        if any(assignment.space_id in space_ids for assignment in current):
            raise SpatialError("Move current device assignments before changing this space.")

    def _descendant_ids(
        self,
        repository: Any,
        root: Space,
        space_id: str,
    ) -> set[str]:
        spaces = repository.list_spaces(root_id=root.id)
        children: dict[str | None, list[Space]] = defaultdict(list)
        for item in spaces:
            children[item.parent_id].append(item)
        result = {space_id}

        def visit(identifier: str) -> None:
            for child in children.get(identifier, []):
                result.add(child.id)
                visit(child.id)

        visit(space_id)
        return result


def _detail(space: Space) -> SpaceDetail:
    return SpaceDetail.model_validate(space)


def _tree(root: Space, spaces: list[Space]) -> SpaceTreeNode:
    nodes = {space.id: SpaceTreeNode.model_validate(space) for space in spaces}
    children: dict[str | None, list[Space]] = defaultdict(list)
    for space in spaces:
        children[space.parent_id].append(space)
    for space in spaces:
        if space.parent_id is not None and space.parent_id in nodes:
            nodes[space.parent_id].children.append(nodes[space.id])
    return nodes[root.id]


def _assigned_device(device: Device, assignment: Any) -> AssignedDevice:
    return AssignedDevice(
        device_id=device.id,
        entity_id=device.entity_id or assignment.entity_id,
        adapter_id=device.adapter_id,
        external_id=device.external_id,
        name=device.name,
        device_type=device.device_type,
        is_online=device.is_online,
        is_enabled=device.is_enabled,
        assignment_id=assignment.id,
        assignment_type=assignment.assignment_type,
        valid_from=assignment.valid_from,
        valid_until=assignment.valid_until,
        confidence=assignment.confidence,
        source_type=assignment.source_type,
        source_id=assignment.source_id,
        reason=assignment.reason,
    )


def _history_item(device: Device, assignment: Any, space: Space) -> AssignmentHistoryItem:
    return AssignmentHistoryItem(
        id=assignment.id,
        entity_id=assignment.entity_id,
        device_id=device.id,
        space_id=space.id,
        space_name=space.name,
        space_path=space.path,
        assignment_type=assignment.assignment_type,
        valid_from=assignment.valid_from,
        valid_until=assignment.valid_until,
        confidence=assignment.confidence,
        source_type=assignment.source_type,
        source_id=assignment.source_id,
        source_observation_id=assignment.source_observation_id,
        reason=assignment.reason,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def _assignment_result(
    device: Device,
    assignment: Any,
    space: Space,
) -> DeviceAssignmentResult:
    return DeviceAssignmentResult(
        assignment=_history_item(device, assignment, space),
        space=_detail(space),
    )


__all__ = ["SpatialService"]
