from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from figaro_nats import Subjects, traced

if TYPE_CHECKING:
    from figaro.services.nats.service import NatsService

logger = logging.getLogger(__name__)


@traced("orchestrator.publish_task_assignment")
async def publish_task_assignment(
    svc: NatsService,
    worker_id: str,
    task: Any,
) -> None:
    """Publish a task assignment to a specific worker."""
    await svc.conn.publish(
        Subjects.worker_task(worker_id),
        {
            "task_id": task.task_id,
            "prompt": task.prompt,
            "options": task.options,
        },
    )

    # Publish to JetStream for durable replay on UI refresh
    assigned_payload = {
        "task_id": task.task_id,
        "worker_id": worker_id,
        "prompt": task.prompt,
    }
    await svc.conn.js_publish(
        Subjects.task_assigned(task.task_id),
        assigned_payload,
    )

    # Also broadcast to UI
    await svc.conn.publish(
        "figaro.broadcast.task_assigned",
        assigned_payload,
    )


async def publish_supervisor_task(
    svc: NatsService,
    supervisor_id: str,
    task: Any,
) -> bool:
    """Publish a task assignment to a specific supervisor.

    Uses request/reply with a short timeout to verify the supervisor is alive.
    Returns True if the supervisor acknowledged, False if it's unreachable.
    """
    try:
        await svc.conn.request(
            Subjects.supervisor_task(supervisor_id),
            {
                "task_id": task.task_id,
                "prompt": task.prompt,
                "options": task.options,
                "source": task.source,
                "source_metadata": task.source_metadata,
            },
            timeout=5.0,
        )
    except Exception:
        logger.warning(
            f"Supervisor {supervisor_id} did not ack task {task.task_id}, "
            "unregistering stale supervisor"
        )
        await svc._registry.unregister(supervisor_id)
        await svc.broadcast_supervisors()
        return False

    # Publish to JetStream for durable replay on UI refresh
    assigned_payload = {
        "task_id": task.task_id,
        "supervisor_id": supervisor_id,
        "prompt": task.prompt,
    }
    await svc.conn.js_publish(
        Subjects.task_assigned(task.task_id),
        assigned_payload,
    )

    # Also broadcast to UI
    await svc.conn.publish(
        "figaro.broadcast.task_submitted_to_supervisor",
        assigned_payload,
    )
    return True


async def try_assign_to_supervisor(svc: NatsService, task: Any) -> bool:
    """Try to assign a task to an idle supervisor, retrying on stale ones.

    Loops through available supervisors, verifying each is alive via
    request/reply before committing the assignment. Dead supervisors
    are automatically unregistered by publish_supervisor_task.
    """
    while True:
        supervisor = await svc._registry.claim_idle_supervisor()
        if not supervisor:
            return False
        if await svc.publish_supervisor_task(supervisor.client_id, task):
            await svc._task_manager.assign_task(task.task_id, supervisor.client_id)
            await svc.broadcast_supervisors()
            return True
        # Dead supervisor was unregistered, try next one


async def broadcast_workers(svc: NatsService) -> None:
    """Publish current worker list to broadcast subject."""
    workers = await svc._registry.get_workers()
    workers_list = [
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
    await svc.conn.publish(
        Subjects.BROADCAST_WORKERS,
        {"workers": workers_list},
    )


async def broadcast_supervisors(svc: NatsService) -> None:
    """Publish current supervisor list to broadcast subject."""
    supervisors = await svc._registry.get_supervisors()
    supervisors_list = [
        {
            "id": s.client_id,
            "status": s.status.value,
            "capabilities": s.capabilities,
        }
        for s in supervisors
    ]
    await svc.conn.publish(
        Subjects.BROADCAST_SUPERVISORS,
        {"supervisors": supervisors_list},
    )


async def publish_help_response(
    svc: NatsService,
    request_id: str,
    task_id: str,
    worker_id: str,
    answers: dict[str, str] | None = None,
    source: str = "ui",
    error: str | None = None,
) -> None:
    """Publish a help response to the worker via JetStream for guaranteed delivery."""
    payload: dict[str, Any] = {
        "request_id": request_id,
        "task_id": task_id,
        "answers": answers,
        "source": source,
    }
    if error:
        payload["error"] = error
    await svc.conn.js_publish(
        Subjects.help_response(request_id),
        payload,
    )


async def publish_gateway_send(
    svc: NatsService, channel: str, message: dict[str, Any]
) -> None:
    """Publish a message to a gateway channel."""
    await svc.conn.publish(
        Subjects.gateway_send(channel),
        message,
    )
