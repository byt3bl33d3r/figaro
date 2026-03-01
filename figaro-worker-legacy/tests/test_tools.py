"""Tests for the desktop control tools module."""

import base64

import pytest
from unittest.mock import AsyncMock, patch, mock_open

from figaro_worker.worker.tools import (
    _run_command,
    _result,
    _error,
    BUTTON_MAP,
    create_desktop_tools_server,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestResultHelper:
    """Tests for the _result formatting helper."""

    def test_result_with_dict(self):
        data = {"ok": True}
        res = _result(data)
        assert res["content"][0]["type"] == "text"
        assert '"ok": true' in res["content"][0]["text"]

    def test_result_with_list(self):
        data = [1, 2, 3]
        res = _result(data)
        assert res["content"][0]["type"] == "text"
        assert "[" in res["content"][0]["text"]

    def test_result_with_string(self):
        res = _result("hello")
        assert res["content"][0]["text"] == "hello"


class TestErrorHelper:
    """Tests for the _error formatting helper."""

    def test_error_message(self):
        res = _error("something broke")
        assert res["content"][0]["type"] == "text"
        assert res["content"][0]["text"] == "Error: something broke"


class TestButtonMap:
    """Tests for the BUTTON_MAP constant."""

    def test_left(self):
        assert BUTTON_MAP["left"] == "1"

    def test_middle(self):
        assert BUTTON_MAP["middle"] == "2"

    def test_right(self):
        assert BUTTON_MAP["right"] == "3"


# ---------------------------------------------------------------------------
# Subprocess mock fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_subprocess():
    """Mock asyncio.create_subprocess_exec used by _run_command.

    Yields (create_subprocess_exec_mock, process_mock) so tests can
    inspect call args and customise returncode / stdout / stderr.
    """
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_proc.returncode = 0

    with patch("figaro_worker.worker.tools.asyncio") as mock_asyncio:
        # Preserve subprocess constants so _run_command can reference them.
        import asyncio as _real_asyncio

        mock_asyncio.subprocess = _real_asyncio.subprocess
        mock_asyncio.create_subprocess_exec = AsyncMock(return_value=mock_proc)
        yield mock_asyncio.create_subprocess_exec, mock_proc


# ---------------------------------------------------------------------------
# _run_command
# ---------------------------------------------------------------------------

class TestRunCommand:
    """Tests for the module-level _run_command helper."""

    @pytest.mark.asyncio
    async def test_success(self, mock_subprocess):
        create_exec, mock_proc = mock_subprocess
        mock_proc.communicate = AsyncMock(return_value=(b"output", b""))
        mock_proc.returncode = 0

        stdout, stderr, rc = await _run_command("echo", "hello")

        assert stdout == "output"
        assert stderr == ""
        assert rc == 0

        # Verify the command was passed correctly.
        create_exec.assert_called_once()
        args = create_exec.call_args
        assert args[0] == ("echo", "hello")

    @pytest.mark.asyncio
    async def test_command_failure(self, mock_subprocess):
        create_exec, mock_proc = mock_subprocess
        mock_proc.communicate = AsyncMock(return_value=(b"", b"not found"))
        mock_proc.returncode = 127

        stdout, stderr, rc = await _run_command("nonexistent")

        assert stdout == ""
        assert stderr == "not found"
        assert rc == 127

    @pytest.mark.asyncio
    async def test_stderr_output(self, mock_subprocess):
        create_exec, mock_proc = mock_subprocess
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b"warning"))
        mock_proc.returncode = 0

        stdout, stderr, rc = await _run_command("cmd")

        assert stdout == "ok"
        assert stderr == "warning"
        assert rc == 0

    @pytest.mark.asyncio
    async def test_display_env_set(self, mock_subprocess):
        """_run_command should pass DISPLAY=:1 in the env."""
        create_exec, _ = mock_subprocess

        await _run_command("xdotool", "getmouselocation")

        call_kwargs = create_exec.call_args[1]
        assert call_kwargs["env"]["DISPLAY"] == ":1"

    @pytest.mark.asyncio
    async def test_none_returncode_treated_as_zero(self, mock_subprocess):
        """When proc.returncode is None, _run_command should return 0."""
        _, mock_proc = mock_subprocess
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = None

        _, _, rc = await _run_command("cmd")
        assert rc == 0


# ---------------------------------------------------------------------------
# Tool tests — mock _run_command at module level, call tools through server
# Since tools are defined inside create_desktop_tools_server(), we mock
# _run_command at the module level and exercise tools by calling them via
# the inner functions extracted from the server.  The simplest approach is
# to mock _run_command so every tool call ends up verifying the correct
# subprocess arguments.
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_run_command():
    """Mock _run_command at the module level so tool functions use it."""
    with patch("figaro_worker.worker.tools._run_command", new_callable=AsyncMock) as m:
        m.return_value = ("", "", 0)
        yield m


def _get_tools_map():
    """Create a desktop tools server and return a name -> callable map.

    The tool functions are local to create_desktop_tools_server, but
    create_sdk_mcp_server stores them.  We patch create_sdk_mcp_server
    to capture the list of tool callables.
    """
    captured_tools: list = []

    def fake_create_server(*, name, version, tools):
        captured_tools.extend(tools)
        return object()  # dummy server

    with patch(
        "figaro_worker.worker.tools.create_sdk_mcp_server",
        side_effect=fake_create_server,
    ):
        create_desktop_tools_server()

    return {t.name: t.handler for t in captured_tools}


# Cache the tools map so we don't re-patch per test.
_TOOLS = _get_tools_map()


class TestScreenshotTool:
    """Tests for the screenshot desktop tool."""

    @pytest.mark.asyncio
    async def test_screenshot_success(self, mock_run_command):
        """Verify scrot is called and PNG data is returned as base64."""
        fake_png = b"\x89PNG\r\n\x1a\nfake-image-data"
        mock_run_command.return_value = ("", "", 0)

        m_open = mock_open(read_data=fake_png)
        with patch("builtins.open", m_open), \
             patch("os.unlink") as mock_unlink, \
             patch("tempfile.NamedTemporaryFile") as mock_tmp:
            mock_tmp.return_value.name = "/tmp/fake_screenshot.png"
            mock_tmp.return_value.close = lambda: None

            result = await _TOOLS["screenshot"]({})

        # Verify scrot was called with the temp path.
        mock_run_command.assert_called_once_with(
            "scrot", "--overwrite", "/tmp/fake_screenshot.png"
        )

        # Verify the returned content is a base64-encoded image.
        assert result["content"][0]["type"] == "image"
        assert result["content"][0]["mimeType"] == "image/png"
        expected_b64 = base64.b64encode(fake_png).decode("utf-8")
        assert result["content"][0]["data"] == expected_b64

        # Verify temp file cleanup.
        mock_unlink.assert_called_once_with("/tmp/fake_screenshot.png")

    @pytest.mark.asyncio
    async def test_screenshot_command_failure(self, mock_run_command):
        """When scrot fails, an error result should be returned."""
        mock_run_command.return_value = ("", "X display error", 1)

        with patch("tempfile.NamedTemporaryFile") as mock_tmp, \
             patch("os.unlink"):
            mock_tmp.return_value.name = "/tmp/fake.png"
            mock_tmp.return_value.close = lambda: None

            result = await _TOOLS["screenshot"]({})

        assert result["content"][0]["type"] == "text"
        assert "Error" in result["content"][0]["text"]
        assert "rc=1" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_screenshot_empty_file(self, mock_run_command):
        """When the screenshot file is empty, an error should be returned."""
        mock_run_command.return_value = ("", "", 0)

        m_open = mock_open(read_data=b"")
        with patch("builtins.open", m_open), \
             patch("os.unlink"), \
             patch("tempfile.NamedTemporaryFile") as mock_tmp:
            mock_tmp.return_value.name = "/tmp/empty.png"
            mock_tmp.return_value.close = lambda: None

            result = await _TOOLS["screenshot"]({})

        assert result["content"][0]["type"] == "text"
        assert "empty" in result["content"][0]["text"].lower()


class TestMouseClickTool:
    """Tests for the mouse_click desktop tool."""

    @pytest.mark.asyncio
    async def test_click_default_button(self, mock_run_command):
        """Default click should use button 1 (left)."""
        result = await _TOOLS["mouse_click"]({"x": 100, "y": 200})

        mock_run_command.assert_called_once_with(
            "xdotool", "mousemove", "--sync", "100", "200", "click", "1"
        )
        assert '"ok": true' in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_click_right_button(self, mock_run_command):
        """Right click should use button 3."""
        await _TOOLS["mouse_click"]({"x": 50, "y": 75, "button": "right"})

        mock_run_command.assert_called_once_with(
            "xdotool", "mousemove", "--sync", "50", "75", "click", "3"
        )

    @pytest.mark.asyncio
    async def test_click_middle_button(self, mock_run_command):
        """Middle click should use button 2."""
        await _TOOLS["mouse_click"]({"x": 10, "y": 20, "button": "middle"})

        mock_run_command.assert_called_once_with(
            "xdotool", "mousemove", "--sync", "10", "20", "click", "2"
        )

    @pytest.mark.asyncio
    async def test_click_failure(self, mock_run_command):
        """When xdotool fails, an error result should be returned."""
        mock_run_command.return_value = ("", "no display", 1)

        result = await _TOOLS["mouse_click"]({"x": 0, "y": 0})

        assert "Error" in result["content"][0]["text"]


class TestMouseMoveTool:
    """Tests for the mouse_move desktop tool."""

    @pytest.mark.asyncio
    async def test_move(self, mock_run_command):
        result = await _TOOLS["mouse_move"]({"x": 300, "y": 400})

        mock_run_command.assert_called_once_with(
            "xdotool", "mousemove", "--sync", "300", "400"
        )
        assert '"ok": true' in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_move_failure(self, mock_run_command):
        mock_run_command.return_value = ("", "error", 1)

        result = await _TOOLS["mouse_move"]({"x": 0, "y": 0})

        assert "Error" in result["content"][0]["text"]


class TestTypeTextTool:
    """Tests for the type_text desktop tool."""

    @pytest.mark.asyncio
    async def test_type_default_delay(self, mock_run_command):
        """Default delay should be 50ms."""
        result = await _TOOLS["type_text"]({"text": "hello world"})

        mock_run_command.assert_called_once_with(
            "xdotool", "type", "--delay", "50", "--", "hello world"
        )
        assert '"ok": true' in result["content"][0]["text"]
        assert '"length": 11' in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_type_custom_delay(self, mock_run_command):
        """Custom delay should be passed to xdotool."""
        await _TOOLS["type_text"]({"text": "fast", "delay": 10})

        mock_run_command.assert_called_once_with(
            "xdotool", "type", "--delay", "10", "--", "fast"
        )

    @pytest.mark.asyncio
    async def test_type_failure(self, mock_run_command):
        mock_run_command.return_value = ("", "kbd error", 1)

        result = await _TOOLS["type_text"]({"text": "x"})

        assert "Error" in result["content"][0]["text"]


class TestPressKeyTool:
    """Tests for the press_key desktop tool."""

    @pytest.mark.asyncio
    async def test_single_key(self, mock_run_command):
        result = await _TOOLS["press_key"]({"keys": "Return"})

        mock_run_command.assert_called_once_with(
            "xdotool", "key", "--", "Return"
        )
        assert '"ok": true' in result["content"][0]["text"]
        assert '"keys": "Return"' in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_key_combination(self, mock_run_command):
        await _TOOLS["press_key"]({"keys": "ctrl+c"})

        mock_run_command.assert_called_once_with(
            "xdotool", "key", "--", "ctrl+c"
        )

    @pytest.mark.asyncio
    async def test_key_failure(self, mock_run_command):
        mock_run_command.return_value = ("", "key error", 1)

        result = await _TOOLS["press_key"]({"keys": "F13"})

        assert "Error" in result["content"][0]["text"]


class TestScrollTool:
    """Tests for the scroll desktop tool."""

    @pytest.mark.asyncio
    async def test_scroll_up_default_clicks(self, mock_run_command):
        """Scroll up should use button 4, default 3 clicks."""
        result = await _TOOLS["scroll"]({"direction": "up"})

        mock_run_command.assert_called_once_with(
            "xdotool", "click", "--repeat", "3", "--delay", "50", "4"
        )
        assert '"ok": true' in result["content"][0]["text"]
        assert '"direction": "up"' in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_scroll_down(self, mock_run_command):
        """Scroll down should use button 5."""
        await _TOOLS["scroll"]({"direction": "down"})

        mock_run_command.assert_called_once_with(
            "xdotool", "click", "--repeat", "3", "--delay", "50", "5"
        )

    @pytest.mark.asyncio
    async def test_scroll_custom_clicks(self, mock_run_command):
        """Custom click count should be passed to xdotool."""
        await _TOOLS["scroll"]({"direction": "up", "clicks": 10})

        mock_run_command.assert_called_once_with(
            "xdotool", "click", "--repeat", "10", "--delay", "50", "4"
        )

    @pytest.mark.asyncio
    async def test_scroll_failure(self, mock_run_command):
        mock_run_command.return_value = ("", "scroll err", 1)

        result = await _TOOLS["scroll"]({"direction": "down"})

        assert "Error" in result["content"][0]["text"]


class TestMouseDragTool:
    """Tests for the mouse_drag desktop tool."""

    def _get_script(self, mock_run_command) -> str:
        """Extract the bash script from the mock call."""
        mock_run_command.assert_called_once()
        args = list(mock_run_command.call_args[0])
        assert args[:2] == ["bash", "-c"]
        return args[2]

    @pytest.mark.asyncio
    async def test_drag_default_button(self, mock_run_command):
        """Default drag should use button 1 (left) with smooth steps."""
        result = await _TOOLS["mouse_drag"]({
            "start_x": 10,
            "start_y": 20,
            "end_x": 100,
            "end_y": 200,
        })

        script = self._get_script(mock_run_command)
        lines = script.strip().splitlines()
        # First two lines: move to start + mousedown
        assert lines[0] == "xdotool mousemove --sync 10 20"
        assert lines[1] == "xdotool mousedown 1"
        # Last line: mouseup
        assert lines[-1] == "xdotool mouseup 1"
        # Intermediate lines alternate: sleep / xdotool mousemove
        moves = [l for l in lines if l.startswith("xdotool mousemove ") and "--sync" not in l]
        assert len(moves) >= 10  # auto-calculated steps
        # Final move reaches end coordinates
        assert moves[-1] == "xdotool mousemove 100 200"

        text = result["content"][0]["text"]
        assert '"ok": true' in text
        assert '"steps"' in text

    @pytest.mark.asyncio
    async def test_drag_right_button(self, mock_run_command):
        """Right-button drag should use button 3."""
        await _TOOLS["mouse_drag"]({
            "start_x": 0,
            "start_y": 0,
            "end_x": 50,
            "end_y": 50,
            "button": "right",
        })

        script = self._get_script(mock_run_command)
        lines = script.strip().splitlines()
        assert lines[1] == "xdotool mousedown 3"
        assert lines[-1] == "xdotool mouseup 3"

    @pytest.mark.asyncio
    async def test_drag_explicit_steps(self, mock_run_command):
        """Explicit steps parameter should control the number of intermediate moves."""
        await _TOOLS["mouse_drag"]({
            "start_x": 0,
            "start_y": 0,
            "end_x": 100,
            "end_y": 0,
            "steps": 5,
        })

        script = self._get_script(mock_run_command)
        lines = script.strip().splitlines()
        sleep_lines = [l for l in lines if l.startswith("sleep ")]
        assert len(sleep_lines) == 5

    @pytest.mark.asyncio
    async def test_drag_easing_starts_slow(self, mock_run_command):
        """Eased movement: the first step should move less than half the distance."""
        await _TOOLS["mouse_drag"]({
            "start_x": 0,
            "start_y": 0,
            "end_x": 1000,
            "end_y": 0,
            "steps": 10,
        })

        script = self._get_script(mock_run_command)
        moves = [l for l in script.splitlines() if l.startswith("xdotool mousemove ") and "--sync" not in l]
        # First intermediate move x coordinate
        first_x = int(moves[0].split()[2])
        # With ease-in-out cubic, first step (t=0.1) → eased ≈ 0.004
        assert first_x < 50  # well under linear (100)

    @pytest.mark.asyncio
    async def test_drag_failure(self, mock_run_command):
        mock_run_command.return_value = ("", "drag err", 1)

        result = await _TOOLS["mouse_drag"]({
            "start_x": 0,
            "start_y": 0,
            "end_x": 1,
            "end_y": 1,
        })

        assert "Error" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_drag_does_not_block_event_loop(self):
        """The subprocess await should yield to the event loop, not block it."""
        import asyncio as _asyncio

        tick_count = 0

        async def tick_counter():
            """Increment a counter every time we get scheduled by the loop."""
            nonlocal tick_count
            while True:
                tick_count += 1
                await _asyncio.sleep(0)

        # Simulate a slow xdotool process (takes 0.15s)
        async def slow_communicate():
            await _asyncio.sleep(0.15)
            return (b"", b"")

        mock_proc = AsyncMock()
        mock_proc.communicate = slow_communicate
        mock_proc.returncode = 0

        with patch("figaro_worker.worker.tools.asyncio") as mock_asyncio_mod:
            mock_asyncio_mod.subprocess = _asyncio.subprocess
            mock_asyncio_mod.create_subprocess_exec = AsyncMock(
                return_value=mock_proc,
            )

            ticker = _asyncio.create_task(tick_counter())
            try:
                await _TOOLS["mouse_drag"]({
                    "start_x": 0,
                    "start_y": 0,
                    "end_x": 100,
                    "end_y": 0,
                    "steps": 3,
                    "duration_ms": 100,
                })
            finally:
                ticker.cancel()
                try:
                    await ticker
                except _asyncio.CancelledError:
                    pass

        # If the event loop was blocked, tick_counter would never run.
        # It should have ticked many times during the 0.15s sleep.
        assert tick_count > 0, "Event loop was blocked during mouse_drag"


# ---------------------------------------------------------------------------
# create_desktop_tools_server
# ---------------------------------------------------------------------------

class TestCreateDesktopToolsServer:
    """Tests for the factory function."""

    def test_returns_server_object(self):
        """Verify the factory returns without crashing."""
        server = create_desktop_tools_server()
        assert server is not None

    def test_server_has_all_tools(self):
        """Verify all 7 tools are registered."""
        expected_names = {
            "screenshot",
            "mouse_click",
            "mouse_move",
            "type_text",
            "press_key",
            "scroll",
            "mouse_drag",
        }
        assert set(_TOOLS.keys()) == expected_names
