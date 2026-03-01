"""Channel registry — tracks active channel instances."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .channel import Channel

logger = logging.getLogger(__name__)


class ChannelRegistry:
    """Registry of active communication channels."""

    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}

    def register(self, channel: Channel) -> None:
        """Register a channel."""
        self._channels[channel.name] = channel
        logger.info(f"Registered channel: {channel.name}")

    def unregister(self, name: str) -> None:
        """Unregister a channel by name."""
        self._channels.pop(name, None)

    def get(self, name: str) -> Channel | None:
        """Get a channel by name."""
        return self._channels.get(name)

    def get_all(self) -> list[Channel]:
        """Get all registered channels."""
        return list(self._channels.values())

    @property
    def names(self) -> list[str]:
        """Get all channel names."""
        return list(self._channels.keys())
