"""NATS Router — wires NATS subjects to channel methods."""

from __future__ import annotations

import logging
from typing import Any

from figaro_nats import NatsConnection, Subjects

from .registry import ChannelRegistry

logger = logging.getLogger(__name__)


class NatsRouter:
    """Routes NATS messages to/from communication channels."""

    def __init__(self, nats_url: str, registry: ChannelRegistry) -> None:
        self._nats_url = nats_url
        self._registry = registry
        self._conn = NatsConnection(url=nats_url, name="gateway")
        self._subscriptions: list[Any] = []

    @property
    def conn(self) -> NatsConnection:
        return self._conn

    async def start(self) -> None:
        """Connect to NATS, start all channels, and set up subscriptions."""
        await self._conn.connect()

        # Start all registered channels
        for channel in self._registry.get_all():
            # Register message callback BEFORE starting so it's available during start
            channel.on_message(self._make_message_handler(channel.name))

            await channel.start()

            # Subscribe to NATS subjects for this channel
            sub = await self._conn.subscribe(
                Subjects.gateway_send(channel.name),
                self._make_send_handler(channel.name),
            )
            self._subscriptions.append(sub)

            # Publish channel registration to NATS
            await self._conn.publish(
                Subjects.gateway_register(channel.name),
                {
                    "channel": channel.name,
                    "status": "online",
                },
            )

            logger.info(f"Channel {channel.name} started and wired to NATS")

        # Subscribe to help requests (route to appropriate channel)
        sub = await self._conn.subscribe(
            Subjects.HELP_REQUEST,
            self._handle_help_request,
        )
        self._subscriptions.append(sub)

    async def stop(self) -> None:
        """Stop all channels and disconnect from NATS."""
        for channel in self._registry.get_all():
            try:
                await channel.stop()
            except Exception:
                logger.exception(f"Error stopping channel {channel.name}")

        await self._conn.close()

    def _make_message_handler(self, channel_name: str):
        """Create a callback for incoming messages from a channel."""

        async def _handler(chat_id: str, text: str, task_id: str | None) -> None:
            await self._conn.publish(
                Subjects.gateway_task(channel_name),
                {
                    "channel": channel_name,
                    "chat_id": chat_id,
                    "text": text,
                    "task_id": task_id,
                },
            )
            logger.debug(f"Published message from {channel_name} chat {chat_id} to NATS")

        return _handler

    def _make_send_handler(self, channel_name: str):
        """Create a handler for outbound send messages from NATS."""

        async def _handler(data: dict[str, Any]) -> None:
            channel = self._registry.get(channel_name)
            if channel is None:
                logger.warning(f"Channel {channel_name} not found for send")
                return
            chat_id = str(data.get("chat_id", ""))
            if data.get("image") and hasattr(channel, "send_photo"):
                await channel.send_photo(chat_id, data["image"], data.get("caption"))
            else:
                text = data.get("text", "")
                await channel.send_message(chat_id, text)

        return _handler

    async def _handle_help_request(self, data: dict[str, Any]) -> None:
        """Route help request to appropriate channel(s)."""
        # Broadcast help request to all channels for now
        # In the future, can route based on source_metadata.channel
        questions = data.get("questions", [])
        request_id = data.get("request_id", "")
        task_id = data.get("task_id", "")

        question_text = f"Help requested for task {task_id}:\n"
        for q in questions:
            question_text += f"\n{q.get('question', '')}"
            if q.get("options"):
                for opt in q["options"]:
                    question_text += f"\n  - {opt.get('label', '')}: {opt.get('description', '')}"

        for channel in self._registry.get_all():
            try:
                # Use ask_question for interactive channels
                # For the first allowed chat, ask the question
                answer = await channel.ask_question(
                    chat_id="",  # Channel determines default chat
                    question_id=request_id,
                    question=question_text,
                    options=[opt for q in questions for opt in (q.get("options") or [])],
                )
                if answer is not None:
                    # Publish response back
                    answers = {}
                    for q in questions:
                        answers[q.get("question", "")] = answer
                    await self._conn.publish(
                        Subjects.help_response(request_id),
                        {
                            "request_id": request_id,
                            "answers": answers,
                            "source": channel.name,
                        },
                    )
                    break  # First channel to respond wins
            except Exception:
                logger.exception(f"Error routing help request to {channel.name}")
