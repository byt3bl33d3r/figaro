"""WebSocket adapter — lets asyncvnc speak RFB over a websockets connection."""

import asyncio
import logging

import websockets
import websockets.asyncio.client

logger = logging.getLogger(__name__)


class _WsStreamWriter:
    """StreamWriter-compatible wrapper that buffers writes and sends via WebSocket on drain."""

    def __init__(self, ws: websockets.asyncio.client.ClientConnection) -> None:
        self._ws = ws
        self._buf = bytearray()
        self._closing = False

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        if self._buf:
            data = bytes(self._buf)
            self._buf.clear()
            await self._ws.send(data)

    def close(self) -> None:
        self._closing = True

    async def wait_closed(self) -> None:
        pass

    def is_closing(self) -> bool:
        return self._closing


class WsVncAdapter:
    """Wraps a ``websockets`` connection to provide the reader/writer interface
    that ``asyncvnc.Client.create()`` expects.

    Usage::

        ws = await websockets.connect(url, ping_interval=None)
        adapter = WsVncAdapter(ws)
        await adapter.start()
        client = await asyncvnc.Client.create(adapter.reader, adapter.writer, ...)
        ...
        await adapter.close()
    """

    def __init__(self, ws: websockets.asyncio.client.ClientConnection) -> None:
        self._ws = ws
        self._reader = asyncio.StreamReader()
        self._writer = _WsStreamWriter(ws)
        self._recv_task: asyncio.Task[None] | None = None

    @property
    def reader(self) -> asyncio.StreamReader:
        return self._reader

    @property
    def writer(self) -> _WsStreamWriter:
        return self._writer

    async def start(self) -> None:
        """Start the background recv loop that feeds data into the reader."""
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def _recv_loop(self) -> None:
        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    self._reader.feed_data(message)
                else:
                    self._reader.feed_data(message.encode())
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as exc:
            self._reader.feed_eof()
            logger.debug("WsVncAdapter recv loop error: %s", exc)
            return
        self._reader.feed_eof()

    async def close(self) -> None:
        """Stop the recv loop and close the WebSocket."""
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None
        self._writer.close()
        await self._ws.close()
