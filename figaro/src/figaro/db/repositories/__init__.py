"""Repository classes for database operations."""

from figaro.db.repositories.tasks import TaskRepository
from figaro.db.repositories.scheduled import ScheduledTaskRepository
from figaro.db.repositories.help_requests import HelpRequestRepository
from figaro.db.repositories.workers import WorkerSessionRepository
from figaro.db.repositories.desktop_workers import DesktopWorkerRepository

__all__ = [
    "TaskRepository",
    "ScheduledTaskRepository",
    "HelpRequestRepository",
    "WorkerSessionRepository",
    "DesktopWorkerRepository",
]
