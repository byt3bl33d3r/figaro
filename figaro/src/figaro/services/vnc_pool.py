"""VNC connection pool — keeps asyncvnc connections alive across calls."""

import asyncio
import logging
import ssl
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import asyncvnc
import websockets

from figaro.services.vnc_client import WsVncAdapter

logger = logging.getLogger(__name__)


def _create_ssl_context() -> ssl.SSLContext:
    """Create a permissive SSL context for TLS-wrapped VNC connections."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


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
        connect_timeout: float = 15.0,
    ) -> None:
        self._idle_timeout = idle_timeout
        self._sweep_interval = sweep_interval
        self._connect_timeout = connect_timeout
        self._entries: dict[str, _PoolEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._tls_keys: set[str] = set()
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
        self._tls_keys.clear()

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
            except (ConnectionError, BrokenPipeError, OSError) as exc:
                logger.error("VNC TCP connection broke for %s: %s", key, exc)
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
            ) as exc:
                logger.error("VNC WebSocket connection broke for %s: %s", key, exc)
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
            logger.debug("VNC pool: reusing TCP connection %s", key)
            return entry.client

        # Stale entry — clean it up
        if entry is not None:
            logger.info("VNC pool: evicting stale TCP connection %s", key)
            await entry.close()
            del self._entries[key]

        use_tls = key in self._tls_keys

        # Create a fresh connection (with timeout to avoid blocking on unreachable hosts)
        logger.info(
            "VNC pool: connecting %s to %s:%d (timeout=%.0fs)",
            "TLS" if use_tls else "TCP",
            host,
            port,
            self._connect_timeout,
        )
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    host,
                    port,
                    ssl=_create_ssl_context() if use_tls else None,
                ),
                timeout=self._connect_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(
                "VNC pool: TCP connect to %s:%d timed out after %.0fs",
                host,
                port,
                self._connect_timeout,
            )
            raise
        except OSError as exc:
            logger.error("VNC pool: TCP connect to %s:%d failed: %s", host, port, exc)
            raise
        try:
            client = await asyncio.wait_for(
                asyncvnc.Client.create(reader, writer, username, password),
                timeout=self._connect_timeout,
            )
        except (ValueError, asyncio.IncompleteReadError) as exc:
            writer.close()
            if use_tls:
                logger.error(
                    "VNC pool: RFB handshake with %s:%d failed (TLS): %s",
                    host,
                    port,
                    exc,
                )
                raise
            # Plain TCP rejected — retry with TLS (macOS Screen Sharing)
            logger.info(
                "VNC pool: plain TCP handshake with %s:%d failed (%s), retrying with TLS",
                host,
                port,
                exc,
            )
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port, ssl=_create_ssl_context()),
                    timeout=self._connect_timeout,
                )
                client = await asyncio.wait_for(
                    asyncvnc.Client.create(reader, writer, username, password),
                    timeout=self._connect_timeout,
                )
                self._tls_keys.add(key)
                logger.info("VNC pool: TLS connection to %s:%d established", host, port)
            except Exception as tls_exc:
                logger.error(
                    "VNC pool: TLS handshake with %s:%d also failed: %s",
                    host,
                    port,
                    tls_exc,
                )
                writer.close()
                raise
        except asyncio.TimeoutError:
            logger.error(
                "VNC pool: RFB handshake with %s:%d timed out after %.0fs",
                host,
                port,
                self._connect_timeout,
            )
            writer.close()
            raise
        except Exception as exc:
            logger.error(
                "VNC pool: RFB handshake with %s:%d failed: %s", host, port, exc
            )
            writer.close()
            raise
        logger.info("VNC pool: TCP connection to %s established", key)
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
            logger.debug("VNC pool: reusing WebSocket connection %s", key)
            return entry.client

        if entry is not None:
            logger.info("VNC pool: evicting stale WebSocket connection %s", key)
            await entry.close()
            del self._entries[key]

        logger.info(
            "VNC pool: connecting WebSocket to %s (timeout=%.0fs)",
            url,
            self._connect_timeout,
        )
        try:
            ws = await asyncio.wait_for(
                websockets.connect(url, ping_interval=None),
                timeout=self._connect_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(
                "VNC pool: WebSocket connect to %s timed out after %.0fs",
                url,
                self._connect_timeout,
            )
            raise
        except Exception as exc:
            logger.error("VNC pool: WebSocket connect to %s failed: %s", url, exc)
            raise
        adapter = WsVncAdapter(ws)
        await adapter.start()
        try:
            client = await asyncio.wait_for(
                asyncvnc.Client.create(
                    adapter.reader, adapter.writer, username, password
                ),
                timeout=self._connect_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(
                "VNC pool: RFB handshake over WebSocket %s timed out after %.0fs",
                url,
                self._connect_timeout,
            )
            await adapter.close()
            raise
        except Exception as exc:
            logger.error(
                "VNC pool: RFB handshake over WebSocket %s failed: %s", url, exc
            )
            await adapter.close()
            raise
        logger.info("VNC pool: WebSocket connection to %s established", key)
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
