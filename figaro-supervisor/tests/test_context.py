"""Tests for figaro_supervisor.context module."""

import asyncio
from unittest.mock import MagicMock

from figaro_supervisor.context import (
    SupervisorContext,
    set_context,
    get_context,
    get_client,
    get_task_id,
    update_task_context,
)


class TestSupervisorContext:
    """Tests for the SupervisorContext dataclass."""

    def test_default_values(self):
        """Test SupervisorContext default values."""
        ctx = SupervisorContext()
        assert ctx.client is None
        assert ctx.task_id is None

    def test_with_values(self):
        """Test SupervisorContext with provided values."""
        mock_client = MagicMock()

        ctx = SupervisorContext(
            client=mock_client,
            task_id="task-123",
        )

        assert ctx.client is mock_client
        assert ctx.task_id == "task-123"


class TestContextFunctions:
    """Tests for context management functions."""

    def setup_method(self):
        """Reset context before each test."""
        set_context(None)

    def test_set_and_get_context(self):
        """Test setting and getting context."""
        ctx = SupervisorContext(task_id="test-task")
        set_context(ctx)

        retrieved = get_context()
        assert retrieved is ctx
        assert retrieved.task_id == "test-task"

    def test_get_context_returns_none_when_not_set(self):
        """Test get_context returns None when not set."""
        result = get_context()
        assert result is None

    def test_get_client_with_context(self):
        """Test get_client returns client from context."""
        mock_client = MagicMock()
        ctx = SupervisorContext(client=mock_client)
        set_context(ctx)

        result = get_client()
        assert result is mock_client

    def test_get_client_without_context(self):
        """Test get_client returns None when no context."""
        result = get_client()
        assert result is None

    def test_get_task_id_with_context(self):
        """Test get_task_id returns task_id from context."""
        ctx = SupervisorContext(task_id="task-abc")
        set_context(ctx)

        result = get_task_id()
        assert result == "task-abc"

    def test_get_task_id_without_context(self):
        """Test get_task_id returns None when no context."""
        result = get_task_id()
        assert result is None


class TestUpdateTaskContext:
    """Tests for update_task_context function."""

    def setup_method(self):
        """Reset context before each test."""
        set_context(None)

    def test_update_replaces_client_and_task_id(self):
        """Test that update_task_context replaces client and task_id."""
        old_client = MagicMock()
        new_client = MagicMock()
        initial_ctx = SupervisorContext(client=old_client, task_id="old-task")
        set_context(initial_ctx)

        update_task_context(new_client, "new-task")

        new_ctx = get_context()
        assert new_ctx is not None
        assert new_ctx.client is new_client
        assert new_ctx.task_id == "new-task"

    def test_update_does_nothing_without_existing_context(self):
        """Test update_task_context does nothing if no context exists."""
        mock_client = MagicMock()
        update_task_context(mock_client, "task-123")

        # Context should still be None since there was no initial context
        result = get_context()
        assert result is None


class TestContextIsolation:
    """Tests for context isolation between coroutines."""

    async def test_context_isolated_between_coroutines(self):
        """Test that context is properly isolated between concurrent coroutines."""
        results = {}

        async def coroutine1():
            ctx = SupervisorContext(task_id="task-1")
            set_context(ctx)
            await asyncio.sleep(0.01)  # Yield control
            results["coro1"] = get_task_id()

        async def coroutine2():
            ctx = SupervisorContext(task_id="task-2")
            set_context(ctx)
            await asyncio.sleep(0.01)  # Yield control
            results["coro2"] = get_task_id()

        await asyncio.gather(coroutine1(), coroutine2())

        # Each coroutine should see its own task_id
        assert results["coro1"] == "task-1"
        assert results["coro2"] == "task-2"

    async def test_context_inherited_by_child_tasks(self):
        """Test that child tasks inherit parent context."""
        parent_ctx = SupervisorContext(task_id="parent-task")
        set_context(parent_ctx)

        async def child_coroutine():
            # Child should see parent's context
            return get_task_id()

        result = await child_coroutine()
        assert result == "parent-task"
