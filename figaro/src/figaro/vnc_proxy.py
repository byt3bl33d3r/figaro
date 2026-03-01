"""WebSocket proxy for VNC connections to workers."""

import asyncio
import logging
from urllib.parse import urlparse

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from figaro.services import Registry

logger = logging.getLogger(__name__)

# Timeout for a single connection attempt (seconds)
VNC_CONNECT_TIMEOUT = 5
# Interval between retry attempts (seconds)
VNC_RETRY_INTERVAL = 3
# Maximum number of retries before giving up
VNC_MAX_RETRIES = 20  # ~60 seconds total


def parse_vnc_url(url: str) -> tuple[str, str, int]:
    """Parse a VNC URL and return (scheme, host, port).

    Supports vnc://, ws://, and wss:// schemes.
    Default ports: 5900 for vnc://, 6080 for ws:///wss://.

    Args:
        url: The VNC URL to parse.

    Returns:
        A tuple of (scheme, host, port).
    """
    parsed = urlparse(url)
    scheme = parsed.scheme
    host = parsed.hostname or "localhost"
    if parsed.port is not None:
        port = parsed.port
    elif scheme == "vnc":
        port = 5900
    else:
        port = 6080
    return scheme, host, port


class _TcpBackend:
    """Backend wrapping a raw TCP connection (asyncio streams)."""

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._reader = reader
        self._writer = writer

    async def send(self, data: bytes) -> None:
        self._writer.write(data)
        await self._writer.drain()

    async def recv(self) -> bytes | None:
        data = await self._reader.read(65536)
        if not data:
            return None
        return data

    async def close(self) -> None:
        self._writer.close()
        await self._writer.wait_closed()


class _WsBackend:
    """Backend wrapping a websockets connection."""

    def __init__(self, ws: websockets.WebSocketClientProtocol) -> None:
        self._ws = ws

    async def send(self, data: bytes) -> None:
        await self._ws.send(data)

    async def recv(self) -> bytes | None:
        try:
            message = await self._ws.recv()
            if isinstance(message, bytes):
                return message
            return message.encode()
        except websockets.exceptions.ConnectionClosed:
            return None

    async def close(self) -> None:
        await self._ws.close()


async def proxy_vnc(
    client_ws: WebSocket,
    worker_id: str,
    registry: Registry,
) -> None:
    """Proxy VNC WebSocket connection from browser to worker.

    Supports both vnc:// (raw TCP) and ws:///wss:// (WebSocket) URLs.

    Args:
        client_ws: WebSocket connection from browser
        worker_id: ID of worker to connect to
        registry: Registry to look up worker's VNC URL
    """
    # Look up worker
    conn = await registry.get_connection(worker_id)
    if conn is None:
        await client_ws.close(code=4004, reason="Worker not found")
        return

    if not conn.novnc_url:
        await client_ws.close(code=4004, reason="Worker has no VNC URL")
        return

    vnc_url = conn.novnc_url
    logger.info(f"Proxying VNC for worker {worker_id} to {vnc_url}")

    scheme, host, port = parse_vnc_url(vnc_url)

    # Retry loop to connect to worker's VNC
    backend: _TcpBackend | _WsBackend | None = None
    for attempt in range(VNC_MAX_RETRIES):
        try:
            logger.debug(f"Connecting to worker VNC (attempt {attempt + 1}): {vnc_url}")
            if scheme == "vnc":
                async with asyncio.timeout(VNC_CONNECT_TIMEOUT):
                    reader, writer = await asyncio.open_connection(host, port)
                backend = _TcpBackend(reader, writer)
            else:
                try:
                    async with asyncio.timeout(VNC_CONNECT_TIMEOUT):
                        # Disable ping to avoid timeout issues - VNC streams binary data
                        # continuously so we don't need keepalive pings
                        ws = await websockets.connect(vnc_url, ping_interval=None)
                    backend = _WsBackend(ws)
                except websockets.exceptions.InvalidURI as e:
                    # InvalidURI is not retryable - fail immediately
                    logger.error(f"Invalid VNC URL {vnc_url}: {e}")
                    await client_ws.close(code=4002, reason="Invalid VNC URL")
                    return
            logger.info(f"Connected to worker VNC: {vnc_url}")
            break
        except (TimeoutError, websockets.exceptions.WebSocketException, OSError) as e:
            logger.debug(f"VNC connection attempt {attempt + 1} failed: {e}")
            if attempt < VNC_MAX_RETRIES - 1:
                await asyncio.sleep(VNC_RETRY_INTERVAL)
            else:
                logger.error(
                    f"Failed to connect to worker VNC after {VNC_MAX_RETRIES} attempts: {vnc_url}"
                )
                await client_ws.close(code=4003, reason="Cannot connect to worker VNC")
                return

    if backend is None:
        logger.error("Failed to establish VNC connection")
        await client_ws.close(code=4003, reason="Cannot connect to worker VNC")
        return

    # Now proxy data between client and worker
    try:

        async def client_to_worker():
            """Forward messages from browser to worker."""
            try:
                while True:
                    data = await client_ws.receive_bytes()
                    await backend.send(data)
            except WebSocketDisconnect:
                logger.debug("Client disconnected")
            except Exception as e:
                logger.debug(f"Client->Worker error: {e}")

        async def worker_to_client():
            """Forward messages from worker to browser."""
            try:
                while True:
                    message = await backend.recv()
                    if message is None:
                        break
                    await client_ws.send_bytes(message)
            except Exception as e:
                logger.debug(f"Worker->Client error: {e}")

        # Run both directions concurrently
        await asyncio.gather(
            client_to_worker(),
            worker_to_client(),
            return_exceptions=True,
        )

    except Exception as e:
        logger.exception(f"VNC proxy error: {e}")
        try:
            await client_ws.close(code=4000, reason="Proxy error")
        except Exception:
            pass
    finally:
        await backend.close()
