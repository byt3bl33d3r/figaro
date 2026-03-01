"""Tests for ChannelRegistry."""

from unittest.mock import AsyncMock, PropertyMock

from figaro_gateway.core.registry import ChannelRegistry


def _make_mock_channel(name: str):
    """Create a mock channel with the given name."""
    channel = AsyncMock()
    type(channel).name = PropertyMock(return_value=name)
    return channel


class TestChannelRegistry:
    def test_register(self):
        """Test registering a channel."""
        registry = ChannelRegistry()
        channel = _make_mock_channel("telegram")
        registry.register(channel)
        assert "telegram" in registry.names
        assert registry.get("telegram") is channel

    def test_unregister(self):
        """Test unregistering a channel."""
        registry = ChannelRegistry()
        channel = _make_mock_channel("telegram")
        registry.register(channel)
        registry.unregister("telegram")
        assert "telegram" not in registry.names
        assert registry.get("telegram") is None

    def test_unregister_nonexistent(self):
        """Test unregistering a channel that doesn't exist does not raise."""
        registry = ChannelRegistry()
        registry.unregister("nonexistent")  # Should not raise

    def test_get_nonexistent(self):
        """Test getting a channel that doesn't exist returns None."""
        registry = ChannelRegistry()
        assert registry.get("nonexistent") is None

    def test_get_all(self):
        """Test getting all registered channels."""
        registry = ChannelRegistry()
        ch1 = _make_mock_channel("telegram")
        ch2 = _make_mock_channel("slack")
        registry.register(ch1)
        registry.register(ch2)
        all_channels = registry.get_all()
        assert len(all_channels) == 2
        assert ch1 in all_channels
        assert ch2 in all_channels

    def test_names(self):
        """Test getting all channel names."""
        registry = ChannelRegistry()
        ch1 = _make_mock_channel("telegram")
        ch2 = _make_mock_channel("whatsapp")
        registry.register(ch1)
        registry.register(ch2)
        assert sorted(registry.names) == ["telegram", "whatsapp"]

    def test_register_overwrites(self):
        """Test registering a channel with the same name overwrites."""
        registry = ChannelRegistry()
        ch1 = _make_mock_channel("telegram")
        ch2 = _make_mock_channel("telegram")
        registry.register(ch1)
        registry.register(ch2)
        assert registry.get("telegram") is ch2
        assert len(registry.get_all()) == 1
