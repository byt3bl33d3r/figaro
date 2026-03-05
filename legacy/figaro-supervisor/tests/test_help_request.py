"""Tests for figaro_supervisor.supervisor.help_request module."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from figaro_supervisor.supervisor.help_request import HelpRequestHandler


class TestHelpRequestHandlerInit:
    """Tests for HelpRequestHandler initialization."""

    def test_initialization(self):
        """Test handler initialization."""
        mock_client = MagicMock()

        handler = HelpRequestHandler(mock_client)

        assert handler._client is mock_client


class TestHelpRequestHandlerRequestHelp:
    """Tests for the request_help method."""

    @pytest.mark.asyncio
    async def test_request_help_success(self):
        """Test successful help request with response."""
        mock_client = MagicMock()
        mock_client.request_help = AsyncMock(return_value={"color": "Red"})

        handler = HelpRequestHandler(mock_client)

        questions = [
            {
                "question": "What color?",
                "header": "Color",
                "options": [{"label": "Red"}],
            },
        ]

        result = await handler.request_help(
            task_id="task-123",
            questions=questions,
            timeout_seconds=1,
        )

        assert result == {"color": "Red"}
        mock_client.request_help.assert_called_once()
        call_args = mock_client.request_help.call_args
        assert call_args.kwargs["task_id"] == "task-123"
        assert call_args.kwargs["questions"] == questions
        assert call_args.kwargs["timeout_seconds"] == 1

    @pytest.mark.asyncio
    async def test_request_help_timeout(self):
        """Test help request timeout returns None."""
        mock_client = MagicMock()
        mock_client.request_help = AsyncMock(return_value=None)

        handler = HelpRequestHandler(mock_client)

        questions = [{"question": "Will timeout?"}]

        result = await handler.request_help(
            task_id="task-123",
            questions=questions,
            timeout_seconds=1,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_request_help_generates_unique_ids(self):
        """Test that each request gets a unique request_id."""
        mock_client = MagicMock()
        mock_client.request_help = AsyncMock(return_value={})

        handler = HelpRequestHandler(mock_client)

        questions = [{"question": "Test?"}]
        request_ids = []

        for _ in range(3):
            await handler.request_help(
                task_id="task-123",
                questions=questions,
                timeout_seconds=1,
            )
            # Capture the request_id passed to client.request_help
            call_args = mock_client.request_help.call_args
            request_ids.append(call_args.kwargs["request_id"])

        assert len(set(request_ids)) == 3  # All unique
