"""Task repository for database operations."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from figaro.db.models import TaskMessageModel, TaskModel, TaskStatus


class TaskRepository:
    """Repository for task database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        prompt: str,
        options: dict[str, Any] | None = None,
        task_id: str | None = None,
        scheduled_task_id: str | None = None,
        source: str = "api",
        source_metadata: dict[str, Any] | None = None,
    ) -> TaskModel:
        """Create a new task.

        Args:
            prompt: The task prompt
            options: Task options/configuration
            task_id: Optional specific task ID
            scheduled_task_id: Optional reference to scheduled task
            source: Task source (api, telegram, scheduler, ui)
            source_metadata: Additional source metadata

        Returns:
            The created TaskModel
        """
        model = TaskModel(
            prompt=prompt,
            options=options or {},
            source=source,
            source_metadata=source_metadata or {},
        )
        if task_id:
            model.task_id = task_id
        if scheduled_task_id:
            model.scheduled_task_id = scheduled_task_id

        self.session.add(model)
        await self.session.flush()
        return model

    async def get(self, task_id: str) -> TaskModel | None:
        """Get a task by ID.

        Args:
            task_id: The task ID to fetch

        Returns:
            TaskModel if found, None otherwise
        """
        result = await self.session.execute(
            select(TaskModel).where(TaskModel.task_id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_with_messages(self, task_id: str) -> TaskModel | None:
        """Get a task with its messages loaded.

        Args:
            task_id: The task ID to fetch

        Returns:
            TaskModel with messages relationship loaded
        """
        result = await self.session.execute(
            select(TaskModel)
            .where(TaskModel.task_id == task_id)
            .options(selectinload(TaskModel.messages))
        )
        return result.scalar_one_or_none()

    async def list_pending(self) -> list[TaskModel]:
        """Get all pending tasks ordered by creation time.

        Returns:
            List of pending TaskModel instances
        """
        result = await self.session.execute(
            select(TaskModel)
            .where(TaskModel.status == TaskStatus.PENDING)
            .order_by(TaskModel.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_by_status(
        self,
        status: TaskStatus,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TaskModel]:
        """Get tasks by status with pagination.

        Args:
            status: The status to filter by
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of TaskModel instances
        """
        result = await self.session.execute(
            select(TaskModel)
            .where(TaskModel.status == status)
            .order_by(TaskModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_recent(self, limit: int = 100) -> list[TaskModel]:
        """Get recent tasks ordered by creation time.

        Args:
            limit: Maximum number of results

        Returns:
            List of TaskModel instances
        """
        result = await self.session.execute(
            select(TaskModel).order_by(TaskModel.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def assign(self, task_id: str, worker_id: str) -> TaskModel | None:
        """Assign a task to a worker.

        Args:
            task_id: The task ID to assign
            worker_id: The worker ID to assign to

        Returns:
            Updated TaskModel if successful, None if task not found/already assigned
        """
        result = await self.session.execute(
            update(TaskModel)
            .where(TaskModel.task_id == task_id)
            .where(TaskModel.status == TaskStatus.PENDING)
            .values(
                status=TaskStatus.ASSIGNED,
                worker_id=worker_id,
                assigned_at=datetime.now(timezone.utc),
            )
            .returning(TaskModel)
        )
        return result.scalar_one_or_none()

    async def start(self, task_id: str, session_id: str | None = None) -> TaskModel | None:
        """Mark a task as running.

        Args:
            task_id: The task ID to start
            session_id: Optional SDK session ID

        Returns:
            Updated TaskModel if successful
        """
        values: dict[str, Any] = {
            "status": TaskStatus.RUNNING,
            "started_at": datetime.now(timezone.utc),
        }
        if session_id:
            values["session_id"] = session_id

        result = await self.session.execute(
            update(TaskModel)
            .where(TaskModel.task_id == task_id)
            .where(TaskModel.status == TaskStatus.ASSIGNED)
            .values(**values)
            .returning(TaskModel)
        )
        return result.scalar_one_or_none()

    async def complete(
        self, task_id: str, result_data: dict[str, Any] | None = None
    ) -> TaskModel | None:
        """Mark a task as completed.

        Args:
            task_id: The task ID to complete
            result_data: The task result data

        Returns:
            Updated TaskModel if successful
        """
        result = await self.session.execute(
            update(TaskModel)
            .where(TaskModel.task_id == task_id)
            .values(
                status=TaskStatus.COMPLETED,
                result=result_data,
                completed_at=datetime.now(timezone.utc),
            )
            .returning(TaskModel)
        )
        return result.scalar_one_or_none()

    async def fail(
        self, task_id: str, error: str | None = None
    ) -> TaskModel | None:
        """Mark a task as failed.

        Args:
            task_id: The task ID to fail
            error: The error message

        Returns:
            Updated TaskModel if successful
        """
        result = await self.session.execute(
            update(TaskModel)
            .where(TaskModel.task_id == task_id)
            .values(
                status=TaskStatus.FAILED,
                result={"error": error} if error else None,
                completed_at=datetime.now(timezone.utc),
            )
            .returning(TaskModel)
        )
        return result.scalar_one_or_none()

    async def append_message(
        self,
        task_id: str,
        message: dict[str, Any],
    ) -> TaskMessageModel:
        """Append a message to a task's conversation history.

        Args:
            task_id: The task ID to append to
            message: The message content

        Returns:
            The created TaskMessageModel
        """
        # Get current max sequence number
        result = await self.session.execute(
            select(func.coalesce(func.max(TaskMessageModel.sequence_number), 0)).where(
                TaskMessageModel.task_id == task_id
            )
        )
        max_seq = result.scalar() or 0

        msg_model = TaskMessageModel(
            task_id=task_id,
            sequence_number=max_seq + 1,
            message_type=message.get("__type__", "unknown"),
            content=message,
        )
        self.session.add(msg_model)

        # Update denormalized count
        await self.session.execute(
            update(TaskModel)
            .where(TaskModel.task_id == task_id)
            .values(message_count=TaskModel.message_count + 1)
        )

        await self.session.flush()
        return msg_model

    async def get_messages(self, task_id: str) -> list[dict[str, Any]]:
        """Get all messages for a task.

        Args:
            task_id: The task ID to get messages for

        Returns:
            List of message content dictionaries
        """
        result = await self.session.execute(
            select(TaskMessageModel)
            .where(TaskMessageModel.task_id == task_id)
            .order_by(TaskMessageModel.sequence_number.asc())
        )
        return [msg.content for msg in result.scalars().all()]

    async def list_all(
        self,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[TaskModel]:
        """Get all tasks with optional filters.

        Args:
            status: Optional status filter (pending, assigned, completed, failed)
            limit: Optional limit on number of results

        Returns:
            List of TaskModel instances with messages loaded
        """
        query = select(TaskModel).options(selectinload(TaskModel.messages))

        if status:
            status_enum = TaskStatus(status)
            query = query.where(TaskModel.status == status_enum)

        query = query.order_by(TaskModel.created_at.desc())

        if limit:
            query = query.limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def search_by_prompt(
        self,
        query: str,
        status: str | None = None,
    ) -> list[TaskModel]:
        """Search tasks by prompt content.

        Args:
            query: Search string to match in prompts
            status: Optional status filter

        Returns:
            List of matching TaskModel instances with messages loaded
        """
        stmt = (
            select(TaskModel)
            .options(selectinload(TaskModel.messages))
            .where(TaskModel.prompt.ilike(f"%{query}%"))
        )

        if status:
            status_enum = TaskStatus(status)
            stmt = stmt.where(TaskModel.status == status_enum)

        stmt = stmt.order_by(TaskModel.created_at.desc())

        result = await self.session.execute(stmt)
        return list(result.scalars().all())
