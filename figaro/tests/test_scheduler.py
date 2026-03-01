"""Tests for the SchedulerService."""

import asyncio
import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from figaro.models.scheduled_task import ScheduledTask
from figaro.services.scheduler import SchedulerService
from figaro.services import TaskManager, Registry


@pytest.fixture
def task_manager():
    """Create a TaskManager instance."""
    return TaskManager()


@pytest.fixture
def registry():
    """Create a Registry instance."""
    return Registry()


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
def temp_storage_path(tmp_path):
    """Create a temporary storage path."""
    return tmp_path / "scheduled_tasks.json"


@pytest.fixture
def scheduler(task_manager, registry, temp_storage_path, mock_nats_service):
    """Create a SchedulerService instance."""
    sched = SchedulerService(
        task_manager=task_manager,
        registry=registry,
        storage_path=temp_storage_path,
    )
    sched.set_nats_service(mock_nats_service)
    return sched


class TestScheduledTaskModel:
    """Tests for the ScheduledTask model."""

    def test_create_scheduled_task(self):
        """Test creating a scheduled task."""
        task = ScheduledTask(
            schedule_id="test-id",
            name="Test Task",
            prompt="Do something",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        assert task.schedule_id == "test-id"
        assert task.name == "Test Task"
        assert task.prompt == "Do something"
        assert task.start_url == "https://example.com"
        assert task.interval_seconds == 3600
        assert task.enabled is True
        assert task.run_count == 0
        assert task.last_run_at is None
        assert task.next_run_at is None

    def test_scheduled_task_with_options(self):
        """Test creating a scheduled task with custom options."""
        task = ScheduledTask(
            schedule_id="test-id",
            name="Test Task",
            prompt="Do something",
            start_url="https://example.com",
            interval_seconds=3600,
            enabled=False,
            options={"max_turns": 10},
        )

        assert task.enabled is False
        assert task.options == {"max_turns": 10}


class TestSchedulerServiceCRUD:
    """Tests for SchedulerService CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_scheduled_task(self, scheduler):
        """Test creating a scheduled task."""
        task = await scheduler.create_scheduled_task(
            name="Test Task",
            prompt="Navigate and click",
            start_url="https://example.com",
            interval_seconds=300,
        )

        assert task.name == "Test Task"
        assert task.prompt == "Navigate and click"
        assert task.start_url == "https://example.com"
        assert task.interval_seconds == 300
        assert task.enabled is True
        assert task.schedule_id is not None
        assert task.next_run_at is not None

    @pytest.mark.asyncio
    async def test_create_scheduled_task_with_options(self, scheduler):
        """Test creating a scheduled task with custom options."""
        task = await scheduler.create_scheduled_task(
            name="Test Task",
            prompt="Do something",
            start_url="https://example.com",
            interval_seconds=600,
            options={"permission_mode": "plan"},
        )

        assert task.options == {"permission_mode": "plan"}

    @pytest.mark.asyncio
    async def test_get_scheduled_task(self, scheduler):
        """Test getting a scheduled task by ID."""
        created = await scheduler.create_scheduled_task(
            name="Test Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
        )

        fetched = await scheduler.get_scheduled_task(created.schedule_id)

        assert fetched is not None
        assert fetched.schedule_id == created.schedule_id
        assert fetched.name == "Test Task"

    @pytest.mark.asyncio
    async def test_get_scheduled_task_nonexistent(self, scheduler):
        """Test getting a non-existent scheduled task returns None."""
        task = await scheduler.get_scheduled_task("nonexistent")
        assert task is None

    @pytest.mark.asyncio
    async def test_get_all_scheduled_tasks(self, scheduler):
        """Test getting all scheduled tasks."""
        await scheduler.create_scheduled_task(
            name="Task 1",
            prompt="Prompt 1",
            start_url="https://example1.com",
            interval_seconds=300,
        )
        await scheduler.create_scheduled_task(
            name="Task 2",
            prompt="Prompt 2",
            start_url="https://example2.com",
            interval_seconds=600,
        )

        tasks = await scheduler.get_all_scheduled_tasks()

        assert len(tasks) == 2
        names = [t.name for t in tasks]
        assert "Task 1" in names
        assert "Task 2" in names

    @pytest.mark.asyncio
    async def test_update_scheduled_task(self, scheduler):
        """Test updating a scheduled task."""
        task = await scheduler.create_scheduled_task(
            name="Original Name",
            prompt="Original prompt",
            start_url="https://example.com",
            interval_seconds=300,
        )

        updated = await scheduler.update_scheduled_task(
            task.schedule_id,
            name="Updated Name",
            prompt="Updated prompt",
            interval_seconds=600,
        )

        assert updated is not None
        assert updated.name == "Updated Name"
        assert updated.prompt == "Updated prompt"
        assert updated.interval_seconds == 600
        assert updated.start_url == "https://example.com"  # Unchanged

    @pytest.mark.asyncio
    async def test_update_scheduled_task_nonexistent(self, scheduler):
        """Test updating a non-existent scheduled task returns None."""
        result = await scheduler.update_scheduled_task(
            "nonexistent",
            name="New Name",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_update_scheduled_task_partial_update(self, scheduler):
        """Test that partial updates only change specified fields."""
        task = await scheduler.create_scheduled_task(
            name="Original Name",
            prompt="Original prompt",
            start_url="https://example.com",
            interval_seconds=300,
        )

        # Only update name
        updated = await scheduler.update_scheduled_task(
            task.schedule_id,
            name="New Name",
        )

        assert updated.name == "New Name"
        assert updated.prompt == "Original prompt"  # Unchanged
        assert updated.start_url == "https://example.com"  # Unchanged
        assert updated.interval_seconds == 300  # Unchanged

    @pytest.mark.asyncio
    async def test_delete_scheduled_task(self, scheduler):
        """Test deleting a scheduled task."""
        task = await scheduler.create_scheduled_task(
            name="To Delete",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
        )

        result = await scheduler.delete_scheduled_task(task.schedule_id)

        assert result is True
        assert await scheduler.get_scheduled_task(task.schedule_id) is None

    @pytest.mark.asyncio
    async def test_delete_scheduled_task_nonexistent(self, scheduler):
        """Test deleting a non-existent scheduled task returns False."""
        result = await scheduler.delete_scheduled_task("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_toggle_scheduled_task(self, scheduler):
        """Test toggling a scheduled task's enabled state."""
        task = await scheduler.create_scheduled_task(
            name="Test Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
        )
        assert task.enabled is True

        toggled = await scheduler.toggle_scheduled_task(task.schedule_id)
        assert toggled.enabled is False

        toggled_again = await scheduler.toggle_scheduled_task(task.schedule_id)
        assert toggled_again.enabled is True

    @pytest.mark.asyncio
    async def test_toggle_scheduled_task_resets_next_run(self, scheduler):
        """Test that re-enabling a task resets next_run_at."""
        task = await scheduler.create_scheduled_task(
            name="Test Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
        )
        original_next_run = task.next_run_at

        # Disable
        await scheduler.toggle_scheduled_task(task.schedule_id)

        # Wait a tiny bit to ensure time difference
        await asyncio.sleep(0.01)

        # Re-enable
        toggled = await scheduler.toggle_scheduled_task(task.schedule_id)

        # next_run_at should be reset to a new time
        assert toggled.next_run_at is not None
        assert toggled.next_run_at >= original_next_run

    @pytest.mark.asyncio
    async def test_toggle_scheduled_task_nonexistent(self, scheduler):
        """Test toggling a non-existent scheduled task returns None."""
        result = await scheduler.toggle_scheduled_task("nonexistent")
        assert result is None


class TestSchedulerServicePersistence:
    """Tests for SchedulerService storage persistence."""

    @pytest.mark.asyncio
    async def test_save_and_load_tasks(
        self, task_manager, registry, temp_storage_path, mock_nats_service
    ):
        """Test saving and loading tasks from storage."""
        # Create scheduler and add tasks
        scheduler1 = SchedulerService(
            task_manager=task_manager,
            registry=registry,
            storage_path=temp_storage_path,
        )
        scheduler1.set_nats_service(mock_nats_service)
        await scheduler1.start()

        await scheduler1.create_scheduled_task(
            name="Task 1",
            prompt="Prompt 1",
            start_url="https://example1.com",
            interval_seconds=300,
        )
        await scheduler1.create_scheduled_task(
            name="Task 2",
            prompt="Prompt 2",
            start_url="https://example2.com",
            interval_seconds=600,
        )
        await scheduler1.stop()

        # Create new scheduler and verify tasks are loaded
        scheduler2 = SchedulerService(
            task_manager=task_manager,
            registry=registry,
            storage_path=temp_storage_path,
        )
        scheduler2.set_nats_service(mock_nats_service)
        await scheduler2.start()

        tasks = await scheduler2.get_all_scheduled_tasks()
        assert len(tasks) == 2

        await scheduler2.stop()

    @pytest.mark.asyncio
    async def test_load_empty_storage(
        self, task_manager, registry, temp_storage_path, mock_nats_service
    ):
        """Test loading when no storage file exists."""
        scheduler = SchedulerService(
            task_manager=task_manager,
            registry=registry,
            storage_path=temp_storage_path,
        )
        scheduler.set_nats_service(mock_nats_service)
        await scheduler.start()

        tasks = await scheduler.get_all_scheduled_tasks()
        assert len(tasks) == 0

        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_storage_file_format(self, scheduler, temp_storage_path):
        """Test that storage file has correct JSON format."""
        await scheduler.create_scheduled_task(
            name="Test Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=3600,
            options={"max_turns": 5},
        )

        # Verify file exists and is valid JSON
        assert temp_storage_path.exists()
        data = json.loads(temp_storage_path.read_text())

        assert len(data) == 1
        task_data = data[0]
        assert "schedule_id" in task_data
        assert task_data["name"] == "Test Task"
        assert task_data["prompt"] == "Test prompt"
        assert task_data["start_url"] == "https://example.com"
        assert task_data["interval_seconds"] == 3600
        assert task_data["enabled"] is True
        assert task_data["options"] == {"max_turns": 5}
        assert "created_at" in task_data
        assert "next_run_at" in task_data


class TestSchedulerServiceExecution:
    """Tests for SchedulerService task execution."""

    @pytest.mark.asyncio
    async def test_execute_scheduled_task_builds_prompt(
        self, scheduler, task_manager, registry, mock_nats_service
    ):
        """Test that execution passes prompt and start_url to worker."""
        # Create a scheduled task
        scheduled_task = await scheduler.create_scheduled_task(
            name="Test Task",
            prompt="click the login button",
            start_url="https://example.com",
            interval_seconds=300,
        )

        # Mock the worker assignment
        mock_worker = MagicMock()
        mock_worker.client_id = "worker-1"

        with patch.object(
            registry, "claim_idle_worker", new_callable=AsyncMock
        ) as mock_claim:
            mock_claim.return_value = mock_worker

            await scheduler._execute_scheduled_task(scheduled_task)

            # Verify NATS publish_task_assignment was called
            mock_nats_service.publish_task_assignment.assert_called_once()
            call_args = mock_nats_service.publish_task_assignment.call_args
            assert call_args[0][0] == "worker-1"  # worker_id
            task_obj = call_args[0][1]
            assert task_obj.prompt == "click the login button"
            assert task_obj.options["start_url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_execute_scheduled_task_no_idle_worker(
        self, scheduler, registry, mock_nats_service
    ):
        """Test execution when no idle worker is available - tasks get queued."""
        scheduled_task = await scheduler.create_scheduled_task(
            name="Test Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
        )

        with patch.object(
            registry, "claim_idle_worker", new_callable=AsyncMock
        ) as mock_claim:
            mock_claim.return_value = None

            await scheduler._execute_scheduled_task(scheduled_task)

            # Should broadcast executed message via NATS
            nats_publish_calls = mock_nats_service.conn.publish.call_args_list
            exec_calls = [
                c
                for c in nats_publish_calls
                if c[0][0] == "figaro.broadcast.scheduled_task_executed"
            ]
            assert len(exec_calls) == 1
            payload = exec_calls[0][0][1]
            assert payload["tasks_created"] == 1
            assert payload["tasks_assigned"] == 0
            assert payload["tasks_queued"] == 1

            # Task should be queued for later assignment
            assert await scheduler._task_manager.has_pending_tasks()

    @pytest.mark.asyncio
    async def test_execute_scheduled_task_updates_metadata(
        self, scheduler, registry, mock_nats_service
    ):
        """Test that execution updates task metadata."""
        scheduled_task = await scheduler.create_scheduled_task(
            name="Test Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
        )
        original_next_run = scheduled_task.next_run_at

        mock_worker = MagicMock()
        mock_worker.client_id = "worker-1"

        with patch.object(
            registry, "claim_idle_worker", new_callable=AsyncMock
        ) as mock_claim:
            mock_claim.return_value = mock_worker
            await scheduler._execute_scheduled_task(scheduled_task)

        # Verify metadata updated
        updated = await scheduler.get_scheduled_task(scheduled_task.schedule_id)
        assert updated.last_run_at is not None
        assert updated.run_count == 1
        assert updated.next_run_at > original_next_run

    @pytest.mark.asyncio
    async def test_check_due_tasks(self, scheduler, registry, mock_nats_service):
        """Test that due tasks are detected and executed."""
        # Create a task that's immediately due
        task = await scheduler.create_scheduled_task(
            name="Due Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=1,  # 1 second
        )

        # Manually set next_run_at to past
        task.next_run_at = datetime.now(timezone.utc) - timedelta(seconds=10)

        mock_worker = MagicMock()
        mock_worker.client_id = "worker-1"

        with patch.object(
            registry, "claim_idle_worker", new_callable=AsyncMock
        ) as mock_claim:
            mock_claim.return_value = mock_worker
            await scheduler._check_due_tasks()

            # Give asyncio.create_task a chance to run
            await asyncio.sleep(0.1)

            # Verify task was executed via NATS
            assert mock_nats_service.publish_task_assignment.called

    @pytest.mark.asyncio
    async def test_disabled_tasks_not_executed(
        self, scheduler, registry, mock_nats_service
    ):
        """Test that disabled tasks are not executed."""
        task = await scheduler.create_scheduled_task(
            name="Disabled Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=1,
        )

        # Disable the task
        await scheduler.toggle_scheduled_task(task.schedule_id)

        # Set next_run_at to past
        disabled_task = await scheduler.get_scheduled_task(task.schedule_id)
        disabled_task.next_run_at = datetime.now(timezone.utc) - timedelta(seconds=10)

        with patch.object(
            registry, "claim_idle_worker", new_callable=AsyncMock
        ) as mock_claim:
            await scheduler._check_due_tasks()
            await asyncio.sleep(0.1)

            # Should not have executed
            mock_claim.assert_not_called()
            mock_nats_service.publish_task_assignment.assert_not_called()


class TestSchedulerServiceLifecycle:
    """Tests for SchedulerService start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_and_stop(self, scheduler):
        """Test starting and stopping the scheduler."""
        assert scheduler._running is False

        await scheduler.start()
        assert scheduler._running is True

        await scheduler.stop()
        assert scheduler._running is False

    @pytest.mark.asyncio
    async def test_scheduler_loop_runs(
        self, task_manager, registry, temp_storage_path, mock_nats_service
    ):
        """Test that the scheduler loop actually runs."""
        scheduler = SchedulerService(
            task_manager=task_manager,
            registry=registry,
            storage_path=temp_storage_path,
        )
        scheduler.set_nats_service(mock_nats_service)
        scheduler._check_interval = 0.1  # Fast interval for testing

        check_count = 0

        async def mock_check():
            nonlocal check_count
            check_count += 1

        with patch.object(scheduler, "_check_due_tasks", side_effect=mock_check):
            await scheduler.start()
            await asyncio.sleep(0.35)  # Should run ~3 times
            await scheduler.stop()

        assert check_count >= 2  # At least a couple checks


class TestParallelWorkers:
    """Tests for parallel workers functionality."""

    @pytest.mark.asyncio
    async def test_create_task_with_parallel_workers(self, scheduler):
        """Test creating a scheduled task with parallel_workers."""
        task = await scheduler.create_scheduled_task(
            name="Parallel Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
            parallel_workers=3,
        )

        assert task.parallel_workers == 3

    @pytest.mark.asyncio
    async def test_default_parallel_workers_is_one(self, scheduler):
        """Test that default parallel_workers is 1."""
        task = await scheduler.create_scheduled_task(
            name="Single Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
        )

        assert task.parallel_workers == 1

    @pytest.mark.asyncio
    async def test_execute_creates_multiple_tasks(
        self, scheduler, task_manager, registry, mock_nats_service
    ):
        """Test that execution creates multiple tasks for parallel_workers > 1."""
        scheduled_task = await scheduler.create_scheduled_task(
            name="Parallel Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
            parallel_workers=3,
        )

        # Mock 3 idle workers
        mock_workers = [MagicMock(client_id=f"worker-{i}") for i in range(3)]
        worker_iter = iter(mock_workers)

        with patch.object(
            registry, "claim_idle_worker", new_callable=AsyncMock
        ) as mock_claim:
            mock_claim.side_effect = lambda: next(worker_iter, None)

            await scheduler._execute_scheduled_task(scheduled_task)

            # Should have published to 3 workers via NATS
            assert mock_nats_service.publish_task_assignment.call_count == 3

            # Check broadcast contains correct counts via NATS
            nats_publish_calls = mock_nats_service.conn.publish.call_args_list
            exec_calls = [
                c
                for c in nats_publish_calls
                if c[0][0] == "figaro.broadcast.scheduled_task_executed"
            ]
            assert len(exec_calls) == 1
            payload = exec_calls[0][0][1]
            assert payload["tasks_created"] == 3
            assert payload["tasks_assigned"] == 3
            assert payload["tasks_queued"] == 0

    @pytest.mark.asyncio
    async def test_execute_partial_assignment(
        self, scheduler, task_manager, registry, mock_nats_service
    ):
        """Test execution when fewer workers available than requested."""
        scheduled_task = await scheduler.create_scheduled_task(
            name="Parallel Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
            parallel_workers=3,
        )

        # Only 1 worker available
        mock_worker = MagicMock(client_id="worker-1")
        call_count = [0]

        def mock_claim():
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_worker
            return None

        with patch.object(
            registry, "claim_idle_worker", new_callable=AsyncMock
        ) as mock_claim_patch:
            mock_claim_patch.side_effect = mock_claim

            await scheduler._execute_scheduled_task(scheduled_task)

            # Should have published to only 1 worker via NATS
            assert mock_nats_service.publish_task_assignment.call_count == 1

            # Check broadcast contains correct counts via NATS
            nats_publish_calls = mock_nats_service.conn.publish.call_args_list
            exec_calls = [
                c
                for c in nats_publish_calls
                if c[0][0] == "figaro.broadcast.scheduled_task_executed"
            ]
            payload = exec_calls[0][0][1]
            assert payload["tasks_created"] == 3
            assert payload["tasks_assigned"] == 1
            assert payload["tasks_queued"] == 2

            # 2 tasks should be queued
            assert await task_manager.has_pending_tasks()

    @pytest.mark.asyncio
    async def test_parallel_tasks_include_instance_info(
        self, scheduler, registry, mock_nats_service
    ):
        """Test that parallel tasks include instance metadata."""
        scheduled_task = await scheduler.create_scheduled_task(
            name="Parallel Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
            parallel_workers=2,
        )

        mock_workers = [MagicMock(client_id=f"worker-{i}") for i in range(2)]
        worker_iter = iter(mock_workers)

        with patch.object(
            registry, "claim_idle_worker", new_callable=AsyncMock
        ) as mock_claim:
            mock_claim.side_effect = lambda: next(worker_iter, None)

            await scheduler._execute_scheduled_task(scheduled_task)

            # Check that tasks have instance info via NATS publish
            calls = mock_nats_service.publish_task_assignment.call_args_list
            task_objs = [c[0][1] for c in calls]

            assert task_objs[0].options["parallel_instance"] == 1
            assert task_objs[0].options["parallel_total"] == 2
            assert task_objs[1].options["parallel_instance"] == 2
            assert task_objs[1].options["parallel_total"] == 2

    @pytest.mark.asyncio
    async def test_parallel_workers_persistence(
        self, task_manager, registry, temp_storage_path, mock_nats_service
    ):
        """Test that parallel_workers is saved and loaded correctly."""
        scheduler1 = SchedulerService(
            task_manager=task_manager,
            registry=registry,
            storage_path=temp_storage_path,
        )
        scheduler1.set_nats_service(mock_nats_service)
        await scheduler1.start()

        await scheduler1.create_scheduled_task(
            name="Parallel Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
            parallel_workers=5,
        )
        await scheduler1.stop()

        # Load in new scheduler
        scheduler2 = SchedulerService(
            task_manager=task_manager,
            registry=registry,
            storage_path=temp_storage_path,
        )
        scheduler2.set_nats_service(mock_nats_service)
        await scheduler2.start()

        tasks = await scheduler2.get_all_scheduled_tasks()
        assert len(tasks) == 1
        assert tasks[0].parallel_workers == 5

        await scheduler2.stop()


class TestMaxRuns:
    """Tests for max_runs (auto-pause) functionality."""

    @pytest.mark.asyncio
    async def test_create_task_with_max_runs(self, scheduler):
        """Test creating a scheduled task with max_runs."""
        task = await scheduler.create_scheduled_task(
            name="Limited Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
            max_runs=5,
        )

        assert task.max_runs == 5

    @pytest.mark.asyncio
    async def test_default_max_runs_is_none(self, scheduler):
        """Test that default max_runs is None (unlimited)."""
        task = await scheduler.create_scheduled_task(
            name="Unlimited Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
        )

        assert task.max_runs is None

    @pytest.mark.asyncio
    async def test_auto_pause_at_max_runs(self, scheduler, registry, mock_nats_service):
        """Test that task is auto-paused when max_runs is reached."""
        scheduled_task = await scheduler.create_scheduled_task(
            name="Limited Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
            max_runs=2,
        )

        mock_worker = MagicMock(client_id="worker-1")

        with patch.object(
            registry, "claim_idle_worker", new_callable=AsyncMock
        ) as mock_claim:
            mock_claim.return_value = mock_worker

            # First run
            await scheduler._execute_scheduled_task(scheduled_task)
            task = await scheduler.get_scheduled_task(scheduled_task.schedule_id)
            assert task.run_count == 1
            assert task.enabled is True

            # Second run (should trigger auto-pause)
            await scheduler._execute_scheduled_task(scheduled_task)
            task = await scheduler.get_scheduled_task(scheduled_task.schedule_id)
            assert task.run_count == 2
            assert task.enabled is False

            # Verify auto-pause broadcast via NATS
            nats_publish_calls = mock_nats_service.conn.publish.call_args_list
            pause_calls = [
                c
                for c in nats_publish_calls
                if c[0][0] == "figaro.broadcast.scheduled_task_auto_paused"
            ]
            assert len(pause_calls) == 1
            assert pause_calls[0][0][1]["run_count"] == 2
            assert pause_calls[0][0][1]["max_runs"] == 2

    @pytest.mark.asyncio
    async def test_no_auto_pause_when_max_runs_none(
        self, scheduler, registry, mock_nats_service
    ):
        """Test that task is not auto-paused when max_runs is None."""
        scheduled_task = await scheduler.create_scheduled_task(
            name="Unlimited Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
            max_runs=None,
        )

        mock_worker = MagicMock(client_id="worker-1")

        with patch.object(
            registry, "claim_idle_worker", new_callable=AsyncMock
        ) as mock_claim:
            mock_claim.return_value = mock_worker

            # Run multiple times
            for _ in range(5):
                await scheduler._execute_scheduled_task(scheduled_task)

            task = await scheduler.get_scheduled_task(scheduled_task.schedule_id)
            assert task.run_count == 5
            assert task.enabled is True

            # No auto-pause broadcasts via NATS
            nats_publish_calls = mock_nats_service.conn.publish.call_args_list
            pause_calls = [
                c
                for c in nats_publish_calls
                if c[0][0] == "figaro.broadcast.scheduled_task_auto_paused"
            ]
            assert len(pause_calls) == 0

    @pytest.mark.asyncio
    async def test_max_runs_persistence(
        self, task_manager, registry, temp_storage_path, mock_nats_service
    ):
        """Test that max_runs is saved and loaded correctly."""
        scheduler1 = SchedulerService(
            task_manager=task_manager,
            registry=registry,
            storage_path=temp_storage_path,
        )
        scheduler1.set_nats_service(mock_nats_service)
        await scheduler1.start()

        await scheduler1.create_scheduled_task(
            name="Limited Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
            max_runs=10,
        )
        await scheduler1.stop()

        # Load in new scheduler
        scheduler2 = SchedulerService(
            task_manager=task_manager,
            registry=registry,
            storage_path=temp_storage_path,
        )
        scheduler2.set_nats_service(mock_nats_service)
        await scheduler2.start()

        tasks = await scheduler2.get_all_scheduled_tasks()
        assert len(tasks) == 1
        assert tasks[0].max_runs == 10

        await scheduler2.stop()

    @pytest.mark.asyncio
    async def test_update_max_runs(self, scheduler):
        """Test updating max_runs on an existing task."""
        task = await scheduler.create_scheduled_task(
            name="Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
            max_runs=5,
        )

        updated = await scheduler.update_scheduled_task(
            task.schedule_id,
            max_runs=10,
        )

        assert updated.max_runs == 10


class TestTriggerScheduledTask:
    """Tests for manually triggering scheduled tasks."""

    @pytest.mark.asyncio
    async def test_trigger_scheduled_task(
        self, scheduler, registry, mock_nats_service
    ):
        """Test manually triggering a scheduled task executes it."""
        scheduled_task = await scheduler.create_scheduled_task(
            name="Trigger Test",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        mock_worker = MagicMock()
        mock_worker.client_id = "worker-1"

        with patch.object(
            registry, "claim_idle_worker", new_callable=AsyncMock
        ) as mock_claim:
            mock_claim.return_value = mock_worker

            result = await scheduler.trigger_scheduled_task(
                scheduled_task.schedule_id
            )

            assert result is not None
            assert result.schedule_id == scheduled_task.schedule_id

            # Give asyncio.create_task a chance to run
            await asyncio.sleep(0.1)

            # Verify task was executed via NATS
            assert mock_nats_service.publish_task_assignment.called

    @pytest.mark.asyncio
    async def test_trigger_nonexistent_task(self, scheduler):
        """Test triggering a non-existent task returns None."""
        result = await scheduler.trigger_scheduled_task("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_trigger_disabled_task_still_executes(
        self, scheduler, registry, mock_nats_service
    ):
        """Test that triggering a disabled task still executes it."""
        scheduled_task = await scheduler.create_scheduled_task(
            name="Disabled Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        # Disable the task
        await scheduler.toggle_scheduled_task(scheduled_task.schedule_id)
        disabled = await scheduler.get_scheduled_task(scheduled_task.schedule_id)
        assert disabled.enabled is False

        mock_worker = MagicMock()
        mock_worker.client_id = "worker-1"

        with patch.object(
            registry, "claim_idle_worker", new_callable=AsyncMock
        ) as mock_claim:
            mock_claim.return_value = mock_worker

            result = await scheduler.trigger_scheduled_task(
                scheduled_task.schedule_id
            )

            assert result is not None

            # Give asyncio.create_task a chance to run
            await asyncio.sleep(0.1)

            # Should still execute even though disabled
            assert mock_nats_service.publish_task_assignment.called

    @pytest.mark.asyncio
    async def test_trigger_queues_when_no_worker(
        self, scheduler, registry, mock_nats_service
    ):
        """Test that trigger queues task when no idle worker available."""
        scheduled_task = await scheduler.create_scheduled_task(
            name="Trigger Test",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=3600,
        )

        with patch.object(
            registry, "claim_idle_worker", new_callable=AsyncMock
        ) as mock_claim:
            mock_claim.return_value = None

            await scheduler.trigger_scheduled_task(scheduled_task.schedule_id)

            # Give asyncio.create_task a chance to run
            await asyncio.sleep(0.1)

            # Task should be queued
            assert await scheduler._task_manager.has_pending_tasks()


class TestTaskManagerQueue:
    """Tests for TaskManager queue functionality."""

    @pytest.mark.asyncio
    async def test_queue_task(self, task_manager):
        """Test queuing a task."""
        task = await task_manager.create_task(prompt="Test", options={})
        await task_manager.queue_task(task.task_id)

        assert await task_manager.has_pending_tasks()

    @pytest.mark.asyncio
    async def test_get_next_pending_task(self, task_manager):
        """Test getting next pending task from queue."""
        task1 = await task_manager.create_task(prompt="Test 1", options={})
        task2 = await task_manager.create_task(prompt="Test 2", options={})

        await task_manager.queue_task(task1.task_id)
        await task_manager.queue_task(task2.task_id)

        # Should get tasks in FIFO order
        next_id = await task_manager.get_next_pending_task()
        assert next_id == task1.task_id

        next_id = await task_manager.get_next_pending_task()
        assert next_id == task2.task_id

        # Queue should now be empty
        assert not await task_manager.has_pending_tasks()

    @pytest.mark.asyncio
    async def test_get_next_pending_task_empty_queue(self, task_manager):
        """Test getting next pending task when queue is empty."""
        result = await task_manager.get_next_pending_task()
        assert result is None

    @pytest.mark.asyncio
    async def test_has_pending_tasks_empty(self, task_manager):
        """Test has_pending_tasks when queue is empty."""
        assert not await task_manager.has_pending_tasks()

    @pytest.mark.asyncio
    async def test_has_pending_tasks_non_empty(self, task_manager):
        """Test has_pending_tasks when queue has items."""
        task = await task_manager.create_task(prompt="Test", options={})
        await task_manager.queue_task(task.task_id)

        assert await task_manager.has_pending_tasks()


class TestNotifyOnComplete:
    """Tests for notify_on_complete functionality."""

    @pytest.mark.asyncio
    async def test_create_task_with_notify_on_complete(self, scheduler):
        """Test creating a scheduled task with notify_on_complete."""
        task = await scheduler.create_scheduled_task(
            name="Notified Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
            notify_on_complete=True,
        )

        assert task.notify_on_complete is True

    @pytest.mark.asyncio
    async def test_default_notify_on_complete_is_false(self, scheduler):
        """Test that default notify_on_complete is False."""
        task = await scheduler.create_scheduled_task(
            name="Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
        )

        assert task.notify_on_complete is False

    @pytest.mark.asyncio
    async def test_update_notify_on_complete(self, scheduler):
        """Test updating notify_on_complete on an existing task."""
        task = await scheduler.create_scheduled_task(
            name="Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
        )

        updated = await scheduler.update_scheduled_task(
            task.schedule_id,
            notify_on_complete=True,
        )

        assert updated.notify_on_complete is True

    @pytest.mark.asyncio
    async def test_notify_on_complete_persistence(
        self, task_manager, registry, temp_storage_path, mock_nats_service
    ):
        """Test that notify_on_complete is saved and loaded correctly."""
        scheduler1 = SchedulerService(
            task_manager=task_manager,
            registry=registry,
            storage_path=temp_storage_path,
        )
        scheduler1.set_nats_service(mock_nats_service)
        await scheduler1.start()

        await scheduler1.create_scheduled_task(
            name="Notified Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=300,
            notify_on_complete=True,
        )
        await scheduler1.stop()

        # Load in new scheduler
        scheduler2 = SchedulerService(
            task_manager=task_manager,
            registry=registry,
            storage_path=temp_storage_path,
        )
        scheduler2.set_nats_service(mock_nats_service)
        await scheduler2.start()

        tasks = await scheduler2.get_all_scheduled_tasks()
        assert len(tasks) == 1
        assert tasks[0].notify_on_complete is True

        await scheduler2.stop()

    @pytest.mark.asyncio
    async def test_notify_on_complete_in_storage_format(
        self, scheduler, temp_storage_path
    ):
        """Test that notify_on_complete is included in storage JSON."""
        await scheduler.create_scheduled_task(
            name="Test Task",
            prompt="Test prompt",
            start_url="https://example.com",
            interval_seconds=3600,
            notify_on_complete=True,
        )

        # Verify file contains notify_on_complete
        data = json.loads(temp_storage_path.read_text())
        assert len(data) == 1
        assert data[0]["notify_on_complete"] is True

    @pytest.mark.asyncio
    async def test_migration_from_notification_url(
        self, task_manager, registry, temp_storage_path, mock_nats_service
    ):
        """Test migration from old notification_url format to notify_on_complete."""
        # Write old format data with notification_url
        old_data = [
            {
                "schedule_id": "test-id",
                "name": "Test Task",
                "prompt": "Test prompt",
                "start_url": "https://example.com",
                "interval_seconds": 3600,
                "enabled": True,
                "created_at": "2024-01-01T00:00:00+00:00",
                "last_run_at": None,
                "next_run_at": "2024-01-01T01:00:00+00:00",
                "run_count": 0,
                "options": {},
                "parallel_workers": 1,
                "max_runs": None,
                "notification_url": "discord://webhook/token",  # Old field
            }
        ]
        temp_storage_path.write_text(json.dumps(old_data))

        # Load scheduler and verify migration
        scheduler = SchedulerService(
            task_manager=task_manager,
            registry=registry,
            storage_path=temp_storage_path,
        )
        scheduler.set_nats_service(mock_nats_service)
        await scheduler.start()

        tasks = await scheduler.get_all_scheduled_tasks()
        assert len(tasks) == 1
        assert tasks[0].notify_on_complete is True  # Migrated from notification_url

        await scheduler.stop()
