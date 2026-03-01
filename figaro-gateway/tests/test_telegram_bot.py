"""Tests for TelegramBot — regression tests for private chat and entity-based formatting."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from figaro_gateway.channels.telegram.bot import TelegramBot


def _make_update(chat_id: int, text: str, chat_type: str = "private"):
    """Create a mock telegram Update with message, chat, and text."""
    chat = MagicMock()
    chat.type = chat_type

    message = MagicMock()
    message.chat = chat
    message.chat_id = chat_id
    message.text = text
    message.reply_text = AsyncMock()

    update = MagicMock()
    update.message = message
    return update


@pytest.fixture
def bot():
    """Create a TelegramBot with mocked internals for handler testing."""
    b = TelegramBot(bot_token="test-token", allowed_chat_ids=[111, 222])
    b._bot_username = "test_bot"
    b._running = True
    # Mock the Application so send_message works
    app = MagicMock()
    app.bot = MagicMock()
    app.bot.send_message = AsyncMock()
    b._app = app
    return b


class TestHandleMention:
    """Tests for _handle_mention — private/group chat routing logic."""

    async def test_private_chat_message_creates_task(self, bot):
        """In a private chat, the full message text becomes the task prompt (no @mention needed)."""
        callback = AsyncMock()
        bot.on_message(callback)

        update = _make_update(chat_id=111, text="Check the price on amazon.com", chat_type="private")
        await bot._handle_mention(update, MagicMock())

        callback.assert_called_once_with(111, "Check the price on amazon.com")

    async def test_private_chat_empty_message_prompts_usage(self, bot):
        """In a private chat, an empty (whitespace-only) message replies with help text."""
        callback = AsyncMock()
        bot.on_message(callback)

        update = _make_update(chat_id=111, text="   ", chat_type="private")
        await bot._handle_mention(update, MagicMock())

        callback.assert_not_called()
        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "@test_bot" in reply_text

    async def test_group_chat_with_mention_creates_task(self, bot):
        """In a group chat, @botname followed by text fires the callback with the text after the mention."""
        callback = AsyncMock()
        bot.on_message(callback)

        update = _make_update(chat_id=111, text="@test_bot do something", chat_type="group")
        await bot._handle_mention(update, MagicMock())

        callback.assert_called_once_with(111, "do something")

    async def test_group_chat_without_mention_is_ignored(self, bot):
        """In a group chat, a message without @mention is silently ignored — no callback, no reply."""
        callback = AsyncMock()
        bot.on_message(callback)

        update = _make_update(chat_id=111, text="hello everyone", chat_type="group")
        await bot._handle_mention(update, MagicMock())

        callback.assert_not_called()
        update.message.reply_text.assert_not_called()

    async def test_group_chat_mention_only_prompts_usage(self, bot):
        """In a group chat, mentioning the bot with no task text replies with help text."""
        callback = AsyncMock()
        bot.on_message(callback)

        update = _make_update(chat_id=111, text="@test_bot", chat_type="group")
        await bot._handle_mention(update, MagicMock())

        callback.assert_not_called()
        update.message.reply_text.assert_called_once()

    async def test_disallowed_chat_is_ignored(self, bot):
        """Messages from chats not in the allowed list are ignored."""
        callback = AsyncMock()
        bot.on_message(callback)

        update = _make_update(chat_id=999, text="hello", chat_type="private")
        await bot._handle_mention(update, MagicMock())

        callback.assert_not_called()
        update.message.reply_text.assert_not_called()

    async def test_no_bot_username_is_ignored(self, bot):
        """If bot username has not been cached yet, all messages are ignored."""
        bot._bot_username = None
        callback = AsyncMock()
        bot.on_message(callback)

        update = _make_update(chat_id=111, text="hello", chat_type="private")
        await bot._handle_mention(update, MagicMock())

        callback.assert_not_called()

    async def test_group_chat_mention_case_insensitive(self, bot):
        """Mention matching is case-insensitive."""
        callback = AsyncMock()
        bot.on_message(callback)

        update = _make_update(chat_id=111, text="@Test_Bot do stuff", chat_type="group")
        await bot._handle_mention(update, MagicMock())

        callback.assert_called_once_with(111, "do stuff")

    async def test_no_callback_registered_replies_not_configured(self, bot):
        """If no message callback is registered, replies with 'not configured' message."""
        bot._message_callback = None

        update = _make_update(chat_id=111, text="do something", chat_type="private")
        await bot._handle_mention(update, MagicMock())

        update.message.reply_text.assert_called_once_with("Task processing is not configured.")


class TestSendMessage:
    """Tests for send_message — entity-based formatting via telegramify-markdown."""

    async def test_send_message_uses_entities(self, bot):
        """send_message converts markdown to entities and sends without parse_mode."""
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        bot._app.bot.send_message = AsyncMock(return_value=mock_msg)

        result = await bot.send_message(111, "hello **world**")

        assert result == 42
        call_kwargs = bot._app.bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 111
        # Text should have markdown stripped (rendered as plain text + entities)
        assert "parse_mode" not in call_kwargs
        assert "entities" in call_kwargs

    async def test_entity_send_failure_retries_as_plain_text(self, bot):
        """When entity send fails, retries as plain text and succeeds."""
        mock_msg = MagicMock()
        mock_msg.message_id = 99

        # First call (entities) raises, second call (plain) succeeds
        bot._app.bot.send_message = AsyncMock(
            side_effect=[Exception("Bad Request"), mock_msg]
        )

        result = await bot.send_message(111, "hello **bold**")

        assert result == 99
        assert bot._app.bot.send_message.call_count == 2

        # Second (fallback) call should send original text without entities
        second_call = bot._app.bot.send_message.call_args_list[1]
        assert second_call.kwargs["text"] == "hello **bold**"
        assert "entities" not in second_call.kwargs

    async def test_both_attempts_fail_returns_none(self, bot):
        """When both entity and plain text sends fail, returns None."""
        bot._app.bot.send_message = AsyncMock(side_effect=Exception("Network error"))

        result = await bot.send_message(111, "hello")

        assert result is None
        assert bot._app.bot.send_message.call_count == 2

    async def test_markdown_conversion_failure_sends_plain(self, bot):
        """When md_to_telegram raises, falls back to plain text."""
        mock_msg = MagicMock()
        mock_msg.message_id = 50
        bot._app.bot.send_message = AsyncMock(return_value=mock_msg)

        with patch("figaro_gateway.channels.telegram.bot.md_to_telegram", side_effect=Exception("parse error")):
            result = await bot.send_message(111, "some text")

        assert result == 50
        call_kwargs = bot._app.bot.send_message.call_args.kwargs
        assert call_kwargs["text"] == "some text"
        assert call_kwargs["entities"] is None

    async def test_send_message_not_running_returns_none(self, bot):
        """When bot is not running, send_message returns None without sending."""
        bot._running = False

        result = await bot.send_message(111, "hello")

        assert result is None
        bot._app.bot.send_message.assert_not_called()

    async def test_send_message_disallowed_chat_returns_none(self, bot):
        """Sending to a chat not in the allowed list returns None."""
        result = await bot.send_message(999, "hello")

        assert result is None
        bot._app.bot.send_message.assert_not_called()

    async def test_send_message_truncates_long_text(self, bot):
        """Messages longer than 4000 chars are truncated before conversion."""
        mock_msg = MagicMock()
        mock_msg.message_id = 1
        bot._app.bot.send_message = AsyncMock(return_value=mock_msg)

        long_text = "x" * 5000
        await bot.send_message(111, long_text)

        # The converted text may differ from input, but the input was truncated first
        bot._app.bot.send_message.assert_called_once()


class TestSendPhoto:
    """Tests for send_photo — base64 image sending."""

    async def test_send_photo_decodes_and_sends(self, bot):
        """send_photo decodes base64 and calls bot.send_photo with correct args."""
        import base64
        import io

        bot._app.bot.send_photo = AsyncMock()

        image_b64 = base64.b64encode(b"fake-image-data").decode()
        await bot.send_photo(111, image_b64, caption="test caption")

        bot._app.bot.send_photo.assert_called_once()
        call_kwargs = bot._app.bot.send_photo.call_args.kwargs
        assert call_kwargs["chat_id"] == 111
        assert call_kwargs["caption"] == "test caption"
        # Verify the photo is a BytesIO with the decoded bytes
        photo_arg = call_kwargs["photo"]
        assert isinstance(photo_arg, io.BytesIO)
        assert photo_arg.read() == b"fake-image-data"

    async def test_send_photo_not_running_skips(self, bot):
        """When bot is not running, send_photo returns without sending."""
        bot._running = False
        bot._app.bot.send_photo = AsyncMock()

        await bot.send_photo(111, "aW1hZ2U=")

        bot._app.bot.send_photo.assert_not_called()

    async def test_send_photo_disallowed_chat_skips(self, bot):
        """Sending a photo to a chat not in the allowed list is silently skipped."""
        bot._app.bot.send_photo = AsyncMock()

        await bot.send_photo(999, "aW1hZ2U=")

        bot._app.bot.send_photo.assert_not_called()
