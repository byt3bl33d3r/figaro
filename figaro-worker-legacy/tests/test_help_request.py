"""Tests for the worker HelpRequestHandler."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from figaro_worker.worker.help_request import HelpRequestHandler


class TestHelpRequestHandler:
    @pytest.fixture
    def mock_sub(self):
        sub = MagicMock()
        sub.unsubscribe = AsyncMock()
        return sub

    @pytest.fixture
    def mock_conn(self, mock_sub):
        """Mock NatsConnection that captures the subscribe callback."""
        conn = MagicMock()
        conn.subscribe = AsyncMock(return_value=mock_sub)
        return conn

    @pytest.fixture
    def mock_client(self, mock_conn):
        client = MagicMock()
        client.publish_help_request = AsyncMock()
        client.conn = mock_conn
        return client

    @pytest.fixture
    def handler(self, mock_client):
        return HelpRequestHandler(mock_client)

    @pytest.fixture
    def sample_questions(self):
        return [
            {
                "question": "Which framework should I use?",
                "header": "Framework",
                "options": [
                    {"label": "React", "description": "Component-based UI"},
                    {"label": "Vue", "description": "Progressive framework"},
                ],
                "multiSelect": False,
            }
        ]

    def _get_subscribe_callback(self, mock_conn):
        """Extract the callback passed to conn.subscribe."""
        return mock_conn.subscribe.call_args[0][1]

    @pytest.mark.asyncio
    async def test_request_help_sends_message(self, handler, mock_client, mock_conn, sample_questions):
        task = asyncio.create_task(
            handler.request_help(
                task_id="task-1",
                questions=sample_questions,
                timeout_seconds=1,
            )
        )

        await asyncio.sleep(0.1)

        # Verify Core NATS subscribe was called for the specific response subject
        mock_conn.subscribe.assert_called_once()
        subject = mock_conn.subscribe.call_args[0][0]
        assert subject.startswith("figaro.help.")
        assert subject.endswith(".response")

        # Verify publish_help_request was called
        mock_client.publish_help_request.assert_called_once()
        call_kwargs = mock_client.publish_help_request.call_args[1]
        assert call_kwargs["task_id"] == "task-1"
        assert call_kwargs["questions"] == sample_questions
        assert call_kwargs["timeout_seconds"] == 1

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_request_help_waits_for_response(self, handler, mock_client, mock_conn, sample_questions):
        task = asyncio.create_task(
            handler.request_help(
                task_id="task-1",
                questions=sample_questions,
                timeout_seconds=5,
            )
        )

        await asyncio.sleep(0.1)

        # Get request_id and callback
        call_kwargs = mock_client.publish_help_request.call_args[1]
        request_id = call_kwargs["request_id"]
        callback = self._get_subscribe_callback(mock_conn)

        # Simulate response arriving via the Core NATS callback
        await callback({
            "request_id": request_id,
            "answers": {"Which framework should I use?": "React"},
        })

        result = await task
        assert result == {"Which framework should I use?": "React"}

    @pytest.mark.asyncio
    async def test_request_help_timeout(self, handler, mock_conn, sample_questions):
        result = await handler.request_help(
            task_id="task-1",
            questions=sample_questions,
            timeout_seconds=0.1,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_request_help_error_response(self, handler, mock_client, mock_conn, sample_questions):
        task = asyncio.create_task(
            handler.request_help(
                task_id="task-1",
                questions=sample_questions,
                timeout_seconds=5,
            )
        )

        await asyncio.sleep(0.1)

        call_kwargs = mock_client.publish_help_request.call_args[1]
        request_id = call_kwargs["request_id"]
        callback = self._get_subscribe_callback(mock_conn)

        # Simulate error response
        await callback({
            "request_id": request_id,
            "error": "timeout",
            "answers": None,
        })

        result = await task
        assert result is None

    @pytest.mark.asyncio
    async def test_subscription_unsubscribed_after_response(self, handler, mock_client, mock_conn, mock_sub, sample_questions):
        task = asyncio.create_task(
            handler.request_help(
                task_id="task-1",
                questions=sample_questions,
                timeout_seconds=5,
            )
        )

        await asyncio.sleep(0.1)

        call_kwargs = mock_client.publish_help_request.call_args[1]
        request_id = call_kwargs["request_id"]
        callback = self._get_subscribe_callback(mock_conn)

        await callback({
            "request_id": request_id,
            "answers": {"Which framework should I use?": "React"},
        })

        await task

        # Verify subscription was cleaned up
        mock_sub.unsubscribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscription_unsubscribed_on_timeout(self, handler, mock_conn, mock_sub, sample_questions):
        result = await handler.request_help(
            task_id="task-1",
            questions=sample_questions,
            timeout_seconds=0.1,
        )

        assert result is None
        # Verify subscription was cleaned up even on timeout
        mock_sub.unsubscribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_with_context(self, handler, mock_client, mock_conn, sample_questions):
        context = {"current_url": "https://example.com", "screenshot": "base64..."}

        task = asyncio.create_task(
            handler.request_help(
                task_id="task-1",
                questions=sample_questions,
                context=context,
                timeout_seconds=1,
            )
        )

        await asyncio.sleep(0.1)

        mock_client.publish_help_request.assert_called_once()
        call_kwargs = mock_client.publish_help_request.call_args[1]
        assert call_kwargs["task_id"] == "task-1"
        assert call_kwargs["questions"] == sample_questions

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_ignores_response_with_wrong_request_id(self, handler, mock_client, mock_conn, sample_questions):
        """Response with wrong request_id should not resolve the request."""
        task = asyncio.create_task(
            handler.request_help(
                task_id="task-1",
                questions=sample_questions,
                timeout_seconds=0.5,
            )
        )

        await asyncio.sleep(0.1)

        callback = self._get_subscribe_callback(mock_conn)

        # Send a response with a wrong request_id
        await callback({
            "request_id": "wrong-id",
            "answers": {"Which framework should I use?": "React"},
        })

        # Should timeout since the correct response never came
        result = await task
        assert result is None
