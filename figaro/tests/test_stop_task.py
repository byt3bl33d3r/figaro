"""Tests for the stop task API handler in NatsService."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from figaro.models import ClientType
from figaro.models.messages import WorkerStatus
from figaro.services import Registry, TaskManager
from figaro.services.task_manager import TaskStatus
from figaro_nats import Subjects


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

    service = NatsService(
        registry=registry,
        task_manager=task_manager,
        scheduler=mock_scheduler,
        help_request_manager=mock_help_request_manager,
        settings=mock_settings,
    )

    mock_conn = MagicMock()
    mock_conn.publish = AsyncMock()
    mock_conn.request = AsyncMock(return_value={"status": "ok"})
    mock_conn.js_publish = AsyncMock()
    mock_conn.is_connected = True
    service._conn = mock_conn

    return service


class TestApiStopTask:
    """Tests for NatsService._api_stop_task."""

    @pytest.mark.asyncio
    async def test_stop_worker_task(self, nats_service, task_manager, registry):
        """Stopping a task assigned to a worker sends stop signal and cancels."""
        # Register a worker and create + assign a task
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            status=WorkerStatus.BUSY,
        )
        task = await task_manager.create_task(prompt="Do something")
        await task_manager.assign_task(task.task_id, "worker-1")

        result = await nats_service._api_stop_task({"task_id": task.task_id})

        assert result["success"] is True
        assert result["task_id"] == task.task_id

        # Verify stop signal was sent to the worker
        nats_service.conn.publish.assert_any_call(
            Subjects.worker_stop("worker-1"), {"task_id": task.task_id}
        )

        # Verify task was cancelled
        updated_task = await task_manager.get_task(task.task_id)
        assert updated_task.status == TaskStatus.CANCELLED

        # Verify worker set to idle
        conn = await registry.get_connection("worker-1")
        assert conn.status == WorkerStatus.IDLE

        # Verify JetStream error event published
        nats_service.conn.js_publish.assert_called_once_with(
            Subjects.task_error(task.task_id),
            {
                "task_id": task.task_id,
                "error": "Task cancelled by user",
                "cancelled": True,
            },
        )

        # Verify broadcast
        nats_service.conn.publish.assert_any_call(
            Subjects.BROADCAST_TASK_CANCELLED,
            {
                "task_id": task.task_id,
                "agent_id": "worker-1",
                "agent_type": "worker",
            },
        )

    @pytest.mark.asyncio
    async def test_stop_supervisor_task(self, nats_service, task_manager, registry):
        """Stopping a task assigned to a supervisor sends stop signal via supervisor subject."""
        await registry.register(
            client_id="supervisor-1",
            client_type=ClientType.SUPERVISOR,
            status=WorkerStatus.BUSY,
        )
        task = await task_manager.create_task(prompt="Supervise something")
        await task_manager.assign_task(task.task_id, "supervisor-1")

        result = await nats_service._api_stop_task({"task_id": task.task_id})

        assert result["success"] is True

        # Verify stop signal sent to supervisor
        nats_service.conn.publish.assert_any_call(
            Subjects.supervisor_stop("supervisor-1"), {"task_id": task.task_id}
        )

        # Verify broadcast_supervisors called (supervisors list broadcast)
        nats_service.conn.publish.assert_any_call(
            Subjects.BROADCAST_SUPERVISORS,
            {
                "supervisors": [
                    {"id": "supervisor-1", "status": "idle", "capabilities": []}
                ]
            },
        )

    @pytest.mark.asyncio
    async def test_stop_task_not_found(self, nats_service):
        """Stopping a non-existent task returns error."""
        result = await nats_service._api_stop_task({"task_id": "nonexistent"})
        assert result["error"] == "Task not found"

    @pytest.mark.asyncio
    async def test_stop_task_not_running(self, nats_service, task_manager):
        """Stopping a task that is not running returns error."""
        task = await task_manager.create_task(prompt="Pending task")
        # Task is in PENDING status, not ASSIGNED or RUNNING

        result = await nats_service._api_stop_task({"task_id": task.task_id})
        assert result["error"] == "Task is not running"

    @pytest.mark.asyncio
    async def test_stop_completed_task(self, nats_service, task_manager):
        """Stopping an already completed task returns error."""
        task = await task_manager.create_task(prompt="Done task")
        await task_manager.assign_task(task.task_id, "worker-1")
        await task_manager.complete_task(task.task_id, {"result": "done"})

        result = await nats_service._api_stop_task({"task_id": task.task_id})
        assert result["error"] == "Task is not running"

    @pytest.mark.asyncio
    async def test_stop_task_missing_task_id(self, nats_service):
        """Stopping without task_id returns error."""
        result = await nats_service._api_stop_task({})
        assert result["error"] == "task_id is required"

    @pytest.mark.asyncio
    async def test_stop_task_processes_pending_queue(
        self, nats_service, task_manager, registry
    ):
        """After stopping a task, pending queue is processed."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            status=WorkerStatus.BUSY,
        )
        task = await task_manager.create_task(prompt="Running task")
        await task_manager.assign_task(task.task_id, "worker-1")

        # Queue a pending task
        pending = await task_manager.create_task(prompt="Waiting task")
        await task_manager.queue_task(pending.task_id)

        # Spy on publish_task_assignment
        nats_service.publish_task_assignment = AsyncMock()

        result = await nats_service._api_stop_task({"task_id": task.task_id})
        assert result["success"] is True

        # The pending task should have been assigned to the now-idle worker
        updated_pending = await task_manager.get_task(pending.task_id)
        assert updated_pending.status == TaskStatus.ASSIGNED


class TestHandleTaskErrorCancelledGuard:
    """Tests for the cancelled task guard in _handle_task_error."""

    @pytest.mark.asyncio
    async def test_error_skipped_for_cancelled_task(
        self, nats_service, task_manager, registry
    ):
        """When a cancelled task sends an error event, it should be ignored."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            status=WorkerStatus.BUSY,
        )
        task = await task_manager.create_task(prompt="Will be cancelled")
        await task_manager.assign_task(task.task_id, "worker-1")
        await task_manager.cancel_task(task.task_id, "Stopped by user")

        # Now simulate an error event arriving after cancellation
        await nats_service._handle_task_error(
            {
                "task_id": task.task_id,
                "error": "Process killed",
                "worker_id": "worker-1",
            }
        )

        # Task should still be CANCELLED, not FAILED
        updated = await task_manager.get_task(task.task_id)
        assert updated.status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_error_processed_for_non_cancelled_task(
        self, nats_service, task_manager, registry
    ):
        """Normal error handling proceeds for non-cancelled tasks."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            status=WorkerStatus.BUSY,
        )
        task = await task_manager.create_task(prompt="Will fail normally")
        await task_manager.assign_task(task.task_id, "worker-1")

        await nats_service._handle_task_error(
            {
                "task_id": task.task_id,
                "error": "Something broke",
                "worker_id": "worker-1",
            }
        )

        # Task should be FAILED
        updated = await task_manager.get_task(task.task_id)
        assert updated.status == TaskStatus.FAILED
