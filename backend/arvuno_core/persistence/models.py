from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime


def utc_now() -> datetime:
    return datetime.now(UTC)


def uuid_string() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    adapter_id: Mapped[str] = mapped_column(String(100))
    external_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255))
    device_type: Mapped[str] = mapped_column(String(100))
    area: Mapped[str | None] = mapped_column(String(255))
    manufacturer: Mapped[str | None] = mapped_column(String(255))
    model: Mapped[str | None] = mapped_column(String(255))
    is_online: Mapped[bool]
    is_enabled: Mapped[bool]
    risk_level: Mapped[str] = mapped_column(String(50))
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON)
    metadata_summary: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        UniqueConstraint("adapter_id", "external_id", name="uq_devices_adapter_external"),
        Index("ix_devices_adapter_external", "adapter_id", "external_id"),
        Index("ix_devices_device_type", "device_type"),
        Index("ix_devices_area", "area"),
    )

    states: Mapped[list["DeviceState"]] = relationship(
        back_populates="device", cascade="all, delete-orphan", passive_deletes=True
    )
    capability_records: Mapped[list["DeviceCapability"]] = relationship(
        back_populates="device", cascade="all, delete-orphan", passive_deletes=True
    )


class DeviceState(Base):
    __tablename__ = "device_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(100))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON)
    raw_state: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(100))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (Index("ix_device_states_device_observed", "device_id", "observed_at"),)

    device: Mapped[Device] = relationship(back_populates="states")


class DeviceCapability(Base):
    __tablename__ = "device_capabilities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    capability: Mapped[str] = mapped_column(String(100))
    supported_actions: Mapped[list[str]] = mapped_column(JSON)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    risk_level: Mapped[str] = mapped_column(String(50))
    requires_confirmation: Mapped[bool]
    enabled: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        UniqueConstraint("device_id", "capability", name="uq_device_capabilities_capability"),
        Index("ix_device_capabilities_capability", "capability"),
    )

    device: Mapped[Device] = relationship(back_populates="capability_records")


class Environment(Base):
    __tablename__ = "environments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (Index("ix_environments_name", "name"),)

    snapshots: Mapped[list["EnvironmentSnapshot"]] = relationship(
        back_populates="environment", cascade="all, delete-orphan", passive_deletes=True
    )


class EnvironmentSnapshot(Base):
    __tablename__ = "environment_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    context: Mapped[dict[str, Any]] = mapped_column(JSON)
    active_task_ids: Mapped[list[str]] = mapped_column(JSON)
    anomaly_count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("ix_environment_snapshots_environment_created", "environment_id", "created_at"),
    )

    environment: Mapped[Environment] = relationship(back_populates="snapshots")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    event_type: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(100))
    subject_type: Mapped[str | None] = mapped_column(String(100))
    subject_id: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("ix_events_type_occurred", "event_type", "occurred_at"),
        Index("ix_events_subject_occurred", "subject_type", "subject_id", "occurred_at"),
        Index("ix_events_correlation", "correlation_id"),
    )

    automation_runs: Mapped[list["AutomationRun"]] = relationship(back_populates="trigger_event")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )
    tasks: Mapped[list["Task"]] = relationship(back_populates="conversation")


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(Text)
    structured_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    provider_log_id: Mapped[str | None] = mapped_column(String(36))
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (Index("ix_conversation_messages_created", "conversation_id", "created_at"),)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    task_type: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50))
    origin: Mapped[str] = mapped_column(String(50))
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    plan: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_tasks_status_created", "status", "created_at"),
        Index("ix_tasks_conversation", "conversation_id"),
        Index("ix_tasks_correlation", "correlation_id"),
    )

    conversation: Mapped[Conversation | None] = relationship(back_populates="tasks")
    steps: Mapped[list["TaskStep"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    executions: Mapped[list["ToolExecution"]] = relationship(back_populates="task")


class TaskStep(Base):
    __tablename__ = "task_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    step_index: Mapped[int]
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50))
    input: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("task_id", "step_index", name="uq_task_steps_index"),
        Index("ix_task_steps_index", "task_id", "step_index"),
    )

    task: Mapped[Task] = relationship(back_populates="steps")
    executions: Mapped[list["ToolExecution"]] = relationship(back_populates="task_step")


class Tool(Base):
    __tablename__ = "tools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    name: Mapped[str] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100))
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    risk_level: Mapped[str] = mapped_column(String(50))
    default_permission: Mapped[str] = mapped_column(String(50))
    requires_confirmation: Mapped[bool]
    enabled: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (UniqueConstraint("name", name="uq_tools_name"),)

    executions: Mapped[list["ToolExecution"]] = relationship(back_populates="tool")


class ToolExecution(Base):
    __tablename__ = "tool_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.id"))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    task_step_id: Mapped[str | None] = mapped_column(ForeignKey("task_steps.id"))
    status: Mapped[str] = mapped_column(String(50))
    input: Mapped[dict[str, Any]] = mapped_column(JSON)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    risk_level: Mapped[str] = mapped_column(String(50))
    permission_result: Mapped[str] = mapped_column(String(100))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None]

    __table_args__ = (
        Index("ix_tool_executions_tool_started", "tool_id", "started_at"),
        Index("ix_tool_executions_task", "task_id"),
        Index("ix_tool_executions_correlation", "correlation_id"),
    )

    tool: Mapped[Tool] = relationship(back_populates="executions")
    task: Mapped[Task | None] = relationship(back_populates="executions")
    task_step: Mapped[TaskStep | None] = relationship(back_populates="executions")


class ProviderLog(Base):
    __tablename__ = "provider_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    provider: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(255))
    request_kind: Mapped[str] = mapped_column(String(50))
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(50))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    latency_ms: Mapped[int | None]
    prompt_tokens: Mapped[int | None]
    completion_tokens: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (Index("ix_provider_logs_created", "created_at"),)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    key: Mapped[str] = mapped_column(String(255))
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    category: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100))
    confirmed: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (UniqueConstraint("key", name="uq_user_preferences_key"),)


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    memory_type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(JSON)
    importance: Mapped[int]
    source_type: Mapped[str] = mapped_column(String(100))
    source_id: Mapped[str | None] = mapped_column(String(255))
    user_confirmed: Mapped[bool]
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        Index("ix_memories_type_created", "memory_type", "created_at"),
        Index("ix_memories_source", "source_type", "source_id"),
    )


class Automation(Base):
    __tablename__ = "automations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool]
    trigger: Mapped[dict[str, Any]] = mapped_column(JSON)
    condition: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    action: Mapped[dict[str, Any]] = mapped_column(JSON)
    cooldown_seconds: Mapped[int]
    risk_level: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    runs: Mapped[list["AutomationRun"]] = relationship(
        back_populates="automation", cascade="all, delete-orphan", passive_deletes=True
    )


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    automation_id: Mapped[str] = mapped_column(ForeignKey("automations.id", ondelete="CASCADE"))
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"))
    status: Mapped[str] = mapped_column(String(50))
    matched_context: Mapped[dict[str, Any]] = mapped_column(JSON)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_automation_runs_started", "automation_id", "started_at"),)

    automation: Mapped[Automation] = relationship(back_populates="runs")
    trigger_event: Mapped[Event | None] = relationship(back_populates="automation_runs")
    task: Mapped[Task | None] = relationship()


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    key: Mapped[str] = mapped_column(String(255))
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    value_type: Mapped[str] = mapped_column(String(50))
    is_secret: Mapped[bool]
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (UniqueConstraint("key", name="uq_system_settings_key"),)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    channel: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50))
    related_event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"))
    related_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_notifications_created", "created_at"),
        Index("ix_notifications_related_task", "related_task_id"),
    )

    related_event: Mapped[Event | None] = relationship()
    related_task: Mapped[Task | None] = relationship()
