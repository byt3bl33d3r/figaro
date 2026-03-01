"""Channel protocol — interface that all communication channels must implement."""

from __future__ import annotations

from typing import Any, Protocol, Callable, Awaitable


class Channel(Protocol):
    """Interface for communication channels (Telegram, WhatsApp, Slack, etc.)."""

    @property
    def name(self) -> str:
        """Channel identifier (e.g., 'telegram', 'whatsapp', 'slack')."""
        ...

    async def start(self) -> None:
        """Start the channel (connect, start polling, etc.)."""
        ...

    async def stop(self) -> None:
        """Graceful shutdown."""
        ...

    async def send_message(self, chat_id: str, text: str, **kwargs: Any) -> None:
        """Send a text message to a chat/conversation."""
        ...

    async def ask_question(
        self,
        chat_id: str,
        question_id: str,
        question: str,
        options: list[dict[str, Any]] | None = None,
        timeout: int = 300,
    ) -> str | None:
        """Ask a question and wait for response. Returns answer text or None on timeout."""
        ...

    def on_message(self, callback: Callable[[str, str, str | None], Awaitable[None]]) -> None:
        """Register callback for incoming messages: (chat_id, text, task_id?) -> None."""
        ...
