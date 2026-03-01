"""Telegram channel implementation."""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from .bot import TelegramBot

logger = logging.getLogger(__name__)


class TelegramChannel:
    """Telegram communication channel implementing the Channel protocol."""

    def __init__(
        self,
        bot_token: str,
        allowed_chat_ids: list[int] | None = None,
    ) -> None:
        self._bot = TelegramBot(
            bot_token=bot_token,
            allowed_chat_ids=allowed_chat_ids or [],
        )
        self._message_callback: Callable[[str, str, str | None], Awaitable[None]] | None = None

    @property
    def name(self) -> str:
        return "telegram"

    async def start(self) -> None:
        """Start the Telegram bot."""
        # Wire up message callback
        if self._message_callback:
            self._bot.on_message(self._wrap_callback)
        await self._bot.start()

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        await self._bot.stop()

    async def send_message(self, chat_id: str, text: str, **kwargs: Any) -> None:
        """Send message via Telegram."""
        int_chat_id = (
            int(chat_id)
            if chat_id
            else (list(self._bot._allowed_chat_ids)[0] if self._bot._allowed_chat_ids else 0)
        )
        parse_mode = kwargs.get("parse_mode", "Markdown")
        await self._bot.send_message(int_chat_id, text, parse_mode=parse_mode)

    async def send_photo(self, chat_id: str, image_b64: str, caption: str | None = None) -> None:
        """Send a photo via Telegram."""
        await self._bot.send_photo(int(chat_id), image_b64, caption)

    async def ask_question(
        self,
        chat_id: str,
        question_id: str,
        question: str,
        options: list[dict[str, Any]] | None = None,
        timeout: int = 300,
    ) -> str | None:
        """Ask a question via Telegram and wait for response."""
        int_chat_id = (
            int(chat_id)
            if chat_id
            else (list(self._bot._allowed_chat_ids)[0] if self._bot._allowed_chat_ids else 0)
        )
        return await self._bot.ask_question(
            question_id=question_id,
            question=question,
            options=options,
            chat_id=int_chat_id,
            timeout_seconds=timeout,
        )

    def on_message(self, callback: Callable[[str, str, str | None], Awaitable[None]]) -> None:
        """Register callback for incoming messages."""
        self._message_callback = callback

    async def _wrap_callback(self, chat_id: int, text: str, task_id: str | None = None) -> None:
        """Wrap the internal bot callback to match Channel protocol signature."""
        if self._message_callback:
            await self._message_callback(str(chat_id), text, task_id)
