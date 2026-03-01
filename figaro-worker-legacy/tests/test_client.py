"""Tests for the NatsClient."""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from figaro_worker.worker.client import NatsClient


@pytest.fixture(autouse=True)
def mock_ensure_streams():
    with patch("figaro_worker.worker.client.ensure_streams", new_callable=AsyncMock):
        yield


class TestNatsClient:
    """Tests for NatsClient class."""

    @pytest.fixture
    def client(self):
        return NatsClient(
            nats_url="nats://localhost:4222",
            worker_id="test-worker",
            capabilities=["browser"],
            novnc_url="ws://localhost:6080/websockify",
        )

    def test_worker_id(self, client: NatsClient):
        """Test worker_id property."""
        assert client.worker_id == "test-worker"

    def test_is_connected_initially_false(self, client: NatsClient):
        """Test that client is not connected initially."""
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_success(self, client: NatsClient):
        """Test successful connection to NATS."""
        mock_conn = MagicMock()
        mock_conn.connect = AsyncMock()
        mock_conn.is_connected = True
        mock_conn.subscribe = AsyncMock(return_value=MagicMock())
        mock_conn.request = AsyncMock(return_value={"status": "ok"})
        client._conn = mock_conn

        result = await client.connect()
        await asyncio.sleep(0)  # Let background registration task run

        assert result is True
        mock_conn.connect.assert_called_once()
        # Should have subscribed to task assignment (Core NATS)
        mock_conn.subscribe.assert_called_once()
        # Should have sent registration request
        mock_conn.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_failure(self, client: NatsClient):
        """Test connection failure handling."""
        mock_conn = MagicMock()
        mock_conn.connect = AsyncMock(side_effect=Exception("Connection refused"))
        client._conn = mock_conn

        result = await client.connect()

        assert result is False

    @pytest.mark.asyncio
    async def test_register_publishes_worker_info(self, client: NatsClient):
        """Test that registration sends worker information via request/reply."""
        mock_conn = MagicMock()
        mock_conn.connect = AsyncMock()
        mock_conn.is_connected = True
        mock_conn.subscribe = AsyncMock(return_value=MagicMock())
        mock_conn.request = AsyncMock(return_value={"status": "ok"})
        client._conn = mock_conn

        await client.connect()
        await asyncio.sleep(0)  # Let background registration task run

        # Verify registration request
        request_call = mock_conn.request.call_args
        assert request_call[0][0] == "figaro.register.worker"
        payload = request_call[0][1]
        assert payload["worker_id"] == "test-worker"
        assert payload["capabilities"] == ["browser"]
        assert payload["novnc_url"] == "ws://localhost:6080/websockify"
        assert payload["status"] == "idle"

    @pytest.mark.asyncio
    async def test_publish_task_message(self, client: NatsClient):
        """Test publishing a task message."""
        mock_conn = MagicMock()
        mock_conn.js_publish = AsyncMock()
        client._conn = mock_conn

        await client.publish_task_message("task-1", {"content": "Hello"})

        mock_conn.js_publish.assert_called_once()
        subject = mock_conn.js_publish.call_args[0][0]
        payload = mock_conn.js_publish.call_args[0][1]
        assert subject == "figaro.task.task-1.message"
        assert payload["task_id"] == "task-1"
        assert payload["worker_id"] == "test-worker"
        assert payload["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_publish_task_complete(self, client: NatsClient):
        """Test publishing task completion."""
        mock_conn = MagicMock()
        mock_conn.js_publish = AsyncMock()
        client._conn = mock_conn

        await client.publish_task_complete("task-1", {"result": "Done"})

        mock_conn.js_publish.assert_called_once()
        subject = mock_conn.js_publish.call_args[0][0]
        payload = mock_conn.js_publish.call_args[0][1]
        assert subject == "figaro.task.task-1.complete"
        assert payload["task_id"] == "task-1"
        assert payload["result"] == {"result": "Done"}

    @pytest.mark.asyncio
    async def test_publish_task_error(self, client: NatsClient):
        """Test publishing task error."""
        mock_conn = MagicMock()
        mock_conn.js_publish = AsyncMock()
        client._conn = mock_conn

        await client.publish_task_error("task-1", "Something went wrong")

        mock_conn.js_publish.assert_called_once()
        subject = mock_conn.js_publish.call_args[0][0]
        payload = mock_conn.js_publish.call_args[0][1]
        assert subject == "figaro.task.task-1.error"
        assert payload["task_id"] == "task-1"
        assert payload["error"] == "Something went wrong"

    @pytest.mark.asyncio
    async def test_publish_help_request(self, client: NatsClient):
        """Test publishing a help request."""
        mock_conn = MagicMock()
        mock_conn.publish = AsyncMock()
        client._conn = mock_conn

        questions = [{"question": "What to do?"}]
        await client.publish_help_request("req-1", "task-1", questions, 300)

        mock_conn.publish.assert_called_once()
        subject = mock_conn.publish.call_args[0][0]
        payload = mock_conn.publish.call_args[0][1]
        assert subject == "figaro.help.request"
        assert payload["request_id"] == "req-1"
        assert payload["task_id"] == "task-1"
        assert payload["questions"] == questions
        assert payload["timeout_seconds"] == 300

    @pytest.mark.asyncio
    async def test_send_status(self, client: NatsClient):
        """Test sending status update."""
        mock_conn = MagicMock()
        mock_conn.publish = AsyncMock()
        client._conn = mock_conn

        await client.send_status("busy")

        mock_conn.publish.assert_called_once()
        subject = mock_conn.publish.call_args[0][0]
        payload = mock_conn.publish.call_args[0][1]
        assert subject == "figaro.heartbeat.worker.test-worker"
        assert payload["client_id"] == "test-worker"
        assert payload["status"] == "busy"

    @pytest.mark.asyncio
    async def test_send_heartbeat(self, client: NatsClient):
        """Test sending heartbeat."""
        mock_conn = MagicMock()
        mock_conn.publish = AsyncMock()
        client._conn = mock_conn

        await client.send_heartbeat()

        mock_conn.publish.assert_called_once()
        subject = mock_conn.publish.call_args[0][0]
        payload = mock_conn.publish.call_args[0][1]
        assert subject == "figaro.heartbeat.worker.test-worker"
        assert "status" not in payload

    @pytest.mark.asyncio
    async def test_heartbeat_includes_client_type(self, client: NatsClient):
        """Test that send_heartbeat includes client_type: 'worker' in its payload."""
        mock_conn = MagicMock()
        mock_conn.publish = AsyncMock()
        client._conn = mock_conn

        await client.send_heartbeat()

        mock_conn.publish.assert_called_once()
        payload = mock_conn.publish.call_args[0][1]
        assert payload["client_type"] == "worker"

    def test_on_handler_registration(self, client: NatsClient):
        """Test registering event handlers."""
        async def task_handler(payload):
            pass

        client.on("task", task_handler)

        assert "task" in client._handlers
        assert task_handler in client._handlers["task"]

    @pytest.mark.asyncio
    async def test_emit_dispatches_to_handlers(self, client: NatsClient):
        """Test that _emit dispatches events to registered handlers."""
        received = []

        async def handler(payload):
            received.append(payload)

        client.on("task", handler)
        await client._emit("task", {"task_id": "123"})

        assert len(received) == 1
        assert received[0]["task_id"] == "123"

    @pytest.mark.asyncio
    async def test_handle_task_emits_event(self, client: NatsClient):
        """Test that _handle_task emits task event."""
        received = []

        async def handler(payload):
            received.append(payload)

        client.on("task", handler)
        await client._handle_task({"task_id": "123", "prompt": "Do something"})

        assert len(received) == 1
        assert received[0]["task_id"] == "123"

    def test_stop(self, client: NatsClient):
        """Test stopping the client."""
        client._running = True
        client.stop()
        assert client._running is False

    @pytest.mark.asyncio
    async def test_close_publishes_deregister(self, client: NatsClient):
        """Test that close publishes deregistration and closes connection."""
        mock_conn = MagicMock()
        mock_conn.publish = AsyncMock()
        mock_conn.close = AsyncMock()
        client._conn = mock_conn
        client._running = True

        await client.close()

        assert client._running is False
        # Should publish deregister
        deregister_call = mock_conn.publish.call_args
        assert "deregister" in deregister_call[0][0]
        assert deregister_call[0][1]["client_id"] == "test-worker"
        mock_conn.close.assert_called_once()
