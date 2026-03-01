"""VNC connection pool — keeps asyncvnc connections alive across calls."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import asyncvnc
import websockets

from figaro.services.vnc_client import WsVncAdapter

logger = logging.getLogger(__name__)


class _PoolEntry:
    """A single pooled VNC connection."""

    __slots__ = ("client", "writer", "last_used", "_adapter")

    def __init__(
        self,
        client: asyncvnc.Client,
        writer: asyncio.StreamWriter | None,
        adapter: WsVncAdapter | None = None,
    ) -> None:
        self.client = client
        self.writer = writer
        self._adapter = adapter
        self.last_used = time.monotonic()

    @property
    def is_stale(self) -> bool:
        if self._adapter is not None:
            return self._adapter.writer.is_closing()
        if self.writer is not None:
            return self.writer.is_closing()
        return True

    async def close(self) -> None:
        try:
            if self._adapter is not None:
                await self._adapter.close()
            elif self.writer is not None:
                self.writer.close()
                await self.writer.wait_closed()
        except Exception:
            pass


class VncConnectionPool:
    """Pool of VNC connections keyed by string key.

    Raw TCP connections use ``"tcp://{host}:{port}"`` as key.
    WebSocket connections use the full URL as key.

    Each key gets at most one connection.  A per-key ``asyncio.Lock``
    serialises operations to the same worker (asyncvnc's StreamWriter is
    not concurrent-safe) while allowing full parallelism across workers.
    """

    def __init__(
        self,
        idle_timeout: int = 60,
        sweep_interval: int = 15,
    ) -> None:
        self._idle_timeout = idle_timeout
        self._sweep_interval = sweep_interval
        self._entries: dict[str, _PoolEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._sweep_task: asyncio.Task[None] | None = None

    # ── lifecycle ───────────────────────────────────────────────

    def start(self) -> None:
        """Start the background idle sweep."""
        if self._sweep_task is None:
            self._sweep_task = asyncio.create_task(self._sweep_loop())

    async def close(self) -> None:
        """Close all pooled connections and stop the sweep."""
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            try:
                await self._sweep_task
            except asyncio.CancelledError:
                pass
            self._sweep_task = None

        for entry in self._entries.values():
            await entry.close()
        self._entries.clear()
        self._locks.clear()

    # ── public API ──────────────────────────────────────────────

    @asynccontextmanager
    async def connection(
        self,
        host: str,
        port: int,
        username: str | None = None,
        password: str | None = None,
    ) -> AsyncIterator[asyncvnc.Client]:
        """Acquire a raw TCP VNC connection, yield the client, then release it.

        Serialises per ``(host, port)`` so only one caller at a time
        uses a given worker's VNC connection.
        """
        key = f"tcp://{host}:{port}"
        lock = self._locks.setdefault(key, asyncio.Lock())

        async with lock:
            client = await self._acquire_tcp(key, host, port, username, password)
            try:
                yield client
            except (ConnectionError, BrokenPipeError, OSError):
                # Connection broke — evict and re-raise
                await self._evict(key)
                raise
            else:
                # Mark as recently used
                entry = self._entries.get(key)
                if entry is not None:
                    entry.last_used = time.monotonic()

    @asynccontextmanager
    async def ws_connection(
        self,
        url: str,
        username: str | None = None,
        password: str | None = None,
    ) -> AsyncIterator[asyncvnc.Client]:
        """Acquire a WebSocket-tunneled VNC connection, yield the client, then release it.

        The *url* should be a ``wss://`` (or ``ws://``) websockify endpoint.
        """
        key = url
        lock = self._locks.setdefault(key, asyncio.Lock())

        async with lock:
            client = await self._acquire_ws(key, url, username, password)
            try:
                yield client
            except (
                ConnectionError,
                BrokenPipeError,
                OSError,
                websockets.exceptions.ConnectionClosed,
            ):
                await self._evict(key)
                raise
            else:
                entry = self._entries.get(key)
                if entry is not None:
                    entry.last_used = time.monotonic()

    # ── internals ───────────────────────────────────────────────

    async def _acquire_tcp(
        self,
        key: str,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
    ) -> asyncvnc.Client:
        """Return a pooled TCP client, creating a new one if necessary."""
        entry = self._entries.get(key)
        if entry is not None and not entry.is_stale:
            return entry.client

        # Stale entry — clean it up
        if entry is not None:
            await entry.close()
            del self._entries[key]

        # Create a fresh connection
        reader, writer = await asyncio.open_connection(host, port)
        client = await asyncvnc.Client.create(reader, writer, username, password)
        self._entries[key] = _PoolEntry(client, writer)
        return client

    async def _acquire_ws(
        self,
        key: str,
        url: str,
        username: str | None,
        password: str | None,
    ) -> asyncvnc.Client:
        """Return a pooled WebSocket client, creating a new one if necessary."""
        entry = self._entries.get(key)
        if entry is not None and not entry.is_stale:
            return entry.client

        if entry is not None:
            await entry.close()
            del self._entries[key]

        ws = await websockets.connect(url, ping_interval=None)
        adapter = WsVncAdapter(ws)
        await adapter.start()
        client = await asyncvnc.Client.create(
            adapter.reader, adapter.writer, username, password
        )
        self._entries[key] = _PoolEntry(client, writer=None, adapter=adapter)
        return client

    async def _evict(self, key: str) -> None:
        """Remove and close a connection (called on errors)."""
        entry = self._entries.pop(key, None)
        if entry is not None:
            await entry.close()

    async def _sweep_loop(self) -> None:
        """Periodically close connections that have been idle too long."""
        while True:
            await asyncio.sleep(self._sweep_interval)
            now = time.monotonic()
            to_evict: list[str] = []
            for key, entry in self._entries.items():
                if now - entry.last_used > self._idle_timeout:
                    to_evict.append(key)
            for key in to_evict:
                lock = self._locks.get(key)
                if lock is not None and lock.locked():
                    # Connection is in use — skip
                    continue
                logger.debug("VNC pool: closing idle connection %s", key)
                await self._evict(key)
