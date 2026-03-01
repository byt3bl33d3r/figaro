"""Telegram bot for gateway user communication."""

import asyncio
import base64
import io
import logging
from collections.abc import Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegramify_markdown import convert as md_to_telegram
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)


class TelegramBot:
    """Telegram bot for gateway to communicate with users."""

    def __init__(
        self,
        bot_token: str,
        allowed_chat_ids: list[int],
    ) -> None:
        self._bot_token = bot_token
        self._allowed_chat_ids = set(allowed_chat_ids)
        self._app: Application | None = None
        self._bot_username: str | None = None
        self._running = False

        # Callbacks
        self._message_callback: Callable[[int, str], Awaitable[None]] | None = None

        # Pending questions (for ask_user tool)
        # Maps question_id -> (chat_id, message_id, future)
        self._pending_questions: dict[str, tuple[int, int, asyncio.Future[str]]] = {}

    def on_message(
        self,
        callback: Callable[[int, str], Awaitable[None]],
    ) -> None:
        """
        Set callback for when a new message is received.

        The callback receives (chat_id, message_text).
        """
        self._message_callback = callback

    async def start(self) -> None:
        """Start the Telegram bot in polling mode."""
        if self._running:
            return

        self._app = Application.builder().token(self._bot_token).build()

        # Handle inline keyboard button presses (for quick option selection)
        self._app.add_handler(CallbackQueryHandler(self._handle_callback_query))

        # Handle text message replies (for question responses)
        self._app.add_handler(
            MessageHandler(
                filters.TEXT & filters.REPLY & ~filters.COMMAND,
                self._handle_reply,
            )
        )

        # Handle non-reply text messages (for new tasks via bot mention)
        self._app.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & ~filters.REPLY,
                self._handle_mention,
            )
        )

        # Initialize and start polling
        await self._app.initialize()
        # Clear any stale polling sessions from previous runs
        await self._app.bot.delete_webhook(drop_pending_updates=True)
        await self._app.start()
        if self._app.updater:
            await self._app.updater.start_polling(drop_pending_updates=True)

        # Cache bot username for mention detection
        bot_info = await self._app.bot.get_me()
        self._bot_username = bot_info.username

        self._running = True
        logger.info(f"Telegram bot started (@{self._bot_username})")

    async def stop(self) -> None:
        """Stop the Telegram bot gracefully."""
        if not self._running or not self._app:
            return

        if self._app.updater:
            await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()

        # Cancel pending questions
        for _question_id, (_, _, future) in self._pending_questions.items():
            if not future.done():
                future.cancel()
        self._pending_questions.clear()

        self._running = False
        logger.info("Telegram bot stopped")

    async def run(self) -> None:
        """Run the bot (start and wait until stopped)."""
        await self.start()
        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def send_message(
        self,
        chat_id: int,
        text: str,
    ) -> int | None:
        """Send a message to a chat. Returns message_id if successful.

        Markdown in the text is converted to Telegram entities via
        ``telegramify-markdown`` so formatting renders correctly without
        needing a ``parse_mode``.
        """
        if not self._app or not self._running:
            logger.warning("Telegram bot not running, cannot send message")
            return None

        if chat_id not in self._allowed_chat_ids:
            logger.warning(f"Chat {chat_id} not in allowed list")
            return None

        # Telegram message limit is 4096 characters
        if len(text) > 4000:
            text = text[:4000] + "..."

        # Convert standard markdown to Telegram (text, entities)
        try:
            tg_text, entities = md_to_telegram(text)
            entity_dicts = [e.to_dict() for e in entities] if entities else None
        except Exception:
            logger.warning("Failed to convert markdown, sending as plain text")
            tg_text, entity_dicts = text, None

        try:
            msg = await self._app.bot.send_message(
                chat_id=chat_id,
                text=tg_text,
                entities=entity_dicts,
            )
            return msg.message_id
        except Exception:
            # Retry as plain text if entity send failed
            logger.warning("Failed to send message with entities, retrying as plain text")
            try:
                msg = await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                )
                return msg.message_id
            except Exception:
                logger.exception(f"Failed to send plain text message to chat {chat_id}")
                return None

    async def send_photo(
        self,
        chat_id: int,
        image_b64: str,
        caption: str | None = None,
    ) -> None:
        """Send a photo to a chat from a base64-encoded image."""
        if not self._app or not self._running:
            logger.warning("Telegram bot not running, cannot send photo")
            return

        if chat_id not in self._allowed_chat_ids:
            logger.warning(f"Chat {chat_id} not in allowed list")
            return

        try:
            image_bytes = base64.b64decode(image_b64)
            await self._app.bot.send_photo(
                chat_id=chat_id,
                photo=io.BytesIO(image_bytes),
                caption=caption,
            )
        except Exception:
            logger.exception(f"Failed to send photo to chat {chat_id}")

    async def send_notification(
        self,
        text: str,
        chat_id: int | None = None,
    ) -> None:
        """Send a notification to a specific chat or all allowed chats."""
        target_chats = [chat_id] if chat_id else list(self._allowed_chat_ids)

        for cid in target_chats:
            if cid in self._allowed_chat_ids:
                await self.send_message(cid, text)

    async def ask_question(
        self,
        question_id: str,
        question: str,
        options: list[dict[str, str]] | None = None,
        chat_id: int | None = None,
        timeout_seconds: int = 300,
    ) -> str | None:
        """
        Ask a question and wait for response.

        Args:
            question_id: Unique ID for this question
            question: The question text
            options: Optional list of options with 'label' and 'description'
            chat_id: Specific chat to send to (or all allowed chats)
            timeout_seconds: How long to wait for response

        Returns:
            The user's answer or None if timeout
        """
        if not self._app or not self._running:
            return None

        target_chats = [chat_id] if chat_id else list(self._allowed_chat_ids)

        # Build message
        message_lines = ["Question:", "", question]

        if options:
            message_lines.append("")
            for i, opt in enumerate(options, 1):
                label = opt.get("label", f"Option {i}")
                description = opt.get("description", "")
                if description:
                    message_lines.append(f"  {i}. {label} - {description}")
                else:
                    message_lines.append(f"  {i}. {label}")

        message_lines.append("")
        message_lines.append("Reply to this message with your answer.")

        message_text = "\n".join(message_lines)

        # Build keyboard for quick selection
        keyboard = None
        if options and len(options) <= 4:
            buttons = []
            for opt in options:
                label = opt.get("label", "")
                callback_data = f"{question_id[:16]}:{label[:30]}"
                buttons.append([InlineKeyboardButton(label, callback_data=callback_data)])
            keyboard = InlineKeyboardMarkup(buttons)

        # Create future for response
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()

        # Convert markdown in the question text to Telegram entities
        try:
            tg_text, entities = md_to_telegram(message_text)
            entity_dicts = [e.to_dict() for e in entities] if entities else None
        except Exception:
            tg_text, entity_dicts = message_text, None

        # Send to target chats and track
        for cid in target_chats:
            if cid not in self._allowed_chat_ids:
                continue
            try:
                msg = await self._app.bot.send_message(
                    chat_id=cid,
                    text=tg_text,
                    entities=entity_dicts,
                    reply_markup=keyboard,
                )
                # Track this question
                self._pending_questions[question_id] = (cid, msg.message_id, future)
                logger.info(f"Sent question {question_id} to chat {cid}")
                break  # Only send to first available chat
            except Exception:
                logger.exception(f"Failed to send question to chat {cid}")

        if question_id not in self._pending_questions:
            return None

        # Wait for response
        try:
            answer = await asyncio.wait_for(future, timeout=timeout_seconds)
            return answer
        except asyncio.TimeoutError:
            logger.warning(f"Question {question_id} timed out")
            return None
        except asyncio.CancelledError:
            return None
        finally:
            self._pending_questions.pop(question_id, None)

    async def _handle_callback_query(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle inline keyboard button presses."""
        query = update.callback_query
        if not query or not query.data or not query.message:
            return

        # Ensure we have a proper Message (not InaccessibleMessage)
        if not isinstance(query.message, Message):
            return

        chat_id = query.message.chat_id
        if chat_id not in self._allowed_chat_ids:
            await query.answer("Not authorized")
            return

        # Parse callback data: question_id_prefix:answer
        parts = query.data.split(":", 1)
        if len(parts) != 2:
            await query.answer("Invalid response")
            return

        question_id_prefix, answer = parts

        # Find matching pending question
        for question_id, (
            q_chat_id,
            q_msg_id,
            future,
        ) in self._pending_questions.items():
            if question_id.startswith(question_id_prefix) and q_chat_id == chat_id:
                if not future.done():
                    future.set_result(answer)
                    await query.answer("Response recorded!")

                    # Edit message to show it was answered
                    try:
                        msg_text = getattr(query.message, "text", "") or ""
                        await query.message.edit_text(
                            msg_text + f"\n\nAnswered: {answer}",
                        )
                    except Exception:
                        pass
                    return

        await query.answer("Question expired or already answered")

    async def _handle_reply(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle text message replies to questions."""
        message = update.message
        if not message or not message.reply_to_message or not message.text:
            return

        chat_id = message.chat_id
        if chat_id not in self._allowed_chat_ids:
            return

        replied_to_message_id = message.reply_to_message.message_id
        answer_text = message.text.strip()

        # Find matching pending question
        for question_id, (q_chat_id, q_msg_id, future) in list(self._pending_questions.items()):
            if q_chat_id == chat_id and q_msg_id == replied_to_message_id:
                if not future.done():
                    future.set_result(answer_text)
                    await message.reply_text("Response recorded!")
                    logger.info(f"Received reply for question {question_id}")
                return

        # Not a reply to a pending question - ignore

    async def _handle_mention(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle messages that mention the bot to create tasks."""
        message = update.message
        if not message or not message.text:
            return

        chat_id = message.chat_id
        text = message.text

        if chat_id not in self._allowed_chat_ids:
            return

        if not self._bot_username:
            return

        # In private chats, treat the entire message as a task prompt.
        # In group chats, require an explicit @mention.
        mention = f"@{self._bot_username}"
        prompt = None

        if message.chat.type == "private":
            prompt = text.strip()
        elif mention.lower() in text.lower():
            # Extract prompt (everything after the mention)
            mention_idx = text.lower().find(mention.lower())
            prompt = text[mention_idx + len(mention) :].strip()

        if prompt is None:
            return  # Bot not mentioned in group chat, ignore

        if not prompt:
            await message.reply_text(
                f"Please provide a task description after mentioning me.\n"
                f"Example: {mention} Check the price on amazon.com"
            )
            return

        if not self._message_callback:
            await message.reply_text("Task processing is not configured.")
            return

        try:
            # Call the message callback
            await self._message_callback(chat_id, prompt)
        except Exception:
            logger.exception("Error handling Telegram message")
            await message.reply_text("Error processing message.")
