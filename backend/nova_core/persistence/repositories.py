from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from nova_core.persistence.exceptions import RepositoryError
from nova_core.persistence.models import Device, Event, SystemSetting

ModelT = TypeVar("ModelT")


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
