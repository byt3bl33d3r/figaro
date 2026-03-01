"""Tests for ScheduledTaskRepository database operations."""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from figaro.db.repositories.scheduled import ScheduledTaskRepository


class TestScheduledTaskRepository:
    """Tests for ScheduledTaskRepository."""

    @pytest.fixture
    async def repo(self, db_session):
        """Create a ScheduledTaskRepository instance."""
        return ScheduledTaskRepository(db_session)

    async def test_create_scheduled_task(self, repo, db_session):
        """Test creating a new scheduled task."""
        task = await repo.create(
            name="Test Task",
            prompt="Do something",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await db_session.commit()

        assert task.schedule_id is not None
        assert task.name == "Test Task"
        assert task.prompt == "Do something"
        assert task.start_url == "https://example.com"
        assert task.interval_seconds == 3600
        assert task.enabled is True
        assert task.parallel_workers == 1
        assert task.run_count == 0
        assert task.next_run_at is not None
        assert task.self_healing is False  # default

    async def test_create_with_all_options(self, repo, db_session):
        """Test creating a scheduled task with all options."""
        task = await repo.create(
            name="Full Task",
            prompt="Do everything",
            start_url="https://example.com",
            interval_seconds=1800,
            options={"key": "value"},
            parallel_workers=3,
            max_runs=10,
            notify_on_complete=True,
            self_healing=True,
        )
        await db_session.commit()

        assert task.options == {"key": "value"}
        assert task.parallel_workers == 3
        assert task.max_runs == 10
        assert task.notify_on_complete is True
        assert task.self_healing is True

    async def test_create_with_specific_id(self, repo, db_session):
        """Test creating a scheduled task with a specific ID."""
        schedule_id = str(uuid4())
        task = await repo.create(
            name="Test Task",
            prompt="Do something",
            start_url="https://example.com",
            interval_seconds=3600,
            schedule_id=schedule_id,
        )
        await db_session.commit()

        assert task.schedule_id == schedule_id

    async def test_get_scheduled_task(self, repo, db_session):
        """Test getting a scheduled task by ID."""
        created = await repo.create(
            name="Test Task",
            prompt="Do something",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await db_session.commit()

        fetched = await repo.get(created.schedule_id)
        assert fetched is not None
        assert fetched.schedule_id == created.schedule_id
        assert fetched.name == "Test Task"

    async def test_get_not_found(self, repo):
        """Test getting a non-existent scheduled task."""
        fetched = await repo.get(str(uuid4()))
        assert fetched is None

    async def test_get_deleted_returns_none(self, repo, db_session):
        """Test that getting a deleted task returns None."""
        task = await repo.create(
            name="Test Task",
            prompt="Do something",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await db_session.commit()

        await repo.soft_delete(task.schedule_id)
        await db_session.commit()

        fetched = await repo.get(task.schedule_id)
        assert fetched is None

    async def test_list_all(self, repo, db_session):
        """Test listing all scheduled tasks."""
        await repo.create(
            name="Task 1",
            prompt="Do 1",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await repo.create(
            name="Task 2",
            prompt="Do 2",
            start_url="https://example.com",
            interval_seconds=1800,
        )
        await db_session.commit()

        tasks = await repo.list_all()
        assert len(tasks) == 2

    async def test_list_all_excludes_deleted(self, repo, db_session):
        """Test that list_all excludes deleted tasks."""
        task1 = await repo.create(
            name="Task 1",
            prompt="Do 1",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await repo.create(
            name="Task 2",
            prompt="Do 2",
            start_url="https://example.com",
            interval_seconds=1800,
        )
        await db_session.commit()

        await repo.soft_delete(task1.schedule_id)
        await db_session.commit()

        tasks = await repo.list_all()
        assert len(tasks) == 1
        assert tasks[0].name == "Task 2"

    async def test_list_enabled(self, repo, db_session):
        """Test listing enabled scheduled tasks."""
        await repo.create(
            name="Enabled Task",
            prompt="Do",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        task2 = await repo.create(
            name="Also Enabled",
            prompt="Do",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await db_session.commit()

        # Disable one
        await repo.toggle_enabled(task2.schedule_id)
        await db_session.commit()

        enabled = await repo.list_enabled()
        assert len(enabled) == 1
        assert enabled[0].name == "Enabled Task"

    async def test_get_due_tasks(self, repo, db_session):
        """Test getting tasks due for execution."""
        # Create a task that's due now
        task1 = await repo.create(
            name="Due Task",
            prompt="Do",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        # Set next_run_at to the past
        await repo.update(task1.schedule_id, next_run_at=datetime.now(timezone.utc) - timedelta(hours=1))
        await db_session.commit()

        # Create a task that's not due yet
        await repo.create(
            name="Future Task",
            prompt="Do later",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await db_session.commit()

        due = await repo.get_due_tasks()
        assert len(due) == 1
        assert due[0].name == "Due Task"

    async def test_get_due_tasks_excludes_disabled(self, repo, db_session):
        """Test that get_due_tasks excludes disabled tasks."""
        task = await repo.create(
            name="Due Task",
            prompt="Do",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await repo.update(task.schedule_id, next_run_at=datetime.now(timezone.utc) - timedelta(hours=1))
        await db_session.commit()

        # Disable it
        await repo.toggle_enabled(task.schedule_id)
        await db_session.commit()

        due = await repo.get_due_tasks()
        assert len(due) == 0

    async def test_update_task(self, repo, db_session):
        """Test updating a scheduled task."""
        task = await repo.create(
            name="Original Name",
            prompt="Original prompt",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await db_session.commit()

        updated = await repo.update(
            task.schedule_id,
            name="New Name",
            prompt="New prompt",
            interval_seconds=1800,
        )
        await db_session.commit()

        assert updated is not None
        assert updated.name == "New Name"
        assert updated.prompt == "New prompt"
        assert updated.interval_seconds == 1800

    async def test_update_self_healing_round_trip(self, repo, db_session):
        """Test that self_healing field round-trips correctly through create and update."""
        # Create with self_healing=False (default)
        task = await repo.create(
            name="Healing Task",
            prompt="Do something",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await db_session.commit()
        assert task.self_healing is False

        # Update to enable self_healing
        updated = await repo.update(task.schedule_id, self_healing=True)
        await db_session.commit()
        assert updated is not None
        assert updated.self_healing is True

        # Verify via fresh get
        fetched = await repo.get(task.schedule_id)
        assert fetched.self_healing is True

        # Update back to disabled
        updated2 = await repo.update(task.schedule_id, self_healing=False)
        await db_session.commit()
        assert updated2 is not None
        assert updated2.self_healing is False

    async def test_update_nonexistent_returns_none(self, repo):
        """Test that updating a non-existent task returns None."""
        result = await repo.update(str(uuid4()), name="New Name")
        assert result is None

    async def test_toggle_enabled(self, repo, db_session):
        """Test toggling the enabled state."""
        task = await repo.create(
            name="Test Task",
            prompt="Do",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await db_session.commit()
        assert task.enabled is True

        # Disable
        toggled = await repo.toggle_enabled(task.schedule_id)
        await db_session.commit()
        assert toggled.enabled is False
        assert toggled.next_run_at is None

        # Enable again
        toggled = await repo.toggle_enabled(task.schedule_id)
        await db_session.commit()
        assert toggled.enabled is True
        assert toggled.next_run_at is not None

    async def test_mark_executed(self, repo, db_session):
        """Test marking a task as executed."""
        task = await repo.create(
            name="Test Task",
            prompt="Do",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await db_session.commit()
        original_next_run = task.next_run_at

        executed = await repo.mark_executed(task.schedule_id)
        await db_session.commit()

        assert executed.run_count == 1
        assert executed.last_run_at is not None
        assert executed.next_run_at > original_next_run

    async def test_mark_executed_auto_disables_on_max_runs(self, repo, db_session):
        """Test that mark_executed disables the task when max_runs is reached."""
        task = await repo.create(
            name="Test Task",
            prompt="Do",
            start_url="https://example.com",
            interval_seconds=3600,
            max_runs=2,
        )
        await db_session.commit()

        # First execution
        await repo.mark_executed(task.schedule_id)
        await db_session.commit()
        task = await repo.get(task.schedule_id)
        assert task.run_count == 1
        assert task.enabled is True

        # Second (final) execution
        executed = await repo.mark_executed(task.schedule_id)
        await db_session.commit()

        assert executed.run_count == 2
        assert executed.enabled is False
        assert executed.next_run_at is None

    async def test_soft_delete(self, repo, db_session):
        """Test soft deleting a scheduled task."""
        task = await repo.create(
            name="Test Task",
            prompt="Do",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await db_session.commit()

        deleted = await repo.soft_delete(task.schedule_id)
        await db_session.commit()

        assert deleted is True

        # Verify it's not retrievable
        fetched = await repo.get(task.schedule_id)
        assert fetched is None

    async def test_soft_delete_nonexistent_returns_false(self, repo):
        """Test that soft deleting a non-existent task returns False."""
        result = await repo.soft_delete(str(uuid4()))
        assert result is False

    async def test_scheduled_task_lifecycle(self, repo, db_session):
        """Test complete scheduled task lifecycle."""
        # Create
        task = await repo.create(
            name="Daily Check",
            prompt="Check the website",
            start_url="https://example.com",
            interval_seconds=86400,  # 24 hours
            max_runs=3,
        )
        await db_session.commit()

        # Verify initial state
        assert task.enabled is True
        assert task.run_count == 0

        # Simulate 3 executions
        for i in range(3):
            # Set as due
            await repo.update(task.schedule_id, next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1))
            await db_session.commit()

            due = await repo.get_due_tasks()
            # Should be due until max_runs is reached
            assert len(due) == 1

            await repo.mark_executed(task.schedule_id)
            await db_session.commit()

        # After 3rd execution, task should be auto-disabled
        final = await repo.get(task.schedule_id)
        assert final.run_count == 3
        assert final.enabled is False
        assert final.next_run_at is None

        # Verify no longer due
        await repo.update(task.schedule_id, next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        await db_session.commit()
        due = await repo.get_due_tasks()
        assert len(due) == 0  # Disabled, so not due

    async def test_create_with_self_learning_max_runs(self, repo, db_session):
        """Test creating a scheduled task with self_learning_max_runs."""
        task = await repo.create(
            name="Learning Task",
            prompt="Do something",
            start_url="https://example.com",
            interval_seconds=3600,
            self_learning=True,
            self_learning_max_runs=10,
        )
        await db_session.commit()

        assert task.self_learning is True
        assert task.self_learning_max_runs == 10
        assert task.self_learning_run_count == 0

    async def test_create_default_self_learning_max_runs_is_none(self, repo, db_session):
        """Test that self_learning_max_runs defaults to None (unlimited)."""
        task = await repo.create(
            name="Task",
            prompt="Do something",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await db_session.commit()

        assert task.self_learning_max_runs is None
        assert task.self_learning_run_count == 0

    async def test_update_self_learning_max_runs(self, repo, db_session):
        """Test updating self_learning_max_runs."""
        task = await repo.create(
            name="Task",
            prompt="Do something",
            start_url="https://example.com",
            interval_seconds=3600,
        )
        await db_session.commit()

        updated = await repo.update(task.schedule_id, self_learning_max_runs=5)
        await db_session.commit()

        assert updated is not None
        assert updated.self_learning_max_runs == 5

    async def test_increment_learning_count(self, repo, db_session):
        """Test incrementing the self_learning_run_count."""
        task = await repo.create(
            name="Learning Task",
            prompt="Do something",
            start_url="https://example.com",
            interval_seconds=3600,
            self_learning=True,
        )
        await db_session.commit()
        assert task.self_learning_run_count == 0

        # Increment once
        updated = await repo.increment_learning_count(task.schedule_id)
        await db_session.commit()
        assert updated is not None
        assert updated.self_learning_run_count == 1

        # Increment again
        updated2 = await repo.increment_learning_count(task.schedule_id)
        await db_session.commit()
        assert updated2 is not None
        assert updated2.self_learning_run_count == 2

    async def test_increment_learning_count_nonexistent(self, repo):
        """Test incrementing learning count for non-existent task returns None."""
        from uuid import uuid4
        result = await repo.increment_learning_count(str(uuid4()))
        assert result is None
