"""Tests for the VNC client utilities."""

import asyncio
import base64

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from figaro.services.vnc_client import (
    WsVncAdapter,
    _WsStreamWriter,
    _normalize_key,
    parse_vnc_url,
    vnc_click,
    vnc_key,
    vnc_screenshot,
    vnc_type,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_vnc_client():
    """Create a mock asyncvnc client wrapped in an async context manager."""
    client = MagicMock()

    # Keyboard mock
    client.keyboard = MagicMock()
    client.keyboard.write = MagicMock()
    client.keyboard.press = MagicMock()

    # Mouse mock
    client.mouse = MagicMock()
    client.mouse.move = MagicMock()
    client.mouse.click = MagicMock()
    client.mouse.right_click = MagicMock()
    client.mouse.middle_click = MagicMock()

    # Screenshot returns a coroutine that yields a numpy RGBA array
    rgba = np.zeros((100, 200, 4), dtype=np.uint8)
    rgba[:, :, 0] = 255  # red channel
    rgba[:, :, 3] = 255  # alpha channel
    client.screenshot = AsyncMock(return_value=rgba)

    # Wrap in async context manager
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)

    return cm, client


# ---------------------------------------------------------------------------
# parse_vnc_url
# ---------------------------------------------------------------------------


class TestParseVncUrl:
    """Tests for parse_vnc_url()."""

    def test_vnc_scheme_with_port(self):
        host, port, user, pw = parse_vnc_url("vnc://myhost:5900")
        assert host == "myhost"
        assert port == 5900
        assert user is None
        assert pw is None

    def test_vnc_scheme_default_port(self):
        """vnc:// without port defaults to 5900."""
        host, port, user, pw = parse_vnc_url("vnc://myhost")
        assert host == "myhost"
        assert port == 5900

    def test_ws_scheme_with_port(self):
        host, port, user, pw = parse_vnc_url("ws://myhost:6080/websockify")
        assert host == "myhost"
        assert port == 6080

    def test_ws_scheme_no_port_uses_default(self):
        host, port, _, _ = parse_vnc_url("ws://myhost/websockify", default_port=5901)
        assert port == 5901

    def test_credentials_extracted(self):
        host, port, user, pw = parse_vnc_url("vnc://admin:secret@myhost:5901")
        assert host == "myhost"
        assert port == 5901
        assert user == "admin"
        assert pw == "secret"

    def test_empty_url_defaults(self):
        host, port, user, pw = parse_vnc_url("", default_port=5901)
        assert host == "localhost"
        assert port == 5901
        assert user is None
        assert pw is None


# ---------------------------------------------------------------------------
# vnc_screenshot
# ---------------------------------------------------------------------------


class TestVncScreenshot:
    """Tests for vnc_screenshot()."""

    async def test_returns_base64_jpeg(self, mock_vnc_client):
        """Screenshot returns a valid base64-encoded JPEG string and mime type."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            b64, mime, orig_w, orig_h, disp_w, disp_h = await vnc_screenshot(
                "host", port=5900, password="secret"
            )

        assert mime == "image/jpeg"
        # Verify it is valid base64
        raw = base64.b64decode(b64)
        # JPEG files start with the bytes FF D8 FF
        assert raw[:2] == b"\xff\xd8"
        assert orig_w == 200  # numpy array is 100x200x4
        assert orig_h == 100
        assert disp_w == 200  # no max_width/max_height, so same as original
        assert disp_h == 100

    async def test_calls_client_screenshot(self, mock_vnc_client):
        """Ensure client.screenshot() is awaited exactly once."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            _ = await vnc_screenshot("host", port=5900, password="pw")

        client.screenshot.assert_awaited_once()

    async def test_custom_quality(self, mock_vnc_client):
        """Different quality values produce output without errors."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            b64, mime, *_ = await vnc_screenshot(
                "host", port=5900, password="pw", quality=10
            )

        assert mime == "image/jpeg"
        assert len(b64) > 0

    async def test_resizes_large_image(self, mock_vnc_client):
        """When max_width/max_height are given and the image exceeds them, it is resized."""
        cm, client = mock_vnc_client
        # Override with a large 3840x2160 image
        large_rgba = np.zeros((2160, 3840, 4), dtype=np.uint8)
        large_rgba[:, :, 3] = 255
        client.screenshot = AsyncMock(return_value=large_rgba)

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            b64, mime, orig_w, orig_h, disp_w, disp_h = await vnc_screenshot(
                "host", port=5900, password="pw",
                max_width=1280, max_height=800,
            )

        assert mime == "image/jpeg"
        assert orig_w == 3840
        assert orig_h == 2160
        # thumbnail preserves aspect ratio, fitting within 1280x800
        assert disp_w <= 1280
        assert disp_h <= 800
        assert disp_w > 0 and disp_h > 0


# ---------------------------------------------------------------------------
# vnc_type
# ---------------------------------------------------------------------------


class TestVncType:
    """Tests for vnc_type()."""

    async def test_calls_keyboard_write(self, mock_vnc_client):
        """Verify keyboard.write is called with the provided text."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                await vnc_type("host", port=5900, password="pw", text="hello world")

        client.keyboard.write.assert_called_once_with("hello world")

    async def test_empty_text(self, mock_vnc_client):
        """Typing empty string still calls keyboard.write."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                await vnc_type("host", port=5900, password="pw", text="")

        client.keyboard.write.assert_called_once_with("")

    async def test_special_characters(self, mock_vnc_client):
        """Typing special characters is passed through."""
        cm, client = mock_vnc_client
        text = "user@example.com\tpassword123\n"

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                await vnc_type("host", port=5900, password="pw", text=text)

        client.keyboard.write.assert_called_once_with(text)


# ---------------------------------------------------------------------------
# vnc_key
# ---------------------------------------------------------------------------


class TestVncKey:
    """Tests for vnc_key()."""

    async def test_single_key(self, mock_vnc_client):
        """Pressing a single key without modifiers."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                await vnc_key("host", port=5900, password="pw", key="Return")

        client.keyboard.press.assert_called_once_with("Return")

    async def test_key_with_single_modifier(self, mock_vnc_client):
        """Pressing a key with one modifier (e.g. Ctrl+C) — normalizes 'ctrl'."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                await vnc_key(
                    "host",
                    port=5900,
                    password="pw",
                    key="c",
                    modifiers=["ctrl"],
                )

        client.keyboard.press.assert_called_once_with("Ctrl", "c")

    async def test_key_with_multiple_modifiers(self, mock_vnc_client):
        """Pressing a key with multiple modifiers (e.g. Ctrl+Shift+S)."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                await vnc_key(
                    "host",
                    port=5900,
                    password="pw",
                    key="s",
                    modifiers=["Control_L", "Shift_L"],
                )

        # Control_L -> Ctrl, Shift_L -> Shift via normalization
        client.keyboard.press.assert_called_once_with("Ctrl", "Shift", "s")

    async def test_no_modifiers_defaults_to_none(self, mock_vnc_client):
        """When modifiers is None, only the key itself is pressed."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                await vnc_key(
                    "host", port=5900, password="pw", key="Escape", modifiers=None
                )

        # Escape -> Esc via normalization
        client.keyboard.press.assert_called_once_with("Esc")

    async def test_key_normalization_control_variant(self, mock_vnc_client):
        """'Control' (capitalized, no _L) is normalized to 'Ctrl'."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                await vnc_key(
                    "host",
                    port=5900,
                    password="pw",
                    key="c",
                    modifiers=["Control"],
                )

        client.keyboard.press.assert_called_once_with("Ctrl", "c")

    async def test_hold_seconds(self, mock_vnc_client):
        """When hold_seconds is given, keyboard.hold is used instead of press."""
        cm, client = mock_vnc_client
        # Make hold() return a context manager that records its args
        from contextlib import contextmanager

        held_keys: list[tuple[str, ...]] = []

        @contextmanager
        def fake_hold(*keys):
            held_keys.append(keys)
            yield

        client.keyboard.hold = fake_hold

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await vnc_key(
                    "host", port=5900, password="pw",
                    key="a", hold_seconds=2.5,
                )

        assert held_keys == [("a",)]
        # First sleep call should be the hold duration
        mock_sleep.assert_any_call(2.5)
        # press should NOT be called
        client.keyboard.press.assert_not_called()

    async def test_hold_seconds_with_modifiers(self, mock_vnc_client):
        """hold_seconds works together with modifier keys."""
        cm, client = mock_vnc_client
        from contextlib import contextmanager

        held_keys: list[tuple[str, ...]] = []

        @contextmanager
        def fake_hold(*keys):
            held_keys.append(keys)
            yield

        client.keyboard.hold = fake_hold

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                await vnc_key(
                    "host", port=5900, password="pw",
                    key="c", modifiers=["ctrl"], hold_seconds=1.0,
                )

        assert held_keys == [("Ctrl", "c")]
        client.keyboard.press.assert_not_called()

    async def test_hold_seconds_zero_uses_press(self, mock_vnc_client):
        """hold_seconds=0 falls back to the normal press behavior."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                await vnc_key(
                    "host", port=5900, password="pw",
                    key="Return", hold_seconds=0,
                )

        client.keyboard.press.assert_called_once_with("Return")

    async def test_unrecognized_key_raises_value_error(self, mock_vnc_client):
        """KeyError from asyncvnc is wrapped in a descriptive ValueError."""
        cm, client = mock_vnc_client
        client.keyboard.press.side_effect = KeyError("BadKey")

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(ValueError, match="Unrecognized key.*BadKey"):
                    await vnc_key("host", port=5900, password="pw", key="BadKey")


# ---------------------------------------------------------------------------
# _normalize_key
# ---------------------------------------------------------------------------


class TestNormalizeKey:
    """Tests for _normalize_key()."""

    @pytest.mark.parametrize(
        "input_key,expected",
        [
            ("ctrl", "Ctrl"),
            ("Ctrl", "Ctrl"),
            ("CTRL", "Ctrl"),
            ("control", "Ctrl"),
            ("Control", "Ctrl"),
            ("Control_L", "Ctrl"),
            ("shift", "Shift"),
            ("alt", "Alt"),
            ("escape", "Esc"),
            ("Escape", "Esc"),
            ("enter", "Return"),
            ("Return", "Return"),
            ("a", "a"),  # unknown keys pass through unchanged
            ("F1", "F1"),
        ],
    )
    def test_key_aliases(self, input_key, expected):
        assert _normalize_key(input_key) == expected


# ---------------------------------------------------------------------------
# vnc_click
# ---------------------------------------------------------------------------


class TestVncClick:
    """Tests for vnc_click()."""

    async def test_left_click(self, mock_vnc_client):
        """Default left click moves mouse and calls click()."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                await vnc_click("host", port=5900, password="pw", x=100, y=200)

        client.mouse.move.assert_called_once_with(100, 200)
        client.mouse.click.assert_called_once()
        client.mouse.right_click.assert_not_called()
        client.mouse.middle_click.assert_not_called()

    async def test_right_click(self, mock_vnc_client):
        """Right click moves mouse and calls right_click()."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                await vnc_click(
                    "host", port=5900, password="pw", x=50, y=75, button="right"
                )

        client.mouse.move.assert_called_once_with(50, 75)
        client.mouse.right_click.assert_called_once()
        client.mouse.click.assert_not_called()
        client.mouse.middle_click.assert_not_called()

    async def test_middle_click(self, mock_vnc_client):
        """Middle click moves mouse and calls middle_click()."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                await vnc_click(
                    "host", port=5900, password="pw", x=300, y=400, button="middle"
                )

        client.mouse.move.assert_called_once_with(300, 400)
        client.mouse.middle_click.assert_called_once()
        client.mouse.click.assert_not_called()
        client.mouse.right_click.assert_not_called()

    async def test_explicit_left_button(self, mock_vnc_client):
        """Explicitly passing button='left' uses click()."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                await vnc_click(
                    "host", port=5900, password="pw", x=0, y=0, button="left"
                )

        client.mouse.click.assert_called_once()
        client.mouse.right_click.assert_not_called()
        client.mouse.middle_click.assert_not_called()

    async def test_coordinates_passed_correctly(self, mock_vnc_client):
        """Verify exact x, y coordinates are forwarded to mouse.move."""
        cm, client = mock_vnc_client

        with patch("figaro.services.vnc_client.asyncvnc.connect", return_value=cm):
            with patch("figaro.services.vnc_client.asyncio.sleep", new_callable=AsyncMock):
                await vnc_click("host", port=5900, password="pw", x=1920, y=1080)

        client.mouse.move.assert_called_once_with(1920, 1080)


# ---------------------------------------------------------------------------
# _WsStreamWriter
# ---------------------------------------------------------------------------


class TestWsStreamWriter:
    """Tests for _WsStreamWriter."""

    def test_write_buffers_data(self):
        """write() appends data to an internal buffer without sending."""
        ws = MagicMock()
        writer = _WsStreamWriter(ws)

        writer.write(b"hello")
        writer.write(b" world")

        # Nothing sent yet — data is only buffered
        ws.send.assert_not_called()

    async def test_drain_sends_buffered_data(self):
        """drain() sends the buffered bytes via WebSocket and clears the buffer."""
        ws = AsyncMock()
        writer = _WsStreamWriter(ws)

        writer.write(b"hello")
        writer.write(b" world")
        await writer.drain()

        ws.send.assert_awaited_once_with(b"hello world")

        # Buffer is cleared — a second drain should not send anything
        ws.send.reset_mock()
        await writer.drain()
        ws.send.assert_not_awaited()

    async def test_drain_noop_when_buffer_empty(self):
        """drain() does nothing when the buffer is empty."""
        ws = AsyncMock()
        writer = _WsStreamWriter(ws)

        await writer.drain()

        ws.send.assert_not_awaited()

    def test_close_sets_is_closing(self):
        """close() marks the writer as closing."""
        ws = MagicMock()
        writer = _WsStreamWriter(ws)

        assert writer.is_closing() is False
        writer.close()
        assert writer.is_closing() is True

    async def test_wait_closed_returns_immediately(self):
        """wait_closed() returns without error."""
        ws = MagicMock()
        writer = _WsStreamWriter(ws)
        writer.close()

        # Should not raise
        await writer.wait_closed()


# ---------------------------------------------------------------------------
# WsVncAdapter
# ---------------------------------------------------------------------------


class TestWsVncAdapter:
    """Tests for WsVncAdapter."""

    @pytest.fixture
    def mock_ws(self):
        """Create a mock WebSocket that yields bytes via async iteration."""
        ws = AsyncMock()
        ws.close = AsyncMock()
        ws.send = AsyncMock()
        # Default: no messages (empty iteration)
        ws.__aiter__ = MagicMock(return_value=AsyncMock(
            __anext__=AsyncMock(side_effect=StopAsyncIteration)
        ))
        return ws

    async def test_start_creates_recv_task(self, mock_ws):
        """start() spawns a background task that feeds data into reader."""
        adapter = WsVncAdapter(mock_ws)
        await adapter.start()

        assert adapter._recv_task is not None
        assert not adapter._recv_task.done()

        await adapter.close()

    async def test_reader_receives_bytes_from_websocket(self):
        """reader.readexactly() returns data fed from WebSocket messages."""
        messages = [b"hello", b" world"]
        ws = AsyncMock()
        ws.close = AsyncMock()
        ws.send = AsyncMock()

        async def async_iter():
            for msg in messages:
                yield msg

        ws.__aiter__ = lambda self: async_iter()

        adapter = WsVncAdapter(ws)
        await adapter.start()

        data = await asyncio.wait_for(adapter.reader.readexactly(11), timeout=2.0)
        assert data == b"hello world"

        await adapter.close()

    async def test_reader_receives_text_encoded_as_bytes(self):
        """Text WebSocket messages are encoded to bytes before feeding into reader."""
        ws = AsyncMock()
        ws.close = AsyncMock()
        ws.send = AsyncMock()

        async def async_iter():
            yield "text message"

        ws.__aiter__ = lambda self: async_iter()

        adapter = WsVncAdapter(ws)
        await adapter.start()

        data = await asyncio.wait_for(
            adapter.reader.readexactly(len("text message")), timeout=2.0
        )
        assert data == b"text message"

        await adapter.close()

    async def test_close_cancels_recv_task(self):
        """close() cancels the recv task and closes the WebSocket."""
        ws = AsyncMock()
        ws.close = AsyncMock()
        ws.send = AsyncMock()

        # Create a long-running iteration so the task stays alive
        event = asyncio.Event()

        async def async_iter():
            await event.wait()
            return
            yield  # make it a generator

        ws.__aiter__ = lambda self: async_iter()

        adapter = WsVncAdapter(ws)
        await adapter.start()

        recv_task = adapter._recv_task
        assert recv_task is not None
        assert not recv_task.done()

        await adapter.close()

        assert recv_task.cancelled() or recv_task.done()
        assert adapter._recv_task is None
        ws.close.assert_awaited_once()

    async def test_close_marks_writer_as_closing(self):
        """close() also closes the writer."""
        ws = AsyncMock()
        ws.close = AsyncMock()
        ws.send = AsyncMock()
        ws.__aiter__ = MagicMock(return_value=AsyncMock(
            __anext__=AsyncMock(side_effect=StopAsyncIteration)
        ))

        adapter = WsVncAdapter(ws)
        await adapter.start()

        assert adapter.writer.is_closing() is False
        await adapter.close()
        assert adapter.writer.is_closing() is True

    async def test_reader_gets_eof_when_ws_iteration_ends(self):
        """When the WebSocket iteration finishes, feed_eof is called on reader."""
        ws = AsyncMock()
        ws.close = AsyncMock()
        ws.send = AsyncMock()

        async def async_iter():
            yield b"data"

        ws.__aiter__ = lambda self: async_iter()

        adapter = WsVncAdapter(ws)
        await adapter.start()

        # Read the available data first
        data = await asyncio.wait_for(adapter.reader.readexactly(4), timeout=2.0)
        assert data == b"data"

        # After the async iterator completes, reader should hit EOF
        # readexactly on EOF raises IncompleteReadError
        with pytest.raises(asyncio.IncompleteReadError):
            await asyncio.wait_for(adapter.reader.readexactly(1), timeout=2.0)

        await adapter.close()

    async def test_writer_property_returns_ws_stream_writer(self):
        """writer property returns a _WsStreamWriter instance."""
        ws = AsyncMock()
        adapter = WsVncAdapter(ws)

        assert isinstance(adapter.writer, _WsStreamWriter)

    async def test_reader_property_returns_stream_reader(self):
        """reader property returns an asyncio.StreamReader instance."""
        ws = AsyncMock()
        adapter = WsVncAdapter(ws)

        assert isinstance(adapter.reader, asyncio.StreamReader)
