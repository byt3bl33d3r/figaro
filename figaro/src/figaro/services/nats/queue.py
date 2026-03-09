from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from figaro_nats import traced

from figaro.models import ClientType
from figaro.services.nats.publishing import try_assign_to_supervisor
from figaro.services.task_manager import TaskStatus

if TYPE_CHECKING:
    from figaro.services.nats.service import NatsService

logger = logging.getLogger(__name__)


@traced("orchestrator.process_pending_queue")
async def process_pending_queue(svc: NatsService) -> None:
    """Check for pending tasks and assign to idle workers/supervisors."""
    while await svc._task_manager.has_pending_tasks():
        task_id = await svc._task_manager.get_next_pending_task()
        if task_id is None:
            break

        task = await svc._task_manager.get_task(task_id)
        if task is None or task.status != TaskStatus.PENDING:
            continue

        if task.source in ("optimizer", "healer"):
            # Optimizer and healer tasks go to supervisors only
            if not await try_assign_to_supervisor(svc, task):
                await svc._task_manager.queue_task(task_id)
                break
        else:
            # Regular tasks: try supervisor first, fall back to worker
            if await try_assign_to_supervisor(svc, task):
                pass  # assigned successfully
            else:
                worker = await svc._registry.claim_idle_worker()
                if worker:
                    await svc._task_manager.assign_task(task_id, worker.client_id)
                    await svc.publish_task_assignment(worker.client_id, task)
                    await svc.broadcast_workers()
                    logger.info(
                        f"Assigned queued task {task_id} to worker {worker.client_id}"
                    )
                else:
                    await svc._task_manager.queue_task(task_id)
                    break


async def heartbeat_monitor(svc: NatsService) -> None:
    """Background task to check for timed-out clients."""
    while True:
        try:
            await asyncio.sleep(30)
            timed_out = await svc._registry.check_heartbeats(
                timeout=svc._settings.heartbeat_timeout,
            )
            for client_id in timed_out:
                logger.warning(f"Client {client_id} timed out, unregistering")
                conn = await svc._registry.get_connection(client_id)
                await svc._help_request_manager.cancel_requests_for_worker(client_id)
                if client_id in svc._desktop_worker_ids:
                    await svc._registry.downgrade_to_desktop_only(client_id)
                    logger.info(
                        f"Downgraded timed-out worker {client_id} to desktop-only"
                    )
                else:
                    await svc._registry.unregister(client_id)
                if conn and conn.client_type == ClientType.WORKER:
                    await svc.broadcast_workers()
                elif conn and conn.client_type == ClientType.SUPERVISOR:
                    await svc.broadcast_supervisors()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Error in heartbeat monitor")
