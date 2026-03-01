"""Tests for TaskRepository database operations."""

import pytest
from uuid import uuid4

from figaro.db.models import TaskStatus
from figaro.db.repositories.tasks import TaskRepository


class TestTaskRepository:
    """Tests for TaskRepository."""

    @pytest.fixture
    async def repo(self, db_session):
        """Create a TaskRepository instance."""
        return TaskRepository(db_session)

    async def test_create_task(self, repo, db_session):
        """Test creating a new task."""
        task = await repo.create(
            prompt="Test prompt",
            options={"key": "value"},
            source="test",
        )
        await db_session.commit()

        assert task.task_id is not None
        assert task.prompt == "Test prompt"
        assert task.options == {"key": "value"}
        assert task.status == TaskStatus.PENDING
        assert task.source == "test"
        assert task.result is None
        assert task.worker_id is None

    async def test_create_task_with_id(self, repo, db_session):
        """Test creating a task with a specific ID."""
        task_id = str(uuid4())
        task = await repo.create(
            prompt="Test prompt",
            task_id=task_id,
        )
        await db_session.commit()

        assert task.task_id == task_id

    async def test_get_task(self, repo, db_session):
        """Test getting a task by ID."""
        created = await repo.create(prompt="Test prompt")
        await db_session.commit()

        fetched = await repo.get(created.task_id)
        assert fetched is not None
        assert fetched.task_id == created.task_id
        assert fetched.prompt == "Test prompt"

    async def test_get_task_not_found(self, repo):
        """Test getting a non-existent task."""
        fetched = await repo.get(str(uuid4()))
        assert fetched is None

    async def test_get_with_messages(self, repo, db_session):
        """Test getting a task with messages loaded."""
        task = await repo.create(prompt="Test prompt")
        await db_session.commit()

        # Add some messages
        await repo.append_message(task.task_id, {"__type__": "user", "text": "Hello"})
        await repo.append_message(task.task_id, {"__type__": "assistant", "text": "Hi"})
        await db_session.commit()

        fetched = await repo.get_with_messages(task.task_id)
        assert fetched is not None
        assert len(fetched.messages) == 2

    async def test_list_pending(self, repo, db_session):
        """Test listing pending tasks."""
        # Create tasks with different statuses
        task1 = await repo.create(prompt="Pending 1")
        task2 = await repo.create(prompt="Pending 2")
        await db_session.commit()

        # Assign one task
        await repo.assign(task2.task_id, "worker-1")
        await db_session.commit()

        pending = await repo.list_pending()
        assert len(pending) == 1
        assert pending[0].task_id == task1.task_id

    async def test_list_by_status(self, repo, db_session):
        """Test listing tasks by status."""
        task1 = await repo.create(prompt="Task 1")
        await repo.create(prompt="Task 2")
        await db_session.commit()

        # Complete one task
        await repo.assign(task1.task_id, "worker-1")
        await db_session.commit()

        assigned = await repo.list_by_status(TaskStatus.ASSIGNED)
        pending = await repo.list_by_status(TaskStatus.PENDING)

        assert len(assigned) == 1
        assert len(pending) == 1

    async def test_list_recent(self, repo, db_session):
        """Test listing recent tasks."""
        for i in range(5):
            await repo.create(prompt=f"Task {i}")
        await db_session.commit()

        recent = await repo.list_recent(limit=3)
        assert len(recent) == 3

    async def test_assign_task(self, repo, db_session):
        """Test assigning a task to a worker."""
        task = await repo.create(prompt="Test prompt")
        await db_session.commit()

        assigned = await repo.assign(task.task_id, "worker-1")
        await db_session.commit()

        assert assigned is not None
        assert assigned.status == TaskStatus.ASSIGNED
        assert assigned.worker_id == "worker-1"
        assert assigned.assigned_at is not None

    async def test_assign_already_assigned(self, repo, db_session):
        """Test that assigning an already assigned task returns None."""
        task = await repo.create(prompt="Test prompt")
        await db_session.commit()

        await repo.assign(task.task_id, "worker-1")
        await db_session.commit()

        # Try to assign again
        result = await repo.assign(task.task_id, "worker-2")
        assert result is None

    async def test_start_task(self, repo, db_session):
        """Test starting a task."""
        task = await repo.create(prompt="Test prompt")
        await db_session.commit()

        await repo.assign(task.task_id, "worker-1")
        await db_session.commit()

        started = await repo.start(task.task_id, session_id="session-123")
        await db_session.commit()

        assert started is not None
        assert started.status == TaskStatus.RUNNING
        assert started.session_id == "session-123"
        assert started.started_at is not None

    async def test_start_unassigned_task_fails(self, repo, db_session):
        """Test that starting an unassigned task returns None."""
        task = await repo.create(prompt="Test prompt")
        await db_session.commit()

        result = await repo.start(task.task_id)
        assert result is None

    async def test_complete_task(self, repo, db_session):
        """Test completing a task."""
        task = await repo.create(prompt="Test prompt")
        await db_session.commit()

        await repo.assign(task.task_id, "worker-1")
        await db_session.commit()

        completed = await repo.complete(task.task_id, {"success": True})
        await db_session.commit()

        assert completed is not None
        assert completed.status == TaskStatus.COMPLETED
        assert completed.result == {"success": True}
        assert completed.completed_at is not None

    async def test_fail_task(self, repo, db_session):
        """Test failing a task."""
        task = await repo.create(prompt="Test prompt")
        await db_session.commit()

        failed = await repo.fail(task.task_id, "Something went wrong")
        await db_session.commit()

        assert failed is not None
        assert failed.status == TaskStatus.FAILED
        assert failed.result == {"error": "Something went wrong"}
        assert failed.completed_at is not None

    async def test_append_message(self, repo, db_session):
        """Test appending messages to a task."""
        task = await repo.create(prompt="Test prompt")
        await db_session.commit()

        msg1 = await repo.append_message(
            task.task_id,
            {"__type__": "user", "text": "Hello"},
        )
        msg2 = await repo.append_message(
            task.task_id,
            {"__type__": "assistant", "text": "Hi there"},
        )
        await db_session.commit()

        assert msg1.sequence_number == 1
        assert msg2.sequence_number == 2
        assert msg1.message_type == "user"
        assert msg2.message_type == "assistant"

    async def test_get_messages(self, repo, db_session):
        """Test getting all messages for a task."""
        task = await repo.create(prompt="Test prompt")
        await db_session.commit()

        await repo.append_message(task.task_id, {"__type__": "user", "text": "First"})
        await repo.append_message(task.task_id, {"__type__": "assistant", "text": "Second"})
        await repo.append_message(task.task_id, {"__type__": "user", "text": "Third"})
        await db_session.commit()

        messages = await repo.get_messages(task.task_id)
        assert len(messages) == 3
        assert messages[0]["text"] == "First"
        assert messages[1]["text"] == "Second"
        assert messages[2]["text"] == "Third"

    async def test_message_count_updated(self, repo, db_session):
        """Test that message_count is updated when adding messages."""
        task = await repo.create(prompt="Test prompt")
        await db_session.commit()

        await repo.append_message(task.task_id, {"__type__": "user", "text": "1"})
        await repo.append_message(task.task_id, {"__type__": "user", "text": "2"})
        await db_session.commit()

        # Refresh to get updated count
        updated = await repo.get(task.task_id)
        assert updated.message_count == 2

    async def test_task_lifecycle(self, repo, db_session):
        """Test complete task lifecycle: create -> assign -> start -> complete."""
        # Create
        task = await repo.create(
            prompt="Do something",
            options={"url": "https://example.com"},
        )
        await db_session.commit()
        assert task.status == TaskStatus.PENDING

        # Assign
        assigned = await repo.assign(task.task_id, "worker-1")
        await db_session.commit()
        assert assigned.status == TaskStatus.ASSIGNED

        # Start
        started = await repo.start(task.task_id, "session-abc")
        await db_session.commit()
        assert started.status == TaskStatus.RUNNING

        # Add messages during execution
        await repo.append_message(task.task_id, {"__type__": "status", "msg": "Working..."})
        await db_session.commit()

        # Complete
        completed = await repo.complete(task.task_id, {"output": "Done!"})
        await db_session.commit()
        assert completed.status == TaskStatus.COMPLETED
        assert completed.result == {"output": "Done!"}
