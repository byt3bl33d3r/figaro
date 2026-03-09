"""Tests for the SchedulerService."""

import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from figaro.models.messages import ClientType
from figaro.services.scheduler import SchedulerService


@pytest.fixture
def mock_nats_service():
    """Create a mock NatsService for scheduler tests."""
    service = MagicMock()
    service.publish_task_assignment = AsyncMock()
    service.broadcast_workers = AsyncMock()

    mock_conn = MagicMock()
    mock_conn.publish = AsyncMock()
    mock_conn.is_connected = True
    service.conn = mock_conn

    return service


@pytest.fixture
def scheduler(task_manager, registry, session_factory, mock_nats_service):
    """Create a SchedulerService instance with DB session."""
    sched = SchedulerService(
        task_manager=task_manager,
        registry=registry,
        session_factory=session_factory,
    )
    sched.set_nats_service(mock_nats_service)
    return sched


class TestSchedulerServiceCRUD:
    """Tests for CRUD operations on scheduled tasks."""

    @pytest.mark.asyncio
    async def test_create_scheduled_task(self, scheduler):
        """Test creating a scheduled task."""
        task = await scheduler.create_scheduled_task(
            name="Test Task",
            prompt="Do something",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        assert task.name == "Test Task"
        assert task.prompt == "Do something"
        assert task.start_url == "https://example.com"
        assert task.interval_seconds == 3600
        assert task.enabled is True
        assert task.run_count == 0

    @pytest.mark.asyncio
    async def test_create_scheduled_task_with_options(self, scheduler):
        """Test creating a scheduled task with custom options."""
        task = await scheduler.create_scheduled_task(
            name="Custom Task",
            prompt="Custom prompt",
            start_url="https://example.com",
            interval_seconds=1800,
            options={"key": "value"},
        )

        assert task.options == {"key": "value"}
        assert task.interval_seconds == 1800

    @pytest.mark.asyncio
    async def test_get_scheduled_task(self, scheduler):
        """Test getting a scheduled task by ID."""
        created = await scheduler.create_scheduled_task(
            name="Test Task",
            prompt="Do something",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        retrieved = await scheduler.get_scheduled_task(created.schedule_id)
        assert retrieved is not None
        assert retrieved.schedule_id == created.schedule_id
        assert retrieved.name == "Test Task"

    @pytest.mark.asyncio
    async def test_get_scheduled_task_nonexistent(self, scheduler):
        """Test getting a nonexistent scheduled task."""
        result = await scheduler.get_scheduled_task("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_scheduled_tasks(self, scheduler):
        """Test getting all scheduled tasks."""
        await scheduler.create_scheduled_task(
            name="Task 1",
            prompt="Prompt 1",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await scheduler.create_scheduled_task(
            name="Task 2",
            prompt="Prompt 2",
            start_url="https://example.com",
            interval_seconds=1800,
        )

        tasks = await scheduler.get_all_scheduled_tasks()
        assert len(tasks) == 2
        names = {t.name for t in tasks}
        assert names == {"Task 1", "Task 2"}

    @pytest.mark.asyncio
    async def test_update_scheduled_task(self, scheduler):
        """Test updating a scheduled task."""
        task = await scheduler.create_scheduled_task(
            name="Original",
            prompt="Original prompt",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        updated = await scheduler.update_scheduled_task(
            task.schedule_id, name="Updated", prompt="Updated prompt"
        )

        assert updated is not None
        assert updated.name == "Updated"
        assert updated.prompt == "Updated prompt"

    @pytest.mark.asyncio
    async def test_update_scheduled_task_nonexistent(self, scheduler):
        """Test updating a nonexistent scheduled task."""
        result = await scheduler.update_scheduled_task("nonexistent-id", name="Updated")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_scheduled_task_partial_update(self, scheduler):
        """Test partial update preserves other fields."""
        task = await scheduler.create_scheduled_task(
            name="Original",
            prompt="Original prompt",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        updated = await scheduler.update_scheduled_task(
            task.schedule_id, name="Updated"
        )

        assert updated is not None
        assert updated.name == "Updated"
        assert updated.prompt == "Original prompt"

    @pytest.mark.asyncio
    async def test_delete_scheduled_task(self, scheduler):
        """Test deleting a scheduled task."""
        task = await scheduler.create_scheduled_task(
            name="To Delete",
            prompt="Delete me",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        result = await scheduler.delete_scheduled_task(task.schedule_id)
        assert result is True

        retrieved = await scheduler.get_scheduled_task(task.schedule_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_scheduled_task_nonexistent(self, scheduler):
        """Test deleting a nonexistent scheduled task."""
        result = await scheduler.delete_scheduled_task("nonexistent-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_toggle_scheduled_task(self, scheduler):
        """Test toggling a scheduled task's enabled state."""
        task = await scheduler.create_scheduled_task(
            name="Toggle Task",
            prompt="Toggle me",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        assert task.enabled is True

        toggled = await scheduler.toggle_scheduled_task(task.schedule_id)
        assert toggled is not None
        assert toggled.enabled is False

        toggled_back = await scheduler.toggle_scheduled_task(task.schedule_id)
        assert toggled_back is not None
        assert toggled_back.enabled is True

    @pytest.mark.asyncio
    async def test_toggle_scheduled_task_nonexistent(self, scheduler):
        """Test toggling a nonexistent scheduled task."""
        result = await scheduler.toggle_scheduled_task("nonexistent-id")
        assert result is None


class TestSchedulerServiceExecution:
    """Tests for scheduled task execution."""

    @pytest.mark.asyncio
    async def test_execute_scheduled_task_builds_prompt(
        self, scheduler, registry, mock_nats_service
    ):
        """Test that executing a scheduled task creates tasks correctly."""
        task = await scheduler.create_scheduled_task(
            name="Execute Test",
            prompt="Do the thing",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        # Register a worker
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="http://localhost:6080",
        )

        await scheduler._execute_scheduled_task(task)

        # Verify task was assigned
        mock_nats_service.publish_task_assignment.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_scheduled_task_no_idle_worker(
        self, scheduler, mock_nats_service
    ):
        """Test execution when no idle worker is available."""
        task = await scheduler.create_scheduled_task(
            name="Queue Test",
            prompt="Queue me",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        await scheduler._execute_scheduled_task(task)

        # Task should be queued, not assigned
        mock_nats_service.publish_task_assignment.assert_not_called()

        # Broadcast should still be sent
        mock_nats_service.conn.publish.assert_called()
        call_args = mock_nats_service.conn.publish.call_args_list[0]
        assert call_args[0][1]["tasks_queued"] == 1

    @pytest.mark.asyncio
    async def test_check_due_tasks(self, scheduler, registry, mock_nats_service):
        """Test that due tasks are detected and executed."""
        await scheduler.create_scheduled_task(
            name="Due Task",
            prompt="Execute me",
            start_url="https://example.com",
            interval_seconds=0,  # Due immediately
        )

        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="http://localhost:6080",
        )

        await scheduler._check_due_tasks()
        # Give the background task a moment to run
        await asyncio.sleep(0.1)

        # Task should have been executed
        mock_nats_service.publish_task_assignment.assert_called_once()

    @pytest.mark.asyncio
    async def test_disabled_tasks_not_executed(
        self, scheduler, registry, mock_nats_service
    ):
        """Test that disabled tasks are not executed during due check."""
        task = await scheduler.create_scheduled_task(
            name="Disabled Task",
            prompt="Don't execute me",
            start_url="https://example.com",
            interval_seconds=0,
        )

        # Disable the task
        await scheduler.toggle_scheduled_task(task.schedule_id)

        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="http://localhost:6080",
        )

        await scheduler._check_due_tasks()
        await asyncio.sleep(0.1)

        mock_nats_service.publish_task_assignment.assert_not_called()


class TestSchedulerServiceLifecycle:
    """Tests for scheduler start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_and_stop(self, scheduler):
        """Test starting and stopping the scheduler."""
        await scheduler.start()
        assert scheduler._running is True

        await scheduler.stop()
        assert scheduler._running is False

    @pytest.mark.asyncio
    async def test_scheduler_loop_runs(self, scheduler, registry, mock_nats_service):
        """Test that the scheduler loop checks due tasks."""
        scheduler._check_interval = 0.05

        await scheduler.start()
        await asyncio.sleep(0.15)
        await scheduler.stop()

        # The scheduler ran without errors
        assert scheduler._running is False


class TestParallelWorkers:
    """Tests for parallel worker execution."""

    @pytest.mark.asyncio
    async def test_create_task_with_parallel_workers(self, scheduler):
        """Test creating a task with parallel_workers setting."""
        task = await scheduler.create_scheduled_task(
            name="Parallel Task",
            prompt="Run in parallel",
            start_url="https://example.com",
            interval_seconds=3600,
            parallel_workers=3,
        )
        assert task.parallel_workers == 3

    @pytest.mark.asyncio
    async def test_default_parallel_workers_is_one(self, scheduler):
        """Test default parallel_workers is 1."""
        task = await scheduler.create_scheduled_task(
            name="Default Task",
            prompt="Single worker",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        assert task.parallel_workers == 1

    @pytest.mark.asyncio
    async def test_execute_creates_multiple_tasks(
        self, scheduler, registry, mock_nats_service
    ):
        """Test that execution creates multiple task instances."""
        task = await scheduler.create_scheduled_task(
            name="Parallel Execute",
            prompt="Run 3x",
            start_url="https://example.com",
            interval_seconds=3600,
            parallel_workers=3,
        )

        # Register 3 workers
        for i in range(3):
            await registry.register(
                client_id=f"worker-{i}",
                client_type=ClientType.WORKER,
                novnc_url=f"http://localhost:608{i}",
            )

        await scheduler._execute_scheduled_task(task)

        # All 3 should be assigned
        assert mock_nats_service.publish_task_assignment.call_count == 3

    @pytest.mark.asyncio
    async def test_execute_partial_assignment(
        self, scheduler, registry, mock_nats_service
    ):
        """Test partial assignment when fewer workers than parallel count."""
        task = await scheduler.create_scheduled_task(
            name="Partial Parallel",
            prompt="Run 3x",
            start_url="https://example.com",
            interval_seconds=3600,
            parallel_workers=3,
        )

        # Only register 1 worker
        await registry.register(
            client_id="worker-0",
            client_type=ClientType.WORKER,
            novnc_url="http://localhost:6080",
        )

        await scheduler._execute_scheduled_task(task)

        # Only 1 assigned, 2 queued
        assert mock_nats_service.publish_task_assignment.call_count == 1

        # Check broadcast data
        broadcast_call = mock_nats_service.conn.publish.call_args_list[0]
        data = broadcast_call[0][1]
        assert data["tasks_assigned"] == 1
        assert data["tasks_queued"] == 2

    @pytest.mark.asyncio
    async def test_parallel_tasks_include_instance_info(
        self, scheduler, registry, mock_nats_service, task_manager
    ):
        """Test that parallel task instances include instance metadata."""
        task = await scheduler.create_scheduled_task(
            name="Instance Info",
            prompt="Check instances",
            start_url="https://example.com",
            interval_seconds=3600,
            parallel_workers=2,
        )

        await registry.register(
            client_id="worker-0",
            client_type=ClientType.WORKER,
            novnc_url="http://localhost:6080",
        )
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="http://localhost:6081",
        )

        await scheduler._execute_scheduled_task(task)

        # Check that tasks have instance info in options
        all_tasks = await task_manager.get_all_tasks()
        assert len(all_tasks) == 2

        instances = sorted([t.options.get("parallel_instance") for t in all_tasks])
        assert instances == [1, 2]
        for t in all_tasks:
            assert t.options.get("parallel_total") == 2


class TestMaxRuns:
    """Tests for max_runs auto-pause feature."""

    @pytest.mark.asyncio
    async def test_create_task_with_max_runs(self, scheduler):
        """Test creating a task with max_runs."""
        task = await scheduler.create_scheduled_task(
            name="Max Runs Task",
            prompt="Limited runs",
            start_url="https://example.com",
            interval_seconds=3600,
            max_runs=5,
        )
        assert task.max_runs == 5

    @pytest.mark.asyncio
    async def test_default_max_runs_is_none(self, scheduler):
        """Test default max_runs is None."""
        task = await scheduler.create_scheduled_task(
            name="Unlimited Task",
            prompt="Unlimited runs",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        assert task.max_runs is None

    @pytest.mark.asyncio
    async def test_update_max_runs(self, scheduler):
        """Test updating max_runs."""
        task = await scheduler.create_scheduled_task(
            name="Update Max Runs",
            prompt="Update me",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        updated = await scheduler.update_scheduled_task(task.schedule_id, max_runs=10)
        assert updated is not None
        assert updated.max_runs == 10


class TestTriggerScheduledTask:
    """Tests for manual task triggering."""

    @pytest.mark.asyncio
    async def test_trigger_scheduled_task(self, scheduler, registry, mock_nats_service):
        """Test manually triggering a scheduled task."""
        task = await scheduler.create_scheduled_task(
            name="Trigger Test",
            prompt="Trigger me",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="http://localhost:6080",
        )

        result = await scheduler.trigger_scheduled_task(task.schedule_id)
        assert result is not None

        # Give the background task a moment
        await asyncio.sleep(0.1)

        mock_nats_service.publish_task_assignment.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_nonexistent_task(self, scheduler):
        """Test triggering a nonexistent task."""
        result = await scheduler.trigger_scheduled_task("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_trigger_disabled_task_still_executes(
        self, scheduler, registry, mock_nats_service
    ):
        """Test that triggering a disabled task still executes it."""
        task = await scheduler.create_scheduled_task(
            name="Disabled Trigger",
            prompt="Trigger even when disabled",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        # Disable the task
        await scheduler.toggle_scheduled_task(task.schedule_id)

        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            novnc_url="http://localhost:6080",
        )

        result = await scheduler.trigger_scheduled_task(task.schedule_id)
        assert result is not None

        await asyncio.sleep(0.1)
        mock_nats_service.publish_task_assignment.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_queues_when_no_worker(self, scheduler, mock_nats_service):
        """Test that trigger queues task when no worker available."""
        task = await scheduler.create_scheduled_task(
            name="Queue Trigger",
            prompt="Queue me",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        result = await scheduler.trigger_scheduled_task(task.schedule_id)
        assert result is not None

        await asyncio.sleep(0.1)
        mock_nats_service.publish_task_assignment.assert_not_called()


class TestTaskManagerQueue:
    """Tests for the task queue in TaskManager."""

    @pytest.mark.asyncio
    async def test_queue_task(self, task_manager):
        """Test queueing a task."""
        await task_manager.queue_task("task-1")
        assert await task_manager.has_pending_tasks()

    @pytest.mark.asyncio
    async def test_get_next_pending_task(self, task_manager):
        """Test getting next pending task."""
        task = await task_manager.create_task(
            prompt="Pending task",
            options={},
        )
        await task_manager.queue_task(task.task_id)

        next_task_id = await task_manager.get_next_pending_task()
        assert next_task_id is not None
        assert next_task_id == task.task_id

    @pytest.mark.asyncio
    async def test_get_next_pending_task_empty_queue(self, task_manager):
        """Test getting next pending task from empty queue."""
        result = await task_manager.get_next_pending_task()
        assert result is None

    @pytest.mark.asyncio
    async def test_has_pending_tasks_empty(self, task_manager):
        """Test has_pending_tasks when queue is empty."""
        assert not await task_manager.has_pending_tasks()

    @pytest.mark.asyncio
    async def test_has_pending_tasks_non_empty(self, task_manager):
        """Test has_pending_tasks when queue has items."""
        await task_manager.queue_task("task-1")
        assert await task_manager.has_pending_tasks()


class TestNotifyOnComplete:
    """Tests for the notify_on_complete feature."""

    @pytest.mark.asyncio
    async def test_create_task_with_notify_on_complete(self, scheduler):
        """Test creating a task with notify_on_complete."""
        task = await scheduler.create_scheduled_task(
            name="Notify Task",
            prompt="Notify on complete",
            start_url="https://example.com",
            interval_seconds=3600,
            notify_on_complete=True,
        )
        assert task.notify_on_complete is True

    @pytest.mark.asyncio
    async def test_default_notify_on_complete_is_false(self, scheduler):
        """Test default notify_on_complete is False."""
        task = await scheduler.create_scheduled_task(
            name="Default Task",
            prompt="No notification",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        assert task.notify_on_complete is False

    @pytest.mark.asyncio
    async def test_update_notify_on_complete(self, scheduler):
        """Test updating notify_on_complete."""
        task = await scheduler.create_scheduled_task(
            name="Update Notify",
            prompt="Update me",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        updated = await scheduler.update_scheduled_task(
            task.schedule_id, notify_on_complete=True
        )
        assert updated is not None
        assert updated.notify_on_complete is True


class TestRunAt:
    """Tests for the run_at one-time scheduling feature."""

    @pytest.mark.asyncio
    async def test_create_with_run_at(self, scheduler):
        """Test creating a task with run_at."""
        run_at = datetime.now(timezone.utc) + timedelta(hours=1)
        task = await scheduler.create_scheduled_task(
            name="Run At Task",
            prompt="Run at specific time",
            start_url="https://example.com",
            interval_seconds=0,
            run_at=run_at,
        )
        assert task.run_at is not None

    @pytest.mark.asyncio
    async def test_create_without_run_at_uses_interval(self, scheduler):
        """Test creating without run_at uses interval for next_run_at."""
        task = await scheduler.create_scheduled_task(
            name="Interval Task",
            prompt="Run on interval",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        assert task.next_run_at is not None
        assert task.run_at is None
