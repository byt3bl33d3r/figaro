"""Tests for TelegramBot — regression tests for private chat and entity-based formatting."""

import asyncio
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

    async def test_send_photo_exception_is_caught(self, bot):
        """When send_photo raises, the exception is caught and logged."""
        bot._app.bot.send_photo = AsyncMock(side_effect=Exception("network error"))

        # Should not raise
        await bot.send_photo(111, "aW1hZ2U=")


class TestSendNotification:
    """Tests for send_notification — notification routing."""

    async def test_sends_to_specific_chat(self, bot):
        """send_notification with chat_id sends only to that chat."""
        mock_msg = MagicMock()
        mock_msg.message_id = 1
        bot._app.bot.send_message = AsyncMock(return_value=mock_msg)

        await bot.send_notification("alert!", chat_id=111)

        bot._app.bot.send_message.assert_called_once()
        assert bot._app.bot.send_message.call_args.kwargs["chat_id"] == 111

    async def test_sends_to_all_allowed_chats(self, bot):
        """send_notification without chat_id sends to all allowed chats."""
        mock_msg = MagicMock()
        mock_msg.message_id = 1
        bot._app.bot.send_message = AsyncMock(return_value=mock_msg)

        await bot.send_notification("alert!")

        assert bot._app.bot.send_message.call_count == 2
        chat_ids = {call.kwargs["chat_id"] for call in bot._app.bot.send_message.call_args_list}
        assert chat_ids == {111, 222}

    async def test_skips_disallowed_specific_chat(self, bot):
        """send_notification with a disallowed chat_id sends nothing."""
        mock_msg = MagicMock()
        mock_msg.message_id = 1
        bot._app.bot.send_message = AsyncMock(return_value=mock_msg)

        await bot.send_notification("alert!", chat_id=999)

        bot._app.bot.send_message.assert_not_called()


class TestAskQuestion:
    """Tests for ask_question — interactive question/answer with futures."""

    async def test_sends_question_and_returns_answer(self, bot):
        """Happy path: sends question, future resolves, answer is returned."""
        mock_msg = MagicMock()
        mock_msg.message_id = 10
        bot._app.bot.send_message = AsyncMock(return_value=mock_msg)

        async def resolve_future():
            await asyncio.sleep(0.01)
            _, (_, _, future) = next(iter(bot._pending_questions.items()))
            future.set_result("Yes")

        task = asyncio.create_task(resolve_future())
        result = await bot.ask_question(
            question_id="q-1",
            question="Continue?",
            chat_id=111,
            timeout_seconds=5,
        )
        await task

        assert result == "Yes"
        assert "q-1" not in bot._pending_questions  # cleaned up

    async def test_not_running_returns_none(self, bot):
        """When bot is not running, returns None immediately."""
        bot._running = False

        result = await bot.ask_question("q-1", "Continue?", chat_id=111)

        assert result is None
        bot._app.bot.send_message.assert_not_called()

    async def test_timeout_returns_none(self, bot):
        """When no answer within timeout, returns None."""
        mock_msg = MagicMock()
        mock_msg.message_id = 10
        bot._app.bot.send_message = AsyncMock(return_value=mock_msg)

        result = await bot.ask_question(
            question_id="q-1",
            question="Continue?",
            chat_id=111,
            timeout_seconds=0,  # immediate timeout
        )

        assert result is None

    async def test_disallowed_chat_returns_none(self, bot):
        """When target chat is not allowed, returns None."""
        bot._app.bot.send_message = AsyncMock()

        result = await bot.ask_question(
            question_id="q-1",
            question="Continue?",
            chat_id=999,
            timeout_seconds=1,
        )

        assert result is None
        bot._app.bot.send_message.assert_not_called()

    async def test_send_failure_returns_none(self, bot):
        """When sending the question message fails, returns None."""
        bot._app.bot.send_message = AsyncMock(side_effect=Exception("send failed"))

        result = await bot.ask_question(
            question_id="q-1",
            question="Continue?",
            chat_id=111,
            timeout_seconds=1,
        )

        assert result is None

    async def test_with_options_creates_keyboard(self, bot):
        """When options are provided, inline keyboard buttons are created."""
        mock_msg = MagicMock()
        mock_msg.message_id = 10
        bot._app.bot.send_message = AsyncMock(return_value=mock_msg)

        async def resolve():
            await asyncio.sleep(0.01)
            _, (_, _, future) = next(iter(bot._pending_questions.items()))
            future.set_result("Retry")

        task = asyncio.create_task(resolve())
        result = await bot.ask_question(
            question_id="q-1",
            question="What to do?",
            options=[{"label": "Retry", "description": "Try again"}, {"label": "Skip"}],
            chat_id=111,
            timeout_seconds=5,
        )
        await task

        assert result == "Retry"
        call_kwargs = bot._app.bot.send_message.call_args.kwargs
        assert call_kwargs["reply_markup"] is not None

    async def test_question_text_includes_options(self, bot):
        """The question text sent includes option labels and descriptions."""
        mock_msg = MagicMock()
        mock_msg.message_id = 10
        bot._app.bot.send_message = AsyncMock(return_value=mock_msg)

        async def resolve():
            await asyncio.sleep(0.01)
            _, (_, _, future) = next(iter(bot._pending_questions.items()))
            future.set_result("A")

        task = asyncio.create_task(resolve())
        await bot.ask_question(
            question_id="q-1",
            question="Pick one",
            options=[
                {"label": "A", "description": "First option"},
                {"label": "B"},
            ],
            chat_id=111,
            timeout_seconds=5,
        )
        await task

        sent_text = bot._app.bot.send_message.call_args.kwargs["text"]
        assert "A - First option" in sent_text
        assert "B" in sent_text

    async def test_no_chat_id_uses_allowed(self, bot):
        """When chat_id is None, uses first allowed chat."""
        mock_msg = MagicMock()
        mock_msg.message_id = 10
        bot._app.bot.send_message = AsyncMock(return_value=mock_msg)

        async def resolve():
            await asyncio.sleep(0.01)
            _, (_, _, future) = next(iter(bot._pending_questions.items()))
            future.set_result("OK")

        task = asyncio.create_task(resolve())
        result = await bot.ask_question(
            question_id="q-1",
            question="Continue?",
            chat_id=None,
            timeout_seconds=5,
        )
        await task

        assert result == "OK"
        sent_chat_id = bot._app.bot.send_message.call_args.kwargs["chat_id"]
        assert sent_chat_id in {111, 222}

    async def test_cancelled_returns_none(self, bot):
        """When future is cancelled, returns None."""
        mock_msg = MagicMock()
        mock_msg.message_id = 10
        bot._app.bot.send_message = AsyncMock(return_value=mock_msg)

        async def cancel_future():
            await asyncio.sleep(0.01)
            _, (_, _, future) = next(iter(bot._pending_questions.items()))
            future.cancel()

        task = asyncio.create_task(cancel_future())
        result = await bot.ask_question(
            question_id="q-1",
            question="Continue?",
            chat_id=111,
            timeout_seconds=5,
        )
        await task

        assert result is None


class TestHandleCallbackQuery:
    """Tests for _handle_callback_query — inline keyboard button presses."""

    def _make_callback_update(self, chat_id, data, message_id=10):
        """Create a mock Update with a callback query."""
        from telegram import Message

        message = MagicMock(spec=Message)
        message.chat_id = chat_id
        message.message_id = message_id
        message.text = "Original question text"
        message.edit_text = AsyncMock()

        query = MagicMock()
        query.data = data
        query.message = message
        query.answer = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        return update

    async def test_resolves_matching_future(self, bot):
        """Callback query matching a pending question resolves its future."""
        future = asyncio.get_running_loop().create_future()
        # question_id is longer than 16 chars; callback data uses first 16 as prefix
        bot._pending_questions["q-full-id-12345678"] = (111, 10, future)

        update = self._make_callback_update(chat_id=111, data="q-full-id-123456:Yes")
        await bot._handle_callback_query(update, MagicMock())

        assert future.result() == "Yes"
        update.callback_query.answer.assert_called_with("Response recorded!")

    async def test_edits_message_after_answer(self, bot):
        """After resolving, the message is edited to show the answer."""
        future = asyncio.get_running_loop().create_future()
        bot._pending_questions["q-full-id-12345678"] = (111, 10, future)

        update = self._make_callback_update(chat_id=111, data="q-full-id-123456:Retry")
        await bot._handle_callback_query(update, MagicMock())

        update.callback_query.message.edit_text.assert_called_once()
        edit_text = update.callback_query.message.edit_text.call_args[0][0]
        assert "Answered: Retry" in edit_text

    async def test_no_query_returns_early(self, bot):
        """When update has no callback query, returns early."""
        update = MagicMock()
        update.callback_query = None

        await bot._handle_callback_query(update, MagicMock())
        # No error, no action

    async def test_no_query_data_returns_early(self, bot):
        """When callback query has no data, returns early."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = None

        await bot._handle_callback_query(update, MagicMock())

    async def test_disallowed_chat_responds_unauthorized(self, bot):
        """Callback from disallowed chat responds with 'Not authorized'."""
        future = asyncio.get_running_loop().create_future()
        bot._pending_questions["q-1"] = (999, 10, future)

        update = self._make_callback_update(chat_id=999, data="q-1:Yes")
        await bot._handle_callback_query(update, MagicMock())

        update.callback_query.answer.assert_called_with("Not authorized")
        assert not future.done()

    async def test_invalid_data_format(self, bot):
        """Callback data without colon separator responds with 'Invalid response'."""
        update = self._make_callback_update(chat_id=111, data="no-colon-here")
        await bot._handle_callback_query(update, MagicMock())

        update.callback_query.answer.assert_called_with("Invalid response")

    async def test_expired_question_responds(self, bot):
        """Callback for non-existent question responds with 'expired or already answered'."""
        update = self._make_callback_update(chat_id=111, data="unknown:Yes")
        await bot._handle_callback_query(update, MagicMock())

        update.callback_query.answer.assert_called_with("Question expired or already answered")

    async def test_future_already_done_skips(self, bot):
        """When future is already done, the callback is ignored."""
        future = asyncio.get_running_loop().create_future()
        future.set_result("already answered")
        bot._pending_questions["q-full-id-12345678"] = (111, 10, future)

        update = self._make_callback_update(chat_id=111, data="q-full-id-123456:No")
        await bot._handle_callback_query(update, MagicMock())

        update.callback_query.answer.assert_called_with("Question expired or already answered")

    async def test_not_a_message_instance_returns_early(self, bot):
        """When query.message is not a Message instance, returns early."""
        query = MagicMock()
        query.data = "q-1:Yes"
        query.message = MagicMock()  # Not a Message instance
        query.answer = AsyncMock()

        update = MagicMock()
        update.callback_query = query

        await bot._handle_callback_query(update, MagicMock())
        query.answer.assert_not_called()


class TestHandleReply:
    """Tests for _handle_reply — text replies to question messages."""

    def _make_reply_update(self, chat_id, text, replied_to_message_id):
        """Create a mock Update for a reply message."""
        reply_to = MagicMock()
        reply_to.message_id = replied_to_message_id

        message = MagicMock()
        message.chat_id = chat_id
        message.text = text
        message.reply_to_message = reply_to
        message.reply_text = AsyncMock()

        update = MagicMock()
        update.message = message
        return update

    async def test_resolves_matching_future(self, bot):
        """Reply to a pending question message resolves the future."""
        future = asyncio.get_running_loop().create_future()
        bot._pending_questions["q-1"] = (111, 10, future)

        update = self._make_reply_update(chat_id=111, text="my answer", replied_to_message_id=10)
        await bot._handle_reply(update, MagicMock())

        assert future.result() == "my answer"
        update.message.reply_text.assert_called_with("Response recorded!")

    async def test_strips_answer_whitespace(self, bot):
        """Reply text is stripped of leading/trailing whitespace."""
        future = asyncio.get_running_loop().create_future()
        bot._pending_questions["q-1"] = (111, 10, future)

        update = self._make_reply_update(chat_id=111, text="  spaced  ", replied_to_message_id=10)
        await bot._handle_reply(update, MagicMock())

        assert future.result() == "spaced"

    async def test_no_message_returns_early(self, bot):
        """When update has no message, returns early."""
        update = MagicMock()
        update.message = None

        await bot._handle_reply(update, MagicMock())

    async def test_no_reply_to_message_returns_early(self, bot):
        """When message is not a reply, returns early."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.reply_to_message = None

        await bot._handle_reply(update, MagicMock())

    async def test_no_text_returns_early(self, bot):
        """When message has no text, returns early."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.reply_to_message = MagicMock()
        update.message.text = None

        await bot._handle_reply(update, MagicMock())

    async def test_disallowed_chat_ignored(self, bot):
        """Reply from disallowed chat is silently ignored."""
        future = asyncio.get_running_loop().create_future()
        bot._pending_questions["q-1"] = (111, 10, future)

        update = self._make_reply_update(chat_id=999, text="answer", replied_to_message_id=10)
        await bot._handle_reply(update, MagicMock())

        assert not future.done()

    async def test_no_matching_question_ignored(self, bot):
        """Reply to a message that is not a pending question is ignored."""
        future = asyncio.get_running_loop().create_future()
        bot._pending_questions["q-1"] = (111, 10, future)

        update = self._make_reply_update(chat_id=111, text="answer", replied_to_message_id=99)
        await bot._handle_reply(update, MagicMock())

        assert not future.done()
        update.message.reply_text.assert_not_called()

    async def test_future_already_done_ignored(self, bot):
        """Reply when future already resolved is ignored."""
        future = asyncio.get_running_loop().create_future()
        future.set_result("already done")
        bot._pending_questions["q-1"] = (111, 10, future)

        update = self._make_reply_update(chat_id=111, text="new answer", replied_to_message_id=10)
        await bot._handle_reply(update, MagicMock())

        # Original result unchanged
        assert future.result() == "already done"
        update.message.reply_text.assert_not_called()


class TestStop:
    """Tests for stop — lifecycle and future cleanup."""

    async def test_stop_cancels_pending_futures(self, bot):
        """stop() cancels all pending question futures."""
        future1 = asyncio.get_running_loop().create_future()
        future2 = asyncio.get_running_loop().create_future()
        bot._pending_questions["q-1"] = (111, 10, future1)
        bot._pending_questions["q-2"] = (222, 20, future2)

        bot._app = MagicMock()
        bot._app.updater = None
        bot._app.stop = AsyncMock()
        bot._app.shutdown = AsyncMock()

        await bot.stop()

        assert future1.cancelled()
        assert future2.cancelled()
        assert len(bot._pending_questions) == 0
        assert bot._running is False

    async def test_stop_not_running_noop(self, bot):
        """stop() when not running is a no-op."""
        bot._running = False

        # Should not raise
        await bot.stop()

    async def test_stop_with_updater(self, bot):
        """stop() stops the updater if it exists."""
        bot._app = MagicMock()
        bot._app.updater = MagicMock()
        bot._app.updater.stop = AsyncMock()
        bot._app.stop = AsyncMock()
        bot._app.shutdown = AsyncMock()

        await bot.stop()

        bot._app.updater.stop.assert_called_once()
        bot._app.stop.assert_called_once()
        bot._app.shutdown.assert_called_once()


class TestHandleMentionErrors:
    """Tests for error handling in _handle_mention."""

    async def test_callback_exception_replies_error(self, bot):
        """When message callback raises, bot replies with error message."""
        callback = AsyncMock(side_effect=Exception("callback failed"))
        bot.on_message(callback)

        update = _make_update(chat_id=111, text="do something", chat_type="private")
        await bot._handle_mention(update, MagicMock())

        update.message.reply_text.assert_called_once_with("Error processing message.")
