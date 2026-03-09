"""Tests for the VNC proxy."""

import asyncio
import struct

import pytest
import websockets
from unittest.mock import AsyncMock, patch, MagicMock

from figaro.config import Settings
from figaro.vnc_proxy import (
    _TcpBackend,
    _bridge_server_init,
    _create_ssl_context,
    _pack_ard,
    _perform_server_auth,
    _present_no_auth_to_client,
    _reverse_bits,
    _vnc_des_key,
    _vnc_des_response,
    proxy_vnc,
)
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

        with patch("figaro.vnc_proxy.proxy.websockets.connect") as mock_connect:
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

        with patch("figaro.vnc_proxy.proxy.websockets.connect", side_effect=mock_connect_fn):
            with patch(
                "figaro.vnc_proxy.proxy.asyncio.sleep", new_callable=AsyncMock
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

        with patch("figaro.vnc_proxy.proxy.websockets.connect") as mock_connect:
            mock_connect.side_effect = OSError("Connection refused")
            with patch("figaro.vnc_proxy.proxy.asyncio.sleep", new_callable=AsyncMock):
                with patch("figaro.vnc_proxy.proxy.VNC_MAX_RETRIES", 3):
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
            side_effect=[
                b"vnc_data",
                websockets.exceptions.ConnectionClosed(None, None),
            ]
        )

        # Client sends one message then disconnects
        from fastapi import WebSocketDisconnect

        client_ws.receive_bytes.side_effect = [b"client_data", WebSocketDisconnect()]

        # websockets.connect is async so needs to return awaitable
        async def mock_connect(url, **kwargs):
            return vnc_ws

        with patch("figaro.vnc_proxy.proxy.websockets.connect", side_effect=mock_connect):
            await proxy_vnc(client_ws, "worker-1", registry)

        # Verify data was proxied
        vnc_ws.send.assert_called_with(b"client_data")
        client_ws.send_bytes.assert_called_with(b"vnc_data")
        vnc_ws.close.assert_called_once()


class TestReverseBits:
    """Tests for the VNC DES bit reversal."""

    def test_reverse_bits_zero(self):
        assert _reverse_bits(0) == 0

    def test_reverse_bits_0xff(self):
        assert _reverse_bits(0xFF) == 0xFF

    def test_reverse_bits_0x01(self):
        # 0b00000001 -> 0b10000000 = 0x80
        assert _reverse_bits(0x01) == 0x80

    def test_reverse_bits_0x80(self):
        # 0b10000000 -> 0b00000001 = 0x01
        assert _reverse_bits(0x80) == 0x01

    def test_reverse_bits_round_trip(self):
        for i in range(256):
            assert _reverse_bits(_reverse_bits(i)) == i


class TestVncDesKey:
    """Tests for VNC DES key derivation."""

    def test_short_password_padded(self):
        key = _vnc_des_key("abc")
        assert len(key) == 8

    def test_long_password_truncated(self):
        key = _vnc_des_key("a" * 20)
        assert len(key) == 8
        # Should be same as 8-char password
        assert key == _vnc_des_key("a" * 8)

    def test_empty_password(self):
        key = _vnc_des_key("")
        assert len(key) == 8
        assert key == bytes(8)


class TestVncDesResponse:
    """Tests for VNC DES challenge response."""

    def test_response_length(self):
        challenge = b"\x00" * 16
        response = _vnc_des_response("password", challenge)
        assert len(response) == 16

    def test_deterministic(self):
        challenge = b"\x01\x02\x03\x04\x05\x06\x07\x08" * 2
        r1 = _vnc_des_response("test", challenge)
        r2 = _vnc_des_response("test", challenge)
        assert r1 == r2

    def test_different_passwords_different_responses(self):
        challenge = b"\x01\x02\x03\x04\x05\x06\x07\x08" * 2
        r1 = _vnc_des_response("pass1", challenge)
        r2 = _vnc_des_response("pass2", challenge)
        assert r1 != r2


class TestPerformServerAuth:
    """Tests for _perform_server_auth."""

    @pytest.fixture
    def mock_backend(self):
        backend = AsyncMock()
        return backend

    @pytest.mark.asyncio
    async def test_vnc_auth_type_2(self, mock_backend):
        """Test successful VNC authentication (type 2)."""
        server_version = b"RFB 003.008\n"
        challenge = b"\x00" * 16
        security_result = struct.pack("!I", 0)

        mock_backend.readexactly = AsyncMock(
            side_effect=[
                server_version,  # server version
                struct.pack("!B", 1),  # 1 security type
                bytes([2]),  # type 2 (VNC auth)
                challenge,  # 16-byte challenge
                security_result,  # OK
            ]
        )
        mock_backend.send = AsyncMock()

        result = await _perform_server_auth(mock_backend, "password")
        assert result == server_version

        # Verify we sent version, chose type 2, and sent response
        calls = mock_backend.send.call_args_list
        assert calls[0][0][0] == b"RFB 003.008\n"
        assert calls[1][0][0] == bytes([2])
        assert len(calls[2][0][0]) == 16  # DES response

    @pytest.mark.asyncio
    async def test_no_auth_type_1(self, mock_backend):
        """Test server that only offers type 1 (no auth)."""
        server_version = b"RFB 003.008\n"
        security_result = struct.pack("!I", 0)

        mock_backend.readexactly = AsyncMock(
            side_effect=[
                server_version,
                struct.pack("!B", 1),  # 1 security type
                bytes([1]),  # type 1 (no auth)
                security_result,
            ]
        )
        mock_backend.send = AsyncMock()

        result = await _perform_server_auth(mock_backend, "password")
        assert result == server_version

        calls = mock_backend.send.call_args_list
        assert calls[1][0][0] == bytes([1])

    @pytest.mark.asyncio
    async def test_server_refused(self, mock_backend):
        """Test server that refuses connection."""
        reason = b"Too many connections"
        mock_backend.readexactly = AsyncMock(
            side_effect=[
                b"RFB 003.008\n",
                struct.pack("!B", 0),  # 0 security types = error
                struct.pack("!I", len(reason)),
                reason,
            ]
        )
        mock_backend.send = AsyncMock()

        with pytest.raises(ConnectionError, match="VNC server refused"):
            await _perform_server_auth(mock_backend, "password")

    @pytest.mark.asyncio
    async def test_auth_failed(self, mock_backend):
        """Test authentication failure (wrong password)."""
        mock_backend.readexactly = AsyncMock(
            side_effect=[
                b"RFB 003.008\n",
                struct.pack("!B", 1),
                bytes([2]),
                b"\x00" * 16,  # challenge
                struct.pack("!I", 1),  # SecurityResult: fail
            ]
        )
        mock_backend.send = AsyncMock()

        with pytest.raises(ConnectionError, match="VNC authentication failed"):
            await _perform_server_auth(mock_backend, "wrong")

    @pytest.mark.asyncio
    async def test_unsupported_auth_types(self, mock_backend):
        """Test server with unsupported auth types."""
        mock_backend.readexactly = AsyncMock(
            side_effect=[
                b"RFB 003.008\n",
                struct.pack("!B", 1),
                bytes([18]),  # type 18 (TLS) — unsupported
            ]
        )
        mock_backend.send = AsyncMock()

        with pytest.raises(ConnectionError, match="doesn't support"):
            await _perform_server_auth(mock_backend, "password")


class TestPresentNoAuthToClient:
    """Tests for _present_no_auth_to_client."""

    @pytest.fixture
    def client_ws(self):
        ws = AsyncMock()
        ws.send_bytes = AsyncMock()
        ws.receive_bytes = AsyncMock(side_effect=[b"RFB 003.008\n", bytes([1])])
        return ws

    @pytest.mark.asyncio
    async def test_presents_no_auth(self, client_ws):
        """Test that no-auth is presented correctly."""
        server_version = b"RFB 003.008\n"
        await _present_no_auth_to_client(client_ws, server_version)

        calls = client_ws.send_bytes.call_args_list
        # 1. Server version
        assert calls[0][0][0] == server_version
        # 2. Security types: 1 type, type=1
        assert calls[1][0][0] == bytes([1, 1])
        # 3. SecurityResult: OK
        assert calls[2][0][0] == struct.pack("!I", 0)


class TestBridgeServerInit:
    """Tests for _bridge_server_init."""

    @pytest.fixture
    def client_ws(self):
        ws = AsyncMock()
        ws.send_bytes = AsyncMock()
        ws.receive_bytes = AsyncMock(return_value=bytes([1]))  # shared=True
        return ws

    @pytest.fixture
    def mock_backend(self):
        backend = AsyncMock()
        return backend

    @pytest.mark.asyncio
    async def test_bridges_init_messages(self, client_ws, mock_backend):
        """Test bridging ClientInit/ServerInit."""
        # ServerInit: 1024x768, pixel format, name="Desktop"
        name = b"Desktop"
        header = (
            struct.pack("!HH", 1024, 768)
            + b"\x00" * 16  # pixel format
            + struct.pack("!I", len(name))
        )
        mock_backend.readexactly = AsyncMock(side_effect=[header, name])
        mock_backend.send = AsyncMock()

        await _bridge_server_init(client_ws, mock_backend)

        # Client's shared flag was forwarded
        mock_backend.send.assert_called_once_with(bytes([1]))

        # Full ServerInit was sent to client
        client_ws.send_bytes.assert_called_once_with(header + name)


class TestProxyVncWithAuth:
    """Tests for proxy_vnc with server-side auth."""

    @pytest.fixture
    def registry(self):
        return Registry()

    @pytest.fixture
    def client_ws(self):
        ws = AsyncMock()
        ws.close = AsyncMock()
        ws.receive_bytes = AsyncMock()
        ws.send_bytes = AsyncMock()
        return ws

    @pytest.fixture
    def settings_with_password(self):
        return Settings(
            vnc_password="globalpass",
            database_url="sqlite+aiosqlite:///:memory:",
        )

    @pytest.fixture
    def settings_no_password(self):
        return Settings(
            vnc_password=None,
            database_url="sqlite+aiosqlite:///:memory:",
        )

    @pytest.mark.asyncio
    async def test_auth_with_global_password(
        self, registry: Registry, client_ws, settings_with_password
    ):
        """Test that global password triggers server-side auth."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="ws://localhost:6080/websockify",
        )

        with (
            patch(
                "figaro.vnc_proxy.proxy._perform_server_auth",
                new_callable=AsyncMock,
                return_value=b"RFB 003.008\n",
            ) as mock_auth,
            patch(
                "figaro.vnc_proxy.proxy._present_no_auth_to_client",
                new_callable=AsyncMock,
            ) as mock_present,
            patch(
                "figaro.vnc_proxy.proxy._bridge_server_init",
                new_callable=AsyncMock,
            ) as mock_bridge,
            patch("figaro.vnc_proxy.proxy.websockets.connect") as mock_connect,
        ):
            vnc_ws = MagicMock()
            vnc_ws.close = AsyncMock()
            vnc_ws.send = AsyncMock()
            vnc_ws.recv = AsyncMock(
                side_effect=websockets.exceptions.ConnectionClosed(None, None)
            )

            async def connect_fn(url, **kwargs):
                return vnc_ws

            mock_connect.side_effect = connect_fn
            client_ws.receive_bytes.side_effect = Exception("done")

            await proxy_vnc(client_ws, "worker-1", registry, settings_with_password)

            mock_auth.assert_called_once()
            assert mock_auth.call_args[0][1] == "globalpass"
            assert mock_auth.call_args[1].get("username") is None
            mock_present.assert_called_once()
            mock_bridge.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_auth_without_password(
        self, registry: Registry, client_ws, settings_no_password
    ):
        """Test that no auth is performed when no password is set."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="ws://localhost:6080/websockify",
        )

        with (
            patch(
                "figaro.vnc_proxy.proxy._perform_server_auth",
                new_callable=AsyncMock,
            ) as mock_auth,
            patch("figaro.vnc_proxy.proxy.websockets.connect") as mock_connect,
        ):
            vnc_ws = MagicMock()
            vnc_ws.close = AsyncMock()
            vnc_ws.send = AsyncMock()
            vnc_ws.recv = AsyncMock(
                side_effect=websockets.exceptions.ConnectionClosed(None, None)
            )

            async def connect_fn(url, **kwargs):
                return vnc_ws

            mock_connect.side_effect = connect_fn
            client_ws.receive_bytes.side_effect = Exception("done")

            await proxy_vnc(client_ws, "worker-1", registry, settings_no_password)

            mock_auth.assert_not_called()

    @pytest.mark.asyncio
    async def test_worker_password_overrides_global(
        self, registry: Registry, client_ws, settings_with_password
    ):
        """Test that per-worker password and username take precedence over global."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="ws://localhost:6080/websockify",
            vnc_password="workerpass",
            vnc_username="workeruser",
        )

        with (
            patch(
                "figaro.vnc_proxy.proxy._perform_server_auth",
                new_callable=AsyncMock,
                return_value=b"RFB 003.008\n",
            ) as mock_auth,
            patch(
                "figaro.vnc_proxy.proxy._present_no_auth_to_client",
                new_callable=AsyncMock,
            ),
            patch(
                "figaro.vnc_proxy.proxy._bridge_server_init",
                new_callable=AsyncMock,
            ),
            patch("figaro.vnc_proxy.proxy.websockets.connect") as mock_connect,
        ):
            vnc_ws = MagicMock()
            vnc_ws.close = AsyncMock()
            vnc_ws.send = AsyncMock()
            vnc_ws.recv = AsyncMock(
                side_effect=websockets.exceptions.ConnectionClosed(None, None)
            )

            async def connect_fn(url, **kwargs):
                return vnc_ws

            mock_connect.side_effect = connect_fn
            client_ws.receive_bytes.side_effect = Exception("done")

            await proxy_vnc(client_ws, "worker-1", registry, settings_with_password)

            mock_auth.assert_called_once()
            assert mock_auth.call_args[0][1] == "workerpass"
            assert mock_auth.call_args[1].get("username") == "workeruser"

    @pytest.mark.asyncio
    async def test_auth_failure_closes_connection(
        self, registry: Registry, client_ws, settings_with_password
    ):
        """Test that auth failure closes both connections."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="ws://localhost:6080/websockify",
        )

        with (
            patch(
                "figaro.vnc_proxy.proxy._perform_server_auth",
                new_callable=AsyncMock,
                side_effect=ConnectionError("VNC authentication failed"),
            ),
            patch("figaro.vnc_proxy.proxy.websockets.connect") as mock_connect,
        ):
            vnc_ws = MagicMock()
            vnc_ws.close = AsyncMock()
            vnc_ws.send = AsyncMock()

            async def connect_fn(url, **kwargs):
                return vnc_ws

            mock_connect.side_effect = connect_fn

            await proxy_vnc(client_ws, "worker-1", registry, settings_with_password)

            client_ws.close.assert_called_once_with(
                code=4001, reason="VNC authentication failed"
            )
            vnc_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_settings_no_auth(self, registry: Registry, client_ws):
        """Test that passing settings=None skips auth."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="ws://localhost:6080/websockify",
        )

        with (
            patch(
                "figaro.vnc_proxy.proxy._perform_server_auth",
                new_callable=AsyncMock,
            ) as mock_auth,
            patch("figaro.vnc_proxy.proxy.websockets.connect") as mock_connect,
        ):
            vnc_ws = MagicMock()
            vnc_ws.close = AsyncMock()
            vnc_ws.send = AsyncMock()
            vnc_ws.recv = AsyncMock(
                side_effect=websockets.exceptions.ConnectionClosed(None, None)
            )

            async def connect_fn(url, **kwargs):
                return vnc_ws

            mock_connect.side_effect = connect_fn
            client_ws.receive_bytes.side_effect = Exception("done")

            await proxy_vnc(client_ws, "worker-1", registry)

            mock_auth.assert_not_called()


class TestTcpBackendPrepend:
    """Tests for _TcpBackend prepend buffer support."""

    @pytest.mark.asyncio
    async def test_readexactly_with_prepend(self):
        """Prepended byte is returned first by readexactly."""
        reader = asyncio.StreamReader()
        reader.feed_data(b"FB 003.008\n")
        reader.feed_eof()

        writer = MagicMock()
        backend = _TcpBackend(reader, writer)
        backend._prepend = b"R"

        result = await backend.readexactly(12)
        assert result == b"RFB 003.008\n"

    @pytest.mark.asyncio
    async def test_readexactly_prepend_larger_than_n(self):
        """When prepend has more data than requested, only n bytes returned."""
        reader = asyncio.StreamReader()
        writer = MagicMock()
        backend = _TcpBackend(reader, writer)
        backend._prepend = b"ABCDEF"

        result = await backend.readexactly(3)
        assert result == b"ABC"
        assert backend._prepend == b"DEF"

    @pytest.mark.asyncio
    async def test_recv_returns_prepend_first(self):
        """recv() returns prepend data before reading from stream."""
        reader = asyncio.StreamReader()
        reader.feed_data(b"stream data")
        reader.feed_eof()

        writer = MagicMock()
        backend = _TcpBackend(reader, writer)
        backend._prepend = b"R"

        first = await backend.recv()
        assert first == b"R"

        second = await backend.recv()
        assert second == b"stream data"


class TestTlsAutoDetection:
    """Tests for TLS auto-detection in proxy_vnc."""

    @pytest.fixture
    def registry(self):
        return Registry()

    @pytest.fixture
    def client_ws(self):
        ws = AsyncMock()
        ws.close = AsyncMock()
        ws.receive_bytes = AsyncMock()
        ws.send_bytes = AsyncMock()
        return ws

    @pytest.fixture
    def settings_with_password(self):
        return Settings(
            vnc_password="testpass",
            database_url="sqlite+aiosqlite:///:memory:",
        )

    @pytest.mark.asyncio
    async def test_tls_fallback_on_immediate_close(
        self, registry: Registry, client_ws, settings_with_password
    ):
        """Server closing immediately triggers TLS retry."""
        await registry.register(
            client_id="mac-worker",
            client_type=ClientType.WORKER,
            novnc_url="vnc://mac-host:5900",
        )

        calls = []

        async def mock_open_connection(host, port, **kwargs):
            reader = asyncio.StreamReader()
            writer = MagicMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()

            if "ssl" in kwargs and kwargs["ssl"] is not None:
                # TLS connection — server sends RFB version then EOF
                calls.append("tls")
                reader.feed_data(b"RFB 003.008\n")
                reader.feed_eof()
            else:
                # Plain TCP — server closes immediately (macOS behavior)
                calls.append("plain")
                reader.feed_eof()
            return reader, writer

        with (
            patch(
                "figaro.vnc_proxy.proxy.asyncio.open_connection",
                side_effect=mock_open_connection,
            ),
            patch(
                "figaro.vnc_proxy.proxy._perform_server_auth",
                new_callable=AsyncMock,
                return_value=b"RFB 003.008\n",
            ) as mock_auth,
            patch(
                "figaro.vnc_proxy.proxy._present_no_auth_to_client", new_callable=AsyncMock
            ),
            patch("figaro.vnc_proxy.proxy._bridge_server_init", new_callable=AsyncMock),
        ):
            client_ws.receive_bytes.side_effect = Exception("done")
            await proxy_vnc(client_ws, "mac-worker", registry, settings_with_password)

        assert calls == ["plain", "tls"]
        mock_auth.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_tls_when_plain_works(
        self, registry: Registry, client_ws, settings_with_password
    ):
        """Plain TCP connection that works does not trigger TLS."""
        await registry.register(
            client_id="linux-worker",
            client_type=ClientType.WORKER,
            novnc_url="vnc://linux-host:5900",
        )

        calls = []

        async def mock_open_connection(host, port, **kwargs):
            reader = asyncio.StreamReader()
            writer = MagicMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            calls.append("tls" if kwargs.get("ssl") else "plain")
            # Server sends RFB version immediately then EOF
            reader.feed_data(b"RFB 003.008\n")
            reader.feed_eof()
            return reader, writer

        with (
            patch(
                "figaro.vnc_proxy.proxy.asyncio.open_connection",
                side_effect=mock_open_connection,
            ),
            patch(
                "figaro.vnc_proxy.proxy._perform_server_auth",
                new_callable=AsyncMock,
                return_value=b"RFB 003.008\n",
            ),
            patch(
                "figaro.vnc_proxy.proxy._present_no_auth_to_client", new_callable=AsyncMock
            ),
            patch("figaro.vnc_proxy.proxy._bridge_server_init", new_callable=AsyncMock),
        ):
            client_ws.receive_bytes.side_effect = Exception("done")
            await proxy_vnc(client_ws, "linux-worker", registry, settings_with_password)

        assert calls == ["plain"]


class TestCreateSslContext:
    """Tests for _create_ssl_context."""

    def test_creates_permissive_context(self):
        import ssl

        ctx = _create_ssl_context()
        assert ctx.check_hostname is False
        assert ctx.verify_mode == ssl.CERT_NONE


class TestAppleAuth:
    """Tests for Apple Remote Desktop (type 33) authentication."""

    def test_pack_ard_length(self):
        """Output is always 64 bytes regardless of input length."""
        for length in [0, 1, 10, 32, 63]:
            data = "x" * length
            result = _pack_ard(data)
            assert len(result) == 64, (
                f"Expected 64 bytes for input length {length}, got {len(result)}"
            )

    def test_pack_ard_null_terminated(self):
        """Output starts with input bytes followed by a null byte."""
        data = "hello"
        result = _pack_ard(data)
        encoded = data.encode("utf-8")
        assert result[: len(encoded)] == encoded
        assert result[len(encoded)] == 0

    @pytest.fixture
    def mock_backend(self):
        backend = AsyncMock()
        return backend

    @pytest.mark.asyncio
    async def test_apple_auth_type_33(self, mock_backend):
        """Test successful Apple ARD (type 33) auth flow."""
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
        )

        # Generate a real RSA key pair for the test
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=1024,
        )
        pub_key = private_key.public_key()
        der_pub = pub_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)

        # _apple_auth_response reads:
        #   4 bytes (packet length) + 2 bytes (version) + 4 bytes (key length)
        #   + key_length bytes (DER public key) + 1 byte (trailing)
        #   then after sending encrypted data: 4 bytes (acknowledgement)
        # _perform_server_auth then reads 4 bytes (SecurityResult)
        server_version = b"RFB 003.008\n"
        packet_length = struct.pack("!I", 0)
        version = b"\x01\x00"
        key_length_bytes = struct.pack("!I", len(der_pub))
        trailing = b"\x00"
        ack = b"\x00\x00\x00\x00"
        security_result = struct.pack("!I", 0)

        mock_backend.readexactly = AsyncMock(
            side_effect=[
                server_version,  # server version
                struct.pack("!B", 1),  # 1 security type
                bytes([33]),  # type 33 (Apple ARD)
                packet_length,  # _apple_auth_response: packet_length
                version,  # _apple_auth_response: version
                key_length_bytes,  # _apple_auth_response: key_length
                der_pub,  # _apple_auth_response: DER public key
                trailing,  # _apple_auth_response: trailing byte
                ack,  # _apple_auth_response: acknowledgement
                security_result,  # SecurityResult: OK
            ]
        )
        mock_backend.send = AsyncMock()

        result = await _perform_server_auth(
            mock_backend, "password", username="testuser"
        )
        assert result == server_version

        # Verify we sent: version, chose type 33, ARD auth request, encrypted data
        calls = mock_backend.send.call_args_list
        assert calls[0][0][0] == b"RFB 003.008\n"  # client version
        assert calls[1][0][0] == bytes([33])  # chose type 33
        # calls[2] is the ARD auth request sent by _apple_auth_response
        # calls[3] is the encrypted credentials payload
        assert len(calls) == 4

    @pytest.mark.asyncio
    async def test_apple_auth_no_username_falls_back_to_type_2(self, mock_backend):
        """When type 33 is offered but no username available, fall back to type 2."""
        server_version = b"RFB 003.008\n"
        challenge = b"\x00" * 16
        security_result = struct.pack("!I", 0)

        mock_backend.readexactly = AsyncMock(
            side_effect=[
                server_version,
                struct.pack("!B", 2),  # 2 security types
                bytes([33, 2]),  # type 33 (Apple ARD) + type 2 (VNC auth)
                challenge,  # 16-byte challenge for type 2
                security_result,
            ]
        )
        mock_backend.send = AsyncMock()

        # No username provided — should skip type 33 and use type 2
        result = await _perform_server_auth(mock_backend, "password", username=None)
        assert result == server_version

        calls = mock_backend.send.call_args_list
        assert calls[1][0][0] == bytes([2])  # chose type 2, not 33


class TestUsernameResolution:
    """Tests for username resolution and passing to _perform_server_auth."""

    @pytest.fixture
    def registry(self):
        return Registry()

    @pytest.fixture
    def client_ws(self):
        ws = AsyncMock()
        ws.close = AsyncMock()
        ws.receive_bytes = AsyncMock()
        ws.send_bytes = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_username_resolved_and_passed(self, registry: Registry, client_ws):
        """Verify username from worker's vnc_username or settings.vnc_username flows to _perform_server_auth."""
        settings = Settings(
            vnc_password="globalpass",
            vnc_username="settings-user",
            database_url="sqlite+aiosqlite:///:memory:",
        )

        # Worker has no vnc_username set — should fall back to settings.vnc_username
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="ws://localhost:6080/websockify",
        )

        with (
            patch(
                "figaro.vnc_proxy.proxy._perform_server_auth",
                new_callable=AsyncMock,
                return_value=b"RFB 003.008\n",
            ) as mock_auth,
            patch(
                "figaro.vnc_proxy.proxy._present_no_auth_to_client",
                new_callable=AsyncMock,
            ),
            patch(
                "figaro.vnc_proxy.proxy._bridge_server_init",
                new_callable=AsyncMock,
            ),
            patch("figaro.vnc_proxy.proxy.websockets.connect") as mock_connect,
        ):
            vnc_ws = MagicMock()
            vnc_ws.close = AsyncMock()
            vnc_ws.send = AsyncMock()
            vnc_ws.recv = AsyncMock(
                side_effect=websockets.exceptions.ConnectionClosed(None, None)
            )

            async def connect_fn(url, **kwargs):
                return vnc_ws

            mock_connect.side_effect = connect_fn
            client_ws.receive_bytes.side_effect = Exception("done")

            await proxy_vnc(client_ws, "worker-1", registry, settings)

            mock_auth.assert_called_once()
            # Password should be globalpass (no per-worker override)
            assert mock_auth.call_args[0][1] == "globalpass"
            # Username should come from settings.vnc_username
            assert mock_auth.call_args[1].get("username") == "settings-user"
