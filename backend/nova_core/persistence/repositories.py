from dataclasses import dataclass
from datetime import datetime
from typing import Any, Generic, TypeVar

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from nova_core.persistence.exceptions import RepositoryError
from nova_core.persistence.models import Device, DeviceCapability, DeviceState, Event, SystemSetting

ModelT = TypeVar("ModelT")


@dataclass(frozen=True)
class CapabilityRecord:
    capability: str
    supported_actions: list[str]
    parameters: dict[str, Any]
    risk_level: str
    requires_confirmation: bool
    enabled: bool = True


@dataclass(frozen=True)
class DeviceProjectionUpdate:
    adapter_id: str
    external_id: str
    name: str
    device_type: str
    area: str | None
    manufacturer: str | None
    model: str | None
    is_online: bool
    risk_level: str
    capabilities: dict[str, Any]
    metadata_summary: dict[str, Any]
    last_seen_at: datetime | None


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entity: ModelT) -> ModelT:
        self._session.add(entity)
        return entity

    def get(self, entity_id: str) -> ModelT | None:
        try:
            return self._session.get(self.model, entity_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a database entity.") from exc

    def list(self, *, page: int = 1, page_size: int = 20) -> list[ModelT]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("Page must be positive and page_size must be between 1 and 100")
        try:
            statement = select(self.model).offset((page - 1) * page_size).limit(page_size)
            return list(self._session.scalars(statement))
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list database entities.") from exc


class DeviceRepository(BaseRepository[Device]):
    model = Device

    def get_by_external_id(self, adapter_id: str, external_id: str) -> Device | None:
        try:
            statement = select(Device).where(
                Device.adapter_id == adapter_id,
                Device.external_id == external_id,
            )
            return self._session.scalars(statement).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a device projection.") from exc

    def get_by_id(self, device_id: str) -> Device | None:
        try:
            return self._session.get(Device, device_id)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a device projection.") from exc

    def list_devices(
        self,
        *,
        adapter_id: str | None = None,
        device_type: str | None = None,
        area: str | None = None,
        is_online: bool | None = None,
        is_enabled: bool | None = None,
        keyword: str | None = None,
    ) -> list[Device]:
        try:
            statement = select(Device).order_by(Device.normalized_name, Device.id)
            if adapter_id is not None:
                statement = statement.where(Device.adapter_id == adapter_id)
            if device_type is not None:
                statement = statement.where(Device.device_type == device_type)
            if area is not None:
                statement = statement.where(Device.area == area)
            if is_online is not None:
                statement = statement.where(Device.is_online == is_online)
            if is_enabled is not None:
                statement = statement.where(Device.is_enabled == is_enabled)
            if keyword:
                normalized = keyword.casefold()
                statement = statement.where(
                    or_(
                        Device.normalized_name.ilike(f"%{normalized}%"),
                        Device.name.ilike(f"%{keyword}%"),
                    )
                )
            return list(self._session.scalars(statement))
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list device projections.") from exc

    def upsert_projection(self, update: DeviceProjectionUpdate) -> Device:
        try:
            projection = self.get_by_external_id(update.adapter_id, update.external_id)
            if projection is None:
                projection = Device(
                    adapter_id=update.adapter_id,
                    external_id=update.external_id,
                    name=update.name,
                    normalized_name=update.name.casefold(),
                    device_type=update.device_type,
                    area=update.area,
                    manufacturer=update.manufacturer,
                    model=update.model,
                    is_online=update.is_online,
                    is_enabled=True,
                    risk_level=update.risk_level,
                    capabilities=update.capabilities,
                    metadata_summary=update.metadata_summary,
                    last_seen_at=update.last_seen_at,
                )
                self._session.add(projection)
                self._session.flush()
            else:
                capabilities = dict(update.capabilities)
                existing_profile = (projection.capabilities or {}).get("profile")
                if existing_profile is not None:
                    capabilities["profile"] = existing_profile
                projection.name = update.name
                projection.normalized_name = update.name.casefold()
                projection.device_type = update.device_type
                projection.area = update.area
                projection.manufacturer = update.manufacturer
                projection.model = update.model
                projection.is_online = update.is_online
                projection.risk_level = update.risk_level
                projection.capabilities = capabilities
                projection.metadata_summary = update.metadata_summary
                projection.last_seen_at = update.last_seen_at
            return projection
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a device projection.") from exc

    def disable_not_in_external_ids(self, adapter_id: str, external_ids: list[str]) -> int:
        try:
            statement = select(Device).where(
                Device.adapter_id == adapter_id,
                Device.is_enabled.is_(True),
                Device.external_id.not_in(external_ids),
            )
            disabled = list(self._session.scalars(statement))
            for projection in disabled:
                projection.is_enabled = False
            return len(disabled)
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to disable stale device projections.") from exc

    def replace_capabilities(
        self,
        device_id: str,
        capabilities: list[CapabilityRecord],
    ) -> None:
        try:
            projection = self.get_by_id(device_id)
            if projection is None:
                raise RepositoryError("Device projection does not exist.")
            for existing in list(projection.capability_records):
                self._session.delete(existing)
            self._session.flush()
            for capability in capabilities:
                projection.capability_records.append(
                    DeviceCapability(
                        device_id=device_id,
                        capability=capability.capability,
                        supported_actions=capability.supported_actions,
                        parameters=capability.parameters,
                        risk_level=capability.risk_level,
                        requires_confirmation=capability.requires_confirmation,
                        enabled=capability.enabled,
                    )
                )
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save device capabilities.") from exc

    def update_registry_profile(
        self,
        device_id: str,
        *,
        aliases: list[str] | None = None,
        allowed_actions: list[str] | None = None,
        max_risk_level: str | None = None,
        requires_confirmation: bool | None = None,
    ) -> Device:
        projection = self.get_by_id(device_id)
        if projection is None:
            raise RepositoryError("Device projection does not exist.")
        summary = dict(projection.capabilities)
        entries = list(summary.get("entries", []))
        profile = dict(summary.get("profile", {}))
        if aliases is not None:
            profile["aliases"] = aliases
        permissions = dict(profile.get("permissions", {}))
        if allowed_actions is not None:
            permissions["allowed_actions"] = allowed_actions
        if max_risk_level is not None:
            permissions["max_risk_level"] = max_risk_level
        if requires_confirmation is not None:
            permissions["requires_confirmation"] = requires_confirmation
        profile["permissions"] = permissions
        summary = {"entries": entries, "profile": profile}
        projection.capabilities = summary
        return projection

    def add_state_snapshot(
        self,
        device_id: str,
        *,
        state: str,
        attributes: dict[str, Any],
        raw_state: str | None,
        source: str,
        observed_at: datetime,
    ) -> DeviceState:
        try:
            projection = self.get_by_id(device_id)
            if projection is None:
                raise RepositoryError("Device projection does not exist.")
            snapshot = DeviceState(
                device_id=device_id,
                state=state,
                attributes=attributes,
                raw_state=raw_state,
                source=source,
                observed_at=observed_at,
            )
            self._session.add(snapshot)
            return snapshot
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a device state snapshot.") from exc

    def latest_state(self, device_id: str) -> DeviceState | None:
        try:
            statement = (
                select(DeviceState)
                .where(DeviceState.device_id == device_id)
                .order_by(DeviceState.observed_at.desc(), DeviceState.created_at.desc())
                .limit(1)
            )
            return self._session.scalars(statement).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read the latest device state.") from exc


class EventRepository(BaseRepository[Event]):
    model = Event

    def list(
        self,
        *,
        event_type: str | None = None,
        source: str | None = None,
        subject_id: str | None = None,
        correlation_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[Event]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("Page must be positive and page_size must be between 1 and 100")
        try:
            statement = select(Event).order_by(Event.occurred_at.desc())
            if event_type is not None:
                statement = statement.where(Event.event_type == event_type)
            if source is not None:
                statement = statement.where(Event.source == source)
            if subject_id is not None:
                statement = statement.where(Event.subject_id == subject_id)
            if correlation_id is not None:
                statement = statement.where(Event.correlation_id == correlation_id)
            statement = statement.offset((page - 1) * page_size).limit(page_size)
            return list(self._session.scalars(statement))
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list events.") from exc


class SystemSettingRepository(BaseRepository[SystemSetting]):
    model = SystemSetting

    def upsert_non_sensitive(
        self,
        *,
        key: str,
        value: dict[str, Any],
        value_type: str,
        description: str | None = None,
    ) -> SystemSetting:
        try:
            setting = self.get_by_key(key)
            if setting is None:
                setting = SystemSetting(
                    key=key,
                    value=value,
                    value_type=value_type,
                    is_secret=False,
                    description=description,
                )
                self._session.add(setting)
            else:
                if setting.is_secret:
                    raise RepositoryError("Secret system settings cannot be updated here.")
                setting.value = value
                setting.value_type = value_type
                setting.description = description
            return setting
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to save a system setting.") from exc

    def get_by_key(self, key: str) -> SystemSetting | None:
        try:
            return self._session.scalars(
                select(SystemSetting).where(SystemSetting.key == key)
            ).first()
        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to read a system setting.") from exc
