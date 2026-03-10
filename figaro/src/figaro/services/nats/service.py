"""NATS-based messaging service replacing WebSocket handlers."""

import asyncio
import logging
from typing import Any, TYPE_CHECKING

from figaro_nats import NatsConnection, ensure_streams

from figaro.services.embedding import EmbeddingService
from figaro.services.registry import Registry
from figaro.services.task_manager import Task, TaskManager
from figaro.services.vnc_pool import VncConnectionPool
from figaro.services.nats.subscriptions import setup_subscriptions
from figaro.services.nats.desktop_init import (
    register_desktop_workers,
    load_settings_vnc_password,
)
from figaro.services.nats.api_desktop_workers import (
    api_register_desktop_worker,
    api_remove_desktop_worker,
    api_update_desktop_worker,
)
from figaro.services.nats.api_remote import api_vnc
from figaro.services.nats.api_tasks import api_stop_task
from figaro.services.nats.background import (
    maybe_heal_failed_task,
    maybe_notify_gateway,
    maybe_optimize_scheduled_task,
)
from figaro.services.nats.event_handlers import (
    handle_gateway_channel_register,
    handle_gateway_task,
    handle_heartbeat,
    handle_supervisor_register,
    handle_task_complete,
    handle_task_error,
    handle_worker_register,
)
from figaro.services.nats.queue import heartbeat_monitor
from figaro.services.nats.publishing import (
    broadcast_supervisors,
    broadcast_workers,
    publish_gateway_send,
    publish_help_response,
    publish_supervisor_task,
    publish_task_assignment,
)


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
        self._embedding_service = EmbeddingService(settings.openai_api_key)
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
        await setup_subscriptions(self)
        await register_desktop_workers(self)
        await load_settings_vnc_password(self)
        self._heartbeat_task = asyncio.create_task(heartbeat_monitor(self))
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

    # ── Public method wrappers ──────────────────────────────────

    async def publish_task_assignment(
        self,
        worker_id: str,
        task: Task,
    ) -> None:
        await publish_task_assignment(self, worker_id, task)

    async def publish_supervisor_task(
        self,
        supervisor_id: str,
        task: Task,
    ) -> bool:
        return await publish_supervisor_task(self, supervisor_id, task)

    async def broadcast_workers(self) -> None:
        await broadcast_workers(self)

    async def broadcast_supervisors(self) -> None:
        await broadcast_supervisors(self)

    async def publish_help_response(
        self,
        request_id: str,
        task_id: str,
        worker_id: str,
        answers: dict[str, str] | None = None,
        source: str = "ui",
        error: str | None = None,
    ) -> None:
        await publish_help_response(
            self,
            request_id,
            task_id,
            worker_id,
            answers=answers,
            source=source,
            error=error,
        )

    async def publish_gateway_send(self, channel: str, message: dict[str, Any]) -> None:
        await publish_gateway_send(self, channel, message)

    # ── Private method wrappers (for backward compatibility) ────

    async def _handle_worker_register(self, data: dict[str, Any]) -> dict[str, Any]:
        return await handle_worker_register(self, data)

    async def _handle_supervisor_register(self, data: dict[str, Any]) -> dict[str, Any]:
        return await handle_supervisor_register(self, data)

    async def _handle_heartbeat(self, data: dict[str, Any]) -> None:
        await handle_heartbeat(self, data)

    async def _handle_task_complete(self, data: dict[str, Any]) -> None:
        await handle_task_complete(self, data)

    async def _handle_task_error(self, data: dict[str, Any]) -> None:
        await handle_task_error(self, data)

    async def _handle_gateway_task(self, data: dict[str, Any]) -> None:
        await handle_gateway_task(self, data)

    async def _handle_gateway_channel_register(self, data: dict[str, Any]) -> None:
        await handle_gateway_channel_register(self, data)

    async def _api_vnc(self, data: dict[str, Any]) -> dict[str, Any]:
        return await api_vnc(self, data)

    async def _api_stop_task(self, data: dict[str, Any]) -> dict[str, Any]:
        return await api_stop_task(self, data)

    async def _maybe_notify_gateway(
        self,
        task_id: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        await maybe_notify_gateway(self, task_id, result=result, error=error)

    async def _maybe_optimize_scheduled_task(self, task_id: str) -> None:
        await maybe_optimize_scheduled_task(self, task_id)

    async def _maybe_heal_failed_task(self, task_id: str) -> None:
        await maybe_heal_failed_task(self, task_id)

    async def _register_desktop_workers(self) -> None:
        await register_desktop_workers(self)

    async def _api_register_desktop_worker(
        self, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await api_register_desktop_worker(self, data)

    async def _api_remove_desktop_worker(self, data: dict[str, Any]) -> dict[str, Any]:
        return await api_remove_desktop_worker(self, data)

    async def _api_update_desktop_worker(self, data: dict[str, Any]) -> dict[str, Any]:
        return await api_update_desktop_worker(self, data)
