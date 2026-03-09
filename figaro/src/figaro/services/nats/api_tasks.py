from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from opentelemetry import trace

from figaro_nats import Subjects, traced

from figaro.models import ClientType
from figaro.models.messages import WorkerStatus
from figaro.services.nats.publishing import try_assign_to_supervisor
from figaro.services.nats.queue import process_pending_queue
from figaro.services.task_manager import TaskStatus

if TYPE_CHECKING:
    from figaro.services.nats.service import NatsService

logger = logging.getLogger(__name__)


async def api_delegate(svc: NatsService, data: dict[str, Any]) -> dict[str, Any]:
    """Handle delegate_to_worker request via NATS."""
    prompt = data.get("prompt", "")
    options = data.get("options", {})
    worker_id = data.get("worker_id")
    supervisor_id = data.get("supervisor_id")

    # Build source metadata
    source_metadata: dict[str, Any] = {}
    if supervisor_id:
        source_metadata["supervisor_id"] = supervisor_id

    # Create task
    task = await svc._task_manager.create_task(
        prompt=prompt,
        options=options,
        source="supervisor",
        source_metadata=source_metadata if source_metadata else None,
    )

    # Try to claim worker
    worker = None
    if worker_id:
        conn = await svc._registry.get_connection(worker_id)
        if conn is None:
            return {
                "error": f"Worker {worker_id} not found",
                "task_id": task.task_id,
                "queued": True,
            }
        if conn.client_type != ClientType.WORKER:
            return {
                "error": f"{worker_id} is not a worker",
                "task_id": task.task_id,
                "queued": True,
            }
        if not conn.agent_connected:
            return {
                "error": "Cannot delegate to desktop-only worker",
                "task_id": task.task_id,
                "queued": True,
            }
        if conn.status != WorkerStatus.IDLE:
            return {
                "error": f"Worker {worker_id} is busy",
                "task_id": task.task_id,
                "queued": True,
            }
        await svc._registry.set_worker_status(worker_id, WorkerStatus.BUSY)
        worker = conn
    else:
        worker = await svc._registry.claim_idle_worker()

    if worker is None:
        return {
            "task_id": task.task_id,
            "worker_id": None,
            "queued": True,
            "message": "No workers available. Task queued.",
        }

    await svc._task_manager.assign_task(task.task_id, worker.client_id)
    await svc.publish_task_assignment(worker.client_id, task)

    return {
        "task_id": task.task_id,
        "worker_id": worker.client_id,
        "queued": False,
        "message": "Task delegated.",
    }


async def api_list_workers(svc: NatsService, data: dict[str, Any]) -> dict[str, Any]:
    """List connected workers."""
    workers = await svc._registry.get_workers()
    return {
        "workers": [
            {
                "id": w.client_id,
                "status": w.status.value,
                "capabilities": w.capabilities,
                "novnc_url": w.novnc_url,
                "vnc_username": w.vnc_username,
                "vnc_password": "***" if w.vnc_password else None,
                "agent_connected": w.agent_connected,
                "metadata": w.metadata,
            }
            for w in workers
        ]
    }


async def api_list_tasks(svc: NatsService, data: dict[str, Any]) -> dict[str, Any]:
    """List tasks, optionally filtered by status and/or worker_id."""
    status = data.get("status")
    worker_id = data.get("worker_id")
    limit = data.get("limit", 50)
    tasks = await svc._task_manager.get_all_tasks(
        status=status, limit=limit, worker_id=worker_id
    )
    return {
        "tasks": [
            {
                "task_id": t.task_id,
                "prompt": t.prompt,
                "options": t.options,
                "status": t.status.value,
                "result": t.result,
                "worker_id": t.worker_id,
                "session_id": t.session_id,
                "messages": t.messages,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat()
                if t.completed_at
                else None,
            }
            for t in tasks
        ]
    }


async def api_get_task(svc: NatsService, data: dict[str, Any]) -> dict[str, Any]:
    """Get a specific task by ID."""
    task_id = data.get("task_id", "")
    task = await svc._task_manager.get_task(task_id)
    if task is None:
        return {"error": f"Task {task_id} not found"}
    return {
        "task_id": task.task_id,
        "prompt": task.prompt,
        "options": task.options,
        "status": task.status.value,
        "result": task.result,
        "worker_id": task.worker_id,
        "session_id": task.session_id,
        "messages": task.messages,
    }


async def api_search_tasks(svc: NatsService, data: dict[str, Any]) -> dict[str, Any]:
    """Search tasks by prompt content."""
    query = data.get("q", "")
    status = data.get("status")
    limit = data.get("limit", 20)
    offset = data.get("offset", 0)
    include_messages = data.get("include_messages", False)
    tasks = await svc._task_manager.search_tasks(
        query=query,
        status=status,
        limit=limit,
        offset=offset,
        include_messages=include_messages,
    )
    task_dicts = []
    for t in tasks:
        d = {
            "task_id": t.task_id,
            "prompt": t.prompt,
            "options": t.options,
            "status": t.status.value,
            "result": t.result,
            "worker_id": t.worker_id,
            "session_id": t.session_id,
        }
        if include_messages:
            d["messages"] = t.messages
        task_dicts.append(d)
    return {"tasks": task_dicts}


async def api_supervisor_status(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Get status of all connected supervisors."""
    supervisors = await svc._registry.get_supervisors()
    return {
        "supervisors": [
            {
                "id": s.client_id,
                "status": s.status.value,
                "capabilities": s.capabilities,
            }
            for s in supervisors
        ]
    }


@traced("orchestrator.api_create_task")
async def api_create_task(svc: NatsService, data: dict[str, Any]) -> dict[str, Any]:
    """Create a new task and assign based on target option."""
    prompt = data.get("prompt", "")
    options = data.get("options")

    # Allow caller to specify task_id (e.g. for tracing correlation)
    task_id = options.get("task_id") if isinstance(options, dict) else None

    task = await svc._task_manager.create_task(
        prompt=prompt,
        options=options,
        task_id=task_id,
    )

    # Determine routing target from options
    target = "auto"
    target_worker_id = None
    if isinstance(options, dict):
        target = options.get("target", "auto")
        target_worker_id = options.get("worker_id")

    assigned = False

    if target == "supervisor":
        assigned = await try_assign_to_supervisor(svc, task)
    elif target == "worker":
        if target_worker_id:
            conn = await svc._registry.get_connection(target_worker_id)
            if conn and not conn.agent_connected:
                return {
                    "error": "Cannot assign task to desktop-only worker",
                    "task_id": task.task_id,
                }
            if (
                conn
                and conn.client_type == ClientType.WORKER
                and conn.status == WorkerStatus.IDLE
            ):
                await svc._registry.set_worker_status(
                    target_worker_id, WorkerStatus.BUSY
                )
                await svc._task_manager.assign_task(task.task_id, target_worker_id)
                await svc.publish_task_assignment(target_worker_id, task)
                await svc.broadcast_workers()
                assigned = True
        else:
            worker = await svc._registry.claim_idle_worker()
            if worker:
                await svc._task_manager.assign_task(task.task_id, worker.client_id)
                await svc.publish_task_assignment(worker.client_id, task)
                await svc.broadcast_workers()
                assigned = True
    else:  # auto — try supervisor first, fall back to worker
        assigned = await try_assign_to_supervisor(svc, task)
        if not assigned:
            worker = await svc._registry.claim_idle_worker()
            if worker:
                await svc._task_manager.assign_task(task.task_id, worker.client_id)
                await svc.publish_task_assignment(worker.client_id, task)
                await svc.broadcast_workers()
                assigned = True

    if not assigned:
        await svc._task_manager.queue_task(task.task_id)
        logger.info(f"Task {task.task_id} queued (no available {target})")

    # Refresh task to get updated state
    task = await svc._task_manager.get_task(task.task_id)
    if task is None:
        return {"error": "Failed to create task"}

    # Include the current trace ID so callers can query Jaeger
    span = trace.get_current_span()
    ctx = span.get_span_context()
    trace_id = format(ctx.trace_id, "032x") if ctx.trace_id else ""

    return {
        "task_id": task.task_id,
        "prompt": task.prompt,
        "options": task.options,
        "status": task.status.value,
        "result": task.result,
        "worker_id": task.worker_id,
        "session_id": task.session_id,
        "messages": task.messages,
        "trace_id": trace_id,
    }


async def api_stop_task(svc: NatsService, data: dict[str, Any]) -> dict[str, Any]:
    """Stop a running task by sending a stop signal to the agent and cancelling the task."""
    task_id = data.get("task_id", "")
    if not task_id:
        return {"error": "task_id is required"}

    task = await svc._task_manager.get_task(task_id)
    if not task:
        return {"error": "Task not found"}

    if task.status not in (TaskStatus.ASSIGNED, TaskStatus.RUNNING):
        return {"error": "Task is not running"}

    agent_id = task.worker_id
    if not agent_id:
        return {"error": "Task has no assigned agent"}

    # Determine agent type from registry
    conn = await svc._registry.get_connection(agent_id)
    agent_type = "worker"
    if conn and conn.client_type == ClientType.SUPERVISOR:
        agent_type = "supervisor"

    # Send stop signal to the agent
    if agent_type == "supervisor":
        await svc.conn.publish(
            Subjects.supervisor_stop(agent_id), {"task_id": task_id}
        )
    else:
        await svc.conn.publish(
            Subjects.worker_stop(agent_id), {"task_id": task_id}
        )

    # Cancel the task
    await svc._task_manager.cancel_task(task_id, "Stopped by user")

    # Set agent idle
    await svc._registry.set_worker_status(agent_id, WorkerStatus.IDLE)

    # Broadcast updated lists
    if agent_type == "supervisor":
        await svc.broadcast_supervisors()
    else:
        await svc.broadcast_workers()

    # Broadcast task cancelled event
    await svc.conn.publish(
        Subjects.BROADCAST_TASK_CANCELLED,
        {
            "task_id": task_id,
            "agent_id": agent_id,
            "agent_type": agent_type,
        },
    )

    # Publish task error to JetStream so UI subscribers get notified
    await svc.conn.js_publish(
        Subjects.task_error(task_id),
        {
            "task_id": task_id,
            "error": "Task cancelled by user",
            "cancelled": True,
        },
    )

    # Process pending queue in case there are queued tasks
    await process_pending_queue(svc)

    return {"success": True, "task_id": task_id}
