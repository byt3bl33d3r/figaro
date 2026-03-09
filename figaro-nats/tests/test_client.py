"""Tests for NatsConnection with mocked nats client."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from figaro_nats.client import NatsConnection, _subscribe_cb, _subscribe_request_cb, _js_subscribe_cb


@pytest.fixture
def conn() -> NatsConnection:
    """Create a NatsConnection instance (not connected)."""
    return NatsConnection(url="nats://test:4222", name="test-client")


@pytest.fixture
def mock_nc() -> AsyncMock:
    """Create a mock nats client."""
    nc = AsyncMock()
    nc.is_closed = False
    nc.is_connected = True
    nc.connected_url = "nats://test:4222"
    nc.jetstream.return_value = AsyncMock()
    return nc


@pytest.fixture
def connected_conn(conn: NatsConnection, mock_nc: AsyncMock) -> NatsConnection:
    """Create a connected NatsConnection with mocked internals."""
    conn._nc = mock_nc
    conn._js = mock_nc.jetstream.return_value
    return conn


class TestConnectClose:
    """Test connect/close lifecycle."""

    @pytest.mark.asyncio
    async def test_connect_establishes_connection(self, conn: NatsConnection) -> None:
        mock_nc = AsyncMock()
        mock_nc.is_closed = False
        mock_nc.is_connected = True
        mock_nc.jetstream.return_value = AsyncMock()

        with patch(
            "figaro_nats.client.nats.connect", return_value=mock_nc
        ) as mock_connect:
            await conn.connect()

            mock_connect.assert_called_once()
            assert conn.is_connected is True
            assert conn._nc is mock_nc
            assert conn._js is not None

    @pytest.mark.asyncio
    async def test_close_drains_connection(
        self, connected_conn: NatsConnection
    ) -> None:
        nc = connected_conn._nc
        assert nc is not None
        nc.is_closed = False

        await connected_conn.close()

        nc.drain.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_noop_when_already_closed(
        self, connected_conn: NatsConnection
    ) -> None:
        nc = connected_conn._nc
        assert nc is not None
        nc.is_closed = True

        await connected_conn.close()

        nc.drain.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_noop_when_no_connection(self, conn: NatsConnection) -> None:
        # Should not raise
        await conn.close()

    def test_nc_property_raises_when_not_connected(self, conn: NatsConnection) -> None:
        with pytest.raises(RuntimeError, match="NATS connection not established"):
            _ = conn.nc

    def test_js_property_raises_when_not_connected(self, conn: NatsConnection) -> None:
        with pytest.raises(RuntimeError, match="JetStream not available"):
            _ = conn.js

    def test_is_connected_false_initially(self, conn: NatsConnection) -> None:
        assert conn.is_connected is False


class TestPublish:
    """Test publish serializes JSON."""

    @pytest.mark.asyncio
    async def test_publish_sends_json(self, connected_conn: NatsConnection) -> None:
        data = {"type": "test", "value": 42}

        await connected_conn.publish("test.subject", data)

        connected_conn.nc.publish.assert_called_once()
        call_args = connected_conn.nc.publish.call_args
        assert call_args[0][0] == "test.subject"
        assert call_args[0][1] == json.dumps(data).encode()
        assert "headers" in call_args[1]

    @pytest.mark.asyncio
    async def test_publish_sends_empty_dict_when_no_data(
        self, connected_conn: NatsConnection
    ) -> None:
        await connected_conn.publish("test.subject")

        connected_conn.nc.publish.assert_called_once()
        call_args = connected_conn.nc.publish.call_args
        assert call_args[0][0] == "test.subject"
        assert call_args[0][1] == json.dumps({}).encode()

    @pytest.mark.asyncio
    async def test_publish_none_data(self, connected_conn: NatsConnection) -> None:
        await connected_conn.publish("test.subject", None)

        connected_conn.nc.publish.assert_called_once()
        call_args = connected_conn.nc.publish.call_args
        assert call_args[0][0] == "test.subject"
        assert call_args[0][1] == json.dumps({}).encode()


class TestSubscribe:
    """Test subscribe deserializes JSON and calls handler."""

    @pytest.mark.asyncio
    async def test_subscribe_registers_callback(
        self, connected_conn: NatsConnection
    ) -> None:
        handler = AsyncMock()

        await connected_conn.subscribe("test.subject", handler)

        connected_conn.nc.subscribe.assert_called_once()
        call_kwargs = connected_conn.nc.subscribe.call_args
        assert call_kwargs[0][0] == "test.subject"

    @pytest.mark.asyncio
    async def test_subscribe_with_queue_group(
        self, connected_conn: NatsConnection
    ) -> None:
        handler = AsyncMock()

        await connected_conn.subscribe("test.subject", handler, queue="workers")

        connected_conn.nc.subscribe.assert_called_once()
        call_kwargs = connected_conn.nc.subscribe.call_args
        assert call_kwargs[1]["queue"] == "workers"

    @pytest.mark.asyncio
    async def test_subscribe_callback_deserializes_json(
        self, connected_conn: NatsConnection
    ) -> None:
        handler = AsyncMock()
        captured_cb = None

        async def fake_subscribe(
            subject: str, queue: str | None = None, cb: object = None
        ) -> MagicMock:
            nonlocal captured_cb
            captured_cb = cb
            return MagicMock()

        connected_conn.nc.subscribe = fake_subscribe

        await connected_conn.subscribe("test.subject", handler)

        assert captured_cb is not None

        # Simulate a message
        msg = MagicMock()
        msg.data = json.dumps({"key": "value"}).encode()

        await captured_cb(msg)

        handler.assert_called_once_with({"key": "value"})

    @pytest.mark.asyncio
    async def test_subscribe_callback_handles_empty_data(
        self, connected_conn: NatsConnection
    ) -> None:
        handler = AsyncMock()
        captured_cb = None

        async def fake_subscribe(
            subject: str, queue: str | None = None, cb: object = None
        ) -> MagicMock:
            nonlocal captured_cb
            captured_cb = cb
            return MagicMock()

        connected_conn.nc.subscribe = fake_subscribe

        await connected_conn.subscribe("test.subject", handler)

        msg = MagicMock()
        msg.data = b""

        await captured_cb(msg)

        handler.assert_called_once_with({})

    @pytest.mark.asyncio
    async def test_subscribe_callback_handles_handler_exception(
        self, connected_conn: NatsConnection
    ) -> None:
        handler = AsyncMock(side_effect=ValueError("boom"))
        captured_cb = None

        async def fake_subscribe(
            subject: str, queue: str | None = None, cb: object = None
        ) -> MagicMock:
            nonlocal captured_cb
            captured_cb = cb
            return MagicMock()

        connected_conn.nc.subscribe = fake_subscribe

        await connected_conn.subscribe("test.subject", handler)

        msg = MagicMock()
        msg.data = json.dumps({"key": "value"}).encode()

        # Should not raise, error is logged
        await captured_cb(msg)


class TestJsPublish:
    """Test js_publish goes through JetStream."""

    @pytest.mark.asyncio
    async def test_js_publish_sends_via_jetstream(
        self, connected_conn: NatsConnection
    ) -> None:
        data = {"task_id": "t1", "status": "assigned"}

        await connected_conn.js_publish("figaro.task.t1.assigned", data)

        connected_conn.js.publish.assert_called_once()
        call_args = connected_conn.js.publish.call_args
        assert call_args[0][0] == "figaro.task.t1.assigned"
        assert call_args[0][1] == json.dumps(data).encode()
        assert "headers" in call_args[1]

    @pytest.mark.asyncio
    async def test_js_publish_empty_data(self, connected_conn: NatsConnection) -> None:
        await connected_conn.js_publish("figaro.task.t1.assigned")

        connected_conn.js.publish.assert_called_once()
        call_args = connected_conn.js.publish.call_args
        assert call_args[0][0] == "figaro.task.t1.assigned"
        assert call_args[0][1] == json.dumps({}).encode()


class TestRequest:
    """Test request/reply pattern."""

    @pytest.mark.asyncio
    async def test_request_sends_and_receives(
        self, connected_conn: NatsConnection
    ) -> None:
        response_msg = MagicMock()
        response_msg.data = json.dumps({"status": "ok"}).encode()
        connected_conn.nc.request.return_value = response_msg

        result = await connected_conn.request("test.subject", {"query": "data"})

        connected_conn.nc.request.assert_called_once()
        call_args = connected_conn.nc.request.call_args
        assert call_args[0][0] == "test.subject"
        assert call_args[0][1] == json.dumps({"query": "data"}).encode()
        assert call_args[1]["timeout"] == 10.0
        assert "headers" in call_args[1]
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_request_with_custom_timeout(
        self, connected_conn: NatsConnection
    ) -> None:
        response_msg = MagicMock()
        response_msg.data = json.dumps({}).encode()
        connected_conn.nc.request.return_value = response_msg

        await connected_conn.request("test.subject", timeout=10.0)

        connected_conn.nc.request.assert_called_once()
        call_args = connected_conn.nc.request.call_args
        assert call_args[0][0] == "test.subject"
        assert call_args[1]["timeout"] == 10.0

    @pytest.mark.asyncio
    async def test_request_with_empty_response(
        self, connected_conn: NatsConnection
    ) -> None:
        response_msg = MagicMock()
        response_msg.data = b""
        connected_conn.nc.request.return_value = response_msg

        result = await connected_conn.request("test.subject")

        assert result == {}


class TestErrorHandling:
    """Test error handling in callbacks."""

    def test_nc_property_raises_when_closed(self) -> None:
        conn = NatsConnection()
        mock_nc = MagicMock()
        mock_nc.is_closed = True
        conn._nc = mock_nc

        with pytest.raises(RuntimeError, match="NATS connection not established"):
            _ = conn.nc

    @pytest.mark.asyncio
    async def test_connect_passes_reconnect_options(self) -> None:
        conn = NatsConnection(url="nats://myhost:4222", name="my-service")

        with patch(
            "figaro_nats.client.nats.connect", new_callable=AsyncMock
        ) as mock_connect:
            mock_nc = AsyncMock()
            mock_nc.is_closed = False
            mock_nc.jetstream.return_value = AsyncMock()
            mock_connect.return_value = mock_nc

            await conn.connect()

            call_kwargs = mock_connect.call_args
            assert call_kwargs[0][0] == "nats://myhost:4222"
            assert call_kwargs[1]["name"] == "my-service"
            assert call_kwargs[1]["max_reconnect_attempts"] == -1
            assert call_kwargs[1]["reconnect_time_wait"] == 2

    @pytest.mark.asyncio
    async def test_subscribe_callback_records_error_on_span(self) -> None:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        with patch("figaro_nats.client._tracer", provider.get_tracer("test")):
            handler = AsyncMock(side_effect=ValueError("boom"))
            msg = MagicMock()
            msg.data = json.dumps({"key": "value"}).encode()
            msg.headers = None

            await _subscribe_cb(msg, handler=handler, subject="test.subject")

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.status.status_code == StatusCode.ERROR
        assert "boom" in span.status.description
        events = [e for e in span.events if e.name == "exception"]
        assert len(events) >= 1

    @pytest.mark.asyncio
    async def test_subscribe_request_callback_records_error_on_span(self) -> None:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        with patch("figaro_nats.client._tracer", provider.get_tracer("test")):
            handler = AsyncMock(side_effect=ValueError("boom"))
            msg = MagicMock()
            msg.data = json.dumps({"key": "value"}).encode()
            msg.headers = None
            msg.respond = AsyncMock()

            await _subscribe_request_cb(msg, handler=handler, subject="test.subject")

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.status.status_code == StatusCode.ERROR
        assert "boom" in span.status.description
        # Error response should still be sent
        msg.respond.assert_called_once()
        resp_data = json.loads(msg.respond.call_args[0][0].decode())
        assert "error" in resp_data

    @pytest.mark.asyncio
    async def test_js_subscribe_callback_records_error_on_span(self) -> None:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        with patch("figaro_nats.client._tracer", provider.get_tracer("test")):
            handler = AsyncMock(side_effect=ValueError("boom"))
            msg = MagicMock()
            msg.data = json.dumps({"key": "value"}).encode()
            msg.headers = None
            msg.ack = AsyncMock()
            msg.nak = AsyncMock()

            await _js_subscribe_cb(msg, handler=handler, subject="test.subject")

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.status.status_code == StatusCode.ERROR
        assert "boom" in span.status.description
        # NAK should be called, not ACK
        msg.ack.assert_not_called()
        msg.nak.assert_called_once()
