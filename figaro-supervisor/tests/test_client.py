"""Tests for figaro_supervisor.supervisor.client module."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from figaro_supervisor.supervisor.client import SupervisorNatsClient

# Patch ensure_streams globally for all tests in this module
pytestmark = pytest.mark.usefixtures("mock_ensure_streams")


@pytest.fixture(autouse=True)
def mock_ensure_streams():
    with patch("figaro_supervisor.supervisor.client.ensure_streams", new_callable=AsyncMock):
        yield


class TestSupervisorNatsClientInit:
    """Tests for SupervisorNatsClient initialization."""

    def test_default_initialization(self):
        """Test default initialization values."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        assert client._nats_url == "nats://localhost:4222"
        assert client.supervisor_id == "test-supervisor"
        assert client._capabilities == ["task_processing"]
        assert client._running is False
        assert client._handlers == {}
        assert client._subscriptions == []

    def test_custom_initialization(self):
        """Test initialization with custom values."""
        client = SupervisorNatsClient(
            nats_url="nats://custom:4222",
            supervisor_id="custom-supervisor",
            capabilities=["custom_capability"],
        )

        assert client._nats_url == "nats://custom:4222"
        assert client.supervisor_id == "custom-supervisor"
        assert client._capabilities == ["custom_capability"]


class TestSupervisorNatsClientEventHandlers:
    """Tests for event handler registration."""

    def test_on_registers_handler(self):
        """Test that on() registers handlers correctly."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        async def task_handler(payload):
            pass

        client.on("task", task_handler)

        assert "task" in client._handlers
        assert task_handler in client._handlers["task"]

    def test_on_appends_multiple_handlers(self):
        """Test that registering multiple handlers appends them."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        async def handler1(payload):
            pass

        async def handler2(payload):
            pass

        client.on("task", handler1)
        client.on("task", handler2)

        assert len(client._handlers["task"]) == 2
        assert handler1 in client._handlers["task"]
        assert handler2 in client._handlers["task"]


class TestSupervisorNatsClientConnect:
    """Tests for connection functionality."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful connection to NATS."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        mock_conn = MagicMock()
        mock_conn.connect = AsyncMock()
        mock_conn.subscribe = AsyncMock(return_value=MagicMock())
        mock_conn.js_subscribe = AsyncMock(return_value=MagicMock())
        mock_conn.request = AsyncMock(return_value={"status": "ok"})
        mock_conn.is_connected = True
        client._conn = mock_conn

        result = await client.connect()
        await asyncio.sleep(0)  # Let background registration task run

        assert result is True
        mock_conn.connect.assert_called_once()
        mock_conn.request.assert_called_once()  # Registration

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test connection failure handling."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        mock_conn = MagicMock()
        mock_conn.connect = AsyncMock(side_effect=ConnectionRefusedError("Connection refused"))
        client._conn = mock_conn

        result = await client.connect()

        assert result is False


class TestSupervisorNatsClientPublish:
    """Tests for publish methods."""

    @pytest.mark.asyncio
    async def test_publish_task_message(self):
        """Test publishing task message via JetStream."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        mock_conn = MagicMock()
        mock_conn.js_publish = AsyncMock()
        client._conn = mock_conn

        await client.publish_task_message("task-123", {"text": "hello"})

        mock_conn.js_publish.assert_called_once()
        call_args = mock_conn.js_publish.call_args
        assert "figaro.task.task-123.message" in call_args[0][0]
        payload = call_args[0][1]
        assert payload["task_id"] == "task-123"
        assert payload["supervisor_id"] == "test-supervisor"
        assert payload["text"] == "hello"

    @pytest.mark.asyncio
    async def test_publish_task_complete(self):
        """Test publishing task completion via JetStream."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        mock_conn = MagicMock()
        mock_conn.js_publish = AsyncMock()
        client._conn = mock_conn

        await client.publish_task_complete("task-123", {"data": "result"})

        mock_conn.js_publish.assert_called_once()
        call_args = mock_conn.js_publish.call_args
        assert "figaro.task.task-123.complete" in call_args[0][0]
        payload = call_args[0][1]
        assert payload["task_id"] == "task-123"
        assert payload["result"] == {"data": "result"}

    @pytest.mark.asyncio
    async def test_publish_task_error(self):
        """Test publishing task error via JetStream."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        mock_conn = MagicMock()
        mock_conn.js_publish = AsyncMock()
        client._conn = mock_conn

        await client.publish_task_error("task-123", "Something went wrong")

        mock_conn.js_publish.assert_called_once()
        call_args = mock_conn.js_publish.call_args
        assert "figaro.task.task-123.error" in call_args[0][0]
        payload = call_args[0][1]
        assert payload["error"] == "Something went wrong"

    @pytest.mark.asyncio
    async def test_send_status(self):
        """Test send_status publishes heartbeat."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        mock_conn = MagicMock()
        mock_conn.publish = AsyncMock()
        client._conn = mock_conn

        await client.send_status("busy")

        mock_conn.publish.assert_called_once()
        call_args = mock_conn.publish.call_args
        assert "figaro.heartbeat.supervisor.test-supervisor" in call_args[0][0]
        payload = call_args[0][1]
        assert payload["status"] == "busy"

    @pytest.mark.asyncio
    async def test_send_heartbeat(self):
        """Test send_heartbeat publishes liveness ping with current status."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        mock_conn = MagicMock()
        mock_conn.publish = AsyncMock()
        client._conn = mock_conn

        await client.send_heartbeat()

        mock_conn.publish.assert_called_once()
        call_args = mock_conn.publish.call_args
        payload = call_args[0][1]
        assert payload["status"] == "idle"
        assert payload["client_type"] == "supervisor"

    @pytest.mark.asyncio
    async def test_publish_help_request(self):
        """Test publishing help request."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        mock_conn = MagicMock()
        mock_conn.publish = AsyncMock()
        client._conn = mock_conn

        questions = [{"question": "What color?"}]
        await client.publish_help_request("req-123", "task-456", questions, 300)

        mock_conn.publish.assert_called_once()
        call_args = mock_conn.publish.call_args
        assert call_args[0][0] == "figaro.help.request"
        payload = call_args[0][1]
        assert payload["request_id"] == "req-123"
        assert payload["task_id"] == "task-456"
        assert payload["questions"] == questions


class TestSupervisorNatsClientEmit:
    """Tests for event emission."""

    @pytest.mark.asyncio
    async def test_emit_calls_registered_handlers(self):
        """Test that _emit calls all registered handlers."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        received = []

        async def handler1(payload):
            received.append(("h1", payload))

        async def handler2(payload):
            received.append(("h2", payload))

        client.on("task", handler1)
        client.on("task", handler2)

        await client._emit("task", {"task_id": "123"})

        assert len(received) == 2
        assert received[0] == ("h1", {"task_id": "123"})
        assert received[1] == ("h2", {"task_id": "123"})

    @pytest.mark.asyncio
    async def test_emit_handles_handler_exceptions(self):
        """Test that _emit handles exceptions in handlers gracefully."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        async def failing_handler(payload):
            raise RuntimeError("Handler failed")

        client.on("task", failing_handler)

        # Should not raise
        await client._emit("task", {"task_id": "123"})

    @pytest.mark.asyncio
    async def test_emit_no_handlers(self):
        """Test that _emit handles missing event handlers gracefully."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        # Should not raise
        await client._emit("nonexistent_event", {"data": "test"})


class TestSupervisorNatsClientRequestHelp:
    """Tests for help request functionality."""

    @pytest.mark.asyncio
    async def test_request_help_success(self):
        """Test successful help request."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        mock_sub = MagicMock()
        mock_sub.unsubscribe = AsyncMock()

        mock_conn = MagicMock()
        mock_conn.publish = AsyncMock()

        # When subscribe is called, simulate an immediate response
        async def mock_subscribe(subject, handler, **kwargs):
            # Simulate the response arriving
            async def send_response():
                await asyncio.sleep(0.01)
                await handler({
                    "request_id": "req-123",
                    "answers": {"What color?": "Blue"},
                })
            asyncio.create_task(send_response())
            return mock_sub

        mock_conn.subscribe = mock_subscribe
        client._conn = mock_conn

        questions = [{"question": "What color?", "options": ["Red", "Blue"]}]

        result = await client.request_help(
            request_id="req-123",
            task_id="task-456",
            questions=questions,
            timeout_seconds=1,
        )

        assert result == {"What color?": "Blue"}

    @pytest.mark.asyncio
    async def test_request_help_timeout(self):
        """Test help request timeout."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        mock_sub = MagicMock()
        mock_sub.unsubscribe = AsyncMock()

        mock_conn = MagicMock()
        mock_conn.publish = AsyncMock()
        mock_conn.subscribe = AsyncMock(return_value=mock_sub)
        client._conn = mock_conn

        questions = [{"question": "What color?"}]

        result = await client.request_help(
            request_id="req-123",
            task_id="task-456",
            questions=questions,
            timeout_seconds=1,
        )

        assert result is None


class TestSupervisorNatsClientStop:
    """Tests for stopping the client."""

    def test_stop_sets_running_false(self):
        """Test that stop() sets _running to False."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )
        client._running = True

        client.stop()

        assert client._running is False

    @pytest.mark.asyncio
    async def test_close_publishes_deregister(self):
        """Test that close() publishes deregister and closes connection."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )
        client._running = True

        mock_conn = MagicMock()
        mock_conn.publish = AsyncMock()
        mock_conn.close = AsyncMock()
        client._conn = mock_conn

        await client.close()

        assert client._running is False
        # Should have published deregister
        mock_conn.publish.assert_called_once()
        call_args = mock_conn.publish.call_args
        assert "deregister" in call_args[0][0]
        # Should have closed connection
        mock_conn.close.assert_called_once()


class TestSupervisorNatsClientRun:
    """Tests for the main run loop."""

    @pytest.mark.asyncio
    async def test_run_loop_checks_connection(self):
        """Test that run() loop checks connection status."""
        client = SupervisorNatsClient(
            nats_url="nats://localhost:4222",
            supervisor_id="test-supervisor",
        )

        mock_conn = MagicMock()
        mock_conn.is_connected = True
        client._conn = mock_conn

        # Stop after first iteration
        iteration_count = 0

        original_sleep = asyncio.sleep

        async def mock_sleep(seconds):
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count >= 2:
                client._running = False
            await original_sleep(0.001)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            await client.run()

        assert iteration_count >= 2
