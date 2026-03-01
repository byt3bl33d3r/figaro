"""Scheduled task model for recurring task execution."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ScheduledTask:
    """A scheduled task that executes at regular intervals."""

    schedule_id: str
    name: str
    prompt: str
    start_url: str
    interval_seconds: int
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    run_count: int = 0
    options: dict[str, Any] = field(default_factory=dict)
    parallel_workers: int = 1  # Number of task instances per execution
    max_runs: int | None = None  # Auto-pause after N executions (None = unlimited)
    notify_on_complete: bool = False  # Send Telegram notification on task completion
    self_learning: bool = False
    self_healing: bool = False
    self_learning_max_runs: int | None = None
    self_learning_run_count: int = 0
