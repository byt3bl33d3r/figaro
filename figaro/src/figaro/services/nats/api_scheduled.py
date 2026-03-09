from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from figaro_nats import Subjects

if TYPE_CHECKING:
    from figaro.services.nats.service import NatsService

logger = logging.getLogger(__name__)


def format_scheduled_task(task: Any) -> dict[str, Any]:
    """Format a ScheduledTask for API response."""
    return {
        "schedule_id": task.schedule_id,
        "name": task.name,
        "prompt": task.prompt,
        "start_url": task.start_url,
        "interval_seconds": task.interval_seconds,
        "enabled": task.enabled,
        "created_at": task.created_at.isoformat(),
        "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
        "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
        "run_count": task.run_count,
        "options": task.options,
        "parallel_workers": task.parallel_workers,
        "max_runs": task.max_runs,
        "notify_on_complete": task.notify_on_complete,
        "self_learning": task.self_learning,
        "self_healing": task.self_healing,
        "self_learning_max_runs": task.self_learning_max_runs,
        "self_learning_run_count": task.self_learning_run_count,
        "run_at": task.run_at.isoformat() if task.run_at else None,
    }


async def api_list_scheduled_tasks(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """List all scheduled tasks."""
    tasks = await svc._scheduler.get_all_scheduled_tasks()
    return {"tasks": [format_scheduled_task(t) for t in tasks]}


async def api_get_scheduled_task(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Get a scheduled task by ID."""
    schedule_id = data.get("schedule_id", "")
    task = await svc._scheduler.get_scheduled_task(schedule_id)
    if task is None:
        return {"error": f"Scheduled task {schedule_id} not found"}
    return format_scheduled_task(task)


async def api_create_scheduled_task(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Create a new scheduled task."""
    run_at = None
    if data.get("run_at"):
        run_at = datetime.fromisoformat(data["run_at"]).astimezone(timezone.utc)

    task = await svc._scheduler.create_scheduled_task(
        name=data.get("name", ""),
        prompt=data.get("prompt", ""),
        start_url=data.get("start_url", ""),
        interval_seconds=data.get("interval_seconds", 3600),
        options=data.get("options"),
        parallel_workers=data.get("parallel_workers", 1),
        max_runs=data.get("max_runs"),
        notify_on_complete=data.get("notify_on_complete", False),
        self_learning=data.get("self_learning", False),
        self_healing=data.get("self_healing", False),
        self_learning_max_runs=data.get("self_learning_max_runs"),
        run_at=run_at,
    )
    formatted = format_scheduled_task(task)
    await svc.conn.publish(Subjects.BROADCAST_SCHEDULED_TASK_CREATED, formatted)
    return formatted


async def api_update_scheduled_task(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Update a scheduled task."""
    schedule_id = data.get("schedule_id", "")
    updates: dict[str, Any] = {}
    for key in (
        "name",
        "prompt",
        "start_url",
        "interval_seconds",
        "enabled",
        "options",
        "parallel_workers",
        "max_runs",
        "notify_on_complete",
        "self_learning",
        "self_healing",
        "self_learning_max_runs",
        "self_learning_run_count",
        "run_at",
    ):
        if key in data:
            updates[key] = data[key]

    # Parse run_at ISO string to datetime if present
    if "run_at" in updates and updates["run_at"] is not None:
        updates["run_at"] = datetime.fromisoformat(updates["run_at"]).astimezone(
            timezone.utc
        )
    task = await svc._scheduler.update_scheduled_task(schedule_id, **updates)
    if task is None:
        return {"error": f"Scheduled task {schedule_id} not found"}
    formatted = format_scheduled_task(task)
    await svc.conn.publish(Subjects.BROADCAST_SCHEDULED_TASK_UPDATED, formatted)
    return formatted


async def api_delete_scheduled_task(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Delete a scheduled task."""
    schedule_id = data.get("schedule_id", "")
    success = await svc._scheduler.delete_scheduled_task(schedule_id)
    if success:
        await svc.conn.publish(
            Subjects.BROADCAST_SCHEDULED_TASK_DELETED,
            {"schedule_id": schedule_id},
        )
    return {"success": success}


async def api_toggle_scheduled_task(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Toggle a scheduled task's enabled state."""
    schedule_id = data.get("schedule_id", "")
    task = await svc._scheduler.toggle_scheduled_task(schedule_id)
    if task is None:
        return {"error": f"Scheduled task {schedule_id} not found"}
    formatted = format_scheduled_task(task)
    await svc.conn.publish(Subjects.BROADCAST_SCHEDULED_TASK_UPDATED, formatted)
    return formatted


async def api_trigger_scheduled_task(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Manually trigger a scheduled task immediately."""
    schedule_id = data.get("schedule_id", "")
    task = await svc._scheduler.trigger_scheduled_task(schedule_id)
    if task is None:
        return {"error": f"Scheduled task {schedule_id} not found"}
    return {"schedule_id": task.schedule_id, "triggered": True}
