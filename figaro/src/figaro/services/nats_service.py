"""NATS-based messaging service replacing WebSocket handlers."""

import asyncio
import json
import logging
from typing import Any, TYPE_CHECKING
from urllib.parse import urlparse

from figaro_nats import NatsConnection, Subjects, ensure_streams

from figaro.models import ClientType
from figaro.models.messages import WorkerStatus
from figaro.services.registry import Registry
from figaro.services.task_manager import TaskManager, TaskStatus
from figaro.services.vnc_client import (
    click_with_client,
    key_with_client,
    parse_vnc_url,
    screenshot_with_client,
    type_with_client,
)
from figaro.services.vnc_pool import VncConnectionPool
from figaro.db.repositories.desktop_workers import DesktopWorkerRepository
from figaro.db.repositories.workers import WorkerSessionRepository
from figaro.db.repositories.tasks import TaskRepository
from figaro.db.repositories.scheduled import ScheduledTaskRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from figaro.config import Settings
    from figaro.services.help_request import HelpRequestManager
    from figaro.services.scheduler import SchedulerService

logger = logging.getLogger(__name__)


class NatsService:
    """Core NATS service that replaces WebSocket handlers.

    Manages subscriptions, publishes events, and coordinates
    between registry, task_manager, scheduler, and help_request_manager.
    """

    def __init__(
        self,
        registry: Registry,
        task_manager: TaskManager,
        scheduler: "SchedulerService",
        help_request_manager: "HelpRequestManager",
        settings: "Settings",
        session_factory: "async_sessionmaker[AsyncSession] | None" = None,
    ) -> None:
        self._registry = registry
        self._task_manager = task_manager
        self._scheduler = scheduler
        self._help_request_manager = help_request_manager
        self._settings = settings
        self._session_factory = session_factory
        self._conn: NatsConnection | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._desktop_worker_ids: set[str] = set()
        self._gateway_channels: set[str] = set()
        self._vnc_pool = VncConnectionPool(
            idle_timeout=settings.vnc_pool_idle_timeout,
            sweep_interval=settings.vnc_pool_sweep_interval,
        )

    @property
    def conn(self) -> NatsConnection:
        if self._conn is None:
            raise RuntimeError("NatsService not started")
        return self._conn

    async def start(self) -> None:
        """Connect to NATS and set up all subscriptions."""
        self._conn = NatsConnection(
            url=self._settings.nats_url,
            name="figaro-orchestrator",
        )
        await self._conn.connect()
        await ensure_streams(self._conn.js)
        await self._setup_subscriptions()
        await self._register_desktop_workers()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_monitor())
        self._vnc_pool.start()
        logger.info("NatsService started")

    async def stop(self) -> None:
        """Drain and close the NATS connection."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        await self._vnc_pool.close()
        if self._conn:
            await self._conn.close()
        logger.info("NatsService stopped")

    # ── Desktop worker registration ────────────────────────────

    async def _register_desktop_workers(self) -> None:
        """Register desktop workers from DB (seeded by env var) or env var fallback."""
        raw = self._settings.desktop_workers
        env_entries: list[dict[str, Any]] = []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                env_entries = parsed
        except (json.JSONDecodeError, TypeError):
            pass

        if self._session_factory:
            # Phase 1: seed env-var entries into DB
            try:
                async with self._session_factory() as session:
                    repo = DesktopWorkerRepository(session)
                    for entry in env_entries:
                        worker_id = entry.get("id", "")
                        if not worker_id:
                            continue
                        await repo.upsert(
                            worker_id=worker_id,
                            novnc_url=entry.get("novnc_url", ""),
                            vnc_username=entry.get("vnc_username"),
                            vnc_password=entry.get("vnc_password"),
                            metadata=entry.get("metadata", {}),
                        )
                    await session.commit()

                    # Phase 2: load all desktop workers from DB
                    workers = await repo.list_all()
                    for w in workers:
                        await self._registry.register_desktop_only(
                            client_id=w.worker_id,
                            novnc_url=w.novnc_url,
                            metadata=w.metadata_,
                            vnc_username=w.vnc_username,
                            vnc_password=w.vnc_password,
                        )
                        self._desktop_worker_ids.add(w.worker_id)
                        logger.info(f"Registered desktop worker from DB: {w.worker_id}")
            except Exception:
                logger.warning("Failed to load desktop workers from DB, falling back to env var", exc_info=True)
                await self._register_desktop_workers_from_env(env_entries)
        else:
            await self._register_desktop_workers_from_env(env_entries)

    async def _register_desktop_workers_from_env(self, entries: list[dict[str, Any]]) -> None:
        """Fallback: register desktop workers from parsed env var entries."""
        for entry in entries:
            worker_id = entry.get("id", "")
            if not worker_id:
                logger.warning("Skipping desktop worker entry with no id")
                continue
            await self._registry.register_desktop_only(
                client_id=worker_id,
                novnc_url=entry.get("novnc_url", ""),
                metadata=entry.get("metadata", {}),
                vnc_username=entry.get("vnc_username"),
                vnc_password=entry.get("vnc_password"),
            )
            self._desktop_worker_ids.add(worker_id)
            logger.info(f"Registered desktop-only worker from config: {worker_id}")

    # ── Subscription setup ──────────────────────────────────────

    async def _setup_subscriptions(self) -> None:
        """Set up all NATS subscriptions."""
        conn = self.conn

        # Registration (Core NATS request/reply so clients get ack)
        await conn.subscribe_request(
            Subjects.REGISTER_WORKER,
            self._handle_worker_register,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.REGISTER_SUPERVISOR,
            self._handle_supervisor_register,
            queue="orchestrator",
        )
        await conn.subscribe(
            Subjects.HEARTBEAT_ALL,
            self._handle_heartbeat,
        )
        await conn.subscribe(
            "figaro.deregister.>",
            self._handle_deregister,
        )

        # Task events (JetStream)
        await conn.js_subscribe(
            "figaro.task.*.message",
            self._handle_task_message,
            durable="orchestrator-task-message",
            deliver_policy="new",
        )
        await conn.js_subscribe(
            "figaro.task.*.complete",
            self._handle_task_complete,
            durable="orchestrator-task-complete",
            deliver_policy="new",
        )
        await conn.js_subscribe(
            "figaro.task.*.error",
            self._handle_task_error,
            durable="orchestrator-task-error",
            deliver_policy="new",
        )

        # Help requests (Core NATS)
        await conn.subscribe(
            Subjects.HELP_REQUEST,
            self._handle_help_request,
            queue="orchestrator",
        )

        # Gateway (Core NATS)
        await conn.subscribe(
            Subjects.gateway_task("telegram"),
            self._handle_gateway_task,
            queue="orchestrator",
        )
        await conn.subscribe(
            "figaro.gateway.*.register",
            self._handle_gateway_channel_register,
        )

        # API request/reply handlers (for supervisor NATS-based tool calls)
        await conn.subscribe_request(
            Subjects.API_DELEGATE,
            self._api_delegate,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_WORKERS,
            self._api_list_workers,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_TASKS,
            self._api_list_tasks,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_TASK_GET,
            self._api_get_task,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_TASK_SEARCH,
            self._api_search_tasks,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_SUPERVISOR_STATUS,
            self._api_supervisor_status,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_SCHEDULED_TASKS,
            self._api_list_scheduled_tasks,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_SCHEDULED_TASK_GET,
            self._api_get_scheduled_task,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_SCHEDULED_TASK_CREATE,
            self._api_create_scheduled_task,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_SCHEDULED_TASK_UPDATE,
            self._api_update_scheduled_task,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_SCHEDULED_TASK_DELETE,
            self._api_delete_scheduled_task,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_SCHEDULED_TASK_TOGGLE,
            self._api_toggle_scheduled_task,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_SCHEDULED_TASK_TRIGGER,
            self._api_trigger_scheduled_task,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_TASK_CREATE,
            self._api_create_task,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_HELP_REQUEST_RESPOND,
            self._api_help_request_respond,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_HELP_REQUEST_DISMISS,
            self._api_help_request_dismiss,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_HELP_REQUESTS_LIST,
            self._api_list_help_requests,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_VNC,
            self._api_vnc,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_DESKTOP_WORKERS_REGISTER,
            self._api_register_desktop_worker,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_DESKTOP_WORKERS_REMOVE,
            self._api_remove_desktop_worker,
            queue="orchestrator",
        )
        await conn.subscribe_request(
            Subjects.API_DESKTOP_WORKERS_UPDATE,
            self._api_update_desktop_worker,
            queue="orchestrator",
        )

        logger.info("All NATS subscriptions established")

    # ── Registration handlers ───────────────────────────────────

    async def _handle_worker_register(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle worker registration."""
        worker_id = data.get("worker_id", "")
        capabilities = data.get("capabilities", [])
        novnc_url = data.get("novnc_url")
        metadata = data.get("metadata", {})

        # Check if this worker already exists as desktop-only (upgrade path)
        existing = await self._registry.get_connection(worker_id)
        if existing and not existing.agent_connected:
            await self._registry.upgrade_to_agent(
                client_id=worker_id,
                capabilities=capabilities,
                novnc_url=novnc_url or "",
                metadata=metadata,
            )
            logger.info(f"Upgraded desktop-only worker to agent: {worker_id}")
        else:
            await self._registry.register(
                client_id=worker_id,
                client_type=ClientType.WORKER,
                capabilities=capabilities,
                novnc_url=novnc_url,
                metadata=metadata,
            )

        # Track worker session in database
        if self._session_factory:
            try:
                async with self._session_factory() as session:
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

        await self.broadcast_workers()
        logger.info(f"Worker registered: {worker_id}")
        return {"status": "ok"}

    async def _handle_supervisor_register(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle supervisor registration.

        Also cleans up any stale supervisors (e.g. from Docker container restarts
        where the old container got a different hostname/ID).
        """
        supervisor_id = data.get("worker_id", "")
        capabilities = data.get("capabilities", [])

        # Clean up stale supervisors before registering the new one
        timed_out = await self._registry.check_heartbeats(
            timeout=self._settings.heartbeat_timeout,
        )
        for client_id in timed_out:
            conn = await self._registry.get_connection(client_id)
            if conn and conn.client_type == ClientType.SUPERVISOR:
                logger.warning(
                    f"Removing stale supervisor {client_id} during registration of {supervisor_id}"
                )
                await self._registry.unregister(client_id)

        await self._registry.register(
            client_id=supervisor_id,
            client_type=ClientType.SUPERVISOR,
            capabilities=capabilities,
        )

        await self.broadcast_supervisors()
        logger.info(f"Supervisor registered: {supervisor_id}")
        return {"status": "ok"}

    async def _handle_heartbeat(self, data: dict[str, Any]) -> None:
        """Handle heartbeat from any client.

        If the client is unknown (e.g. registered before orchestrator started),
        auto-register it from the heartbeat data.
        """
        client_id = data.get("client_id", "")
        status_str = data.get("status")
        status = WorkerStatus(status_str) if status_str else None

        # Auto-register unknown clients from heartbeat
        conn = await self._registry.get_connection(client_id)
        if conn is None and data.get("client_type") == "supervisor":
            await self._registry.register(
                client_id=client_id,
                client_type=ClientType.SUPERVISOR,
            )
            if status:
                await self._registry.update_heartbeat(client_id, status=status)
            await self.broadcast_supervisors()
            logger.info(f"Auto-registered supervisor from heartbeat: {client_id}")
        elif conn is None and data.get("client_type") == "worker":
            await self._registry.register(
                client_id=client_id,
                client_type=ClientType.WORKER,
                novnc_url=data.get("novnc_url"),
                capabilities=data.get("capabilities"),
            )
            if status:
                await self._registry.update_heartbeat(client_id, status=status)
            await self.broadcast_workers()
            logger.info(f"Auto-registered worker from heartbeat: {client_id}")
        else:
            await self._registry.update_heartbeat(client_id, status=status)

        # Process pending queue when a client becomes idle
        if status == WorkerStatus.IDLE:
            await self._process_pending_queue()

    async def _handle_deregister(self, data: dict[str, Any]) -> None:
        """Handle client deregistration."""
        client_id = data.get("client_id", "")

        # Cancel help requests
        cancelled = await self._help_request_manager.cancel_requests_for_worker(
            client_id
        )
        if cancelled > 0:
            logger.info(f"Cancelled {cancelled} pending help requests for {client_id}")

        # Mark worker session as disconnected in database
        conn = await self._registry.get_connection(client_id)
        if conn and conn.client_type == ClientType.WORKER and self._session_factory:
            try:
                async with self._session_factory() as session:
                    repo = WorkerSessionRepository(session)
                    await repo.disconnect(client_id, reason="deregister")
                    await session.commit()
            except Exception as e:
                logger.warning(f"Failed to update worker session disconnect: {e}")

        # Downgrade desktop-only workers instead of fully unregistering
        if client_id in self._desktop_worker_ids:
            await self._registry.downgrade_to_desktop_only(client_id)
            logger.info(f"Downgraded worker {client_id} to desktop-only (agent disconnected)")
        else:
            await self._registry.unregister(client_id)

        if conn and conn.client_type == ClientType.WORKER:
            await self.broadcast_workers()
        elif conn and conn.client_type == ClientType.SUPERVISOR:
            await self.broadcast_supervisors()

        logger.info(f"Client deregistered: {client_id}")

    # ── Task event handlers (JetStream) ─────────────────────────

    async def _handle_task_message(self, data: dict[str, Any]) -> None:
        """Handle streaming task message from worker/supervisor."""
        task_id = data.get("task_id")
        worker_id = data.get("worker_id")

        if task_id:
            # Ensure task exists for supervisor messages
            task = await self._task_manager.get_task(task_id)
            if task is None and worker_id:
                await self._task_manager.create_task(
                    prompt="[External task]",
                    options={"worker_id": worker_id},
                    task_id=task_id,
                    source="supervisor",
                    source_metadata={"supervisor_id": worker_id},
                )
            await self._task_manager.append_message(task_id, data)

        # Republish to broadcast for UI
        await self.conn.publish(
            "figaro.broadcast.task_message",
            data,
        )

    async def _handle_task_complete(self, data: dict[str, Any]) -> None:
        """Handle task completion from worker/supervisor."""
        task_id = data.get("task_id")
        result = data.get("result")
        worker_id = data.get("worker_id")
        supervisor_id = data.get("supervisor_id")

        if task_id:
            await self._task_manager.complete_task(task_id, result)

        if worker_id:
            await self._registry.set_worker_status(worker_id, WorkerStatus.IDLE)

            # Increment completed count in DB
            if self._session_factory:
                asyncio.create_task(self._increment_worker_completed_count(worker_id))

        if supervisor_id:
            await self._registry.set_worker_status(supervisor_id, WorkerStatus.IDLE)

        # Broadcast to UI
        await self.conn.publish("figaro.broadcast.task_complete", data)
        await self.broadcast_workers()
        if supervisor_id:
            await self.broadcast_supervisors()

        # Send result back to gateway channel if task originated from one
        if task_id:
            task = await self._task_manager.get_task(task_id)
            if task and task.source == "gateway" and task.source_metadata:
                channel = task.source_metadata.get("channel")
                chat_id = task.source_metadata.get("chat_id")
                if channel and chat_id:
                    if isinstance(result, dict):
                        result_text = result.get("result") or result.get("text", "")
                    else:
                        result_text = result
                    if not result_text:
                        result_text = "Task completed (no result text)."
                    if not isinstance(result_text, str):
                        result_text = str(result_text)
                    await self.publish_gateway_send(
                        channel,
                        {"chat_id": chat_id, "text": result_text},
                    )

        # Notify gateway if scheduled task has notify_on_complete
        if task_id:
            asyncio.create_task(
                self._maybe_notify_gateway(task_id, result=result)
            )

        # Check if completed task should trigger optimization
        if task_id:
            asyncio.create_task(self._maybe_optimize_scheduled_task(task_id))

        # Process pending queue
        await self._process_pending_queue()

    async def _handle_task_error(self, data: dict[str, Any]) -> None:
        """Handle task error from worker/supervisor."""
        task_id = data.get("task_id")
        error = data.get("error", "Unknown error")
        worker_id = data.get("worker_id")

        if task_id:
            await self._task_manager.fail_task(task_id, error)

        if worker_id:
            await self._registry.set_worker_status(worker_id, WorkerStatus.IDLE)

            # Increment failed count in DB
            if self._session_factory:
                asyncio.create_task(self._increment_worker_failed_count(worker_id))

        # Broadcast to UI
        await self.conn.publish("figaro.broadcast.task_error", data)
        await self.broadcast_workers()

        # Notify gateway if scheduled task has notify_on_complete
        if task_id:
            asyncio.create_task(
                self._maybe_notify_gateway(task_id, error=error)
            )

        # Check if failed task should trigger self-healing
        if task_id:
            asyncio.create_task(self._maybe_heal_failed_task(task_id))

        # Process pending queue
        await self._process_pending_queue()

    # ── Help request handlers ───────────────────────────────────

    async def _handle_help_request(self, data: dict[str, Any]) -> None:
        """Handle a help request from a worker/supervisor."""
        request_id = data.get("request_id")
        worker_id = data.get("worker_id") or data.get("supervisor_id", "")
        task_id = data.get("task_id", "")
        questions = data.get("questions", [])
        timeout_seconds = data.get("timeout_seconds")
        context = data.get("context")

        request = await self._help_request_manager.create_request(
            worker_id=worker_id,
            task_id=task_id,
            questions=questions,
            timeout_seconds=timeout_seconds,
            request_id=request_id,
        )

        # Broadcast to UI
        await self.conn.publish(
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

    # ── Gateway handlers ────────────────────────────────────────

    async def _handle_gateway_channel_register(self, data: dict[str, Any]) -> None:
        """Track gateway channel registrations."""
        channel = data.get("channel", "")
        if channel:
            self._gateway_channels.add(channel)
            logger.info(f"Gateway channel registered: {channel}")

    async def _handle_gateway_task(self, data: dict[str, Any]) -> None:
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

        task = await self._task_manager.create_task(
            prompt=prompt,
            options=options,
            task_id=task_id,
            source=source,
            source_metadata=source_metadata,
        )

        # Try to assign to an idle supervisor first (for delegation)
        if not await self._try_assign_to_supervisor(task):
            # Fall back to worker
            worker = await self._registry.claim_idle_worker()
            if worker:
                await self._task_manager.assign_task(task.task_id, worker.client_id)
                await self.publish_task_assignment(worker.client_id, task)
                await self.broadcast_workers()
            else:
                await self._task_manager.queue_task(task.task_id)
                logger.info(
                    f"Gateway task {task.task_id} queued (no idle workers/supervisors)"
                )

    # ── Publish methods ─────────────────────────────────────────

    async def publish_task_assignment(
        self,
        worker_id: str,
        task: Any,
    ) -> None:
        """Publish a task assignment to a specific worker."""
        await self.conn.publish(
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
        await self.conn.js_publish(
            Subjects.task_assigned(task.task_id),
            assigned_payload,
        )

        # Also broadcast to UI
        await self.conn.publish(
            "figaro.broadcast.task_assigned",
            assigned_payload,
        )

    async def publish_supervisor_task(
        self,
        supervisor_id: str,
        task: Any,
    ) -> bool:
        """Publish a task assignment to a specific supervisor.

        Uses request/reply with a short timeout to verify the supervisor is alive.
        Returns True if the supervisor acknowledged, False if it's unreachable.
        """
        try:
            await self.conn.request(
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
            await self._registry.unregister(supervisor_id)
            await self.broadcast_supervisors()
            return False

        # Publish to JetStream for durable replay on UI refresh
        assigned_payload = {
            "task_id": task.task_id,
            "supervisor_id": supervisor_id,
            "prompt": task.prompt,
        }
        await self.conn.js_publish(
            Subjects.task_assigned(task.task_id),
            assigned_payload,
        )

        # Also broadcast to UI
        await self.conn.publish(
            "figaro.broadcast.task_submitted_to_supervisor",
            assigned_payload,
        )
        return True

    async def _try_assign_to_supervisor(self, task: Any) -> bool:
        """Try to assign a task to an idle supervisor, retrying on stale ones.

        Loops through available supervisors, verifying each is alive via
        request/reply before committing the assignment. Dead supervisors
        are automatically unregistered by publish_supervisor_task.
        """
        while True:
            supervisor = await self._registry.claim_idle_supervisor()
            if not supervisor:
                return False
            if await self.publish_supervisor_task(supervisor.client_id, task):
                await self._task_manager.assign_task(
                    task.task_id, supervisor.client_id
                )
                await self.broadcast_supervisors()
                return True
            # Dead supervisor was unregistered, try next one

    async def broadcast_workers(self) -> None:
        """Publish current worker list to broadcast subject."""
        workers = await self._registry.get_workers()
        workers_list = [
            {
                "id": w.client_id,
                "status": w.status.value,
                "capabilities": w.capabilities,
                "novnc_url": w.novnc_url,
                "vnc_username": w.vnc_username,
                "vnc_password": w.vnc_password,
                "agent_connected": w.agent_connected,
                "metadata": w.metadata,
            }
            for w in workers
        ]
        await self.conn.publish(
            Subjects.BROADCAST_WORKERS,
            {"workers": workers_list},
        )

    async def broadcast_supervisors(self) -> None:
        """Publish current supervisor list to broadcast subject."""
        supervisors = await self._registry.get_supervisors()
        supervisors_list = [
            {
                "id": s.client_id,
                "status": s.status.value,
                "capabilities": s.capabilities,
            }
            for s in supervisors
        ]
        await self.conn.publish(
            Subjects.BROADCAST_SUPERVISORS,
            {"supervisors": supervisors_list},
        )

    async def publish_help_response(
        self,
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
        await self.conn.js_publish(
            Subjects.help_response(request_id),
            payload,
        )

    async def publish_gateway_send(self, channel: str, message: dict[str, Any]) -> None:
        """Publish a message to a gateway channel."""
        await self.conn.publish(
            Subjects.gateway_send(channel),
            message,
        )

    async def _maybe_notify_gateway(
        self,
        task_id: str,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        """Send a gateway notification if the task's scheduled task has notify_on_complete."""
        try:
            if not self._session_factory:
                return

            async with self._session_factory() as session:
                repo = TaskRepository(session)
                task_model = await repo.get(task_id)
                if (
                    not task_model
                    or not task_model.scheduled_task_id
                    or task_model.source != "scheduler"
                ):
                    return

                scheduled_task_id = task_model.scheduled_task_id

            scheduled_task = await self._scheduler.get_scheduled_task(scheduled_task_id)
            if not scheduled_task or not scheduled_task.notify_on_complete:
                return

            task_name = scheduled_task.name or scheduled_task_id
            if error:
                text = f"Scheduled task *{task_name}* failed:\n{error}"
            else:
                if isinstance(result, dict):
                    result_text = result.get("result") or result.get("text", "")
                else:
                    result_text = result
                if not result_text:
                    result_text = "No result text."
                if not isinstance(result_text, str):
                    result_text = str(result_text)
                text = f"Scheduled task *{task_name}* completed:\n{result_text}"

            if not self._gateway_channels:
                logger.warning(
                    f"No gateway channels registered, cannot notify for scheduled task {scheduled_task_id}"
                )
                return

            for channel in self._gateway_channels:
                await self.publish_gateway_send(
                    channel,
                    {"chat_id": "", "text": text},
                )
            logger.info(f"Sent gateway notification for scheduled task {scheduled_task_id}")
        except Exception:
            logger.exception(f"Failed to send gateway notification for task {task_id}")

    # ── Pending queue processing ────────────────────────────────

    async def _process_pending_queue(self) -> None:
        """Check for pending tasks and assign to idle workers/supervisors."""
        while await self._task_manager.has_pending_tasks():
            task_id = await self._task_manager.get_next_pending_task()
            if task_id is None:
                break

            task = await self._task_manager.get_task(task_id)
            if task is None or task.status != TaskStatus.PENDING:
                continue

            if task.source in ("optimizer", "healer"):
                # Optimizer and healer tasks go to supervisors only
                if not await self._try_assign_to_supervisor(task):
                    await self._task_manager.queue_task(task_id)
                    break
            else:
                # Regular tasks: try supervisor first, fall back to worker
                if await self._try_assign_to_supervisor(task):
                    pass  # assigned successfully
                else:
                    worker = await self._registry.claim_idle_worker()
                    if worker:
                        await self._task_manager.assign_task(
                            task_id, worker.client_id
                        )
                        await self.publish_task_assignment(worker.client_id, task)
                        await self.broadcast_workers()
                        logger.info(
                            f"Assigned queued task {task_id} to worker {worker.client_id}"
                        )
                    else:
                        await self._task_manager.queue_task(task_id)
                        break

    # ── Heartbeat monitor ───────────────────────────────────────

    async def _heartbeat_monitor(self) -> None:
        """Background task to check for timed-out clients."""
        while True:
            try:
                await asyncio.sleep(30)
                timed_out = await self._registry.check_heartbeats(
                    timeout=self._settings.heartbeat_timeout,
                )
                for client_id in timed_out:
                    logger.warning(f"Client {client_id} timed out, unregistering")
                    conn = await self._registry.get_connection(client_id)
                    await self._help_request_manager.cancel_requests_for_worker(
                        client_id
                    )
                    if client_id in self._desktop_worker_ids:
                        await self._registry.downgrade_to_desktop_only(client_id)
                        logger.info(
                            f"Downgraded timed-out worker {client_id} to desktop-only"
                        )
                    else:
                        await self._registry.unregister(client_id)
                    if conn and conn.client_type == ClientType.WORKER:
                        await self.broadcast_workers()
                    elif conn and conn.client_type == ClientType.SUPERVISOR:
                        await self.broadcast_supervisors()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Error in heartbeat monitor")

    # ── API request/reply handlers ──────────────────────────────

    async def _api_delegate(self, data: dict[str, Any]) -> dict[str, Any]:
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
        task = await self._task_manager.create_task(
            prompt=prompt,
            options=options,
            source="supervisor",
            source_metadata=source_metadata if source_metadata else None,
        )

        # Try to claim worker
        worker = None
        if worker_id:
            conn = await self._registry.get_connection(worker_id)
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
            await self._registry.set_worker_status(worker_id, WorkerStatus.BUSY)
            worker = conn
        else:
            worker = await self._registry.claim_idle_worker()

        if worker is None:
            return {
                "task_id": task.task_id,
                "worker_id": None,
                "queued": True,
                "message": "No workers available. Task queued.",
            }

        await self._task_manager.assign_task(task.task_id, worker.client_id)
        await self.publish_task_assignment(worker.client_id, task)

        return {
            "task_id": task.task_id,
            "worker_id": worker.client_id,
            "queued": False,
            "message": "Task delegated.",
        }

    async def _api_list_workers(self, data: dict[str, Any]) -> dict[str, Any]:
        """List connected workers."""
        workers = await self._registry.get_workers()
        return {
            "workers": [
                {
                    "id": w.client_id,
                    "status": w.status.value,
                    "capabilities": w.capabilities,
                    "novnc_url": w.novnc_url,
                    "vnc_username": w.vnc_username,
                    "vnc_password": w.vnc_password,
                    "agent_connected": w.agent_connected,
                    "metadata": w.metadata,
                }
                for w in workers
            ]
        }

    async def _api_list_tasks(self, data: dict[str, Any]) -> dict[str, Any]:
        """List tasks, optionally filtered by status."""
        status = data.get("status")
        limit = data.get("limit", 50)
        tasks = await self._task_manager.get_all_tasks(status=status, limit=limit)
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
                }
                for t in tasks
            ]
        }

    async def _api_get_task(self, data: dict[str, Any]) -> dict[str, Any]:
        """Get a specific task by ID."""
        task_id = data.get("task_id", "")
        task = await self._task_manager.get_task(task_id)
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

    async def _api_search_tasks(self, data: dict[str, Any]) -> dict[str, Any]:
        """Search tasks by prompt content."""
        query = data.get("q", "")
        status = data.get("status")
        tasks = await self._task_manager.search_tasks(query=query, status=status)
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
                }
                for t in tasks
            ]
        }

    async def _api_supervisor_status(self, data: dict[str, Any]) -> dict[str, Any]:
        """Get status of all connected supervisors."""
        supervisors = await self._registry.get_supervisors()
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

    async def _api_list_scheduled_tasks(self, data: dict[str, Any]) -> dict[str, Any]:
        """List all scheduled tasks."""
        tasks = await self._scheduler.get_all_scheduled_tasks()
        return {
            "tasks": [self._format_scheduled_task(t) for t in tasks]
        }

    async def _api_get_scheduled_task(self, data: dict[str, Any]) -> dict[str, Any]:
        """Get a scheduled task by ID."""
        schedule_id = data.get("schedule_id", "")
        task = await self._scheduler.get_scheduled_task(schedule_id)
        if task is None:
            return {"error": f"Scheduled task {schedule_id} not found"}
        return self._format_scheduled_task(task)

    async def _api_create_scheduled_task(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new scheduled task."""
        task = await self._scheduler.create_scheduled_task(
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
        )
        formatted = self._format_scheduled_task(task)
        await self.conn.publish(
            "figaro.broadcast.scheduled_task_created", formatted
        )
        return formatted

    async def _api_update_scheduled_task(self, data: dict[str, Any]) -> dict[str, Any]:
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
        ):
            if key in data:
                updates[key] = data[key]
        task = await self._scheduler.update_scheduled_task(schedule_id, **updates)
        if task is None:
            return {"error": f"Scheduled task {schedule_id} not found"}
        formatted = self._format_scheduled_task(task)
        await self.conn.publish(
            "figaro.broadcast.scheduled_task_updated", formatted
        )
        return formatted

    async def _api_delete_scheduled_task(self, data: dict[str, Any]) -> dict[str, Any]:
        """Delete a scheduled task."""
        schedule_id = data.get("schedule_id", "")
        success = await self._scheduler.delete_scheduled_task(schedule_id)
        if success:
            await self.conn.publish(
                "figaro.broadcast.scheduled_task_deleted",
                {"schedule_id": schedule_id},
            )
        return {"success": success}

    async def _api_toggle_scheduled_task(self, data: dict[str, Any]) -> dict[str, Any]:
        """Toggle a scheduled task's enabled state."""
        schedule_id = data.get("schedule_id", "")
        task = await self._scheduler.toggle_scheduled_task(schedule_id)
        if task is None:
            return {"error": f"Scheduled task {schedule_id} not found"}
        formatted = self._format_scheduled_task(task)
        await self.conn.publish(
            "figaro.broadcast.scheduled_task_updated", formatted
        )
        return formatted

    async def _api_trigger_scheduled_task(self, data: dict[str, Any]) -> dict[str, Any]:
        """Manually trigger a scheduled task immediately."""
        schedule_id = data.get("schedule_id", "")
        task = await self._scheduler.trigger_scheduled_task(schedule_id)
        if task is None:
            return {"error": f"Scheduled task {schedule_id} not found"}
        return {"schedule_id": task.schedule_id, "triggered": True}

    async def _api_create_task(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new task and assign based on target option."""
        prompt = data.get("prompt", "")
        options = data.get("options")

        task = await self._task_manager.create_task(
            prompt=prompt,
            options=options,
        )

        # Determine routing target from options
        target = "auto"
        target_worker_id = None
        if isinstance(options, dict):
            target = options.get("target", "auto")
            target_worker_id = options.get("worker_id")

        assigned = False

        if target == "supervisor":
            assigned = await self._try_assign_to_supervisor(task)
        elif target == "worker":
            if target_worker_id:
                conn = await self._registry.get_connection(target_worker_id)
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
                    await self._registry.set_worker_status(
                        target_worker_id, WorkerStatus.BUSY
                    )
                    await self._task_manager.assign_task(
                        task.task_id, target_worker_id
                    )
                    await self.publish_task_assignment(target_worker_id, task)
                    await self.broadcast_workers()
                    assigned = True
            else:
                worker = await self._registry.claim_idle_worker()
                if worker:
                    await self._task_manager.assign_task(
                        task.task_id, worker.client_id
                    )
                    await self.publish_task_assignment(worker.client_id, task)
                    await self.broadcast_workers()
                    assigned = True
        else:  # auto — try supervisor first, fall back to worker
            assigned = await self._try_assign_to_supervisor(task)
            if not assigned:
                worker = await self._registry.claim_idle_worker()
                if worker:
                    await self._task_manager.assign_task(
                        task.task_id, worker.client_id
                    )
                    await self.publish_task_assignment(worker.client_id, task)
                    await self.broadcast_workers()
                    assigned = True

        if not assigned:
            await self._task_manager.queue_task(task.task_id)
            logger.info(f"Task {task.task_id} queued (no available {target})")

        # Refresh task to get updated state
        task = await self._task_manager.get_task(task.task_id)
        if task is None:
            return {"error": "Failed to create task"}
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

    async def _api_list_help_requests(self, data: dict[str, Any]) -> dict[str, Any]:
        """List all help requests (pending + recent resolved)."""
        requests = await self._help_request_manager.get_all_requests()
        return {
            "requests": [
                {
                    "request_id": r.request_id,
                    "worker_id": r.worker_id,
                    "task_id": r.task_id,
                    "questions": r.questions,
                    "context": None,
                    "created_at": r.created_at.isoformat(),
                    "timeout_seconds": r.timeout_seconds,
                    "status": r.status.value,
                }
                for r in requests
            ]
        }

    async def _api_help_request_respond(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle help request response via NATS."""
        request_id = data.get("request_id", "")
        answers = data.get("answers", {})
        source = data.get("source", "nats")

        success = await self._help_request_manager.respond(
            request_id=request_id,
            answers=answers,
            source=source,
        )

        if not success:
            return {
                "success": False,
                "error": "Failed to submit response. Request may not exist or already responded.",
                "request_id": request_id,
            }

        return {"success": True, "request_id": request_id}

    async def _api_help_request_dismiss(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle help request dismissal via NATS."""
        request_id = data.get("request_id", "")
        source = data.get("source", "nats")

        success = await self._help_request_manager.dismiss_request(
            request_id=request_id,
            source=source,
        )

        if not success:
            return {
                "success": False,
                "error": "Failed to dismiss request. Request may not exist or already handled.",
                "request_id": request_id,
            }

        return {"success": True, "request_id": request_id}

    async def _api_vnc(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle VNC interaction requests (screenshot, type, key, click)."""
        worker_id = data.get("worker_id", "")
        action = data.get("action", "")

        # Look up worker in registry
        conn = await self._registry.get_connection(worker_id)
        if conn is None:
            return {"error": "Worker not found"}

        # Extract VNC host/port/credentials from worker's URL
        novnc_url = conn.novnc_url or ""
        url_host, url_port, url_user, url_pass = parse_vnc_url(
            novnc_url, default_port=self._settings.vnc_port
        )
        # Per-worker fields → URL-embedded creds → global settings
        username = conn.vnc_username or url_user or self._settings.vnc_username
        password = conn.vnc_password or url_pass or self._settings.vnc_password

        try:
            parsed = urlparse(novnc_url)

            if parsed.scheme == "wss":
                # WebSocket mode — tunnel through websockify (raw VNC port not accessible)
                ctx = self._vnc_pool.ws_connection(
                    novnc_url, username=username, password=password,
                )
            elif parsed.scheme == "vnc":
                # Raw TCP mode — URL points directly at VNC server
                ctx = self._vnc_pool.connection(
                    url_host, url_port, username=username, password=password,
                )
            else:
                # ws:// or other — host is reachable, use raw VNC port
                ctx = self._vnc_pool.connection(
                    url_host, self._settings.vnc_port,
                    username=username, password=password,
                )

            async with ctx as client:
                if action == "screenshot":
                    quality = data.get("quality", 70)
                    max_width = data.get("max_width")
                    max_height = data.get("max_height")
                    image, mime_type, orig_w, orig_h, disp_w, disp_h = (
                        await screenshot_with_client(
                            client, quality, max_width, max_height,
                        )
                    )
                    return {
                        "image": image,
                        "mime_type": mime_type,
                        "original_width": orig_w,
                        "original_height": orig_h,
                        "width": disp_w,
                        "height": disp_h,
                    }
                elif action == "type":
                    await type_with_client(client, data["text"])
                    return {"ok": True}
                elif action == "key":
                    await key_with_client(
                        client, data["key"], data.get("modifiers"),
                        hold_seconds=data.get("hold_seconds"),
                    )
                    return {"ok": True}
                elif action == "click":
                    await click_with_client(
                        client, data["x"], data["y"], data.get("button", "left"),
                    )
                    return {"ok": True}
                else:
                    return {"error": f"Unknown action: {action}"}
        except Exception as e:
            logger.exception("VNC %s failed for worker %s", action, worker_id)
            return {"error": str(e)}

    async def _api_register_desktop_worker(
        self, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Register a desktop-only worker via NATS API."""
        worker_id = data.get("worker_id", "")
        novnc_url = data.get("novnc_url", "")
        metadata = data.get("metadata", {})
        vnc_username = data.get("vnc_username")
        vnc_password = data.get("vnc_password")

        if not worker_id:
            return {"error": "worker_id is required"}

        await self._registry.register_desktop_only(
            client_id=worker_id,
            novnc_url=novnc_url,
            metadata=metadata,
            vnc_username=vnc_username,
            vnc_password=vnc_password,
        )
        self._desktop_worker_ids.add(worker_id)

        # Persist to DB
        if self._session_factory:
            try:
                async with self._session_factory() as session:
                    repo = DesktopWorkerRepository(session)
                    await repo.upsert(
                        worker_id=worker_id,
                        novnc_url=novnc_url,
                        vnc_username=vnc_username,
                        vnc_password=vnc_password,
                        metadata=metadata,
                    )
                    await session.commit()
            except Exception:
                logger.warning(f"Failed to persist desktop worker {worker_id} to DB", exc_info=True)

        await self.broadcast_workers()
        logger.info(f"Registered desktop-only worker via API: {worker_id}")
        return {"status": "ok"}

    async def _api_remove_desktop_worker(
        self, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Remove a desktop-only worker via NATS API."""
        worker_id = data.get("worker_id", "")

        if not worker_id:
            return {"error": "worker_id is required"}

        conn = await self._registry.get_connection(worker_id)
        if conn is None:
            return {"error": f"Worker {worker_id} not found"}

        if conn.agent_connected:
            return {"error": f"Worker {worker_id} has an active agent, cannot remove"}

        await self._registry.unregister(worker_id)
        self._desktop_worker_ids.discard(worker_id)

        # Remove from DB
        if self._session_factory:
            try:
                async with self._session_factory() as session:
                    repo = DesktopWorkerRepository(session)
                    await repo.delete(worker_id)
                    await session.commit()
            except Exception:
                logger.warning(f"Failed to remove desktop worker {worker_id} from DB", exc_info=True)

        await self.broadcast_workers()
        logger.info(f"Removed desktop-only worker via API: {worker_id}")
        return {"status": "ok"}

    async def _api_update_desktop_worker(
        self, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Update a desktop-only worker via NATS API."""
        worker_id = data.get("worker_id", "")
        new_worker_id = data.get("new_worker_id") or None
        novnc_url = data.get("novnc_url") or None
        metadata = data.get("metadata") or None
        vnc_username = data.get("vnc_username") or None
        vnc_password = data.get("vnc_password") or None

        if not worker_id:
            return {"error": "worker_id is required"}

        conn = await self._registry.update_desktop_only(
            client_id=worker_id,
            new_client_id=new_worker_id,
            novnc_url=novnc_url,
            metadata=metadata,
            vnc_username=vnc_username,
            vnc_password=vnc_password,
        )
        if conn is None:
            return {"error": f"Worker {worker_id} not found"}

        if new_worker_id and new_worker_id != worker_id:
            self._desktop_worker_ids.discard(worker_id)
            self._desktop_worker_ids.add(new_worker_id)

        # Persist update to DB
        if self._session_factory:
            try:
                async with self._session_factory() as session:
                    repo = DesktopWorkerRepository(session)
                    await repo.update(
                        worker_id=worker_id,
                        new_worker_id=new_worker_id,
                        novnc_url=novnc_url,
                        vnc_username=vnc_username,
                        vnc_password=vnc_password,
                        metadata=metadata,
                    )
                    await session.commit()
            except Exception:
                logger.warning(f"Failed to persist desktop worker update for {worker_id} to DB", exc_info=True)

        await self.broadcast_workers()
        logger.info(f"Updated desktop-only worker via API: {worker_id}")
        return {"status": "ok"}

    @staticmethod
    def _format_scheduled_task(task: Any) -> dict[str, Any]:
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
        }

    # ── Optimization ───────────────────────────────────────────

    async def _maybe_optimize_scheduled_task(self, task_id: str) -> None:
        """If the completed task came from a self-learning scheduled task, create an optimization task for the supervisor."""
        try:
            # 1. Get the task from DB to access scheduled_task_id and source
            if not self._session_factory:
                return

            async with self._session_factory() as session:
                repo = TaskRepository(session)
                task_model = await repo.get(task_id)
                if (
                    not task_model
                    or not task_model.scheduled_task_id
                    or task_model.source != "scheduler"
                ):
                    return

                scheduled_task_id = task_model.scheduled_task_id

            # 2. Get the scheduled task, check self_learning
            scheduled_task = await self._scheduler.get_scheduled_task(scheduled_task_id)
            if not scheduled_task or not scheduled_task.self_learning:
                return

            # Check if self-learning run count has reached the limit
            if (
                scheduled_task.self_learning_max_runs is not None
                and scheduled_task.self_learning_run_count >= scheduled_task.self_learning_max_runs
            ):
                logger.info(
                    f"Skipping optimization for scheduled task {scheduled_task_id}: "
                    f"learning run count {scheduled_task.self_learning_run_count} >= max {scheduled_task.self_learning_max_runs}"
                )
                return

            # 3. Get conversation history
            messages = await self._task_manager.get_history(task_id)
            if not messages:
                return

            # 4. Filter to key message types and format
            key_types = {"assistant", "tool_result", "result"}
            filtered = [m for m in messages if m.get("type") in key_types]
            if not filtered:
                filtered = messages  # fallback to all messages

            formatted_history = "\n\n".join(
                f"[{m.get('type', 'unknown')}]: {m.get('content', '')[:2000]}"
                for m in filtered[-50:]  # last 50 messages max
            )

            # 5. Build optimization prompt
            prompt = f"""You are optimizing a recurring scheduled task based on a worker's execution history.

## Scheduled Task
- ID: {scheduled_task.schedule_id}
- Name: {scheduled_task.name}
- Current Prompt: {scheduled_task.prompt}

## Worker Conversation History (Task {task_id})
{formatted_history}

## Instructions
Analyze the worker's conversation history above. Based on what happened:
1. Identify what worked well and what was inefficient
2. Note any errors, retries, or wasted steps
3. Look for any human-in-the-loop interactions (AskUserQuestion / help requests). If the worker asked a human for clarification and received answers, incorporate those answers directly into the improved prompt so the worker won't need to ask again next time
4. Improve the task prompt to be more specific and efficient
5. If the task involves website navigation and search, ensure the prompt instructs the worker to use `patchright-cli` for browser automation if available, and to refresh or redo searches to provide fresh results rather than relying on stale page state

Use the `update_scheduled_task` tool to save your improved prompt.
ONLY update the prompt field - do NOT change the schedule, enabled state, start_url, or any other settings.
Keep the core intent of the original prompt intact while making it more actionable and specific."""

            # 6. Create optimization task
            opt_task = await self._task_manager.create_task(
                prompt=prompt,
                source="optimizer",
                options={"source": "optimizer"},
                scheduled_task_id=scheduled_task.schedule_id,
            )

            # 7. Assign to an idle supervisor, or queue for later
            if not await self._try_assign_to_supervisor(opt_task):
                await self._task_manager.queue_task(opt_task.task_id)
                logger.info(
                    f"Queued optimization task {opt_task.task_id} (no idle supervisor)"
                )
                return

            logger.info(
                f"Created optimization task {opt_task.task_id} for scheduled task {scheduled_task.schedule_id}"
            )

            # 8. Increment learning run count
            async with self._session_factory() as session:
                repo = ScheduledTaskRepository(session)
                await repo.increment_learning_count(scheduled_task.schedule_id)
                await session.commit()

        except Exception as e:
            logger.warning(f"Failed to create optimization task for {task_id}: {e}")

    async def _maybe_heal_failed_task(self, task_id: str) -> None:
        """If a failed task has self-healing enabled, create a healer task for the supervisor to retry with an improved approach."""
        try:
            if not self._session_factory:
                return

            async with self._session_factory() as session:
                repo = TaskRepository(session)
                task_model = await repo.get(task_id)
                if not task_model:
                    return

                # Guard: skip healer and optimizer tasks to prevent loops
                if task_model.source in ("healer", "optimizer"):
                    return

                # Resolve healing config
                # 1. Check task options
                options = task_model.options or {}
                source_metadata = task_model.source_metadata or {}
                healing_enabled = options.get("self_healing")

                # 2. If not set in options, check scheduled task
                if healing_enabled is None and task_model.scheduled_task_id:
                    scheduled_task = await self._scheduler.get_scheduled_task(
                        task_model.scheduled_task_id
                    )
                    if scheduled_task:
                        healing_enabled = scheduled_task.self_healing

                # 3. Fall back to system-wide setting
                if healing_enabled is None:
                    healing_enabled = self._settings.self_healing_enabled

                if not healing_enabled:
                    return

                # Check retry limit
                retry_number = source_metadata.get("retry_number", 0)
                max_retries = self._settings.self_healing_max_retries
                if retry_number >= max_retries:
                    logger.info(
                        f"Task {task_id} has reached max healing retries ({retry_number}/{max_retries}), skipping"
                    )
                    return

                # Get conversation history
                messages = await self._task_manager.get_history(task_id)

                # Filter to key message types and format
                formatted_history = ""
                if messages:
                    key_types = {"assistant", "tool_result", "result"}
                    filtered = [m for m in messages if m.get("type") in key_types]
                    if not filtered:
                        filtered = messages  # fallback to all messages

                    formatted_history = "\n\n".join(
                        f"[{m.get('type', 'unknown')}]: {m.get('content', '')[:2000]}"
                        for m in filtered[-50:]  # last 50 messages max
                    )

                # Get the error from the failed task result
                error_msg = ""
                if task_model.result:
                    error_msg = task_model.result.get("error", "")
                if not error_msg:
                    error_msg = "Unknown error"

                # Build healer prompt
                prompt = f"""You are a self-healing agent analyzing a failed task and retrying it with an improved approach.

## Failed Task
- Task ID: {task_id}
- Original Prompt: {task_model.prompt}
- Error: {error_msg}
- Retry Attempt: {retry_number + 1} of {max_retries}

## Conversation History (Task {task_id})
{formatted_history if formatted_history else "[No conversation history available]"}

## Instructions
Analyze the error and conversation history above. Based on what went wrong:
1. Identify the root cause of the failure
2. Determine if this is a recoverable error (e.g., timing issue, element not found, navigation error) or an unrecoverable one (e.g., invalid credentials, service down, fundamental approach problem)
3. If recoverable: use `delegate_to_worker` with an improved prompt that addresses the failure. Modify the approach to avoid the same error.
4. If unrecoverable: do NOT retry. Simply explain why the task cannot be completed.

When delegating, include the original task's start_url if available: {options.get("start_url", "not specified")}

IMPORTANT: Do not simply retry with the exact same prompt. Analyze the failure and adapt the approach."""

                # Determine original_task_id for tracking retry chains
                original_task_id = source_metadata.get("original_task_id", task_id)

                # Create healer task
                healer_task = await self._task_manager.create_task(
                    prompt=prompt,
                    source="healer",
                    options={"source": "healer"},
                    source_metadata={
                        "original_task_id": original_task_id,
                        "failed_task_id": task_id,
                        "retry_number": retry_number + 1,
                        "max_retries": max_retries,
                        "error": str(error_msg),
                    },
                )

                # Broadcast healing event
                await self.conn.publish(
                    "figaro.broadcast.task_healing",
                    {
                        "healer_task_id": healer_task.task_id,
                        "failed_task_id": task_id,
                        "original_task_id": original_task_id,
                        "retry_number": retry_number + 1,
                        "max_retries": max_retries,
                        "error": str(error_msg),
                    },
                )

                # Assign to an idle supervisor, or queue for later
                if not await self._try_assign_to_supervisor(healer_task):
                    await self._task_manager.queue_task(healer_task.task_id)
                    logger.info(
                        f"Queued healer task {healer_task.task_id} (no idle supervisor)"
                    )
                    return

                logger.info(
                    f"Created healer task {healer_task.task_id} for failed task {task_id} "
                    f"(retry {retry_number + 1}/{max_retries})"
                )

        except Exception as e:
            logger.warning(f"Failed to create healer task for {task_id}: {e}")

    # ── DB helper methods ───────────────────────────────────────

    async def _increment_worker_completed_count(self, worker_id: str) -> None:
        """Background task to increment worker completed count in DB."""
        if not self._session_factory:
            return
        try:
            async with self._session_factory() as session:
                repo = WorkerSessionRepository(session)
                await repo.increment_completed(worker_id)
                await session.commit()
        except Exception as e:
            logger.warning(f"Failed to increment completed count for {worker_id}: {e}")

    async def _increment_worker_failed_count(self, worker_id: str) -> None:
        """Background task to increment worker failed count in DB."""
        if not self._session_factory:
            return
        try:
            async with self._session_factory() as session:
                repo = WorkerSessionRepository(session)
                await repo.increment_failed(worker_id)
                await session.commit()
        except Exception as e:
            logger.warning(f"Failed to increment failed count for {worker_id}: {e}")
