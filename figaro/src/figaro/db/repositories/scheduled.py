"""Scheduled task repository for database operations."""

from datetime import datetime, timedelta, timezone
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from figaro.db.models import ScheduledTaskModel


class ScheduledTaskRepository:
    """Repository for scheduled task database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        name: str,
        prompt: str,
        start_url: str,
        interval_seconds: int,
        options: dict[str, Any] | None = None,
        parallel_workers: int = 1,
        max_runs: int | None = None,
        notify_on_complete: bool = False,
        self_learning: bool = False,
        self_healing: bool = False,
        self_learning_max_runs: int | None = None,
        schedule_id: str | None = None,
    ) -> ScheduledTaskModel:
        """Create a new scheduled task.

        Args:
            name: Task name
            prompt: Task prompt
            start_url: Starting URL for the task
            interval_seconds: Execution interval in seconds
            options: Additional task options
            parallel_workers: Number of parallel task instances
            max_runs: Maximum number of executions (None = unlimited)
            notify_on_complete: Whether to send notification on completion
            self_learning: Whether to enable self-learning mode
            self_healing: Whether to enable self-healing mode
            schedule_id: Optional specific schedule ID

        Returns:
            The created ScheduledTaskModel
        """
        now = datetime.now(timezone.utc)
        model = ScheduledTaskModel(
            name=name,
            prompt=prompt,
            start_url=start_url,
            interval_seconds=interval_seconds,
            options=options or {},
            parallel_workers=parallel_workers,
            max_runs=max_runs,
            notify_on_complete=notify_on_complete,
            self_learning=self_learning,
            self_healing=self_healing,
            self_learning_max_runs=self_learning_max_runs,
            next_run_at=now + timedelta(seconds=interval_seconds),
        )
        if schedule_id:
            model.schedule_id = schedule_id

        self.session.add(model)
        await self.session.flush()
        return model

    async def get(self, schedule_id: str) -> ScheduledTaskModel | None:
        """Get a scheduled task by ID.

        Args:
            schedule_id: The schedule ID to fetch

        Returns:
            ScheduledTaskModel if found, None otherwise
        """
        result = await self.session.execute(
            select(ScheduledTaskModel)
            .where(ScheduledTaskModel.schedule_id == schedule_id)
            .where(ScheduledTaskModel.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[ScheduledTaskModel]:
        """Get all non-deleted scheduled tasks.

        Returns:
            List of ScheduledTaskModel instances
        """
        result = await self.session.execute(
            select(ScheduledTaskModel)
            .where(ScheduledTaskModel.deleted_at.is_(None))
            .order_by(ScheduledTaskModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_enabled(self) -> list[ScheduledTaskModel]:
        """Get all enabled scheduled tasks.

        Returns:
            List of enabled ScheduledTaskModel instances
        """
        result = await self.session.execute(
            select(ScheduledTaskModel)
            .where(ScheduledTaskModel.enabled.is_(True))
            .where(ScheduledTaskModel.deleted_at.is_(None))
            .order_by(ScheduledTaskModel.next_run_at.asc())
        )
        return list(result.scalars().all())

    async def get_due_tasks(self) -> list[ScheduledTaskModel]:
        """Get tasks that are due for execution with row-level locking.

        Uses FOR UPDATE SKIP LOCKED to prevent duplicate execution
        when running multiple orchestrator instances.

        Returns:
            List of due ScheduledTaskModel instances
        """
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(ScheduledTaskModel)
            .where(ScheduledTaskModel.enabled.is_(True))
            .where(ScheduledTaskModel.deleted_at.is_(None))
            .where(ScheduledTaskModel.next_run_at <= now)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def update(
        self,
        schedule_id: str,
        **values: Any,
    ) -> ScheduledTaskModel | None:
        """Update a scheduled task.

        Args:
            schedule_id: The schedule ID to update
            **values: Fields to update

        Returns:
            Updated ScheduledTaskModel if successful
        """
        # Filter out None values for explicit update
        update_values = {k: v for k, v in values.items() if v is not None}
        if not update_values:
            return await self.get(schedule_id)

        update_values["updated_at"] = datetime.now(timezone.utc)

        result = await self.session.execute(
            update(ScheduledTaskModel)
            .where(ScheduledTaskModel.schedule_id == schedule_id)
            .where(ScheduledTaskModel.deleted_at.is_(None))
            .values(**update_values)
            .returning(ScheduledTaskModel)
        )
        return result.scalar_one_or_none()

    async def toggle_enabled(self, schedule_id: str) -> ScheduledTaskModel | None:
        """Toggle the enabled state of a scheduled task.

        Args:
            schedule_id: The schedule ID to toggle

        Returns:
            Updated ScheduledTaskModel if successful
        """
        task = await self.get(schedule_id)
        if not task:
            return None

        now = datetime.now(timezone.utc)
        new_enabled = not task.enabled

        # If enabling, calculate next_run_at
        next_run = None
        if new_enabled:
            next_run = now + timedelta(seconds=task.interval_seconds)

        result = await self.session.execute(
            update(ScheduledTaskModel)
            .where(ScheduledTaskModel.schedule_id == schedule_id)
            .values(
                enabled=new_enabled,
                next_run_at=next_run,
                updated_at=now,
            )
            .returning(ScheduledTaskModel)
        )
        return result.scalar_one_or_none()

    async def mark_executed(
        self,
        schedule_id: str,
    ) -> ScheduledTaskModel | None:
        """Mark a scheduled task as executed and update timing.

        Args:
            schedule_id: The schedule ID that was executed

        Returns:
            Updated ScheduledTaskModel if successful
        """
        task = await self.get(schedule_id)
        if not task:
            return None

        now = datetime.now(timezone.utc)
        new_run_count = task.run_count + 1

        # Check if we should auto-disable
        should_disable = task.max_runs is not None and new_run_count >= task.max_runs

        result = await self.session.execute(
            update(ScheduledTaskModel)
            .where(ScheduledTaskModel.schedule_id == schedule_id)
            .values(
                last_run_at=now,
                next_run_at=(
                    None
                    if should_disable
                    else now + timedelta(seconds=task.interval_seconds)
                ),
                run_count=new_run_count,
                enabled=not should_disable,
                updated_at=now,
            )
            .returning(ScheduledTaskModel)
        )
        return result.scalar_one_or_none()

    async def increment_learning_count(
        self,
        schedule_id: str,
    ) -> ScheduledTaskModel | None:
        """Atomically increment the self_learning_run_count.

        Args:
            schedule_id: The schedule ID to update

        Returns:
            Updated ScheduledTaskModel if successful
        """
        result = await self.session.execute(
            update(ScheduledTaskModel)
            .where(ScheduledTaskModel.schedule_id == schedule_id)
            .where(ScheduledTaskModel.deleted_at.is_(None))
            .values(
                self_learning_run_count=ScheduledTaskModel.self_learning_run_count + 1,
                updated_at=datetime.now(timezone.utc),
            )
            .returning(ScheduledTaskModel)
        )
        return result.scalar_one_or_none()

    async def soft_delete(self, schedule_id: str) -> bool:
        """Soft delete a scheduled task.

        Args:
            schedule_id: The schedule ID to delete

        Returns:
            True if deleted, False if not found
        """
        result = await self.session.execute(
            update(ScheduledTaskModel)
            .where(ScheduledTaskModel.schedule_id == schedule_id)
            .where(ScheduledTaskModel.deleted_at.is_(None))
            .values(
                deleted_at=datetime.now(timezone.utc),
                enabled=False,
            )
        )
        return (cast(CursorResult[Any], result).rowcount or 0) > 0
