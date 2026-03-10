"""VNC connection backends (TCP and WebSocket)."""

import asyncio
import ssl

from urllib.parse import urlparse

import websockets
import websockets.asyncio.client
from fastapi import WebSocket, WebSocketDisconnect

import logging

logger = logging.getLogger(__name__)


def _create_ssl_context() -> ssl.SSLContext:
    """Create a permissive SSL context for TLS-wrapped VNC connections.

    Used for macOS Screen Sharing which requires TLS before the RFB
    handshake.  Certificate verification is disabled since these are
    typically internal or Tailscale connections.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


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
        self._prepend = b""

    async def send(self, data: bytes) -> None:
        self._writer.write(data)
        await self._writer.drain()

    async def readexactly(self, n: int) -> bytes:
        if self._prepend:
            if len(self._prepend) >= n:
                result = self._prepend[:n]
                self._prepend = self._prepend[n:]
                return result
            remaining = n - len(self._prepend)
            result = self._prepend + await self._reader.readexactly(remaining)
            self._prepend = b""
            return result
        return await self._reader.readexactly(n)

    async def recv(self) -> bytes | None:
        if self._prepend:
            data = self._prepend
            self._prepend = b""
            return data
        data = await self._reader.read(65536)
        if not data:
            return None
        return data

    async def close(self) -> None:
        self._writer.close()
        await self._writer.wait_closed()


class _WsBackend:
    """Backend wrapping a websockets connection."""

    def __init__(self, ws: websockets.asyncio.client.ClientConnection) -> None:
        self._ws = ws
        self._buf = bytearray()

    async def readexactly(self, n: int) -> bytes:
        while len(self._buf) < n:
            data = await self.recv()
            if data is None:
                raise ConnectionError("WebSocket closed during readexactly")
            self._buf.extend(data)
        result = bytes(self._buf[:n])
        self._buf = self._buf[n:]
        return result

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


async def _forward_client_to_worker(
    client_ws: WebSocket, backend: _TcpBackend | _WsBackend
) -> None:
    """Forward messages from browser to worker."""
    try:
        while True:
            data = await client_ws.receive_bytes()
            await backend.send(data)
    except WebSocketDisconnect:
        logger.debug("Client disconnected")
    except Exception as e:
        logger.debug(f"Client->Worker error: {e}")


async def _forward_worker_to_client(
    client_ws: WebSocket, backend: _TcpBackend | _WsBackend
) -> None:
    """Forward messages from worker to browser."""
    try:
        while True:
            message = await backend.recv()
            if message is None:
                break
            await client_ws.send_bytes(message)
    except Exception as e:
        logger.debug(f"Worker->Client error: {e}")
