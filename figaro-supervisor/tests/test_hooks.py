"""Tests for figaro_supervisor.hooks module."""

from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from claude_agent_sdk.types import HookContext
from figaro_supervisor.hooks.pre_tool_use import pre_tool_use_hook
from figaro_supervisor.hooks.post_tool_use import post_tool_use_hook
from figaro_supervisor.hooks.stop import stop_hook


def make_mock_context() -> HookContext:
    """Create a mock HookContext for testing."""
    return MagicMock(spec=HookContext)  # type: ignore[return-value]


class TestPreToolUseHook:
    """Tests for the pre_tool_use_hook function."""

    @pytest.mark.asyncio
    async def test_pre_tool_use_hook_returns_empty_dict(self):
        """Test that pre_tool_use_hook returns empty dict to allow tool execution."""
        mock_context = make_mock_context()
        input_data: dict[str, Any] = {
            "tool_name": "test_tool",
            "tool_input": {"param1": "value1"},
        }

        result = await pre_tool_use_hook(
            input_data=input_data,
            tool_use_id="tool-123",
            context=mock_context,
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_pre_tool_use_hook_handles_missing_fields(self):
        """Test pre_tool_use_hook handles missing input fields."""
        mock_context = make_mock_context()
        input_data: dict[str, Any] = {}  # Missing tool_name and tool_input

        result = await pre_tool_use_hook(
            input_data=input_data,
            tool_use_id=None,
            context=mock_context,
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_pre_tool_use_hook_logs_tool_info(self):
        """Test that pre_tool_use_hook logs tool information."""
        mock_context = make_mock_context()
        input_data: dict[str, Any] = {
            "tool_name": "mcp__orchestrator__list_workers",
            "tool_input": {"status": "idle"},
        }

        with patch("figaro_supervisor.hooks.pre_tool_use.logger") as mock_logger:
            await pre_tool_use_hook(
                input_data=input_data,
                tool_use_id="tool-456",
                context=mock_context,
            )

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args[0][0]
            assert "mcp__orchestrator__list_workers" in call_args
            assert "tool-456" in call_args


class TestPostToolUseHook:
    """Tests for the post_tool_use_hook function."""

    @pytest.mark.asyncio
    async def test_post_tool_use_hook_returns_empty_dict(self):
        """Test that post_tool_use_hook returns empty dict."""
        mock_context = make_mock_context()
        input_data: dict[str, Any] = {
            "tool_name": "test_tool",
            "tool_input": {},
            "tool_response": {"result": "success"},
        }

        with patch(
            "figaro_supervisor.hooks.post_tool_use.get_client", return_value=None
        ):
            with patch(
                "figaro_supervisor.hooks.post_tool_use.get_task_id", return_value=None
            ):
                result = await post_tool_use_hook(
                    input_data=input_data,
                    tool_use_id="tool-123",
                    context=mock_context,
                )

        assert result == {}

    @pytest.mark.asyncio
    async def test_post_tool_use_hook_publishes_to_nats(self):
        """Test that post_tool_use_hook publishes tool result via NATS."""
        mock_context = make_mock_context()
        mock_client = MagicMock()
        mock_client.publish_task_message = AsyncMock()

        input_data: dict[str, Any] = {
            "tool_name": "mcp__orchestrator__list_workers",
            "tool_input": {},
            "tool_response": {"workers": ["worker-1"]},
        }

        with patch(
            "figaro_supervisor.hooks.post_tool_use.get_client", return_value=mock_client
        ):
            with patch(
                "figaro_supervisor.hooks.post_tool_use.get_task_id",
                return_value="task-123",
            ):
                result = await post_tool_use_hook(
                    input_data=input_data,
                    tool_use_id="tool-456",
                    context=mock_context,
                )

        assert result == {}
        mock_client.publish_task_message.assert_called_once()
        call_args = mock_client.publish_task_message.call_args
        assert call_args[0][0] == "task-123"
        payload = call_args[0][1]
        assert payload["tool_name"] == "mcp__orchestrator__list_workers"
        assert payload["tool_use_id"] == "tool-456"

    @pytest.mark.asyncio
    async def test_post_tool_use_hook_truncates_long_response(self):
        """Test that post_tool_use_hook truncates long tool responses."""
        mock_context = make_mock_context()
        mock_client = MagicMock()
        mock_client.publish_task_message = AsyncMock()

        long_response = "x" * 1000

        input_data: dict[str, Any] = {
            "tool_name": "test_tool",
            "tool_response": long_response,
        }

        with patch(
            "figaro_supervisor.hooks.post_tool_use.get_client", return_value=mock_client
        ):
            with patch(
                "figaro_supervisor.hooks.post_tool_use.get_task_id",
                return_value="task-123",
            ):
                await post_tool_use_hook(
                    input_data=input_data,
                    tool_use_id="tool-789",
                    context=mock_context,
                )

        call_args = mock_client.publish_task_message.call_args
        payload = call_args[0][1]
        assert len(payload["result_summary"]) == 500

    @pytest.mark.asyncio
    async def test_post_tool_use_hook_handles_none_response(self):
        """Test that post_tool_use_hook handles None tool response."""
        mock_context = make_mock_context()
        mock_client = MagicMock()
        mock_client.publish_task_message = AsyncMock()

        input_data: dict[str, Any] = {
            "tool_name": "test_tool",
            "tool_response": None,
        }

        with patch(
            "figaro_supervisor.hooks.post_tool_use.get_client", return_value=mock_client
        ):
            with patch(
                "figaro_supervisor.hooks.post_tool_use.get_task_id",
                return_value="task-123",
            ):
                await post_tool_use_hook(
                    input_data=input_data,
                    tool_use_id="tool-789",
                    context=mock_context,
                )

        call_args = mock_client.publish_task_message.call_args
        payload = call_args[0][1]
        assert payload["result_summary"] is None

    @pytest.mark.asyncio
    async def test_post_tool_use_hook_no_client(self):
        """Test that post_tool_use_hook handles missing client gracefully."""
        mock_context = make_mock_context()

        input_data: dict[str, Any] = {
            "tool_name": "test_tool",
            "tool_response": {"result": "success"},
        }

        with patch(
            "figaro_supervisor.hooks.post_tool_use.get_client", return_value=None
        ):
            with patch(
                "figaro_supervisor.hooks.post_tool_use.get_task_id",
                return_value="task-123",
            ):
                # Should not raise
                result = await post_tool_use_hook(
                    input_data=input_data,
                    tool_use_id="tool-789",
                    context=mock_context,
                )

        assert result == {}

    @pytest.mark.asyncio
    async def test_post_tool_use_hook_no_task_id(self):
        """Test that post_tool_use_hook handles missing task_id gracefully."""
        mock_context = make_mock_context()
        mock_client = MagicMock()
        mock_client.publish_task_message = AsyncMock()

        input_data: dict[str, Any] = {
            "tool_name": "test_tool",
            "tool_response": {"result": "success"},
        }

        with patch(
            "figaro_supervisor.hooks.post_tool_use.get_client", return_value=mock_client
        ):
            with patch(
                "figaro_supervisor.hooks.post_tool_use.get_task_id", return_value=None
            ):
                # Should not send message when task_id is None
                result = await post_tool_use_hook(
                    input_data=input_data,
                    tool_use_id="tool-789",
                    context=mock_context,
                )

        assert result == {}
        mock_client.publish_task_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_post_tool_use_hook_handles_publish_exception(self):
        """Test that post_tool_use_hook handles publish exceptions gracefully."""
        mock_context = make_mock_context()
        mock_client = MagicMock()
        mock_client.publish_task_message = AsyncMock(side_effect=Exception("Network error"))

        input_data: dict[str, Any] = {
            "tool_name": "test_tool",
            "tool_response": {"result": "success"},
        }

        with patch(
            "figaro_supervisor.hooks.post_tool_use.get_client", return_value=mock_client
        ):
            with patch(
                "figaro_supervisor.hooks.post_tool_use.get_task_id",
                return_value="task-123",
            ):
                # Should not raise
                result = await post_tool_use_hook(
                    input_data=input_data,
                    tool_use_id="tool-789",
                    context=mock_context,
                )

        assert result == {}


class TestStopHook:
    """Tests for the stop_hook function."""

    @pytest.mark.asyncio
    async def test_stop_hook_returns_empty_dict(self):
        """Test that stop_hook returns empty dict."""
        mock_context = make_mock_context()
        input_data: dict[str, Any] = {"stop_hook_active": True}

        result = await stop_hook(
            input_data=input_data,
            tool_use_id=None,
            context=mock_context,
        )

        assert result == {}

    @pytest.mark.asyncio
    async def test_stop_hook_logs_cleanup(self):
        """Test that stop_hook logs cleanup message."""
        mock_context = make_mock_context()
        input_data: dict[str, Any] = {}

        with patch("figaro_supervisor.hooks.stop.logger") as mock_logger:
            await stop_hook(
                input_data=input_data,
                tool_use_id=None,
                context=mock_context,
            )

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args[0][0]
            assert "Stop hook" in call_args or "cleaning up" in call_args
