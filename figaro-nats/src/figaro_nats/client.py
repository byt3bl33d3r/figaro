"""NATS connection wrapper with typed publish/subscribe/request methods."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Awaitable

import nats
from nats.aio.client import Client
from nats.js import JetStreamContext

logger = logging.getLogger(__name__)


class NatsConnection:
    """Wrapper around nats.aio.client.Client with JSON serialization and reconnect handling."""

    def __init__(self, url: str = "nats://localhost:4222", name: str | None = None) -> None:
        self._url = url
        self._name = name
        self._nc: Client | None = None
        self._js: JetStreamContext | None = None

    @property
    def nc(self) -> Client:
        if self._nc is None or self._nc.is_closed:
            raise RuntimeError("NATS connection not established. Call connect() first.")
        return self._nc

    @property
    def js(self) -> JetStreamContext:
        if self._js is None:
            raise RuntimeError("JetStream not available. Call connect() first.")
        return self._js

    @property
    def is_connected(self) -> bool:
        return self._nc is not None and self._nc.is_connected

    async def connect(self) -> None:
        """Connect to NATS server with automatic reconnection."""

        async def error_cb(e: Exception) -> None:
            logger.error("NATS error: %s", e)

        async def disconnected_cb() -> None:
            logger.warning("NATS disconnected")

        async def reconnected_cb() -> None:
            logger.info("NATS reconnected to %s", self._nc.connected_url if self._nc else "unknown")

        self._nc = await nats.connect(
            self._url,
            name=self._name,
            error_cb=error_cb,
            disconnected_cb=disconnected_cb,
            reconnected_cb=reconnected_cb,
            max_reconnect_attempts=-1,  # Infinite reconnect
            reconnect_time_wait=2,  # 2s between attempts
        )
        self._js = self._nc.jetstream()
        logger.info("Connected to NATS at %s", self._url)

    async def close(self) -> None:
        """Gracefully drain and close the connection."""
        if self._nc and not self._nc.is_closed:
            await self._nc.drain()
            logger.info("NATS connection drained and closed")

    async def publish(self, subject: str, data: dict[str, Any] | None = None) -> None:
        """Publish a JSON message to a subject."""
        payload = json.dumps(data or {}).encode()
        await self.nc.publish(subject, payload)

    async def js_publish(self, subject: str, data: dict[str, Any] | None = None) -> None:
        """Publish a JSON message via JetStream (for durable task events)."""
        payload = json.dumps(data or {}).encode()
        await self.js.publish(subject, payload)

    async def subscribe(
        self,
        subject: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
        queue: str | None = None,
    ) -> nats.aio.subscription.Subscription:
        """Subscribe to a subject with a JSON message handler."""

        async def _cb(msg: nats.aio.msg.Msg) -> None:
            try:
                data = json.loads(msg.data.decode()) if msg.data else {}
                await handler(data)
            except Exception:
                logger.exception("Error handling message on %s", subject)

        sub = await self.nc.subscribe(subject, queue=queue, cb=_cb)
        logger.debug("Subscribed to %s", subject)
        return sub

    async def request(
        self,
        subject: str,
        data: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Send a request and wait for a response (request/reply pattern)."""
        payload = json.dumps(data or {}).encode()
        msg = await self.nc.request(subject, payload, timeout=timeout)
        return json.loads(msg.data.decode()) if msg.data else {}

    async def subscribe_request(
        self,
        subject: str,
        handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        queue: str | None = None,
    ) -> nats.aio.subscription.Subscription:
        """Subscribe to a request/reply subject. Handler returns the response dict."""

        async def _cb(msg: nats.aio.msg.Msg) -> None:
            try:
                data = json.loads(msg.data.decode()) if msg.data else {}
                result = await handler(data)
                await msg.respond(json.dumps(result or {}).encode())
            except Exception:
                logger.exception("Error handling request on %s", subject)
                error_resp = json.dumps({"error": "Internal error"}).encode()
                try:
                    await msg.respond(error_resp)
                except Exception:
                    pass

        sub = await self.nc.subscribe(subject, queue=queue, cb=_cb)
        logger.debug("Subscribed to request subject %s", subject)
        return sub

    async def js_subscribe(
        self,
        subject: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
        durable: str | None = None,
        deliver_policy: str = "all",
    ) -> Any:
        """Subscribe to a JetStream subject."""

        async def _cb(msg: nats.aio.msg.Msg) -> None:
            try:
                data = json.loads(msg.data.decode()) if msg.data else {}
                await handler(data)
                await msg.ack()
            except Exception:
                logger.exception("Error handling JetStream message on %s", subject)
                # NAK so message can be redelivered
                await msg.nak()

        if deliver_policy == "new":
            from nats.js.api import DeliverPolicy, ConsumerConfig

            config = ConsumerConfig(deliver_policy=DeliverPolicy.NEW)
        else:
            config = None

        sub = await self.js.subscribe(
            subject,
            durable=durable,
            cb=_cb,
            manual_ack=True,
            config=config,
        )
        logger.debug("JetStream subscribed to %s (durable=%s)", subject, durable)
        return sub
