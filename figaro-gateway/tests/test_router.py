"""Tests for NatsRouter."""

import asyncio
from unittest.mock import AsyncMock, PropertyMock, MagicMock, patch

import pytest

from figaro_gateway.core.registry import ChannelRegistry
from figaro_gateway.core.router import NatsRouter


def _make_mock_channel(name: str):
    """Create a mock channel with the given name."""
    channel = AsyncMock()
    type(channel).name = PropertyMock(return_value=name)
    channel.on_message = MagicMock()
    return channel


@pytest.fixture
def registry():
    return ChannelRegistry()


@pytest.fixture
def mock_conn():
    conn = AsyncMock()
    conn.connect = AsyncMock()
    conn.close = AsyncMock()
    conn.publish = AsyncMock()
    conn.subscribe = AsyncMock(return_value=AsyncMock())
    return conn


@pytest.fixture
def router(registry, mock_conn):
    r = NatsRouter(nats_url="nats://localhost:4222", registry=registry)
    r._conn = mock_conn
    return r


class TestNatsRouter:
    async def test_start_connects_to_nats(self, router, mock_conn):
        """Test that start() connects to NATS."""
        await router.start()
        mock_conn.connect.assert_called_once()

    async def test_start_starts_channels(self, router, registry, mock_conn):
        """Test that start() starts all registered channels."""
        ch = _make_mock_channel("telegram")
        registry.register(ch)
        await router.start()
        ch.start.assert_called_once()

    async def test_start_subscribes_to_channel_subjects(self, router, registry, mock_conn):
        """Test that start() subscribes to send subject for each channel."""
        ch = _make_mock_channel("telegram")
        registry.register(ch)
        await router.start()
        # Should subscribe to gateway send subject and help request subject
        subjects_subscribed = [call.args[0] for call in mock_conn.subscribe.call_args_list]
        assert "figaro.gateway.telegram.send" in subjects_subscribed
        assert "figaro.help.request" in subjects_subscribed

    async def test_start_publishes_registration(self, router, registry, mock_conn):
        """Test that start() publishes channel registration to NATS."""
        ch = _make_mock_channel("telegram")
        registry.register(ch)
        await router.start()
        mock_conn.publish.assert_any_call(
            "figaro.gateway.telegram.register",
            {"channel": "telegram", "status": "online"},
        )

    async def test_start_registers_message_callback(self, router, registry, mock_conn):
        """Test that start() registers on_message callback for channels."""
        ch = _make_mock_channel("telegram")
        registry.register(ch)
        await router.start()
        ch.on_message.assert_called_once()

    async def test_send_handler_routes_to_channel(self, router, registry, mock_conn):
        """Test that the send handler forwards messages to the channel."""
        ch = _make_mock_channel("telegram")
        registry.register(ch)

        await router.start()

        # Get the send handler that was registered
        send_handler = None
        for call in mock_conn.subscribe.call_args_list:
            if call.args[0] == "figaro.gateway.telegram.send":
                send_handler = call.args[1]
                break

        assert send_handler is not None

        # Call the handler with a message
        await send_handler({"chat_id": "123", "text": "hello"})
        ch.send_message.assert_called_once_with("123", "hello")

    async def test_message_handler_publishes_to_nats(self, router, registry, mock_conn):
        """Test that incoming channel messages get published to NATS."""
        ch = _make_mock_channel("telegram")
        registry.register(ch)

        await router.start()

        # Get the message handler that was set on the channel
        message_handler_call = ch.on_message.call_args
        message_handler = message_handler_call.args[0]

        # Simulate incoming message
        await message_handler("456", "test message", None)

        mock_conn.publish.assert_any_call(
            "figaro.gateway.telegram.task",
            {
                "channel": "telegram",
                "chat_id": "456",
                "text": "test message",
                "task_id": None,
            },
        )

    async def test_stop_stops_channels(self, router, registry, mock_conn):
        """Test that stop() stops all channels."""
        ch = _make_mock_channel("telegram")
        registry.register(ch)
        await router.start()
        await router.stop()
        ch.stop.assert_called_once()

    async def test_stop_drains_nats(self, router, mock_conn):
        """Test that stop() closes the NATS connection."""
        await router.start()
        await router.stop()
        mock_conn.close.assert_called_once()

    async def test_stop_handles_channel_error(self, router, registry, mock_conn):
        """Test that stop() handles errors from channel.stop() gracefully."""
        ch = _make_mock_channel("telegram")
        ch.stop.side_effect = RuntimeError("stop error")
        registry.register(ch)
        await router.start()
        # Should not raise
        await router.stop()
        ch.stop.assert_called_once()

    async def test_send_handler_missing_channel(self, router, registry, mock_conn):
        """Test send handler when channel is not found in registry."""
        ch = _make_mock_channel("telegram")
        registry.register(ch)
        await router.start()

        # Get the send handler
        send_handler = None
        for call in mock_conn.subscribe.call_args_list:
            if call.args[0] == "figaro.gateway.telegram.send":
                send_handler = call.args[1]
                break

        # Remove channel from registry
        registry.unregister("telegram")

        # Should not raise
        await send_handler({"chat_id": "123", "text": "hello"})
        ch.send_message.assert_not_called()

    async def test_send_handler_routes_image_to_send_photo(self, router, registry, mock_conn):
        """Test that the send handler calls send_photo when data has an image field."""
        ch = _make_mock_channel("telegram")
        registry.register(ch)

        await router.start()

        # Get the send handler
        send_handler = None
        for call in mock_conn.subscribe.call_args_list:
            if call.args[0] == "figaro.gateway.telegram.send":
                send_handler = call.args[1]
                break

        assert send_handler is not None

        await send_handler({"chat_id": "123", "image": "aW1hZ2U=", "caption": "screenshot"})
        ch.send_photo.assert_called_once_with("123", "aW1hZ2U=", "screenshot")
        ch.send_message.assert_not_called()

    async def test_send_handler_falls_back_to_send_message(self, router, registry, mock_conn):
        """Test that the send handler calls send_message when no image field is present."""
        ch = _make_mock_channel("telegram")
        registry.register(ch)

        await router.start()

        # Get the send handler
        send_handler = None
        for call in mock_conn.subscribe.call_args_list:
            if call.args[0] == "figaro.gateway.telegram.send":
                send_handler = call.args[1]
                break

        assert send_handler is not None

        await send_handler({"chat_id": "123", "text": "hello"})
        ch.send_message.assert_called_once_with("123", "hello")
        ch.send_photo.assert_not_called()

    async def test_start_creates_registration_loop(self, router, registry, mock_conn):
        """Test that start() creates a periodic registration task."""
        ch = _make_mock_channel("telegram")
        registry.register(ch)
        await router.start()

        assert router._registration_task is not None
        assert not router._registration_task.done()

        # Clean up
        await router.stop()

    async def test_registration_loop_re_publishes(self, router, registry, mock_conn):
        """Test that the registration loop periodically re-publishes channel registrations."""
        ch1 = _make_mock_channel("telegram")
        ch2 = _make_mock_channel("whatsapp")
        registry.register(ch1)
        registry.register(ch2)

        # Patch the interval to 0 so the loop fires immediately
        with patch.object(NatsRouter, "REGISTRATION_INTERVAL", 0):
            await router.start()
            # Reset publish counts from start() initial registration
            mock_conn.publish.reset_mock()
            # Let the loop fire once
            await asyncio.sleep(0.05)

        await router.stop()

        published_subjects = [call.args[0] for call in mock_conn.publish.call_args_list]
        assert "figaro.gateway.telegram.register" in published_subjects
        assert "figaro.gateway.whatsapp.register" in published_subjects

    async def test_stop_cancels_registration_loop(self, router, registry, mock_conn):
        """Test that stop() cancels the periodic registration task."""
        ch = _make_mock_channel("telegram")
        registry.register(ch)
        await router.start()

        task = router._registration_task
        assert task is not None
        assert not task.done()

        await router.stop()
        assert task.done()
