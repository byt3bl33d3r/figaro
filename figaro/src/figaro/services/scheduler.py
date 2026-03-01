"""Scheduler service for managing recurring tasks."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from figaro.db.models import ScheduledTaskModel
from figaro.db.repositories.scheduled import ScheduledTaskRepository
from figaro.models.scheduled_task import ScheduledTask
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
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        storage_path: Path | None = None,
    ) -> None:
        self._task_manager = task_manager
        self._registry = registry
        self._session_factory = session_factory
        self._nats_service: "NatsService | None" = None
        self._scheduled_tasks: dict[str, ScheduledTask] = {}
        self._storage_path = storage_path or Path("scheduled_tasks.json")
        self._lock = asyncio.Lock()
        self._running = False
        self._check_interval = 10  # Check every 10 seconds

    def set_nats_service(self, nats_service: "NatsService") -> None:
        """Set the NATS service for publishing task assignments."""
        self._nats_service = nats_service

    def _model_to_dataclass(self, model: ScheduledTaskModel) -> ScheduledTask:
        """Convert a database model to a dataclass."""
        return ScheduledTask(
            schedule_id=model.schedule_id,
            name=model.name,
            prompt=model.prompt,
            start_url=model.start_url,
            interval_seconds=model.interval_seconds,
            enabled=model.enabled,
            created_at=model.created_at,
            last_run_at=model.last_run_at,
            next_run_at=model.next_run_at,
            run_count=model.run_count,
            options=model.options,
            parallel_workers=model.parallel_workers,
            max_runs=model.max_runs,
            notify_on_complete=model.notify_on_complete,
            self_learning=model.self_learning,
            self_healing=model.self_healing,
            self_learning_max_runs=model.self_learning_max_runs,
            self_learning_run_count=model.self_learning_run_count,
        )

    async def start(self) -> None:
        """Start the scheduler background task."""
        await self._load_from_storage()
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
        """Check and execute due tasks."""
        if self._session_factory:
            # Use database with row-level locking
            try:
                async with asyncio.timeout(30):  # 30 second timeout for DB operations
                    async with self._session_factory() as session:
                        repo = ScheduledTaskRepository(session)
                        due_tasks = await repo.get_due_tasks()
                        for model in due_tasks:
                            task = self._model_to_dataclass(model)
                            # Update in-memory cache
                            async with self._lock:
                                self._scheduled_tasks[task.schedule_id] = task
                            # Execute outside lock
                            asyncio.create_task(self._execute_scheduled_task(task))
            except TimeoutError:
                logger.warning(
                    "Timeout checking due tasks from database, will retry next cycle"
                )
            except Exception as e:
                logger.warning(
                    f"Error checking due tasks from database: {e}, will retry next cycle"
                )
        else:
            # Fall back to in-memory check
            now = datetime.now(timezone.utc)
            async with self._lock:
                for task in list(self._scheduled_tasks.values()):
                    if not task.enabled:
                        continue
                    if task.next_run_at and task.next_run_at <= now:
                        asyncio.create_task(self._execute_scheduled_task(task))

    async def _execute_scheduled_task(self, scheduled_task: ScheduledTask) -> None:
        """Execute a scheduled task, creating parallel instances and queuing as needed."""
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
                "figaro.broadcast.scheduled_task_executed",
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

        # Update scheduled task metadata
        if self._session_factory:
            async with self._session_factory() as session:
                repo = ScheduledTaskRepository(session)
                updated = await repo.mark_executed(scheduled_task.schedule_id)
                await session.commit()
                if updated:
                    # Update in-memory cache
                    async with self._lock:
                        scheduled_task.last_run_at = updated.last_run_at
                        scheduled_task.next_run_at = updated.next_run_at
                        scheduled_task.run_count = updated.run_count
                        scheduled_task.enabled = updated.enabled

                    # Auto-pause notification
                    if not updated.enabled:
                        logger.info(
                            f"Auto-paused scheduled task {scheduled_task.schedule_id} "
                            f"after {updated.run_count} runs"
                        )
                        if self._nats_service:
                            await self._nats_service.conn.publish(
                                "figaro.broadcast.scheduled_task_auto_paused",
                                {
                                    "schedule_id": scheduled_task.schedule_id,
                                    "run_count": updated.run_count,
                                    "max_runs": scheduled_task.max_runs,
                                },
                            )
        else:
            # Fall back to in-memory update
            async with self._lock:
                scheduled_task.last_run_at = datetime.now(timezone.utc)
                scheduled_task.next_run_at = datetime.now(timezone.utc) + timedelta(
                    seconds=scheduled_task.interval_seconds
                )
                scheduled_task.run_count += 1

                # Auto-pause check
                if (
                    scheduled_task.max_runs is not None
                    and scheduled_task.run_count >= scheduled_task.max_runs
                ):
                    scheduled_task.enabled = False
                    logger.info(
                        f"Auto-paused scheduled task {scheduled_task.schedule_id} "
                        f"after {scheduled_task.run_count} runs"
                    )
                    if self._nats_service:
                        await self._nats_service.conn.publish(
                            "figaro.broadcast.scheduled_task_auto_paused",
                            {
                                "schedule_id": scheduled_task.schedule_id,
                                "run_count": scheduled_task.run_count,
                                "max_runs": scheduled_task.max_runs,
                            },
                        )

                await self._save_to_storage()

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
    ) -> ScheduledTask:
        """Create a new scheduled task."""
        schedule_id = str(uuid.uuid4())

        if self._session_factory:
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
                )
                await session.commit()
                task = self._model_to_dataclass(model)
        else:
            task = ScheduledTask(
                schedule_id=schedule_id,
                name=name,
                prompt=prompt,
                start_url=start_url,
                interval_seconds=interval_seconds,
                options=options or {},
                next_run_at=datetime.now(timezone.utc)
                + timedelta(seconds=interval_seconds),
                parallel_workers=parallel_workers,
                max_runs=max_runs,
                notify_on_complete=notify_on_complete,
                self_learning=self_learning,
                self_healing=self_healing,
                self_learning_max_runs=self_learning_max_runs,
            )

        async with self._lock:
            self._scheduled_tasks[schedule_id] = task
            if not self._session_factory:
                await self._save_to_storage()

        logger.info(f"Created scheduled task: {schedule_id}")
        return task

    async def get_scheduled_task(self, schedule_id: str) -> ScheduledTask | None:
        """Get a scheduled task by ID."""
        async with self._lock:
            task = self._scheduled_tasks.get(schedule_id)
            if task:
                return task

        # Try database
        if self._session_factory:
            async with self._session_factory() as session:
                repo = ScheduledTaskRepository(session)
                model = await repo.get(schedule_id)
                if model:
                    task = self._model_to_dataclass(model)
                    async with self._lock:
                        self._scheduled_tasks[schedule_id] = task
                    return task

        return None

    async def get_all_scheduled_tasks(self) -> list[ScheduledTask]:
        """Get all scheduled tasks."""
        if self._session_factory:
            async with self._session_factory() as session:
                repo = ScheduledTaskRepository(session)
                models = await repo.list_all()
                tasks = [self._model_to_dataclass(m) for m in models]
                # Update cache
                async with self._lock:
                    for task in tasks:
                        self._scheduled_tasks[task.schedule_id] = task
                return tasks

        async with self._lock:
            return list(self._scheduled_tasks.values())

    async def update_scheduled_task(
        self, schedule_id: str, **updates: Any
    ) -> ScheduledTask | None:
        """Update a scheduled task."""
        if self._session_factory:
            async with self._session_factory() as session:
                repo = ScheduledTaskRepository(session)
                model = await repo.update(schedule_id, **updates)
                await session.commit()
                if model:
                    task = self._model_to_dataclass(model)
                    async with self._lock:
                        self._scheduled_tasks[schedule_id] = task
                    logger.info(f"Updated scheduled task: {schedule_id}")
                    return task
                return None

        async with self._lock:
            task = self._scheduled_tasks.get(schedule_id)
            if task is None:
                return None
            for key, value in updates.items():
                if hasattr(task, key) and key != "schedule_id":
                    setattr(task, key, value)
            await self._save_to_storage()
            logger.info(f"Updated scheduled task: {schedule_id}")
            return task

    async def delete_scheduled_task(self, schedule_id: str) -> bool:
        """Delete a scheduled task."""
        if self._session_factory:
            async with self._session_factory() as session:
                repo = ScheduledTaskRepository(session)
                deleted = await repo.soft_delete(schedule_id)
                await session.commit()
                if deleted:
                    async with self._lock:
                        self._scheduled_tasks.pop(schedule_id, None)
                    logger.info(f"Deleted scheduled task: {schedule_id}")
                    return True
                return False

        async with self._lock:
            if schedule_id in self._scheduled_tasks:
                del self._scheduled_tasks[schedule_id]
                await self._save_to_storage()
                logger.info(f"Deleted scheduled task: {schedule_id}")
                return True
            return False

    async def trigger_scheduled_task(self, schedule_id: str) -> ScheduledTask | None:
        """Manually trigger a scheduled task immediately."""
        task = await self.get_scheduled_task(schedule_id)
        if task is None:
            return None
        asyncio.create_task(self._execute_scheduled_task(task))
        return task

    async def toggle_scheduled_task(self, schedule_id: str) -> ScheduledTask | None:
        """Toggle a scheduled task's enabled state."""
        if self._session_factory:
            async with self._session_factory() as session:
                repo = ScheduledTaskRepository(session)
                model = await repo.toggle_enabled(schedule_id)
                await session.commit()
                if model:
                    task = self._model_to_dataclass(model)
                    async with self._lock:
                        self._scheduled_tasks[schedule_id] = task
                    logger.info(
                        f"Toggled scheduled task {schedule_id}: enabled={task.enabled}"
                    )
                    return task
                return None

        async with self._lock:
            task = self._scheduled_tasks.get(schedule_id)
            if task:
                task.enabled = not task.enabled
                if task.enabled:
                    task.next_run_at = datetime.now(timezone.utc) + timedelta(
                        seconds=task.interval_seconds
                    )
                await self._save_to_storage()
                logger.info(
                    f"Toggled scheduled task {schedule_id}: enabled={task.enabled}"
                )
            return task

    async def _load_from_storage(self) -> None:
        """Load scheduled tasks from database or JSON storage."""
        # Try database first
        if self._session_factory:
            try:
                async with self._session_factory() as session:
                    repo = ScheduledTaskRepository(session)
                    models = await repo.list_all()
                    for model in models:
                        task = self._model_to_dataclass(model)
                        self._scheduled_tasks[task.schedule_id] = task
                    logger.info(
                        f"Loaded {len(self._scheduled_tasks)} scheduled tasks from database"
                    )

                    # Migrate JSON file if it exists
                    if self._storage_path.exists():
                        await self._migrate_json_to_db()
                    return
            except Exception as e:
                logger.warning(
                    f"Failed to load from database, falling back to JSON: {e}"
                )

        # Fall back to JSON storage
        if not self._storage_path.exists():
            logger.info("No scheduled tasks file found, starting fresh")
            return
        try:
            data = json.loads(self._storage_path.read_text())
            for item in data:
                # Migration: convert old notification_url to notify_on_complete
                notify_on_complete = item.get("notify_on_complete", False)
                if not notify_on_complete and item.get("notification_url"):
                    notify_on_complete = True

                task = ScheduledTask(
                    schedule_id=item["schedule_id"],
                    name=item["name"],
                    prompt=item["prompt"],
                    start_url=item["start_url"],
                    interval_seconds=item["interval_seconds"],
                    enabled=item.get("enabled", True),
                    created_at=datetime.fromisoformat(item["created_at"]),
                    last_run_at=(
                        datetime.fromisoformat(item["last_run_at"])
                        if item.get("last_run_at")
                        else None
                    ),
                    next_run_at=(
                        datetime.fromisoformat(item["next_run_at"])
                        if item.get("next_run_at")
                        else None
                    ),
                    run_count=item.get("run_count", 0),
                    options=item.get("options", {}),
                    parallel_workers=item.get("parallel_workers", 1),
                    max_runs=item.get("max_runs"),
                    notify_on_complete=notify_on_complete,
                    self_learning=item.get("self_learning", False),
                    self_healing=item.get("self_healing", False),
                )
                self._scheduled_tasks[task.schedule_id] = task
            logger.info(
                f"Loaded {len(self._scheduled_tasks)} scheduled tasks from JSON"
            )
        except Exception as e:
            logger.error(f"Failed to load scheduled tasks: {e}")

    async def _migrate_json_to_db(self) -> None:
        """Migrate scheduled tasks from JSON file to database."""
        if not self._storage_path.exists() or not self._session_factory:
            return

        try:
            data = json.loads(self._storage_path.read_text())
            migrated_count = 0

            async with self._session_factory() as session:
                repo = ScheduledTaskRepository(session)

                for item in data:
                    # Check if already in DB
                    existing = await repo.get(item["schedule_id"])
                    if existing:
                        continue

                    # Migration: convert old notification_url to notify_on_complete
                    notify_on_complete = item.get("notify_on_complete", False)
                    if not notify_on_complete and item.get("notification_url"):
                        notify_on_complete = True

                    await repo.create(
                        name=item["name"],
                        prompt=item["prompt"],
                        start_url=item["start_url"],
                        interval_seconds=item["interval_seconds"],
                        options=item.get("options", {}),
                        parallel_workers=item.get("parallel_workers", 1),
                        max_runs=item.get("max_runs"),
                        notify_on_complete=notify_on_complete,
                        schedule_id=item["schedule_id"],
                    )
                    migrated_count += 1

                await session.commit()

            if migrated_count > 0:
                logger.info(
                    f"Migrated {migrated_count} scheduled tasks from JSON to database"
                )
                # Rename the JSON file to mark as migrated
                migrated_path = self._storage_path.with_suffix(".json.migrated")
                self._storage_path.rename(migrated_path)
                logger.info(f"Renamed {self._storage_path} to {migrated_path}")

        except Exception as e:
            logger.error(f"Failed to migrate JSON to database: {e}")

    async def _save_to_storage(self) -> None:
        """Save scheduled tasks to JSON storage (only when not using database)."""
        if self._session_factory:
            # Using database, no need to save to JSON
            return

        data = [
            {
                "schedule_id": t.schedule_id,
                "name": t.name,
                "prompt": t.prompt,
                "start_url": t.start_url,
                "interval_seconds": t.interval_seconds,
                "enabled": t.enabled,
                "created_at": t.created_at.isoformat(),
                "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
                "next_run_at": t.next_run_at.isoformat() if t.next_run_at else None,
                "run_count": t.run_count,
                "options": t.options,
                "parallel_workers": t.parallel_workers,
                "max_runs": t.max_runs,
                "notify_on_complete": t.notify_on_complete,
                "self_learning": t.self_learning,
                "self_healing": t.self_healing,
            }
            for t in self._scheduled_tasks.values()
        ]
        self._storage_path.write_text(json.dumps(data, indent=2))
