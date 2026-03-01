import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from figaro.db.models import TaskModel
from figaro.db.repositories.tasks import TaskRepository

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    task_id: str
    prompt: str
    options: dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    worker_id: str | None = None
    session_id: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    source: str = "api"
    source_metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_model(cls, model: TaskModel) -> "Task":
        """Create a Task from a database model."""
        return cls(
            task_id=model.task_id,
            prompt=model.prompt,
            options=model.options,
            status=TaskStatus(model.status.value),
            result=model.result,
            worker_id=model.worker_id,
            session_id=model.session_id,
            messages=[],  # Messages loaded separately
            source=model.source,
            source_metadata=model.source_metadata or {},
        )


class TaskManager:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._tasks: dict[str, Task] = {}
        self._pending_queue: list[str] = []  # Queue of task_ids waiting for workers
        self._lock = asyncio.Lock()
        self._session_factory = session_factory

    async def _get_session(self) -> AsyncSession | None:
        """Get a database session if available."""
        if self._session_factory:
            return self._session_factory()
        return None

    async def load_pending_tasks(self) -> None:
        """Load pending tasks from database on startup."""
        if not self._session_factory:
            return

        async with self._session_factory() as session:
            repo = TaskRepository(session)
            pending_tasks = await repo.list_pending()
            async with self._lock:
                for model in pending_tasks:
                    task = Task.from_model(model)
                    self._tasks[task.task_id] = task
                    if task.task_id not in self._pending_queue:
                        self._pending_queue.append(task.task_id)
            logger.info(f"Loaded {len(pending_tasks)} pending tasks from database")

    async def create_task(
        self,
        prompt: str,
        options: dict[str, Any] | None = None,
        task_id: str | None = None,
        scheduled_task_id: str | None = None,
        source: str = "api",
        source_metadata: dict[str, Any] | None = None,
    ) -> Task:
        if task_id is None:
            task_id = str(uuid.uuid4())

        # Create in database first if available
        if self._session_factory:
            async with self._session_factory() as session:
                repo = TaskRepository(session)
                await repo.create(
                    prompt=prompt,
                    options=options or {},
                    task_id=task_id,
                    scheduled_task_id=scheduled_task_id,
                    source=source,
                    source_metadata=source_metadata or {},
                )
                await session.commit()

        # Create in-memory task
        async with self._lock:
            task = Task(
                task_id=task_id,
                prompt=prompt,
                options=options or {},
                source=source,
                source_metadata=source_metadata or {},
            )
            self._tasks[task_id] = task
            logger.info(f"Created task: {task_id}")
            return task

    async def get_task(self, task_id: str) -> Task | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                return task

        # Try to load from database if not in memory
        if self._session_factory:
            async with self._session_factory() as session:
                repo = TaskRepository(session)
                model = await repo.get_with_messages(task_id)
                if model:
                    task = Task.from_model(model)
                    task.messages = [msg.content for msg in model.messages]
                    async with self._lock:
                        self._tasks[task_id] = task
                    return task

        return None

    async def get_all_tasks(
        self,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[Task]:
        """Get all tasks, optionally filtered by status and limited."""
        # Try to get from database first if available
        if self._session_factory:
            async with self._session_factory() as session:
                repo = TaskRepository(session)
                models = await repo.list_all(status=status, limit=limit)
                tasks = []
                for model in models:
                    task = Task.from_model(model)
                    task.messages = [msg.content for msg in model.messages]
                    tasks.append(task)
                return tasks

        # Fall back to in-memory
        async with self._lock:
            tasks = list(self._tasks.values())
            if status:
                tasks = [t for t in tasks if t.status.value == status]
            if limit:
                tasks = tasks[:limit]
            return tasks

    async def search_tasks(
        self,
        query: str,
        status: str | None = None,
    ) -> list[Task]:
        """Search tasks by prompt content."""
        if self._session_factory:
            async with self._session_factory() as session:
                repo = TaskRepository(session)
                models = await repo.search_by_prompt(query=query, status=status)
                tasks = []
                for model in models:
                    task = Task.from_model(model)
                    task.messages = [msg.content for msg in model.messages]
                    tasks.append(task)
                return tasks

        # Fall back to in-memory search
        async with self._lock:
            query_lower = query.lower()
            tasks = [
                t for t in self._tasks.values()
                if query_lower in t.prompt.lower()
            ]
            if status:
                tasks = [t for t in tasks if t.status.value == status]
            return tasks

    async def get_tasks_by_worker(self, worker_id: str) -> list[Task]:
        async with self._lock:
            return [
                task for task in self._tasks.values() if task.worker_id == worker_id
            ]

    async def assign_task(self, task_id: str, worker_id: str) -> Task | None:
        # Update database first
        if self._session_factory:
            async with self._session_factory() as session:
                repo = TaskRepository(session)
                await repo.assign(task_id, worker_id)
                await session.commit()

        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.worker_id = worker_id
            task.status = TaskStatus.ASSIGNED
            logger.info(f"Assigned task {task_id} to worker {worker_id}")
            return task

    async def start_task(self, task_id: str, session_id: str | None = None) -> Task | None:
        # Update database first
        if self._session_factory:
            async with self._session_factory() as session:
                repo = TaskRepository(session)
                await repo.start(task_id, session_id)
                await session.commit()

        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.status = TaskStatus.RUNNING
            task.session_id = session_id
            logger.info(f"Task {task_id} started running")
            return task

    async def complete_task(self, task_id: str, result: Any = None) -> Task | None:
        # Update database first
        if self._session_factory:
            async with self._session_factory() as session:
                repo = TaskRepository(session)
                await repo.complete(task_id, result)
                await session.commit()

        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.status = TaskStatus.COMPLETED
            task.result = result
            logger.info(f"Task {task_id} completed")
            return task

    async def fail_task(self, task_id: str, error: str) -> Task | None:
        # Update database first
        if self._session_factory:
            async with self._session_factory() as session:
                repo = TaskRepository(session)
                await repo.fail(task_id, error)
                await session.commit()

        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.status = TaskStatus.FAILED
            task.result = {"error": error}
            logger.info(f"Task {task_id} failed: {error}")
            return task

    async def append_message(self, task_id: str, message: dict[str, Any]) -> bool:
        # Store in database first
        if self._session_factory:
            async with self._session_factory() as session:
                repo = TaskRepository(session)
                await repo.append_message(task_id, message)
                await session.commit()

        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.messages.append(message)
            return True

    async def get_history(self, task_id: str) -> list[dict[str, Any]] | None:
        # Try in-memory first
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is not None and task.messages:
                return list(task.messages)

        # Fall back to database
        if self._session_factory:
            async with self._session_factory() as session:
                repo = TaskRepository(session)
                messages = await repo.get_messages(task_id)
                if messages:
                    return messages

        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return list(task.messages)

    async def queue_task(self, task_id: str) -> None:
        """Add a task to the pending queue for later assignment."""
        async with self._lock:
            self._pending_queue.append(task_id)
            logger.info(f"Queued task {task_id} for later assignment")

    async def get_next_pending_task(self) -> str | None:
        """Get and remove the next task from the queue."""
        async with self._lock:
            if self._pending_queue:
                task_id = self._pending_queue.pop(0)
                logger.info(f"Dequeued task {task_id}")
                return task_id
            return None

    async def has_pending_tasks(self) -> bool:
        """Check if there are tasks waiting for workers."""
        async with self._lock:
            return len(self._pending_queue) > 0
