"""Tests for the TaskManager service."""

import pytest

from figaro.services import TaskManager
from figaro.services.task_manager import TaskStatus


class TestTaskManager:
    """Tests for TaskManager class."""

    @pytest.mark.asyncio
    async def test_create_task(self, task_manager: TaskManager):
        """Test creating a task."""
        task = await task_manager.create_task(
            prompt="Test prompt",
            options={"model": "claude-3"},
        )

        assert task.prompt == "Test prompt"
        assert task.options == {"model": "claude-3"}
        assert task.status == TaskStatus.PENDING
        assert task.task_id is not None

    @pytest.mark.asyncio
    async def test_create_task_with_id(self, task_manager: TaskManager):
        """Test creating a task with a specific ID."""
        task = await task_manager.create_task(
            prompt="Test prompt",
            task_id="my-task-id",
        )

        assert task.task_id == "my-task-id"

    @pytest.mark.asyncio
    async def test_get_task(self, task_manager: TaskManager):
        """Test getting a task by ID."""
        created = await task_manager.create_task(prompt="Test")
        fetched = await task_manager.get_task(created.task_id)

        assert fetched is not None
        assert fetched.task_id == created.task_id

    @pytest.mark.asyncio
    async def test_get_task_nonexistent(self, task_manager: TaskManager):
        """Test getting a non-existent task returns None."""
        task = await task_manager.get_task("nonexistent")
        assert task is None

    @pytest.mark.asyncio
    async def test_get_all_tasks(self, task_manager: TaskManager):
        """Test getting all tasks."""
        await task_manager.create_task(prompt="Task 1")
        await task_manager.create_task(prompt="Task 2")
        await task_manager.create_task(prompt="Task 3")

        tasks = await task_manager.get_all_tasks()
        assert len(tasks) == 3

    @pytest.mark.asyncio
    async def test_get_tasks_by_worker(self, task_manager: TaskManager):
        """Test getting tasks assigned to a specific worker."""
        task1 = await task_manager.create_task(prompt="Task 1")
        task2 = await task_manager.create_task(prompt="Task 2")
        task3 = await task_manager.create_task(prompt="Task 3")

        await task_manager.assign_task(task1.task_id, "worker-1")
        await task_manager.assign_task(task2.task_id, "worker-1")
        await task_manager.assign_task(task3.task_id, "worker-2")

        worker1_tasks = await task_manager.get_tasks_by_worker("worker-1")
        assert len(worker1_tasks) == 2

        worker2_tasks = await task_manager.get_tasks_by_worker("worker-2")
        assert len(worker2_tasks) == 1

    @pytest.mark.asyncio
    async def test_assign_task(self, task_manager: TaskManager):
        """Test assigning a task to a worker."""
        task = await task_manager.create_task(prompt="Test")
        result = await task_manager.assign_task(task.task_id, "worker-1")

        assert result is not None
        assert result.worker_id == "worker-1"
        assert result.status == TaskStatus.ASSIGNED

    @pytest.mark.asyncio
    async def test_assign_task_nonexistent(self, task_manager: TaskManager):
        """Test assigning a non-existent task returns None."""
        result = await task_manager.assign_task("nonexistent", "worker-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_start_task(self, task_manager: TaskManager):
        """Test starting a task."""
        task = await task_manager.create_task(prompt="Test")
        await task_manager.assign_task(task.task_id, "worker-1")
        result = await task_manager.start_task(task.task_id, session_id="session-123")

        assert result is not None
        assert result.status == TaskStatus.RUNNING
        assert result.session_id == "session-123"

    @pytest.mark.asyncio
    async def test_complete_task(self, task_manager: TaskManager):
        """Test completing a task."""
        task = await task_manager.create_task(prompt="Test")
        result = await task_manager.complete_task(
            task.task_id, result="Task completed successfully"
        )

        assert result is not None
        assert result.status == TaskStatus.COMPLETED
        assert result.result == "Task completed successfully"

    @pytest.mark.asyncio
    async def test_complete_task_nonexistent(self, task_manager: TaskManager):
        """Test completing a non-existent task returns None."""
        result = await task_manager.complete_task("nonexistent", result="done")
        assert result is None

    @pytest.mark.asyncio
    async def test_fail_task(self, task_manager: TaskManager):
        """Test failing a task."""
        task = await task_manager.create_task(prompt="Test")
        result = await task_manager.fail_task(task.task_id, error="Something went wrong")

        assert result is not None
        assert result.status == TaskStatus.FAILED
        assert result.result == {"error": "Something went wrong"}

    @pytest.mark.asyncio
    async def test_fail_task_nonexistent(self, task_manager: TaskManager):
        """Test failing a non-existent task returns None."""
        result = await task_manager.fail_task("nonexistent", error="error")
        assert result is None

    @pytest.mark.asyncio
    async def test_append_message(self, task_manager: TaskManager):
        """Test appending a message to task history."""
        task = await task_manager.create_task(prompt="Test")
        message = {"type": "AssistantMessage", "content": "Hello"}

        result = await task_manager.append_message(task.task_id, message)
        assert result is True

        history = await task_manager.get_history(task.task_id)
        assert history is not None
        assert len(history) == 1
        assert history[0] == message

    @pytest.mark.asyncio
    async def test_append_message_nonexistent(self, task_manager: TaskManager):
        """Test appending message to non-existent task returns False."""
        message = {"type": "AssistantMessage", "content": "Hello"}
        result = await task_manager.append_message("nonexistent", message)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_history(self, task_manager: TaskManager):
        """Test getting task message history."""
        task = await task_manager.create_task(prompt="Test")

        msg1 = {"type": "UserMessage", "content": "Hi"}
        msg2 = {"type": "AssistantMessage", "content": "Hello"}

        await task_manager.append_message(task.task_id, msg1)
        await task_manager.append_message(task.task_id, msg2)

        history = await task_manager.get_history(task.task_id)
        assert history is not None
        assert len(history) == 2
        assert history[0] == msg1
        assert history[1] == msg2

    @pytest.mark.asyncio
    async def test_get_history_nonexistent(self, task_manager: TaskManager):
        """Test getting history of non-existent task returns None."""
        history = await task_manager.get_history("nonexistent")
        assert history is None

    @pytest.mark.asyncio
    async def test_task_lifecycle(self, task_manager: TaskManager):
        """Test complete task lifecycle."""
        # Create
        task = await task_manager.create_task(prompt="Build a website")
        assert task.status == TaskStatus.PENDING

        # Assign
        task = await task_manager.assign_task(task.task_id, "worker-1")
        assert task is not None
        assert task.status == TaskStatus.ASSIGNED

        # Start
        task = await task_manager.start_task(task.task_id, "session-123")
        assert task is not None
        assert task.status == TaskStatus.RUNNING

        # Add messages
        await task_manager.append_message(task.task_id, {"type": "AssistantMessage"})

        # Complete
        task = await task_manager.complete_task(task.task_id, "Done!")
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.result == "Done!"
