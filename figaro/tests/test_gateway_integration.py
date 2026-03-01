"""Tests for orchestrator gateway integration (task creation + result routing)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from figaro.models import ClientType
from figaro.models.messages import WorkerStatus
from figaro.services import Registry, TaskManager


@pytest.fixture
def registry():
    return Registry()


@pytest.fixture
def task_manager():
    return TaskManager()


@pytest.fixture
def mock_scheduler():
    scheduler = MagicMock()
    scheduler.get_scheduled_task = AsyncMock()
    return scheduler


@pytest.fixture
def mock_help_request_manager():
    return MagicMock()


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.nats_url = "nats://localhost:4222"
    settings.nats_ws_url = "ws://localhost:8443"
    settings.self_healing_enabled = False
    settings.self_healing_max_retries = 2
    return settings


@pytest.fixture
def nats_service(
    registry, task_manager, mock_scheduler, mock_help_request_manager, mock_settings
):
    """Create a real NatsService with mocked external dependencies."""
    from figaro.services.nats_service import NatsService

    mock_sf = MagicMock()

    service = NatsService(
        registry=registry,
        task_manager=task_manager,
        scheduler=mock_scheduler,
        help_request_manager=mock_help_request_manager,
        settings=mock_settings,
        session_factory=mock_sf,
    )

    # Mock the NATS connection so publish methods work
    mock_conn = MagicMock()
    mock_conn.publish = AsyncMock()
    mock_conn.js_publish = AsyncMock()
    mock_conn.request = AsyncMock(return_value={"status": "ok"})
    mock_conn.is_connected = True
    service._conn = mock_conn

    return service


# ── _handle_gateway_task tests ─────────────────────────────────


class TestHandleGatewayTask:
    """Tests for NatsService._handle_gateway_task."""

    @pytest.mark.asyncio
    async def test_gateway_task_reads_text_field(
        self, nats_service, task_manager, registry
    ):
        """When a gateway sends data with 'text' key, the task is created
        with that value as the prompt."""

        # Register an idle supervisor so the task gets assigned
        await registry.register(
            client_id="supervisor-1",
            client_type=ClientType.SUPERVISOR,
            status=WorkerStatus.IDLE,
        )
        nats_service.publish_supervisor_task = AsyncMock()

        data = {
            "text": "Search for flights to Paris",
            "channel": "telegram",
            "chat_id": 12345,
        }

        await nats_service._handle_gateway_task(data)

        all_tasks = await task_manager.get_all_tasks()
        assert len(all_tasks) == 1
        assert all_tasks[0].prompt == "Search for flights to Paris"

    @pytest.mark.asyncio
    async def test_gateway_task_stores_source_metadata(
        self, nats_service, task_manager, registry
    ):
        """The created task stores channel and chat_id in source_metadata."""

        await registry.register(
            client_id="supervisor-1",
            client_type=ClientType.SUPERVISOR,
            status=WorkerStatus.IDLE,
        )
        nats_service.publish_supervisor_task = AsyncMock()

        data = {
            "text": "Do something",
            "channel": "telegram",
            "chat_id": 67890,
        }

        await nats_service._handle_gateway_task(data)

        all_tasks = await task_manager.get_all_tasks()
        assert len(all_tasks) == 1
        task = all_tasks[0]
        assert task.source_metadata["channel"] == "telegram"
        assert task.source_metadata["chat_id"] == 67890

    @pytest.mark.asyncio
    async def test_gateway_task_falls_back_to_prompt_field(
        self, nats_service, task_manager, registry
    ):
        """When data has 'prompt' but no 'text', prompt is used as fallback."""

        await registry.register(
            client_id="supervisor-1",
            client_type=ClientType.SUPERVISOR,
            status=WorkerStatus.IDLE,
        )
        nats_service.publish_supervisor_task = AsyncMock()

        data = {
            "prompt": "Book a hotel in London",
            "channel": "telegram",
            "chat_id": 11111,
        }

        await nats_service._handle_gateway_task(data)

        all_tasks = await task_manager.get_all_tasks()
        assert len(all_tasks) == 1
        assert all_tasks[0].prompt == "Book a hotel in London"


# ── _handle_task_complete gateway routing tests ────────────────


class TestHandleTaskCompleteGatewayRouting:
    """Tests for gateway result routing in NatsService._handle_task_complete."""

    @pytest.mark.asyncio
    async def test_complete_sends_result_to_gateway(
        self, nats_service, task_manager, registry
    ):
        """When a gateway-sourced task completes, the result is published
        back to the originating channel with the correct chat_id and text."""

        # Create a gateway task with source_metadata
        task = await task_manager.create_task(
            prompt="Search for flights",
            source="gateway",
            source_metadata={"channel": "telegram", "chat_id": 12345},
        )

        # Register a worker so _process_pending_queue doesn't fail
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            status=WorkerStatus.IDLE,
        )

        # Spy on publish_gateway_send
        nats_service.publish_gateway_send = AsyncMock()

        # Simulate task completion
        await nats_service._handle_task_complete({
            "task_id": task.task_id,
            "result": "Found 3 flights to Paris starting at $299",
            "worker_id": "worker-1",
        })

        nats_service.publish_gateway_send.assert_called_once_with(
            "telegram",
            {"chat_id": 12345, "text": "Found 3 flights to Paris starting at $299"},
        )

    @pytest.mark.asyncio
    async def test_complete_extracts_result_from_dict(
        self, nats_service, task_manager, registry
    ):
        """When result is a dict with '__type__': 'ResultMessage', only the
        'result' value is extracted and sent to the gateway."""

        task = await task_manager.create_task(
            prompt="Look up the weather",
            source="gateway",
            source_metadata={"channel": "telegram", "chat_id": 99999},
        )

        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            status=WorkerStatus.IDLE,
        )

        nats_service.publish_gateway_send = AsyncMock()

        result_dict = {
            "__type__": "ResultMessage",
            "result": "Sunny, 72F in San Francisco",
            "session_id": "sess-abc",
        }

        await nats_service._handle_task_complete({
            "task_id": task.task_id,
            "result": result_dict,
            "worker_id": "worker-1",
        })

        nats_service.publish_gateway_send.assert_called_once_with(
            "telegram",
            {"chat_id": 99999, "text": "Sunny, 72F in San Francisco"},
        )

    @pytest.mark.asyncio
    async def test_complete_handles_string_result(
        self, nats_service, task_manager, registry
    ):
        """When result is a plain string, it is sent as-is to the gateway."""

        task = await task_manager.create_task(
            prompt="Check stock price",
            source="gateway",
            source_metadata={"channel": "telegram", "chat_id": 55555},
        )

        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            status=WorkerStatus.IDLE,
        )

        nats_service.publish_gateway_send = AsyncMock()

        await nats_service._handle_task_complete({
            "task_id": task.task_id,
            "result": "AAPL is at $185.50",
            "worker_id": "worker-1",
        })

        nats_service.publish_gateway_send.assert_called_once_with(
            "telegram",
            {"chat_id": 55555, "text": "AAPL is at $185.50"},
        )

    @pytest.mark.asyncio
    async def test_complete_no_gateway_send_for_non_gateway_tasks(
        self, nats_service, task_manager, registry
    ):
        """Tasks with source='api' should NOT trigger a gateway send."""

        task = await task_manager.create_task(
            prompt="Run a report",
            source="api",
        )

        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            status=WorkerStatus.IDLE,
        )

        nats_service.publish_gateway_send = AsyncMock()

        await nats_service._handle_task_complete({
            "task_id": task.task_id,
            "result": "Report generated",
            "worker_id": "worker-1",
        })

        nats_service.publish_gateway_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_complete_no_gateway_send_without_channel_metadata(
        self, nats_service, task_manager, registry
    ):
        """A gateway task missing 'channel' in source_metadata should NOT
        trigger a gateway send."""

        task = await task_manager.create_task(
            prompt="Do something",
            source="gateway",
            source_metadata={"chat_id": 12345},  # no "channel" key
        )

        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            status=WorkerStatus.IDLE,
        )

        nats_service.publish_gateway_send = AsyncMock()

        await nats_service._handle_task_complete({
            "task_id": task.task_id,
            "result": "Done",
            "worker_id": "worker-1",
        })

        nats_service.publish_gateway_send.assert_not_called()


# ── publish_supervisor_task payload tests ─────────────────────


class TestPublishSupervisorTaskPayload:
    """Tests for NatsService.publish_supervisor_task payload contents."""

    @pytest.mark.asyncio
    async def test_publish_supervisor_task_includes_source_and_source_metadata(
        self, nats_service, task_manager
    ):
        """publish_supervisor_task must include source and source_metadata
        in the payload sent to the supervisor via NATS request/reply."""

        task = await task_manager.create_task(
            prompt="Search for flights to Paris",
            source="gateway",
            source_metadata={"channel": "telegram", "chat_id": "123"},
        )

        await nats_service.publish_supervisor_task("supervisor-1", task)

        # The method now uses conn.request (request/reply) to verify the
        # supervisor is alive.  Extract the request call.
        mock_conn = nats_service._conn
        supervisor_call = mock_conn.request.call_args
        subject = supervisor_call[0][0]
        payload = supervisor_call[0][1]

        assert subject == "figaro.supervisor.supervisor-1.task"
        assert payload["task_id"] == task.task_id
        assert payload["prompt"] == "Search for flights to Paris"
        assert payload["source"] == "gateway"
        assert payload["source_metadata"] == {"channel": "telegram", "chat_id": "123"}

    @pytest.mark.asyncio
    async def test_publish_supervisor_task_includes_default_source(
        self, nats_service, task_manager
    ):
        """publish_supervisor_task includes the default source='api' and
        empty source_metadata when no explicit values are provided."""

        task = await task_manager.create_task(
            prompt="Run a report",
        )

        await nats_service.publish_supervisor_task("supervisor-2", task)

        mock_conn = nats_service._conn
        supervisor_call = mock_conn.request.call_args
        payload = supervisor_call[0][1]
        assert payload["source"] == "api"
        assert payload["source_metadata"] == {}
