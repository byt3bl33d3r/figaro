"""Tests for VncConnectionPool."""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from figaro.services.vnc_pool import VncConnectionPool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_writer(closing: bool = False) -> MagicMock:
    writer = MagicMock()
    writer.is_closing.return_value = closing
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    return writer


def _make_client() -> MagicMock:
    return MagicMock()


def _make_adapter(closing: bool = False) -> MagicMock:
    adapter = MagicMock()
    adapter.reader = MagicMock()
    adapter.writer = _make_writer(closing)
    adapter.start = AsyncMock()
    adapter.close = AsyncMock()
    return adapter


# ---------------------------------------------------------------------------
# Tests — TCP connections
# ---------------------------------------------------------------------------


class TestAcquireCreatesConnection:
    """First acquire should open a TCP connection and create a Client."""

    async def test_creates_connection(self):
        pool = VncConnectionPool()
        writer = _make_writer()
        client = _make_client()

        with (
            patch("figaro.services.vnc_pool.asyncio.open_connection", new_callable=AsyncMock, return_value=(MagicMock(), writer)) as mock_open,
            patch("figaro.services.vnc_pool.asyncvnc.Client.create", new_callable=AsyncMock, return_value=client),
        ):
            async with pool.connection("host", 5901, password="pw") as c:
                assert c is client

            mock_open.assert_awaited_once_with("host", 5901)

        await pool.close()


class TestReuseConnection:
    """Release then re-acquire should reuse the same client (no second open_connection)."""

    async def test_reuses_client(self):
        pool = VncConnectionPool()
        writer = _make_writer()
        client = _make_client()

        with (
            patch("figaro.services.vnc_pool.asyncio.open_connection", new_callable=AsyncMock, return_value=(MagicMock(), writer)) as mock_open,
            patch("figaro.services.vnc_pool.asyncvnc.Client.create", new_callable=AsyncMock, return_value=client),
        ):
            # First acquire
            async with pool.connection("host", 5901) as c1:
                pass

            # Second acquire — should reuse
            async with pool.connection("host", 5901) as c2:
                pass

            assert c1 is c2
            # open_connection should only have been called once
            mock_open.assert_awaited_once()

        await pool.close()


class TestStaleConnectionReconnects:
    """When writer.is_closing() is True, pool should create a new connection."""

    async def test_stale_triggers_reconnect(self):
        pool = VncConnectionPool()
        writer1 = _make_writer(closing=False)
        writer2 = _make_writer(closing=False)
        client1 = _make_client()
        client2 = _make_client()

        call_count = 0

        async def fake_open(host, port):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (MagicMock(), writer1)
            return (MagicMock(), writer2)

        async def fake_create(reader, writer, username, password):
            if writer is writer1:
                return client1
            return client2

        with (
            patch("figaro.services.vnc_pool.asyncio.open_connection", side_effect=fake_open),
            patch("figaro.services.vnc_pool.asyncvnc.Client.create", side_effect=fake_create),
        ):
            # First acquire
            async with pool.connection("host", 5901) as c:
                assert c is client1

            # Mark writer1 as stale
            writer1.is_closing.return_value = True

            # Second acquire — should reconnect
            async with pool.connection("host", 5901) as c:
                assert c is client2

            assert call_count == 2

        await pool.close()


class TestEvictOnError:
    """ConnectionError inside the context manager should evict the entry."""

    async def test_evicts_on_connection_error(self):
        pool = VncConnectionPool()
        writer = _make_writer()
        client = _make_client()

        with (
            patch("figaro.services.vnc_pool.asyncio.open_connection", new_callable=AsyncMock, return_value=(MagicMock(), writer)),
            patch("figaro.services.vnc_pool.asyncvnc.Client.create", new_callable=AsyncMock, return_value=client),
        ):
            with pytest.raises(ConnectionError):
                async with pool.connection("host", 5901):
                    raise ConnectionError("broken")

            # Entry should be evicted
            assert "tcp://host:5901" not in pool._entries

        await pool.close()


class TestIdleSweep:
    """Idle sweep should close expired connections."""

    async def test_sweep_closes_idle(self):
        pool = VncConnectionPool(idle_timeout=0, sweep_interval=0)
        writer = _make_writer()
        client = _make_client()

        with (
            patch("figaro.services.vnc_pool.asyncio.open_connection", new_callable=AsyncMock, return_value=(MagicMock(), writer)),
            patch("figaro.services.vnc_pool.asyncvnc.Client.create", new_callable=AsyncMock, return_value=client),
        ):
            async with pool.connection("host", 5901):
                pass

            assert "tcp://host:5901" in pool._entries

            # Start sweep and let it run once
            pool.start()
            await asyncio.sleep(0.05)

            # Entry should be swept
            assert "tcp://host:5901" not in pool._entries

        await pool.close()


class TestCloseAll:
    """close() should clean up all connections."""

    async def test_close_cleans_up(self):
        pool = VncConnectionPool()
        writer = _make_writer()
        client = _make_client()

        with (
            patch("figaro.services.vnc_pool.asyncio.open_connection", new_callable=AsyncMock, return_value=(MagicMock(), writer)),
            patch("figaro.services.vnc_pool.asyncvnc.Client.create", new_callable=AsyncMock, return_value=client),
        ):
            async with pool.connection("host", 5901):
                pass

        await pool.close()

        assert len(pool._entries) == 0
        assert len(pool._locks) == 0
        writer.close.assert_called()


class TestConcurrentDifferentHosts:
    """Concurrent acquires to different hosts should work in parallel."""

    async def test_parallel_different_hosts(self):
        pool = VncConnectionPool()
        writer_a = _make_writer()
        writer_b = _make_writer()
        client_a = _make_client()
        client_b = _make_client()

        async def fake_open(host, port):
            if host == "host-a":
                return (MagicMock(), writer_a)
            return (MagicMock(), writer_b)

        async def fake_create(reader, writer, username, password):
            if writer is writer_a:
                return client_a
            return client_b

        with (
            patch("figaro.services.vnc_pool.asyncio.open_connection", side_effect=fake_open),
            patch("figaro.services.vnc_pool.asyncvnc.Client.create", side_effect=fake_create),
        ):
            results = {}

            async def use_host(host):
                async with pool.connection(host, 5901) as c:
                    results[host] = c

            await asyncio.gather(use_host("host-a"), use_host("host-b"))

            assert results["host-a"] is client_a
            assert results["host-b"] is client_b

        await pool.close()


# ---------------------------------------------------------------------------
# Tests — WebSocket connections
# ---------------------------------------------------------------------------


class TestWsConnectionCreates:
    """First ws_connection() should open a WebSocket and return a client."""

    async def test_creates_ws_connection(self):
        pool = VncConnectionPool()
        mock_ws = AsyncMock()
        adapter = _make_adapter()
        client = _make_client()

        with (
            patch("figaro.services.vnc_pool.websockets.connect", new_callable=AsyncMock, return_value=mock_ws) as mock_connect,
            patch("figaro.services.vnc_pool.WsVncAdapter", return_value=adapter) as mock_adapter_cls,
            patch("figaro.services.vnc_pool.asyncvnc.Client.create", new_callable=AsyncMock, return_value=client) as mock_create,
        ):
            async with pool.ws_connection("wss://host:443/vnc", password="pw") as c:
                assert c is client

            mock_connect.assert_awaited_once_with("wss://host:443/vnc", ping_interval=None)
            mock_adapter_cls.assert_called_once_with(mock_ws)
            adapter.start.assert_awaited_once()
            mock_create.assert_awaited_once_with(
                adapter.reader, adapter.writer, None, "pw"
            )

        await pool.close()


class TestWsConnectionReuses:
    """Second ws_connection() with the same URL should reuse the pooled client."""

    async def test_reuses_ws_client(self):
        pool = VncConnectionPool()
        mock_ws = AsyncMock()
        adapter = _make_adapter()
        client = _make_client()

        with (
            patch("figaro.services.vnc_pool.websockets.connect", new_callable=AsyncMock, return_value=mock_ws) as mock_connect,
            patch("figaro.services.vnc_pool.WsVncAdapter", return_value=adapter),
            patch("figaro.services.vnc_pool.asyncvnc.Client.create", new_callable=AsyncMock, return_value=client),
        ):
            # First acquire
            async with pool.ws_connection("wss://host:443/vnc") as c1:
                pass

            # Second acquire — should reuse
            async with pool.ws_connection("wss://host:443/vnc") as c2:
                pass

            assert c1 is c2
            # websockets.connect should only have been called once
            mock_connect.assert_awaited_once()

        await pool.close()


class TestWsEvictOnError:
    """ConnectionError inside ws_connection should evict the entry."""

    async def test_ws_evicts_on_connection_error(self):
        pool = VncConnectionPool()
        mock_ws = AsyncMock()
        adapter = _make_adapter()
        client = _make_client()
        url = "wss://host:443/vnc"

        with (
            patch("figaro.services.vnc_pool.websockets.connect", new_callable=AsyncMock, return_value=mock_ws),
            patch("figaro.services.vnc_pool.WsVncAdapter", return_value=adapter),
            patch("figaro.services.vnc_pool.asyncvnc.Client.create", new_callable=AsyncMock, return_value=client),
        ):
            with pytest.raises(ConnectionError):
                async with pool.ws_connection(url):
                    raise ConnectionError("broken")

            # Entry should be evicted
            assert url not in pool._entries
            adapter.close.assert_awaited_once()

        await pool.close()


class TestWsCloseCleanup:
    """close() should clean up WebSocket entries too."""

    async def test_close_cleans_ws_entries(self):
        pool = VncConnectionPool()
        mock_ws = AsyncMock()
        adapter = _make_adapter()
        client = _make_client()

        with (
            patch("figaro.services.vnc_pool.websockets.connect", new_callable=AsyncMock, return_value=mock_ws),
            patch("figaro.services.vnc_pool.WsVncAdapter", return_value=adapter),
            patch("figaro.services.vnc_pool.asyncvnc.Client.create", new_callable=AsyncMock, return_value=client),
        ):
            async with pool.ws_connection("wss://host:443/vnc"):
                pass

        await pool.close()

        assert len(pool._entries) == 0
        assert len(pool._locks) == 0
        adapter.close.assert_awaited_once()
