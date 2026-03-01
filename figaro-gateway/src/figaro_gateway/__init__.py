"""Figaro Gateway — channel-agnostic messaging gateway."""

import asyncio
import logging
import signal

from .config import Settings
from .core.registry import ChannelRegistry
from .core.router import NatsRouter
from .channels.telegram.channel import TelegramChannel

logger = logging.getLogger(__name__)


async def run_gateway() -> None:
    """Run the gateway service."""
    settings = Settings()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    registry = ChannelRegistry()
    router = NatsRouter(
        nats_url=settings.nats_url,
        registry=registry,
    )

    # Register enabled channels
    if settings.telegram_bot_token:
        if not settings.telegram_allowed_chat_ids:
            logger.warning("GATEWAY_TELEGRAM_ALLOWED_CHAT_IDS is not set — Telegram bot will ignore all messages")
        telegram = TelegramChannel(
            bot_token=settings.telegram_bot_token,
            allowed_chat_ids=settings.telegram_allowed_chat_ids,
        )
        registry.register(telegram)
        logger.info("Telegram channel registered")
    else:
        logger.warning("GATEWAY_TELEGRAM_BOT_TOKEN is not set — Telegram channel disabled")

    # Start router (connects to NATS, starts channels, sets up subscriptions)
    await router.start()

    # Wait for shutdown signal
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        await router.stop()


def main() -> None:
    """CLI entry point."""
    asyncio.run(run_gateway())
