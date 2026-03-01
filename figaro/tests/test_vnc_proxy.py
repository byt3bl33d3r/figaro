"""Tests for the VNC proxy."""

import pytest
import websockets
from unittest.mock import AsyncMock, patch, MagicMock

from figaro.vnc_proxy import proxy_vnc
from figaro.services import Registry
from figaro.models import ClientType


class TestVNCProxy:
    """Tests for VNC proxy functionality."""

    @pytest.fixture
    def registry(self):
        return Registry()

    @pytest.fixture
    def client_ws(self):
        ws = AsyncMock()
        ws.close = AsyncMock()
        ws.receive_bytes = AsyncMock()
        ws.send_bytes = AsyncMock()
        ws.send_text = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_worker_not_found(self, registry: Registry, client_ws):
        """Test proxy closes connection when worker not found."""
        await proxy_vnc(client_ws, "nonexistent", registry)

        client_ws.close.assert_called_once_with(code=4004, reason="Worker not found")

    @pytest.mark.asyncio
    async def test_worker_no_vnc_url(self, registry: Registry, client_ws):
        """Test proxy closes connection when worker has no VNC URL."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url=None,
        )

        await proxy_vnc(client_ws, "worker-1", registry)

        client_ws.close.assert_called_once_with(
            code=4004, reason="Worker has no VNC URL"
        )

    @pytest.mark.asyncio
    async def test_invalid_vnc_url(self, registry: Registry, client_ws):
        """Test proxy handles invalid VNC URL."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="not-a-valid-url",
        )

        with patch("figaro.vnc_proxy.websockets.connect") as mock_connect:
            mock_connect.side_effect = websockets.exceptions.InvalidURI(
                "not-a-valid-url", "Invalid URI"
            )
            await proxy_vnc(client_ws, "worker-1", registry)

        client_ws.close.assert_called_once_with(code=4002, reason="Invalid VNC URL")

    @pytest.mark.asyncio
    async def test_connection_retries(self, registry: Registry, client_ws):
        """Test proxy retries connection on failure."""

        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="ws://localhost:6080/websockify",
        )

        # Fail first 2 attempts, succeed on 3rd
        attempt = 0

        async def mock_connect_fn(url, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt < 3:
                raise OSError("Connection refused")
            mock_ws = AsyncMock()
            mock_ws.close = AsyncMock()
            mock_ws.send = AsyncMock()
            # recv() raises ConnectionClosed so the proxy loop exits
            mock_ws.recv = AsyncMock(
                side_effect=websockets.exceptions.ConnectionClosed(None, None)
            )
            return mock_ws

        # Client disconnects immediately
        client_ws.receive_bytes.side_effect = Exception("Client disconnected")

        with patch("figaro.vnc_proxy.websockets.connect", side_effect=mock_connect_fn):
            with patch(
                "figaro.vnc_proxy.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep:
                await proxy_vnc(client_ws, "worker-1", registry)

        # Should have called sleep twice (between attempts 1-2 and 2-3)
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, registry: Registry, client_ws):
        """Test proxy gives up after max retries."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="ws://localhost:6080/websockify",
        )

        with patch("figaro.vnc_proxy.websockets.connect") as mock_connect:
            mock_connect.side_effect = OSError("Connection refused")
            with patch("figaro.vnc_proxy.asyncio.sleep", new_callable=AsyncMock):
                with patch("figaro.vnc_proxy.VNC_MAX_RETRIES", 3):
                    await proxy_vnc(client_ws, "worker-1", registry)

        client_ws.close.assert_called_with(
            code=4003, reason="Cannot connect to worker VNC"
        )

    @pytest.mark.asyncio
    async def test_successful_proxy(self, registry: Registry, client_ws):
        """Test successful VNC proxying."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="ws://localhost:6080/websockify",
        )

        # Mock the VNC WebSocket - recv returns data then ConnectionClosed
        vnc_ws = MagicMock()
        vnc_ws.close = AsyncMock()
        vnc_ws.send = AsyncMock()
        vnc_ws.recv = AsyncMock(
            side_effect=[b"vnc_data", websockets.exceptions.ConnectionClosed(None, None)]
        )

        # Client sends one message then disconnects
        from fastapi import WebSocketDisconnect

        client_ws.receive_bytes.side_effect = [b"client_data", WebSocketDisconnect()]

        # websockets.connect is async so needs to return awaitable
        async def mock_connect(url, **kwargs):
            return vnc_ws

        with patch("figaro.vnc_proxy.websockets.connect", side_effect=mock_connect):
            await proxy_vnc(client_ws, "worker-1", registry)

        # Verify data was proxied
        vnc_ws.send.assert_called_with(b"client_data")
        client_ws.send_bytes.assert_called_with(b"vnc_data")
        vnc_ws.close.assert_called_once()
