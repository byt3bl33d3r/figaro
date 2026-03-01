"""Tests for figaro_supervisor.supervisor.processor module."""

import dataclasses

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny
from figaro_supervisor.supervisor.processor import TaskProcessor, TaskSession, serialize_message


class TestSerializeMessage:
    """Tests for the serialize_message function."""

    def test_serialize_dataclass(self):
        """Test serializing a dataclass."""

        @dataclasses.dataclass
        class TestMessage:
            text: str
            value: int

        msg = TestMessage(text="hello", value=42)
        result = serialize_message(msg)

        assert result == {"text": "hello", "value": 42, "__type__": "TestMessage"}

    def test_serialize_dict(self):
        """Test serializing a dict passthrough."""
        msg = {"type": "test", "data": [1, 2, 3]}
        result = serialize_message(msg)

        assert result == {"type": "test", "data": [1, 2, 3]}

    def test_serialize_other_type(self):
        """Test serializing other types."""
        result = serialize_message("simple string")

        assert result == {"value": "simple string", "__type__": "str"}

    def test_serialize_none(self):
        """Test serializing None."""
        result = serialize_message(None)

        assert result == {"value": "None", "__type__": "NoneType"}


class TestTaskProcessorInit:
    """Tests for TaskProcessor initialization."""

    def test_initialization(self):
        """Test processor initialization."""
        mock_client = MagicMock()
        mock_client.supervisor_id = "test-supervisor"
        mock_client.conn = MagicMock()

        processor = TaskProcessor(
            client=mock_client,
            model="claude-opus-4-6",
            max_turns=10,
        )

        assert processor.client is mock_client
        assert processor.model == "claude-opus-4-6"
        assert processor.max_turns == 10
        assert processor._sessions == {}

    def test_initialization_defaults(self):
        """Test processor initialization with defaults."""
        mock_client = MagicMock()
        mock_client.supervisor_id = "test-supervisor"
        mock_client.conn = MagicMock()

        processor = TaskProcessor(client=mock_client)

        assert processor.model == "claude-opus-4-6"
        assert processor.max_turns is None


class TestTaskProcessorFormatPrompt:
    """Tests for prompt formatting."""

    def test_format_supervisor_prompt_ui_source(self):
        """Test formatting prompt from UI source."""
        mock_client = MagicMock()
        mock_client.supervisor_id = "supervisor-123"
        mock_client.conn = MagicMock()

        processor = TaskProcessor(client=mock_client)

        result = processor._format_supervisor_prompt(
            user_prompt="Search for flights",
            options={"source": "ui"},
        )

        assert "<task_context>" in result
        assert "Source: ui" in result
        assert "Supervisor ID: supervisor-123" in result
        assert "Search for flights" in result
        assert "<user_request>" in result

    def test_format_supervisor_prompt_gateway_source(self):
        """Test formatting prompt from gateway source."""
        mock_client = MagicMock()
        mock_client.supervisor_id = "supervisor-123"
        mock_client.conn = MagicMock()

        processor = TaskProcessor(client=mock_client)

        result = processor._format_supervisor_prompt(
            user_prompt="Check weather",
            options={"source": "gateway"},
        )

        assert "Source: gateway" in result
        assert "Check weather" in result

    def test_format_supervisor_prompt_default_source(self):
        """Test formatting prompt with default source."""
        mock_client = MagicMock()
        mock_client.supervisor_id = "supervisor-123"
        mock_client.conn = MagicMock()

        processor = TaskProcessor(client=mock_client)

        result = processor._format_supervisor_prompt(
            user_prompt="Test prompt",
            options={},
        )

        assert "Source: unknown" in result  # Default source


class TestTaskProcessorCanUseTool:
    """Tests for the _can_use_tool_for_session callback."""

    @pytest.mark.asyncio
    async def test_can_use_tool_non_ask_user_question(self):
        """Test that non-AskUserQuestion tools are auto-approved."""
        mock_client = MagicMock()
        mock_client.supervisor_id = "test-supervisor"
        mock_client.conn = MagicMock()

        processor = TaskProcessor(client=mock_client)

        session = TaskSession(
            task_id="task-123",
            prompt="test",
        )
        mock_context = MagicMock()
        input_data = {"tool_input": "test"}

        result = await processor._can_use_tool_for_session(
            session=session,
            tool_name="some_other_tool",
            input_data=input_data,
            context=mock_context,
        )

        # Should return PermissionResultAllow
        assert hasattr(result, "updated_input")
        assert result.updated_input == input_data

    @pytest.mark.asyncio
    async def test_can_use_tool_ask_user_question_success(self):
        """Test AskUserQuestion with successful response."""
        mock_client = MagicMock()
        mock_client.supervisor_id = "test-supervisor"
        mock_client.conn = MagicMock()

        processor = TaskProcessor(client=mock_client)

        session = TaskSession(
            task_id="task-123",
            prompt="test",
        )

        # Mock the help handler
        processor.help_handler = MagicMock()
        processor.help_handler.request_help = AsyncMock(return_value={"q1": "answer1"})

        mock_context = MagicMock()
        questions = [{"question": "Test?", "header": "Test"}]
        input_data = {"questions": questions}

        result = await processor._can_use_tool_for_session(
            session=session,
            tool_name="AskUserQuestion",
            input_data=input_data,
            context=mock_context,
        )

        # Should return PermissionResultAllow with answers
        assert isinstance(result, PermissionResultAllow)
        assert result.updated_input is not None
        assert result.updated_input["questions"] == questions
        assert result.updated_input["answers"] == {"q1": "answer1"}

        processor.help_handler.request_help.assert_called_once_with(
            task_id="task-123",
            questions=questions,
            timeout_seconds=300,
        )

    @pytest.mark.asyncio
    async def test_can_use_tool_ask_user_question_timeout(self):
        """Test AskUserQuestion with timeout."""
        mock_client = MagicMock()
        mock_client.supervisor_id = "test-supervisor"
        mock_client.conn = MagicMock()

        processor = TaskProcessor(client=mock_client)

        session = TaskSession(
            task_id="task-123",
            prompt="test",
        )

        # Mock the help handler to return None (timeout)
        processor.help_handler = MagicMock()
        processor.help_handler.request_help = AsyncMock(return_value=None)

        mock_context = MagicMock()
        input_data = {"questions": [{"question": "Test?"}]}

        result = await processor._can_use_tool_for_session(
            session=session,
            tool_name="AskUserQuestion",
            input_data=input_data,
            context=mock_context,
        )

        # Should return PermissionResultDeny
        assert isinstance(result, PermissionResultDeny)
        assert "Timeout" in result.message


class TestTaskProcessorHandleTask:
    """Tests for the handle_task method."""

    @pytest.mark.asyncio
    async def test_handle_task_missing_task_id(self):
        """Test handling task without task_id."""
        mock_client = MagicMock()
        mock_client.supervisor_id = "test-supervisor"
        mock_client.conn = MagicMock()

        processor = TaskProcessor(client=mock_client)

        # Should not raise, just log error
        await processor.handle_task({"prompt": "test"})

        # No session should be created
        assert len(processor._sessions) == 0

    @pytest.mark.asyncio
    async def test_handle_task_creates_session(self):
        """Test that handle_task creates a session and spawns task."""
        mock_client = MagicMock()
        mock_client.supervisor_id = "test-supervisor"
        mock_client.conn = MagicMock()
        mock_client.publish_task_message = AsyncMock()
        mock_client.publish_task_complete = AsyncMock()
        mock_client.send_status = AsyncMock()

        processor = TaskProcessor(client=mock_client)

        sessions_created = []

        # Mock _run_session to complete immediately and capture session
        async def mock_run_session(session):
            sessions_created.append(session)

        with patch.object(processor, "_run_session", side_effect=mock_run_session):
            await processor.handle_task(
                {
                    "task_id": "task-123",
                    "prompt": "test",
                }
            )
            # Give the spawned task time to start
            import asyncio
            await asyncio.sleep(0.01)

        # Session should have been created
        assert len(sessions_created) == 1
        assert sessions_created[0].task_id == "task-123"
        assert sessions_created[0].prompt == "test"


class TestTaskProcessorRunSession:
    """Tests for _run_session method."""

    @pytest.mark.asyncio
    async def test_run_session_publishes_messages(self):
        """Test that _run_session publishes messages via NATS."""
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        mock_client = MagicMock()
        mock_client.supervisor_id = "test-supervisor"
        mock_client.conn = MagicMock()
        mock_client.publish_task_message = AsyncMock()
        mock_client.publish_task_complete = AsyncMock()
        mock_client.send_status = AsyncMock()

        processor = TaskProcessor(client=mock_client)

        session = TaskSession(
            task_id="task-123",
            prompt="Test prompt",
            options={"source": "ui"},
        )

        msg = AssistantMessage(
            content=[TextBlock(text="Response")],
            model="claude-opus-4-6",
        )

        mock_sdk_client = MagicMock()
        mock_sdk_client.__aenter__ = AsyncMock(return_value=mock_sdk_client)
        mock_sdk_client.__aexit__ = AsyncMock(return_value=None)
        mock_sdk_client.query = AsyncMock()

        async def mock_receive_response():
            yield msg

        mock_sdk_client.receive_response = mock_receive_response

        with patch(
            "figaro_supervisor.supervisor.processor.ClaudeSDKClient",
            return_value=mock_sdk_client,
        ):
            await processor._run_session(session)

        # Should have published messages and completion
        assert mock_client.publish_task_message.call_count >= 1
        mock_client.publish_task_complete.assert_called_once()
        # Should have sent status updates
        mock_client.send_status.assert_any_call("busy")

    @pytest.mark.asyncio
    async def test_run_session_publishes_error_on_failure(self):
        """Test that _run_session publishes error on SDK failure."""
        mock_client = MagicMock()
        mock_client.supervisor_id = "test-supervisor"
        mock_client.conn = MagicMock()
        mock_client.publish_task_error = AsyncMock()
        mock_client.send_status = AsyncMock()

        processor = TaskProcessor(client=mock_client)

        session = TaskSession(
            task_id="task-123",
            prompt="Test prompt",
            options={"source": "ui"},
        )

        mock_sdk_client = MagicMock()
        mock_sdk_client.__aenter__ = AsyncMock(
            side_effect=RuntimeError("SDK connection failed")
        )
        mock_sdk_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "figaro_supervisor.supervisor.processor.ClaudeSDKClient",
            return_value=mock_sdk_client,
        ):
            await processor._run_session(session)

        # Should have published error
        mock_client.publish_task_error.assert_called_once()
        call_args = mock_client.publish_task_error.call_args
        assert call_args[0][0] == "task-123"
        assert "SDK connection failed" in call_args[0][1]
