"""NATS client for supervisor-orchestrator communication."""

from __future__ import annotations

import asyncio
import functools
import logging
import platform
import socket
from typing import Any, Callable, Awaitable

from figaro_nats import NatsConnection, Subjects
from figaro_nats.streams import ensure_streams

logger = logging.getLogger(__name__)


async def _handle_help_response(
    data: dict[str, Any],
    *,
    request_id: str,
    response_data: dict[str, Any],
    response_event: asyncio.Event,
) -> None:
    """Handle a help response message by updating shared state and signaling the event."""
    if data.get("request_id") == request_id:
        response_data.update(data)
        response_event.set()


class SupervisorNatsClient:
    """Supervisor NATS client for publishing events and receiving task assignments."""

    def __init__(
        self,
        nats_url: str,
        supervisor_id: str,
        capabilities: list[str] | None = None,
    ) -> None:
        self._nats_url = nats_url
        self._supervisor_id = supervisor_id
        self._capabilities = capabilities or ["task_processing"]
        self._conn = NatsConnection(url=nats_url, name=f"supervisor-{supervisor_id}")
        self._handlers: dict[str, list[Callable[..., Awaitable[None]]]] = {}
        self._running = False
        self._status = "idle"
        self._subscriptions: list[Any] = []

    @property
    def supervisor_id(self) -> str:
        return self._supervisor_id

    @property
    def is_connected(self) -> bool:
        return self._conn.is_connected

    @property
    def conn(self) -> NatsConnection:
        return self._conn

    def on(self, event: str, handler: Callable[..., Awaitable[None]]) -> None:
        """Register an event handler."""
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append(handler)

    async def _emit(self, event: str, payload: dict[str, Any]) -> None:
        """Emit event to registered handlers."""
        for handler in self._handlers.get(event, []):
            try:
                await handler(payload)
            except Exception:
                logger.exception("Error in handler for event %s", event)

    async def connect(self) -> bool:
        """Connect to NATS and set up subscriptions."""
        try:
            await self._conn.connect()
            await ensure_streams(self._conn.js)
            await self._setup_subscriptions()
            # Register in background with retries to handle orchestrator startup race
            asyncio.create_task(self._register_with_retries())
            return True
        except Exception:
            logger.exception("Failed to connect to NATS")
            return False

    async def _setup_subscriptions(self) -> None:
        """Subscribe to subjects this supervisor needs."""
        # Task assignments from orchestrator (request/reply so orchestrator
        # can detect dead supervisors via timeout)
        sub = await self._conn.subscribe_request(
            Subjects.supervisor_task(self._supervisor_id),
            self._handle_task,
        )
        self._subscriptions.append(sub)

        # Help responses via JetStream for guaranteed delivery
        sub = await self._conn.js_subscribe(
            "figaro.help.*.response",
            self._handle_help_response,
            durable=f"help-{self._supervisor_id}",
            deliver_policy="new",
        )
        self._subscriptions.append(sub)

    async def _register_with_retries(self) -> None:
        """Register with orchestrator using request/reply, retrying until acknowledged."""
        payload = {
            "worker_id": self._supervisor_id,
            "capabilities": self._capabilities,
            "status": "idle",
            "metadata": {"os": platform.system().lower(), "hostname": socket.gethostname()},
        }
        for attempt in range(15):
            try:
                await self._conn.request(Subjects.REGISTER_SUPERVISOR, payload, timeout=2.0)
                logger.info("Registered supervisor %s", self._supervisor_id)
                return
            except Exception:
                if attempt == 0:
                    logger.debug("Registration not acked yet, retrying...")
                await asyncio.sleep(2)
        logger.warning("Failed to register supervisor %s after retries", self._supervisor_id)

    async def _handle_task(self, data: dict[str, Any]) -> dict[str, Any]:
        await self._emit("task", data)
        return {"status": "ok"}

    async def _handle_help_response(self, data: dict[str, Any]) -> None:
        await self._emit("help_response", data)

    # -- Publish methods --

    async def publish_task_message(self, task_id: str, message: dict[str, Any]) -> None:
        """Publish supervisor task message via JetStream."""
        await self._conn.js_publish(Subjects.task_message(task_id), {
            "task_id": task_id,
            "supervisor_id": self._supervisor_id,
            **message,
        })

    async def publish_task_complete(self, task_id: str, result: Any) -> None:
        """Publish task completion via JetStream."""
        await self._conn.js_publish(Subjects.task_complete(task_id), {
            "task_id": task_id,
            "supervisor_id": self._supervisor_id,
            "result": result,
        })

    async def publish_task_error(self, task_id: str, error: str) -> None:
        """Publish task error via JetStream."""
        await self._conn.js_publish(Subjects.task_error(task_id), {
            "task_id": task_id,
            "supervisor_id": self._supervisor_id,
            "error": error,
        })

    async def publish_help_request(
        self,
        request_id: str,
        task_id: str,
        questions: list[dict[str, Any]],
        timeout_seconds: int = 300,
    ) -> None:
        """Publish a help request."""
        await self._conn.publish(Subjects.HELP_REQUEST, {
            "request_id": request_id,
            "worker_id": self._supervisor_id,
            "supervisor_id": self._supervisor_id,
            "task_id": task_id,
            "questions": questions,
            "timeout_seconds": timeout_seconds,
        })

    async def send_status(self, status: str) -> None:
        """Publish status update."""
        self._status = status
        await self._conn.publish(Subjects.heartbeat("supervisor", self._supervisor_id), {
            "client_id": self._supervisor_id,
            "status": status,
        })

    async def send_heartbeat(self) -> None:
        """Publish heartbeat with current status."""
        await self._conn.publish(Subjects.heartbeat("supervisor", self._supervisor_id), {
            "client_id": self._supervisor_id,
            "client_type": "supervisor",
            "status": self._status,
        })

    async def subscribe_task_complete(
        self,
        task_id: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> Any:
        """Subscribe to a specific task's completion (for delegated task monitoring)."""
        sub = await self._conn.js_subscribe(
            Subjects.task_complete(task_id),
            handler,
            deliver_policy="new",
        )
        self._subscriptions.append(sub)
        return sub

    async def run(self) -> None:
        """Main run loop."""
        self._running = True
        while self._running:
            if not self._conn.is_connected:
                logger.warning("NATS disconnected, reconnecting...")
                try:
                    await self._conn.connect()
                    await ensure_streams(self._conn.js)
                    await self._setup_subscriptions()
                    asyncio.create_task(self._register_with_retries())
                except Exception:
                    logger.exception("Reconnect failed")
            await asyncio.sleep(1)

    def stop(self) -> None:
        self._running = False

    async def close(self) -> None:
        """Gracefully close."""
        self.stop()
        await self._conn.publish(Subjects.deregister("supervisor", self._supervisor_id), {
            "client_id": self._supervisor_id,
        })
        await self._conn.close()

    async def request_help(
        self,
        request_id: str,
        task_id: str,
        questions: list[dict[str, Any]],
        timeout_seconds: int = 300,
    ) -> dict[str, Any] | None:
        """Request help and wait for response (used by help_request handler)."""
        response_event = asyncio.Event()
        response_data: dict[str, Any] = {}

        # Subscribe to the specific response subject
        sub = await self._conn.subscribe(
            Subjects.help_response(request_id),
            functools.partial(
                _handle_help_response,
                request_id=request_id,
                response_data=response_data,
                response_event=response_event,
            ),
        )

        try:
            await self.publish_help_request(request_id, task_id, questions, timeout_seconds)
            try:
                await asyncio.wait_for(response_event.wait(), timeout=timeout_seconds)
                return response_data.get("answers")
            except asyncio.TimeoutError:
                logger.warning("Help request %s timed out", request_id)
                return None
        finally:
            await sub.unsubscribe()
