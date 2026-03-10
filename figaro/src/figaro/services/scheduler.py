"""Scheduler service for managing recurring tasks."""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from figaro.db.models import ScheduledTaskModel
from figaro.db.repositories.scheduled import ScheduledTaskRepository
from figaro_nats import Subjects
from figaro.services.registry import Registry
from figaro.services.task_manager import TaskManager

if TYPE_CHECKING:
    from figaro.services.nats_service import NatsService

logger = logging.getLogger(__name__)


class SchedulerService:
    """Manages scheduled tasks with automatic execution at intervals."""

    def __init__(
        self,
        task_manager: TaskManager,
        registry: Registry,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._task_manager = task_manager
        self._registry = registry
        self._session_factory = session_factory
        self._nats_service: "NatsService | None" = None
        self._running = False
        self._check_interval = 10  # Check every 10 seconds

    def set_nats_service(self, nats_service: "NatsService") -> None:
        """Set the NATS service for publishing task assignments."""
        self._nats_service = nats_service

    async def start(self) -> None:
        """Start the scheduler background task."""
        self._running = True
        asyncio.create_task(self._scheduler_loop())
        logger.info("Scheduler service started")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        logger.info("Scheduler service stopped")

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop - checks for due tasks."""
        while self._running:
            try:
                await self._check_due_tasks()
            except Exception as e:
                logger.exception(f"Scheduler error: {e}")
            await asyncio.sleep(self._check_interval)

    async def _check_due_tasks(self) -> None:
        """Check and execute due tasks.

        Uses FOR UPDATE SKIP LOCKED to prevent duplicate execution. We call
        mark_executed inside the same session so that next_run_at is advanced
        while the row lock is still held — otherwise a concurrent orchestrator
        could pick up the same task before the lock is released.
        """
        try:
            async with asyncio.timeout(30):
                async with self._session_factory() as session:
                    repo = ScheduledTaskRepository(session)
                    due_tasks = await repo.get_due_tasks()
                    updated_tasks: list[tuple[ScheduledTaskModel, ScheduledTaskModel | None]] = []
                    for model in due_tasks:
                        updated = await repo.mark_executed(model.schedule_id)
                        updated_tasks.append((model, updated))
                    await session.commit()
                    for model, updated in updated_tasks:
                        asyncio.create_task(self._execute_scheduled_task(model, updated))
        except TimeoutError:
            logger.warning(
                "Timeout checking due tasks from database, will retry next cycle"
            )
        except Exception as e:
            logger.warning(
                f"Error checking due tasks from database: {e}, will retry next cycle"
            )

    async def _execute_scheduled_task(
        self,
        scheduled_task: ScheduledTaskModel,
        updated: ScheduledTaskModel | None = None,
    ) -> None:
        """Execute a scheduled task, creating parallel instances and queuing as needed.

        Args:
            scheduled_task: The scheduled task to execute.
            updated: The already-updated model from mark_executed (when called from
                _check_due_tasks). If None, mark_executed is called here (manual trigger).
        """
        parallel_count = scheduled_task.parallel_workers or 1
        created_tasks = []

        # Create all task instances
        for i in range(parallel_count):
            task = await self._task_manager.create_task(
                prompt=scheduled_task.prompt,
                options={
                    **scheduled_task.options,
                    "scheduled_task_id": scheduled_task.schedule_id,
                    "start_url": scheduled_task.start_url,
                    "parallel_instance": i + 1,
                    "parallel_total": parallel_count,
                    "self_healing": scheduled_task.self_healing,
                },
                scheduled_task_id=scheduled_task.schedule_id,
                source="scheduler",
            )
            created_tasks.append(task)

        # Assign to available workers, queue the rest
        assigned_count = 0
        task_ids = []
        worker_ids = []

        for task in created_tasks:
            task_ids.append(task.task_id)
            worker = await self._registry.claim_idle_worker()
            if worker:
                await self._task_manager.assign_task(task.task_id, worker.client_id)
                if self._nats_service:
                    await self._nats_service.publish_task_assignment(
                        worker.client_id, task
                    )
                worker_ids.append(worker.client_id)
                assigned_count += 1
            else:
                # No idle worker - queue for later assignment
                await self._task_manager.queue_task(task.task_id)

        # Broadcast execution summary to UI via NATS
        if self._nats_service:
            await self._nats_service.conn.publish(
                Subjects.BROADCAST_SCHEDULED_TASK_EXECUTED,
                {
                    "schedule_id": scheduled_task.schedule_id,
                    "task_ids": task_ids,
                    "worker_ids": worker_ids,
                    "tasks_created": parallel_count,
                    "tasks_assigned": assigned_count,
                    "tasks_queued": parallel_count - assigned_count,
                },
            )

        logger.info(
            f"Scheduled task {scheduled_task.schedule_id}: "
            f"created {parallel_count} tasks, assigned {assigned_count}, "
            f"queued {parallel_count - assigned_count}"
        )

        # mark_executed already called in _check_due_tasks; only needed for manual trigger
        if updated is None:
            async with self._session_factory() as session:
                repo = ScheduledTaskRepository(session)
                updated = await repo.mark_executed(scheduled_task.schedule_id)
                await session.commit()

        if updated and not updated.enabled:
            logger.info(
                f"Auto-paused scheduled task {scheduled_task.schedule_id} "
                f"after {updated.run_count} runs"
            )
            if self._nats_service:
                await self._nats_service.conn.publish(
                    Subjects.BROADCAST_SCHEDULED_TASK_AUTO_PAUSED,
                    {
                        "schedule_id": scheduled_task.schedule_id,
                        "run_count": updated.run_count,
                        "max_runs": scheduled_task.max_runs,
                    },
                )

    async def create_scheduled_task(
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
        run_at: datetime | None = None,
    ) -> ScheduledTaskModel:
        """Create a new scheduled task."""
        schedule_id = str(uuid.uuid4())

        async with self._session_factory() as session:
            repo = ScheduledTaskRepository(session)
            model = await repo.create(
                name=name,
                prompt=prompt,
                start_url=start_url,
                interval_seconds=interval_seconds,
                options=options,
                parallel_workers=parallel_workers,
                max_runs=max_runs,
                notify_on_complete=notify_on_complete,
                self_learning=self_learning,
                self_healing=self_healing,
                self_learning_max_runs=self_learning_max_runs,
                schedule_id=schedule_id,
                run_at=run_at,
            )
            await session.commit()

        logger.info(f"Created scheduled task: {schedule_id}")
        return model

    async def get_scheduled_task(self, schedule_id: str) -> ScheduledTaskModel | None:
        """Get a scheduled task by ID."""
        async with self._session_factory() as session:
            repo = ScheduledTaskRepository(session)
            return await repo.get(schedule_id)

    async def get_all_scheduled_tasks(self) -> list[ScheduledTaskModel]:
        """Get all scheduled tasks."""
        async with self._session_factory() as session:
            repo = ScheduledTaskRepository(session)
            return await repo.list_all()

    async def update_scheduled_task(
        self, schedule_id: str, **updates: object
    ) -> ScheduledTaskModel | None:
        """Update a scheduled task."""
        async with self._session_factory() as session:
            repo = ScheduledTaskRepository(session)
            model = await repo.update(schedule_id, **updates)
            await session.commit()
            if model:
                logger.info(f"Updated scheduled task: {schedule_id}")
                return model
            return None

    async def delete_scheduled_task(self, schedule_id: str) -> bool:
        """Delete a scheduled task."""
        async with self._session_factory() as session:
            repo = ScheduledTaskRepository(session)
            deleted = await repo.soft_delete(schedule_id)
            await session.commit()
            if deleted:
                logger.info(f"Deleted scheduled task: {schedule_id}")
                return True
            return False

    async def trigger_scheduled_task(
        self, schedule_id: str
    ) -> ScheduledTaskModel | None:
        """Manually trigger a scheduled task immediately."""
        task = await self.get_scheduled_task(schedule_id)
        if task is None:
            return None
        asyncio.create_task(self._execute_scheduled_task(task))
        return task

    async def toggle_scheduled_task(
        self, schedule_id: str
    ) -> ScheduledTaskModel | None:
        """Toggle a scheduled task's enabled state."""
        async with self._session_factory() as session:
            repo = ScheduledTaskRepository(session)
            model = await repo.toggle_enabled(schedule_id)
            await session.commit()
            if model:
                logger.info(
                    f"Toggled scheduled task {schedule_id}: enabled={model.enabled}"
                )
                return model
            return None
