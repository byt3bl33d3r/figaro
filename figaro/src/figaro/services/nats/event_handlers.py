from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

from figaro_nats import traced

from figaro.models import ClientType
from figaro.models.messages import WorkerStatus
from figaro.db.repositories.workers import WorkerSessionRepository
from figaro.services.nats.background import (
    increment_worker_completed_count,
    increment_worker_failed_count,
    maybe_notify_gateway,
    maybe_optimize_scheduled_task,
    maybe_heal_failed_task,
    resolve_result_text,
)
from figaro.services.nats.publishing import try_assign_to_supervisor
from figaro.services.nats.queue import process_pending_queue
from figaro.services.task_manager import TaskStatus

if TYPE_CHECKING:
    from figaro.services.nats.service import NatsService

logger = logging.getLogger(__name__)


async def handle_worker_register(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Handle worker registration."""
    worker_id = data.get("worker_id", "")
    capabilities = data.get("capabilities", [])
    novnc_url = data.get("novnc_url")
    metadata = data.get("metadata", {})

    # Check if this worker already exists as desktop-only (upgrade path)
    existing = await svc._registry.get_connection(worker_id)
    if existing and not existing.agent_connected:
        await svc._registry.upgrade_to_agent(
            client_id=worker_id,
            capabilities=capabilities,
            novnc_url=novnc_url or "",
            metadata=metadata,
        )
        logger.info(f"Upgraded desktop-only worker to agent: {worker_id}")
    else:
        await svc._registry.register(
            client_id=worker_id,
            client_type=ClientType.WORKER,
            capabilities=capabilities,
            novnc_url=novnc_url,
            metadata=metadata,
        )

    # Track worker session in database
    if svc._session_factory:
        try:
            async with svc._session_factory() as session:
                repo = WorkerSessionRepository(session)
                await repo.create(
                    worker_id=worker_id,
                    capabilities=capabilities,
                    novnc_url=novnc_url,
                )
                await session.commit()
            logger.debug(f"Created worker session for {worker_id}")
        except Exception as e:
            logger.warning(f"Failed to create worker session: {e}")

    await svc.broadcast_workers()
    logger.info(f"Worker registered: {worker_id}")
    return {"status": "ok"}


async def handle_supervisor_register(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Handle supervisor registration.

    Also cleans up any stale supervisors (e.g. from Docker container restarts
    where the old container got a different hostname/ID).
    """
    supervisor_id = data.get("worker_id", "")
    capabilities = data.get("capabilities", [])

    # Clean up stale supervisors before registering the new one
    timed_out = await svc._registry.check_heartbeats(
        timeout=svc._settings.heartbeat_timeout,
    )
    for client_id in timed_out:
        conn = await svc._registry.get_connection(client_id)
        if conn and conn.client_type == ClientType.SUPERVISOR:
            logger.warning(
                f"Removing stale supervisor {client_id} during registration of {supervisor_id}"
            )
            await svc._registry.unregister(client_id)

    await svc._registry.register(
        client_id=supervisor_id,
        client_type=ClientType.SUPERVISOR,
        capabilities=capabilities,
    )

    await svc.broadcast_supervisors()
    logger.info(f"Supervisor registered: {supervisor_id}")
    return {"status": "ok"}


async def handle_heartbeat(svc: NatsService, data: dict[str, Any]) -> None:
    """Handle heartbeat from any client.

    If the client is unknown (e.g. registered before orchestrator started),
    auto-register it from the heartbeat data.
    """
    client_id = data.get("client_id", "")
    status_str = data.get("status")
    status = WorkerStatus(status_str) if status_str else None

    # Auto-register unknown clients from heartbeat
    conn = await svc._registry.get_connection(client_id)
    if conn is None and data.get("client_type") == "supervisor":
        await svc._registry.register(
            client_id=client_id,
            client_type=ClientType.SUPERVISOR,
        )
        if status:
            await svc._registry.update_heartbeat(client_id, status=status)
        await svc.broadcast_supervisors()
        logger.info(f"Auto-registered supervisor from heartbeat: {client_id}")
    elif conn is None and data.get("client_type") == "worker":
        await svc._registry.register(
            client_id=client_id,
            client_type=ClientType.WORKER,
            novnc_url=data.get("novnc_url"),
            capabilities=data.get("capabilities"),
        )
        if status:
            await svc._registry.update_heartbeat(client_id, status=status)
        await svc.broadcast_workers()
        logger.info(f"Auto-registered worker from heartbeat: {client_id}")
    else:
        await svc._registry.update_heartbeat(client_id, status=status)

    # Process pending queue when a client becomes idle
    if status == WorkerStatus.IDLE:
        await process_pending_queue(svc)


async def handle_deregister(svc: NatsService, data: dict[str, Any]) -> None:
    """Handle client deregistration."""
    client_id = data.get("client_id", "")

    # Cancel help requests
    cancelled = await svc._help_request_manager.cancel_requests_for_worker(client_id)
    if cancelled > 0:
        logger.info(f"Cancelled {cancelled} pending help requests for {client_id}")

    # Mark worker session as disconnected in database
    conn = await svc._registry.get_connection(client_id)
    if conn and conn.client_type == ClientType.WORKER and svc._session_factory:
        try:
            async with svc._session_factory() as session:
                repo = WorkerSessionRepository(session)
                await repo.disconnect(client_id, reason="deregister")
                await session.commit()
        except Exception as e:
            logger.warning(f"Failed to update worker session disconnect: {e}")

    # Downgrade desktop-only workers instead of fully unregistering
    if client_id in svc._desktop_worker_ids:
        await svc._registry.downgrade_to_desktop_only(client_id)
        logger.info(
            f"Downgraded worker {client_id} to desktop-only (agent disconnected)"
        )
    else:
        await svc._registry.unregister(client_id)

    if conn and conn.client_type == ClientType.WORKER:
        await svc.broadcast_workers()
    elif conn and conn.client_type == ClientType.SUPERVISOR:
        await svc.broadcast_supervisors()

    logger.info(f"Client deregistered: {client_id}")


async def handle_task_message(svc: NatsService, data: dict[str, Any]) -> None:
    """Handle streaming task message from worker/supervisor."""
    task_id = data.get("task_id")
    worker_id = data.get("worker_id")

    if task_id:
        # Ensure task exists for supervisor messages
        task = await svc._task_manager.get_task(task_id)
        if task is None and worker_id:
            await svc._task_manager.create_task(
                prompt="[External task]",
                options={"worker_id": worker_id},
                task_id=task_id,
                source="supervisor",
                source_metadata={"supervisor_id": worker_id},
            )
        await svc._task_manager.append_message(task_id, data)

    # Republish to broadcast for UI
    await svc.conn.publish(
        "figaro.broadcast.task_message",
        data,
    )


@traced("orchestrator.handle_task_complete")
async def handle_task_complete(svc: NatsService, data: dict[str, Any]) -> None:
    """Handle task completion from worker/supervisor."""
    task_id = data.get("task_id")
    result = data.get("result")
    worker_id = data.get("worker_id")
    supervisor_id = data.get("supervisor_id")

    if task_id:
        await svc._task_manager.complete_task(task_id, result)

    if worker_id:
        await svc._registry.set_worker_status(worker_id, WorkerStatus.IDLE)

        # Increment completed count in DB
        if svc._session_factory:
            asyncio.create_task(increment_worker_completed_count(svc, worker_id))

    if supervisor_id:
        await svc._registry.set_worker_status(supervisor_id, WorkerStatus.IDLE)

    # Broadcast to UI
    await svc.conn.publish("figaro.broadcast.task_complete", data)
    await svc.broadcast_workers()
    if supervisor_id:
        await svc.broadcast_supervisors()

    # Resolve result text once for both gateway send and scheduled task notification
    result_text: str | None = None
    if task_id:
        task = await svc._task_manager.get_task(task_id)
        if task and task.source == "gateway" and task.source_metadata:
            channel = task.source_metadata.get("channel")
            chat_id = task.source_metadata.get("chat_id")
            if channel and chat_id:
                result_text = await resolve_result_text(svc, task_id, result)
                await svc.publish_gateway_send(
                    channel,
                    {"chat_id": chat_id, "text": result_text},
                )

    # Notify gateway if scheduled task has notify_on_complete
    if task_id:
        asyncio.create_task(
            maybe_notify_gateway(
                svc, task_id, result=result, result_text=result_text
            )
        )

    # Check if completed task should trigger optimization
    if task_id:
        asyncio.create_task(maybe_optimize_scheduled_task(svc, task_id))

    # Process pending queue
    await process_pending_queue(svc)


@traced("orchestrator.handle_task_error")
async def handle_task_error(svc: NatsService, data: dict[str, Any]) -> None:
    """Handle task error from worker/supervisor."""
    task_id = data.get("task_id")
    error = data.get("error", "Unknown error")
    worker_id = data.get("worker_id")

    # Guard: skip if task was already cancelled (stop task flow handles cleanup)
    if task_id:
        task = await svc._task_manager.get_task(task_id)
        if task and task.status == TaskStatus.CANCELLED:
            logger.debug(f"Skipping error handling for cancelled task {task_id}")
            return

    if task_id:
        await svc._task_manager.fail_task(task_id, error)

    if worker_id:
        await svc._registry.set_worker_status(worker_id, WorkerStatus.IDLE)

        # Increment failed count in DB
        if svc._session_factory:
            asyncio.create_task(increment_worker_failed_count(svc, worker_id))

    # Broadcast to UI
    await svc.conn.publish("figaro.broadcast.task_error", data)
    await svc.broadcast_workers()

    # Notify gateway if scheduled task has notify_on_complete
    if task_id:
        asyncio.create_task(maybe_notify_gateway(svc, task_id, error=error))

    # Check if failed task should trigger self-healing
    if task_id:
        asyncio.create_task(maybe_heal_failed_task(svc, task_id))

    # Process pending queue
    await process_pending_queue(svc)


async def handle_help_request(svc: NatsService, data: dict[str, Any]) -> None:
    """Handle a help request from a worker/supervisor."""
    request_id = data.get("request_id")
    worker_id = data.get("worker_id") or data.get("supervisor_id", "")
    task_id = data.get("task_id", "")
    questions = data.get("questions", [])
    timeout_seconds = data.get("timeout_seconds")
    context = data.get("context")

    request = await svc._help_request_manager.create_request(
        worker_id=worker_id,
        task_id=task_id,
        questions=questions,
        timeout_seconds=timeout_seconds,
        request_id=request_id,
    )

    # Broadcast to UI
    await svc.conn.publish(
        "figaro.broadcast.help_request",
        {
            "type": "help_request_created",
            "request_id": request.request_id,
            "worker_id": worker_id,
            "task_id": task_id,
            "questions": questions,
            "context": context,
            "created_at": request.created_at.isoformat(),
            "timeout_seconds": request.timeout_seconds,
        },
    )

    logger.info(f"Created help request {request.request_id} for {worker_id}")


async def handle_gateway_channel_register(
    svc: NatsService, data: dict[str, Any]
) -> None:
    """Track gateway channel registrations."""
    channel = data.get("channel", "")
    if channel and channel not in svc._gateway_channels:
        svc._gateway_channels.add(channel)
        logger.info(f"Gateway channel registered: {channel}")


async def handle_gateway_task(svc: NatsService, data: dict[str, Any]) -> None:
    """Handle a task from a gateway (e.g., Telegram)."""
    prompt = data.get("text") or data.get("prompt", "")
    options = data.get("options", {})
    task_id = data.get("task_id")
    channel = data.get("channel", "")
    source = data.get("source", "gateway")
    source_metadata = data.get("source_metadata", {})
    if channel:
        source_metadata["channel"] = channel
    chat_id = data.get("chat_id")
    if chat_id:
        source_metadata["chat_id"] = chat_id

    attachments = data.get("attachments")
    if attachments:
        options["attachments"] = attachments

    task = await svc._task_manager.create_task(
        prompt=prompt,
        options=options,
        task_id=task_id,
        source=source,
        source_metadata=source_metadata,
    )

    # Try to assign to an idle supervisor first (for delegation)
    if not await try_assign_to_supervisor(svc, task):
        # Fall back to worker
        worker = await svc._registry.claim_idle_worker()
        if worker:
            await svc._task_manager.assign_task(task.task_id, worker.client_id)
            await svc.publish_task_assignment(worker.client_id, task)
            await svc.broadcast_workers()
        else:
            await svc._task_manager.queue_task(task.task_id)
            logger.info(
                f"Gateway task {task.task_id} queued (no idle workers/supervisors)"
            )
