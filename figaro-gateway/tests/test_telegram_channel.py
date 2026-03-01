"""Tests for TelegramChannel."""

from unittest.mock import AsyncMock

import pytest

from figaro_gateway.channels.telegram.channel import TelegramChannel


@pytest.fixture
def channel():
    """Create a TelegramChannel with a mocked bot."""
    ch = TelegramChannel(bot_token="test-token", allowed_chat_ids=[111, 222])
    ch._bot = AsyncMock()
    ch._bot._allowed_chat_ids = {111, 222}
    return ch


class TestTelegramChannel:
    def test_name(self, channel):
        """Test channel name property."""
        assert channel.name == "telegram"

    def test_on_message_registers_callback(self, channel):
        """Test on_message stores callback."""
        callback = AsyncMock()
        channel.on_message(callback)
        assert channel._message_callback is callback

    async def test_start_starts_bot(self, channel):
        """Test start delegates to bot."""
        await channel.start()
        channel._bot.start.assert_called_once()

    async def test_stop_stops_bot(self, channel):
        """Test stop delegates to bot."""
        await channel.stop()
        channel._bot.stop.assert_called_once()

    async def test_send_message_with_chat_id(self, channel):
        """Test send_message delegates to bot with int chat_id."""
        await channel.send_message("111", "hello")
        channel._bot.send_message.assert_called_once_with(111, "hello", parse_mode="Markdown")

    async def test_send_message_empty_chat_id_uses_first_allowed(self, channel):
        """Test send_message with empty chat_id uses first allowed chat."""
        await channel.send_message("", "hello")
        # Should use first allowed chat id
        call_args = channel._bot.send_message.call_args
        assert call_args[0][0] in {111, 222}
        assert call_args[0][1] == "hello"

    async def test_send_message_custom_parse_mode(self, channel):
        """Test send_message passes parse_mode kwarg."""
        await channel.send_message("111", "hello", parse_mode="HTML")
        channel._bot.send_message.assert_called_once_with(111, "hello", parse_mode="HTML")

    async def test_ask_question_delegates_to_bot(self, channel):
        """Test ask_question delegates to bot."""
        channel._bot.ask_question = AsyncMock(return_value="yes")
        result = await channel.ask_question(
            chat_id="111",
            question_id="q1",
            question="Are you sure?",
            options=[{"label": "Yes"}, {"label": "No"}],
            timeout=60,
        )
        assert result == "yes"
        channel._bot.ask_question.assert_called_once_with(
            question_id="q1",
            question="Are you sure?",
            options=[{"label": "Yes"}, {"label": "No"}],
            chat_id=111,
            timeout_seconds=60,
        )

    async def test_ask_question_empty_chat_id(self, channel):
        """Test ask_question with empty chat_id uses first allowed."""
        channel._bot.ask_question = AsyncMock(return_value="answer")
        await channel.ask_question(
            chat_id="",
            question_id="q2",
            question="What?",
        )
        call_kwargs = channel._bot.ask_question.call_args[1]
        assert call_kwargs["chat_id"] in {111, 222}

    async def test_wrap_callback(self, channel):
        """Test _wrap_callback converts int chat_id to str."""
        callback = AsyncMock()
        channel._message_callback = callback
        await channel._wrap_callback(123, "hello", "task-1")
        callback.assert_called_once_with("123", "hello", "task-1")

    async def test_wrap_callback_no_task_id(self, channel):
        """Test _wrap_callback works without task_id."""
        callback = AsyncMock()
        channel._message_callback = callback
        await channel._wrap_callback(123, "hello")
        callback.assert_called_once_with("123", "hello", None)

    async def test_wrap_callback_no_callback_set(self, channel):
        """Test _wrap_callback does nothing if no callback registered."""
        channel._message_callback = None
        # Should not raise
        await channel._wrap_callback(123, "hello")

    async def test_start_wires_callback(self):
        """Test that start wires up message callback to bot."""
        ch = TelegramChannel(bot_token="test-token", allowed_chat_ids=[111])
        ch._bot = AsyncMock()
        ch._bot._allowed_chat_ids = {111}

        callback = AsyncMock()
        ch.on_message(callback)

        await ch.start()

        # Bot's on_message should have been called
        ch._bot.on_message.assert_called_once()
        ch._bot.start.assert_called_once()
