"""SQLAlchemy ORM models for Figaro orchestrator."""

import enum
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class TaskStatus(str, enum.Enum):
    """Task status enum."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class HelpRequestStatus(str, enum.Enum):
    """Help request status enum."""

    PENDING = "pending"
    RESPONDED = "responded"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class TaskModel(Base):
    """Task model for storing task data and results."""

    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status", create_constraint=True),
        nullable=False,
        default=TaskStatus.PENDING,
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scheduled_task_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("scheduled_tasks.schedule_id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="api")
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    messages: Mapped[list["TaskMessageModel"]] = relationship(
        "TaskMessageModel",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskMessageModel.sequence_number",
    )
    help_requests: Mapped[list["HelpRequestModel"]] = relationship(
        "HelpRequestModel",
        back_populates="task",
        cascade="all, delete-orphan",
    )


class TaskMessageModel(Base):
    """Task message model for storing conversation history."""

    __tablename__ = "task_messages"

    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    message_type: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationship
    task: Mapped["TaskModel"] = relationship("TaskModel", back_populates="messages")

    __table_args__ = (
        # Unique constraint for task_id + sequence_number
        {"sqlite_autoincrement": True},
    )


class ScheduledTaskModel(Base):
    """Scheduled task model for recurring task definitions."""

    __tablename__ = "scheduled_tasks"

    schedule_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    start_url: Mapped[str] = mapped_column(Text, nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    parallel_workers: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notify_on_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    self_learning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    self_healing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    self_learning_max_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    self_learning_run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class HelpRequestModel(Base):
    """Help request model for human-in-the-loop assistance."""

    __tablename__ = "help_requests"

    request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    task_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        nullable=False,
    )
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    status: Mapped[HelpRequestStatus] = mapped_column(
        Enum(HelpRequestStatus, name="help_request_status", create_constraint=True),
        nullable=False,
        default=HelpRequestStatus.PENDING,
    )
    answers: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    response_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationship
    task: Mapped["TaskModel"] = relationship("TaskModel", back_populates="help_requests")


class WorkerSessionModel(Base):
    """Worker session model for tracking worker connections."""

    __tablename__ = "worker_sessions"

    session_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    novnc_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disconnect_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tasks_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tasks_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class DesktopWorkerModel(Base):
    """Desktop worker model for persisting UI-added desktop-only workers."""

    __tablename__ = "desktop_workers"

    worker_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    novnc_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    vnc_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vnc_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )
