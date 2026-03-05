"""Tests for the TaskExecutor."""

import pytest
import dataclasses
from unittest.mock import AsyncMock, patch, MagicMock

from claude_agent_sdk._errors import MessageParseError

from figaro_worker.worker.executor import TaskExecutor, serialize_message


async def async_iter(items):
    """Helper to create an async iterator from a list."""
    for item in items:
        yield item


@dataclasses.dataclass
class MockMessage:
    """Mock SDK message for testing."""
    content: str
    role: str = "assistant"


class TestSerializeMessage:
    """Tests for serialize_message function."""

    def test_serialize_dataclass(self):
        """Test serializing a dataclass."""
        msg = MockMessage(content="Hello", role="assistant")
        result = serialize_message(msg)

        assert result["content"] == "Hello"
        assert result["role"] == "assistant"
        assert result["__type__"] == "MockMessage"

    def test_serialize_dict(self):
        """Test serializing a dict."""
        msg = {"key": "value"}
        result = serialize_message(msg)

        assert result == {"key": "value"}

    def test_serialize_other(self):
        """Test serializing other types."""
        msg = "just a string"
        result = serialize_message(msg)

        assert result["value"] == "just a string"
        assert result["__type__"] == "str"


class TestTaskExecutor:
    """Tests for TaskExecutor class."""

    @pytest.fixture
    def mock_client(self):
        client = MagicMock()
        client.worker_id = "test-worker"
        client.on = MagicMock()
        client.publish_task_message = AsyncMock()
        client.publish_task_complete = AsyncMock()
        client.publish_task_error = AsyncMock()
        client.send_status = AsyncMock()
        return client

    @pytest.fixture
    def executor(self, mock_client):
        return TaskExecutor(mock_client)

    @pytest.fixture(autouse=True)
    def mock_desktop_tools(self):
        with patch("figaro_worker.worker.executor.create_desktop_tools_server", return_value=MagicMock()):
            yield

    @pytest.mark.asyncio
    async def test_handle_task_no_task_id(self, executor: TaskExecutor, mock_client):
        """Test handling task without task_id."""
        await executor.handle_task({"prompt": "Do something"})

        # Should not call any publish methods since task_id is missing
        mock_client.publish_task_message.assert_not_called()
        mock_client.publish_task_complete.assert_not_called()
        mock_client.publish_task_error.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_task_success(self, executor: TaskExecutor, mock_client):
        """Test successful task execution."""
        @dataclasses.dataclass
        class AssistantMessage:
            content: list

        @dataclasses.dataclass
        class ResultMessage:
            result: str

        messages = [
            AssistantMessage(content=[{"text": "Working on it..."}]),
            ResultMessage(result="Done!"),
        ]

        mock_sdk_client = AsyncMock()
        mock_sdk_client.receive_response = lambda: async_iter(messages)

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_sdk_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("figaro_worker.worker.executor.ClaudeSDKClient", mock_cls):
            await executor.handle_task({
                "task_id": "test-123",
                "prompt": "Do something",
                "options": {},
            })

        # Should have published messages for each SDK message
        assert mock_client.publish_task_message.call_count == 2

        # Should have published task_complete
        mock_client.publish_task_complete.assert_called_once()
        complete_call = mock_client.publish_task_complete.call_args
        assert complete_call[0][0] == "test-123"

    @pytest.mark.asyncio
    async def test_handle_task_failure(self, executor: TaskExecutor, mock_client):
        """Test task execution failure."""
        mock_sdk_client = AsyncMock()
        mock_sdk_client.query = AsyncMock(side_effect=Exception("SDK error"))

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_sdk_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("figaro_worker.worker.executor.ClaudeSDKClient", mock_cls):
            await executor.handle_task({
                "task_id": "test-123",
                "prompt": "Do something",
                "options": {},
            })

        # Should have published error
        mock_client.publish_task_error.assert_called_once()
        error_call = mock_client.publish_task_error.call_args
        assert error_call[0][0] == "test-123"
        assert "SDK error" in error_call[0][1]

    @pytest.mark.asyncio
    async def test_handle_task_with_options(self, executor: TaskExecutor, mock_client):
        """Test task execution with custom options."""
        mock_sdk_client = AsyncMock()
        mock_sdk_client.receive_response = lambda: async_iter([])

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_sdk_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("figaro_worker.worker.executor.ClaudeSDKClient", mock_cls):
            await executor.handle_task({
                "task_id": "test-123",
                "prompt": "Do something",
                "options": {
                    "permission_mode": "default",
                    "max_turns": 10,
                },
            })

        # ClaudeSDKClient is called with the options object
        call_args = mock_cls.call_args[0][0]
        assert call_args.permission_mode == "default"
        assert call_args.max_turns == 10

    @pytest.mark.asyncio
    async def test_messages_include_task_id(self, executor: TaskExecutor, mock_client):
        """Test that all messages include task_id in the publish call."""
        @dataclasses.dataclass
        class TestMessage:
            text: str

        mock_sdk_client = AsyncMock()
        mock_sdk_client.receive_response = lambda: async_iter([TestMessage(text="Hello")])

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_sdk_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("figaro_worker.worker.executor.ClaudeSDKClient", mock_cls):
            await executor.handle_task({
                "task_id": "test-123",
                "prompt": "Do something",
                "options": {},
            })

        # Check that publish_task_message was called with the right task_id
        assert mock_client.publish_task_message.call_count >= 1
        first_call = mock_client.publish_task_message.call_args_list[0]
        assert first_call[0][0] == "test-123"
        assert first_call[0][1]["task_id"] == "test-123"

    @pytest.mark.asyncio
    async def test_handle_task_message_parse_error(self, executor: TaskExecutor, mock_client):
        """Test that MessageParseError (e.g. rate_limit_event) doesn't crash the task."""
        @dataclasses.dataclass
        class AssistantMessage:
            content: list

        async def error_messages():
            yield AssistantMessage(content=[{"text": "Working..."}])
            raise MessageParseError("Unknown message type: rate_limit_event", {"type": "rate_limit_event"})

        mock_sdk_client = AsyncMock()
        mock_sdk_client.receive_response = error_messages

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_sdk_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("figaro_worker.worker.executor.ClaudeSDKClient", mock_cls):
            await executor.handle_task({
                "task_id": "test-123",
                "prompt": "Do something",
                "options": {},
            })

        # Should have published the message before the error
        assert mock_client.publish_task_message.call_count == 1

        # Should complete (not error) since we handle MessageParseError gracefully
        mock_client.publish_task_complete.assert_called_once()
        mock_client.publish_task_error.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_receive_response_not_receive_messages(
        self, executor: TaskExecutor, mock_client
    ):
        """Regression: executor must use receive_response(), not receive_messages().

        Previously the worker used receive_messages() which waits for the
        transport stream to close. If the CLI process didn't exit promptly
        after sending the ResultMessage, the loop hung forever and
        publish_task_complete was never called — leaving the worker stuck as busy.

        receive_response() stops immediately after yielding a ResultMessage,
        so completion is always published regardless of transport lifecycle.
        """
        from claude_agent_sdk.types import ResultMessage as SdkResultMessage

        @dataclasses.dataclass
        class AssistantMessage:
            content: list

        result_msg = SdkResultMessage(
            subtype="result",
            duration_ms=1000,
            duration_api_ms=800,
            is_error=False,
            num_turns=1,
            result="Task done",
            session_id="sess-1",
            total_cost_usd=0.01,
            usage=None,
            structured_output=None,
        )

        messages = [
            AssistantMessage(content=[{"text": "Working..."}]),
            result_msg,
        ]

        mock_sdk_client = AsyncMock()
        mock_sdk_client.receive_response = lambda: async_iter(messages)

        # Make receive_messages() blow up if called — the executor must NOT use it
        def must_not_call():
            raise AssertionError(
                "Executor called receive_messages() instead of receive_response(). "
                "receive_messages() hangs until the transport closes, which may "
                "never happen — use receive_response() which stops after ResultMessage."
            )
        mock_sdk_client.receive_messages = must_not_call

        mock_cls = MagicMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_sdk_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("figaro_worker.worker.executor.ClaudeSDKClient", mock_cls):
            await executor.handle_task({
                "task_id": "test-456",
                "prompt": "Do something",
                "options": {},
            })

        # Must have published completion with the result
        mock_client.publish_task_complete.assert_called_once()
        complete_args = mock_client.publish_task_complete.call_args[0]
        assert complete_args[0] == "test-456"
        assert complete_args[1] is not None
        assert complete_args[1]["result"] == "Task done"
