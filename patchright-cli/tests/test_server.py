"""Comprehensive tests for patchright_cli.server module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from patchright_cli.server import BrowserSession, Response


# ---------------------------------------------------------------------------
# 1. BrowserSession init
# ---------------------------------------------------------------------------


class TestBrowserSessionInit:
    def test_default_state(self, sessions_dir, output_dir, default_config):
        session = BrowserSession("test", default_config)
        assert session.session_name == "test"
        assert session.config is default_config
        assert session.playwright is None
        assert session.browser is None
        assert session.context is None
        assert session.pages == []
        assert session.active_page_index == 0
        assert session.element_refs == {}
        assert session.ref_counter == 0
        assert session.dialog_queue == []
        assert session.console_messages == []
        assert session.network_log == []
        assert session.active_routes == {}
        assert session.tracing_active is False
        assert session._last_console_index == 0
        assert session._start_time == 0.0

    def test_active_page_returns_page_when_pages_exist(
        self, browser_session, mock_page
    ):
        assert browser_session.active_page is mock_page

    def test_active_page_returns_none_when_empty(
        self, sessions_dir, output_dir, default_config
    ):
        session = BrowserSession("empty", default_config)
        assert session.active_page is None


# ---------------------------------------------------------------------------
# 2. handle_command dispatch
# ---------------------------------------------------------------------------


class TestHandleCommand:
    async def test_dispatches_hyphen_command(self, browser_session, mock_page):
        result = await browser_session.handle_command("go-back", {})
        assert result["ok"] is True
        mock_page.go_back.assert_awaited_once()

    async def test_unknown_command_returns_error(self, browser_session):
        result = await browser_session.handle_command("nonexistent-command", {})
        assert result["ok"] is False
        assert "Unknown command" in result["error"]

    async def test_exception_in_handler_returns_error(self, browser_session, mock_page):
        mock_page.go_back = AsyncMock(side_effect=RuntimeError("boom"))
        result = await browser_session.handle_command("go-back", {})
        assert result["ok"] is False
        assert "boom" in result["error"]


# ---------------------------------------------------------------------------
# 3. _resolve_ref
# ---------------------------------------------------------------------------


class TestResolveRef:
    def test_valid_ref_returns_selector(self, browser_session):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "About",
            }
        }
        selector = browser_session._resolve_ref("e0")
        assert selector == "aria-ref=e0"

    def test_valid_ref_backward_compat_plain_string(self, browser_session):
        # Old format: plain string value (backward compatibility)
        browser_session.element_refs = {"e0": "aria-ref=e0"}
        selector = browser_session._resolve_ref("e0")
        assert selector == "aria-ref=e0"

    def test_invalid_ref_raises_value_error(self, browser_session):
        browser_session.element_refs = {}
        with pytest.raises(ValueError, match="Element ref 'e99' not found"):
            browser_session._resolve_ref("e99")


# ---------------------------------------------------------------------------
# 4. Command handlers -- Core
# ---------------------------------------------------------------------------


class TestCmdGoto:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_goto(url="https://example.com")
        assert result["ok"] is True
        mock_page.goto.assert_awaited_once_with("https://example.com", wait_until="domcontentloaded")

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_goto(url="https://example.com")
        assert result["ok"] is False
        assert "No active page" in result["error"]


class TestCmdClose:
    async def test_closes_context_browser_playwright(
        self, browser_session, mock_context, mock_browser
    ):
        browser_session.playwright = MagicMock()
        browser_session.playwright.stop = AsyncMock()
        result = await browser_session.cmd_close()
        assert result["ok"] is True
        assert "closed" in result["output"].lower()
        mock_context.close.assert_awaited_once()
        mock_browser.close.assert_awaited_once()
        browser_session.playwright.stop.assert_awaited_once()


class TestCmdType:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_type(text="hello world")
        assert result["ok"] is True
        mock_page.keyboard.type.assert_awaited_once_with("hello world")

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_type(text="hello")
        assert result["ok"] is False
        assert "No active page" in result["error"]


class TestCmdClick:
    async def test_success(self, browser_session, mock_page):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "About",
            }
        }
        result = await browser_session.cmd_click(ref="e0")
        assert result["ok"] is True
        mock_page.locator.assert_any_call("aria-ref=e0")
        mock_page.locator.return_value.click.assert_awaited_once()

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_click(ref="e0")
        assert result["ok"] is False
        assert "No active page" in result["error"]


class TestCmdFill:
    async def test_success(self, browser_session, mock_page):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "About",
            }
        }
        result = await browser_session.cmd_fill(ref="e0", text="test input")
        assert result["ok"] is True
        mock_page.locator.assert_any_call("aria-ref=e0")
        mock_page.locator.return_value.fill.assert_awaited_once_with("test input")

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_fill(ref="e0", text="x")
        assert result["ok"] is False
        assert "No active page" in result["error"]


class TestCmdHover:
    async def test_success(self, browser_session, mock_page):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "About",
            }
        }
        result = await browser_session.cmd_hover(ref="e0")
        assert result["ok"] is True
        mock_page.locator.assert_any_call("aria-ref=e0")
        mock_page.locator.return_value.hover.assert_awaited_once()

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_hover(ref="e0")
        assert result["ok"] is False
        assert "No active page" in result["error"]


# ---------------------------------------------------------------------------
# 5. Command handlers -- Navigation
# ---------------------------------------------------------------------------


class TestCmdGoBack:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_go_back()
        assert result["ok"] is True
        mock_page.go_back.assert_awaited_once()


class TestCmdGoForward:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_go_forward()
        assert result["ok"] is True
        mock_page.go_forward.assert_awaited_once()


class TestCmdReload:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_reload()
        assert result["ok"] is True
        mock_page.reload.assert_awaited_once()


# ---------------------------------------------------------------------------
# 6. Command handlers -- Keyboard
# ---------------------------------------------------------------------------


class TestCmdPress:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_press(key="Enter")
        assert result["ok"] is True
        mock_page.keyboard.press.assert_awaited_once_with("Enter")


class TestCmdKeydown:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_keydown(key="Shift")
        assert result["ok"] is True
        mock_page.keyboard.down.assert_awaited_once_with("Shift")


class TestCmdKeyup:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_keyup(key="Shift")
        assert result["ok"] is True
        mock_page.keyboard.up.assert_awaited_once_with("Shift")


# ---------------------------------------------------------------------------
# 7. Command handlers -- Mouse
# ---------------------------------------------------------------------------


class TestCmdMousemove:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_mousemove(x=100.0, y=200.0)
        assert result["ok"] is True
        mock_page.mouse.move.assert_awaited_once_with(100.0, 200.0)


class TestCmdMousedown:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_mousedown()
        assert result["ok"] is True
        mock_page.mouse.down.assert_awaited_once_with(button="left")


class TestCmdMouseup:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_mouseup()
        assert result["ok"] is True
        mock_page.mouse.up.assert_awaited_once_with(button="left")


class TestCmdMousewheel:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_mousewheel(dx=0.0, dy=100.0)
        assert result["ok"] is True
        mock_page.mouse.wheel.assert_awaited_once_with(0.0, 100.0)


# ---------------------------------------------------------------------------
# 8. Command handlers -- Snapshot
# ---------------------------------------------------------------------------


class TestCmdSnapshot:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_snapshot()
        assert result["ok"] is True
        assert "output" in result

    async def test_with_filename_saves_to_file(
        self, browser_session, mock_page, tmp_path
    ):
        filepath = tmp_path / "snapshot.yml"
        result = await browser_session.cmd_snapshot(filename=str(filepath))
        assert result["ok"] is True
        assert "Snapshot" in result["output"]
        assert filepath.exists()


# ---------------------------------------------------------------------------
# 9. Command handlers -- Eval
# ---------------------------------------------------------------------------


class TestCmdEval:
    async def test_without_ref(self, browser_session, mock_page):
        mock_page.evaluate = AsyncMock(return_value=42)
        result = await browser_session.cmd_eval(expression="1 + 1")
        assert result["ok"] is True
        mock_page.evaluate.assert_any_call("1 + 1")
        assert "42" in result["output"]

    async def test_with_ref(self, browser_session, mock_page):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "About",
            }
        }
        mock_page.locator.return_value.evaluate = AsyncMock(return_value="text content")
        result = await browser_session.cmd_eval(
            expression="el => el.textContent", ref="e0"
        )
        assert result["ok"] is True
        mock_page.locator.assert_any_call("aria-ref=e0")
        mock_page.locator.return_value.evaluate.assert_any_call("el => el.textContent")


# ---------------------------------------------------------------------------
# 10. Command handlers -- Dialog
# ---------------------------------------------------------------------------


class TestCmdDialogAccept:
    async def test_success(self, browser_session, mock_page):
        mock_dialog = MagicMock()
        mock_dialog.accept = AsyncMock()
        browser_session.dialog_queue.append(
            {
                "type": "confirm",
                "message": "Are you sure?",
                "default_value": "",
                "dialog": mock_dialog,
            }
        )
        result = await browser_session.cmd_dialog_accept()
        assert result["ok"] is True
        mock_dialog.accept.assert_awaited_once_with()

    async def test_empty_queue(self, browser_session):
        result = await browser_session.cmd_dialog_accept()
        assert result["ok"] is False
        assert "No dialog to accept" in result["error"]


class TestCmdDialogDismiss:
    async def test_success(self, browser_session, mock_page):
        mock_dialog = MagicMock()
        mock_dialog.dismiss = AsyncMock()
        browser_session.dialog_queue.append(
            {
                "type": "alert",
                "message": "Hello",
                "default_value": "",
                "dialog": mock_dialog,
            }
        )
        result = await browser_session.cmd_dialog_dismiss()
        assert result["ok"] is True
        mock_dialog.dismiss.assert_awaited_once()

    async def test_empty_queue(self, browser_session):
        result = await browser_session.cmd_dialog_dismiss()
        assert result["ok"] is False
        assert "No dialog to dismiss" in result["error"]


# ---------------------------------------------------------------------------
# 11. Command handlers -- Tabs
# ---------------------------------------------------------------------------


class TestCmdTabList:
    async def test_lists_tabs(self, browser_session, mock_page):
        result = await browser_session.cmd_tab_list()
        assert result["ok"] is True
        assert "0:" in result["output"]
        assert "Example" in result["output"]


class TestCmdTabNew:
    async def test_opens_new_tab(self, browser_session, mock_context, mock_page):
        new_page = MagicMock()
        new_page.url = "about:blank"
        new_page.title = AsyncMock(return_value="New Tab")
        new_page.evaluate = AsyncMock(return_value="[]")
        # Need aria_snapshot for the snapshot pathway
        new_page_locator = MagicMock()
        new_page_locator.aria_snapshot = AsyncMock(return_value="- document")
        new_page.locator = MagicMock(return_value=new_page_locator)
        new_page_role_locator = MagicMock()
        new_page_role_locator.nth = MagicMock(return_value=new_page_role_locator)
        new_page_role_locator.evaluate = AsyncMock(return_value=None)
        new_page.get_by_role = MagicMock(return_value=new_page_role_locator)
        # snapshotForAI support for take_snapshot
        new_impl = MagicMock()
        new_channel = MagicMock()
        new_channel.send_return_as_dict = AsyncMock(
            return_value={"full": "- document\n"}
        )
        new_impl._channel = new_channel
        new_page._impl_obj = new_impl
        mock_context.new_page = AsyncMock(return_value=new_page)

        result = await browser_session.cmd_tab_new()
        assert result["ok"] is True
        mock_context.new_page.assert_awaited_once()


class TestCmdTabClose:
    async def test_closes_active_tab(self, browser_session, mock_page):
        result = await browser_session.cmd_tab_close()
        assert result["ok"] is True
        mock_page.close.assert_awaited_once()
        assert "All tabs closed" in result["output"]


class TestCmdTabSelect:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_tab_select(index=0)
        assert result["ok"] is True
        mock_page.bring_to_front.assert_awaited_once()

    async def test_invalid_index(self, browser_session):
        result = await browser_session.cmd_tab_select(index=99)
        assert result["ok"] is False
        assert "Invalid tab index" in result["error"]


# ---------------------------------------------------------------------------
# 12. Command handlers -- Storage (cookies)
# ---------------------------------------------------------------------------


class TestCmdCookieList:
    async def test_lists_cookies(self, browser_session, mock_context):
        mock_context.cookies = AsyncMock(
            return_value=[{"name": "session", "value": "abc", "domain": "example.com"}]
        )
        result = await browser_session.cmd_cookie_list()
        assert result["ok"] is True
        assert "session" in result["output"]
        assert "example.com" in result["output"]


class TestCmdCookieSet:
    async def test_sets_cookie(self, browser_session, mock_context, mock_page):
        result = await browser_session.cmd_cookie_set(name="test", value="val")
        assert result["ok"] is True
        mock_context.add_cookies.assert_awaited_once()
        call_args = mock_context.add_cookies.call_args[0][0]
        assert call_args[0]["name"] == "test"
        assert call_args[0]["value"] == "val"


class TestCmdCookieDelete:
    async def test_deletes_cookie(self, browser_session, mock_context):
        result = await browser_session.cmd_cookie_delete(name="test")
        assert result["ok"] is True
        mock_context.clear_cookies.assert_awaited_once_with(name="test")
        assert "deleted" in result["output"].lower()


class TestCmdCookieClear:
    async def test_clears_all_cookies(self, browser_session, mock_context):
        result = await browser_session.cmd_cookie_clear()
        assert result["ok"] is True
        mock_context.clear_cookies.assert_awaited_once_with()
        assert "cleared" in result["output"].lower()


# ---------------------------------------------------------------------------
# 13. Command handlers -- Storage (localStorage)
# ---------------------------------------------------------------------------


class TestCmdLocalstorageList:
    async def test_lists_entries(self, browser_session, mock_page):
        mock_page.evaluate = AsyncMock(return_value='[["key1","val1"],["key2","val2"]]')
        result = await browser_session.cmd_localstorage_list()
        assert result["ok"] is True
        assert "localStorage" in result["output"]
        assert "key1" in result["output"]


# ---------------------------------------------------------------------------
# 14. Command handlers -- Screenshot / PDF
# ---------------------------------------------------------------------------


class TestCmdScreenshot:
    async def test_success(self, browser_session, mock_page, output_dir):
        mock_page.screenshot = AsyncMock(return_value=b"fake-png-data")
        result = await browser_session.cmd_screenshot()
        assert result["ok"] is True
        assert "Screenshot" in result["output"]
        mock_page.screenshot.assert_awaited_once()

    async def test_with_ref(self, browser_session, mock_page, output_dir):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "About",
            }
        }
        mock_page.locator.return_value.screenshot = AsyncMock(
            return_value=b"fake-png-data"
        )
        result = await browser_session.cmd_screenshot(ref="e0")
        assert result["ok"] is True
        mock_page.locator.assert_any_call("aria-ref=e0")
        mock_page.locator.return_value.screenshot.assert_awaited_once()

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_screenshot()
        assert result["ok"] is False
        assert "No active page" in result["error"]


class TestCmdPdf:
    async def test_success(self, browser_session, mock_page, output_dir):
        mock_page.pdf = AsyncMock(return_value=b"fake-pdf-data")
        result = await browser_session.cmd_pdf()
        assert result["ok"] is True
        assert "pdf" in result["output"].lower()
        mock_page.pdf.assert_awaited_once()


# ---------------------------------------------------------------------------
# 15. Command handlers -- Network (routes)
# ---------------------------------------------------------------------------


class TestCmdRoute:
    async def test_adds_route(self, browser_session, mock_context):
        result = await browser_session.cmd_route(
            pattern="**/api/*", body='{"mock": true}', status=200
        )
        assert result["ok"] is True
        assert "Route added" in result["output"]
        mock_context.route.assert_awaited_once()
        assert "**/api/*" in browser_session.active_routes


class TestCmdRouteList:
    async def test_empty_routes(self, browser_session):
        result = await browser_session.cmd_route_list()
        assert result["ok"] is True
        assert "No active routes" in result["output"]

    async def test_populated_routes(self, browser_session, mock_context):
        browser_session.active_routes = {
            "**/api/*": AsyncMock(),
            "**/images/*": AsyncMock(),
        }
        result = await browser_session.cmd_route_list()
        assert result["ok"] is True
        assert "**/api/*" in result["output"]
        assert "**/images/*" in result["output"]


class TestCmdUnroute:
    async def test_removes_specific_route(self, browser_session, mock_context):
        handler = AsyncMock()
        browser_session.active_routes = {"**/api/*": handler}
        result = await browser_session.cmd_unroute(pattern="**/api/*")
        assert result["ok"] is True
        assert "Route removed" in result["output"]
        mock_context.unroute.assert_awaited_once_with("**/api/*", handler)
        assert "**/api/*" not in browser_session.active_routes


# ---------------------------------------------------------------------------
# 16. Command handlers -- Tracing
# ---------------------------------------------------------------------------


class TestCmdTracingStart:
    async def test_starts_tracing(self, browser_session, mock_context):
        result = await browser_session.cmd_tracing_start()
        assert result["ok"] is True
        assert "Tracing started" in result["output"]
        mock_context.tracing.start.assert_awaited_once_with(
            screenshots=True, snapshots=True
        )
        assert browser_session.tracing_active is True


class TestCmdTracingStop:
    async def test_stops_tracing(self, browser_session, mock_context, output_dir):
        browser_session.tracing_active = True
        result = await browser_session.cmd_tracing_stop()
        assert result["ok"] is True
        assert "Trace saved to" in result["output"]
        mock_context.tracing.stop.assert_awaited_once()
        assert browser_session.tracing_active is False


# ---------------------------------------------------------------------------
# 17. Command handlers -- Console / Network log
# ---------------------------------------------------------------------------


class TestCmdConsole:
    async def test_returns_messages(self, browser_session, output_dir):
        browser_session.console_messages = [
            {"type": "log", "text": "hello", "location": "page.js:1"},
            {"type": "error", "text": "oh no", "location": "page.js:2"},
        ]
        result = await browser_session.cmd_console()
        assert result["ok"] is True
        assert "Console" in result["output"]


class TestCmdNetwork:
    async def test_returns_log(self, browser_session, output_dir):
        browser_session.network_log = [
            {
                "method": "GET",
                "url": "https://example.com/api",
                "resource_type": "fetch",
                "timestamp": 1234567890.0,
                "status": 200,
            },
        ]
        result = await browser_session.cmd_network()
        assert result["ok"] is True
        assert "Network" in result["output"]


# ---------------------------------------------------------------------------
# 18. Command handlers -- Video
# ---------------------------------------------------------------------------


class TestCmdVideoStart:
    async def test_not_enabled(self, browser_session):
        result = await browser_session.cmd_video_start()
        assert result["ok"] is False
        assert "not enabled" in result["error"].lower()


class TestCmdVideoStop:
    async def test_no_video(self, browser_session, mock_page):
        mock_page.video = None
        result = await browser_session.cmd_video_stop()
        assert result["ok"] is False
        assert "No video" in result["error"]

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_video_stop()
        assert result["ok"] is False
        assert "No active page" in result["error"]

    async def test_saves_video(self, browser_session, mock_page, output_dir):
        mock_video = MagicMock()
        mock_video.save_as = AsyncMock()
        mock_page.video = mock_video
        result = await browser_session.cmd_video_stop()
        assert result["ok"] is True
        assert "Video saved to" in result["output"]
        mock_video.save_as.assert_awaited_once()

    async def test_saves_video_with_filename(
        self, browser_session, mock_page, tmp_path
    ):
        mock_video = MagicMock()
        mock_video.save_as = AsyncMock()
        mock_page.video = mock_video
        filepath = str(tmp_path / "my-video.webm")
        result = await browser_session.cmd_video_stop(filename=filepath)
        assert result["ok"] is True
        mock_video.save_as.assert_awaited_once_with(filepath)


class TestCmdVideoStartEnabled:
    async def test_video_enabled(self, browser_session):
        from patchright_cli.config import VideoSize

        browser_session.config.save_video = VideoSize(width=1280, height=720)
        result = await browser_session.cmd_video_start()
        assert result["ok"] is True
        assert "active" in result["output"].lower()


# ---------------------------------------------------------------------------
# Additional Core command handler tests
# ---------------------------------------------------------------------------


class TestCmdDblclick:
    async def test_success(self, browser_session, mock_page):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "About",
            }
        }
        result = await browser_session.cmd_dblclick(ref="e0")
        assert result["ok"] is True
        mock_page.locator.return_value.dblclick.assert_awaited_once()

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_dblclick(ref="e0")
        assert result["ok"] is False
        assert "No active page" in result["error"]


class TestCmdDrag:
    async def test_success(self, browser_session, mock_page):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "Home",
            },
            "e1": {
                "selector": "aria-ref=e1",
                "role": "link",
                "name": "About",
            },
        }
        result = await browser_session.cmd_drag(start_ref="e0", end_ref="e1")
        assert result["ok"] is True
        mock_page.drag_and_drop.assert_awaited_once_with(
            "aria-ref=e0", "aria-ref=e1"
        )

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_drag(start_ref="e0", end_ref="e1")
        assert result["ok"] is False
        assert "No active page" in result["error"]


class TestCmdSelect:
    async def test_success(self, browser_session, mock_page):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "About",
            }
        }
        result = await browser_session.cmd_select(ref="e0", value="option1")
        assert result["ok"] is True
        mock_page.locator.return_value.select_option.assert_awaited_once_with("option1")

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_select(ref="e0", value="x")
        assert result["ok"] is False
        assert "No active page" in result["error"]


class TestCmdUpload:
    async def test_success(self, browser_session, mock_page):
        file_input = MagicMock()
        file_input.set_input_files = AsyncMock()

        # Need to handle multiple locator calls (one for upload, one for body in snapshot)
        def locator_side_effect(selector):
            if selector == 'input[type="file"]':
                return file_input
            # For body locator used by take_snapshot
            body_loc = MagicMock()
            body_loc.aria_snapshot = AsyncMock(return_value="- document")
            return body_loc

        mock_page.locator = MagicMock(side_effect=locator_side_effect)
        result = await browser_session.cmd_upload(file="/tmp/test.pdf")
        assert result["ok"] is True
        file_input.set_input_files.assert_awaited_once_with("/tmp/test.pdf")

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_upload(file="/tmp/test.pdf")
        assert result["ok"] is False
        assert "No active page" in result["error"]


class TestCmdCheck:
    async def test_success(self, browser_session, mock_page):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "About",
            }
        }
        result = await browser_session.cmd_check(ref="e0")
        assert result["ok"] is True
        mock_page.locator.return_value.check.assert_awaited_once()

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_check(ref="e0")
        assert result["ok"] is False
        assert "No active page" in result["error"]


class TestCmdUncheck:
    async def test_success(self, browser_session, mock_page):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "About",
            }
        }
        result = await browser_session.cmd_uncheck(ref="e0")
        assert result["ok"] is True
        mock_page.locator.return_value.uncheck.assert_awaited_once()

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_uncheck(ref="e0")
        assert result["ok"] is False
        assert "No active page" in result["error"]


class TestCmdResize:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_resize(width=800, height=600)
        assert result["ok"] is True
        mock_page.set_viewport_size.assert_awaited_once_with(
            {"width": 800, "height": 600}
        )

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_resize(width=800, height=600)
        assert result["ok"] is False
        assert "No active page" in result["error"]


# ---------------------------------------------------------------------------
# No-page tests for navigation / keyboard / mouse
# ---------------------------------------------------------------------------


class TestNavigationNoPage:
    async def test_go_back_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_go_back()
        assert result["ok"] is False
        assert "No active page" in result["error"]

    async def test_go_forward_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_go_forward()
        assert result["ok"] is False
        assert "No active page" in result["error"]

    async def test_reload_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_reload()
        assert result["ok"] is False
        assert "No active page" in result["error"]


class TestKeyboardNoPage:
    async def test_press_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_press(key="Enter")
        assert result["ok"] is False
        assert "No active page" in result["error"]

    async def test_keydown_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_keydown(key="Shift")
        assert result["ok"] is False
        assert "No active page" in result["error"]

    async def test_keyup_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_keyup(key="Shift")
        assert result["ok"] is False
        assert "No active page" in result["error"]


class TestMouseNoPage:
    async def test_mousemove_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_mousemove(x=0, y=0)
        assert result["ok"] is False
        assert "No active page" in result["error"]

    async def test_mousedown_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_mousedown()
        assert result["ok"] is False
        assert "No active page" in result["error"]

    async def test_mouseup_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_mouseup()
        assert result["ok"] is False
        assert "No active page" in result["error"]

    async def test_mousewheel_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_mousewheel(dx=0, dy=0)
        assert result["ok"] is False
        assert "No active page" in result["error"]


# ---------------------------------------------------------------------------
# Additional dialog tests
# ---------------------------------------------------------------------------


class TestCmdDialogAcceptWithPrompt:
    async def test_with_prompt_text(self, browser_session, mock_page):
        mock_dialog = MagicMock()
        mock_dialog.accept = AsyncMock()
        browser_session.dialog_queue.append(
            {
                "type": "prompt",
                "message": "Enter name",
                "default_value": "",
                "dialog": mock_dialog,
            }
        )
        result = await browser_session.cmd_dialog_accept(prompt_text="Alice")
        assert result["ok"] is True
        mock_dialog.accept.assert_awaited_once_with("Alice")


# ---------------------------------------------------------------------------
# Additional cookie tests
# ---------------------------------------------------------------------------


class TestCmdCookieGet:
    async def test_found(self, browser_session, mock_context):
        mock_context.cookies = AsyncMock(
            return_value=[
                {"name": "token", "value": "abc123", "domain": "example.com"},
            ]
        )
        result = await browser_session.cmd_cookie_get(name="token")
        assert result["ok"] is True
        assert "abc123" in result["output"]

    async def test_not_found(self, browser_session, mock_context):
        mock_context.cookies = AsyncMock(return_value=[])
        result = await browser_session.cmd_cookie_get(name="missing")
        assert result["ok"] is False
        assert "not found" in result["error"].lower()


class TestCmdCookieListWithDomain:
    async def test_filters_by_domain(self, browser_session, mock_context):
        mock_context.cookies = AsyncMock(
            return_value=[
                {"name": "a", "value": "1", "domain": "example.com"},
                {"name": "b", "value": "2", "domain": "other.com"},
            ]
        )
        result = await browser_session.cmd_cookie_list(domain="example")
        assert result["ok"] is True
        assert "example.com" in result["output"]


# ---------------------------------------------------------------------------
# Additional localStorage / sessionStorage tests
# ---------------------------------------------------------------------------


class TestCmdLocalstorageGet:
    async def test_success(self, browser_session, mock_page):
        mock_page.evaluate = AsyncMock(return_value="myvalue")
        result = await browser_session.cmd_localstorage_get(key="mykey")
        assert result["ok"] is True
        assert "myvalue" in result["output"]

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_localstorage_get(key="k")
        assert result["ok"] is False


class TestCmdLocalstorageSet:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_localstorage_set(key="k", value="v")
        assert result["ok"] is True
        mock_page.evaluate.assert_awaited()

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_localstorage_set(key="k", value="v")
        assert result["ok"] is False


class TestCmdLocalstorageDelete:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_localstorage_delete(key="k")
        assert result["ok"] is True
        mock_page.evaluate.assert_awaited()

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_localstorage_delete(key="k")
        assert result["ok"] is False


class TestCmdLocalstorageClear:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_localstorage_clear()
        assert result["ok"] is True
        mock_page.evaluate.assert_awaited()

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_localstorage_clear()
        assert result["ok"] is False


class TestCmdSessionstorageList:
    async def test_success(self, browser_session, mock_page):
        mock_page.evaluate = AsyncMock(return_value='[["sk","sv"]]')
        result = await browser_session.cmd_sessionstorage_list()
        assert result["ok"] is True
        assert "sessionStorage" in result["output"]

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_sessionstorage_list()
        assert result["ok"] is False


class TestCmdSessionstorageGet:
    async def test_success(self, browser_session, mock_page):
        mock_page.evaluate = AsyncMock(return_value="val")
        result = await browser_session.cmd_sessionstorage_get(key="k")
        assert result["ok"] is True

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_sessionstorage_get(key="k")
        assert result["ok"] is False


class TestCmdSessionstorageSet:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_sessionstorage_set(key="k", value="v")
        assert result["ok"] is True
        mock_page.evaluate.assert_awaited()

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_sessionstorage_set(key="k", value="v")
        assert result["ok"] is False


class TestCmdSessionstorageDelete:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_sessionstorage_delete(key="k")
        assert result["ok"] is True
        mock_page.evaluate.assert_awaited()

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_sessionstorage_delete(key="k")
        assert result["ok"] is False


class TestCmdSessionstorageClear:
    async def test_success(self, browser_session, mock_page):
        result = await browser_session.cmd_sessionstorage_clear()
        assert result["ok"] is True
        mock_page.evaluate.assert_awaited()

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_sessionstorage_clear()
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# Additional route tests
# ---------------------------------------------------------------------------


class TestCmdUnrouteAll:
    async def test_removes_all_routes(self, browser_session, mock_context):
        h1 = AsyncMock()
        h2 = AsyncMock()
        browser_session.active_routes = {"**/api/*": h1, "**/img/*": h2}
        result = await browser_session.cmd_unroute()
        assert result["ok"] is True
        assert "All routes removed" in result["output"]
        assert len(browser_session.active_routes) == 0

    async def test_unknown_pattern(self, browser_session):
        result = await browser_session.cmd_unroute(pattern="**/nope/*")
        assert result["ok"] is False
        assert "No active route" in result["error"]


# ---------------------------------------------------------------------------
# Additional tracing tests
# ---------------------------------------------------------------------------


class TestCmdTracingStartAlreadyActive:
    async def test_already_active(self, browser_session):
        browser_session.tracing_active = True
        result = await browser_session.cmd_tracing_start()
        assert result["ok"] is False
        assert "already active" in result["error"].lower()


class TestCmdTracingStopNotActive:
    async def test_not_active(self, browser_session):
        browser_session.tracing_active = False
        result = await browser_session.cmd_tracing_stop()
        assert result["ok"] is False
        assert "not active" in result["error"].lower()


# ---------------------------------------------------------------------------
# Additional console / network tests
# ---------------------------------------------------------------------------


class TestCmdConsoleEmpty:
    async def test_empty(self, browser_session):
        browser_session.console_messages = []
        result = await browser_session.cmd_console()
        assert result["ok"] is True
        assert "No console messages" in result["output"]


class TestCmdConsoleWithMinLevel:
    async def test_filters_by_level(self, browser_session, output_dir):
        browser_session.console_messages = [
            {"type": "log", "text": "info msg"},
            {"type": "error", "text": "error msg"},
        ]
        result = await browser_session.cmd_console(min_level="error")
        assert result["ok"] is True
        # Console output is saved to a file; only error-level messages should be included
        assert "Console" in result["output"]


class TestCmdNetworkEmpty:
    async def test_empty(self, browser_session):
        browser_session.network_log = []
        result = await browser_session.cmd_network()
        assert result["ok"] is True
        assert "No network requests" in result["output"]


# ---------------------------------------------------------------------------
# Snapshot no-page test
# ---------------------------------------------------------------------------


class TestCmdSnapshotNoPage:
    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_snapshot()
        assert result["ok"] is False
        assert "No active page" in result["error"]


# ---------------------------------------------------------------------------
# Eval no-page test
# ---------------------------------------------------------------------------


class TestCmdEvalNoPage:
    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_eval(expression="1+1")
        assert result["ok"] is False
        assert "No active page" in result["error"]


# ---------------------------------------------------------------------------
# Screenshot with filename
# ---------------------------------------------------------------------------


class TestCmdScreenshotWithFilename:
    async def test_custom_filename(self, browser_session, mock_page, tmp_path):
        mock_page.screenshot = AsyncMock(return_value=b"fake-png-data")
        filepath = str(tmp_path / "custom.png")
        result = await browser_session.cmd_screenshot(filename=filepath)
        assert result["ok"] is True
        assert "Screenshot" in result["output"]
        mock_page.screenshot.assert_awaited_once()


# ---------------------------------------------------------------------------
# PDF with filename / no page
# ---------------------------------------------------------------------------


class TestCmdPdfExtra:
    async def test_with_filename(self, browser_session, mock_page, tmp_path):
        mock_page.pdf = AsyncMock(return_value=b"fake-pdf-data")
        filepath = str(tmp_path / "custom.pdf")
        result = await browser_session.cmd_pdf(filename=filepath)
        assert result["ok"] is True
        mock_page.pdf.assert_awaited_once()

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_pdf()
        assert result["ok"] is False
        assert "No active page" in result["error"]


# ---------------------------------------------------------------------------
# Tab close with specific index / invalid index
# ---------------------------------------------------------------------------


class TestCmdTabCloseExtra:
    async def test_close_specific_index(self, browser_session, mock_page):
        page2 = MagicMock()
        page2.url = "https://other.com"
        page2.title = AsyncMock(return_value="Other")
        page2.evaluate = AsyncMock(return_value="[]")
        page2.close = AsyncMock()
        # Needs locator with aria_snapshot for snapshot pathway
        page2_locator = MagicMock()
        page2_locator.aria_snapshot = AsyncMock(return_value="- document")
        page2.locator = MagicMock(return_value=page2_locator)
        page2_role_locator = MagicMock()
        page2_role_locator.nth = MagicMock(return_value=page2_role_locator)
        page2_role_locator.evaluate = AsyncMock(return_value=None)
        page2.get_by_role = MagicMock(return_value=page2_role_locator)
        browser_session.pages = [mock_page, page2]
        browser_session.active_page_index = 0
        result = await browser_session.cmd_tab_close(index=1)
        assert result["ok"] is True
        page2.close.assert_awaited_once()

    async def test_invalid_index(self, browser_session):
        result = await browser_session.cmd_tab_close(index=99)
        assert result["ok"] is False
        assert "Invalid tab index" in result["error"]


# ---------------------------------------------------------------------------
# State save / load
# ---------------------------------------------------------------------------


class TestCmdStateSave:
    async def test_success(self, browser_session, mock_context, output_dir):
        result = await browser_session.cmd_state_save()
        assert result["ok"] is True
        assert "Storage state saved" in result["output"]
        mock_context.storage_state.assert_awaited_once()

    async def test_with_filename(self, browser_session, mock_context, tmp_path):
        filepath = str(tmp_path / "state.json")
        result = await browser_session.cmd_state_save(filename=filepath)
        assert result["ok"] is True
        mock_context.storage_state.assert_awaited_once()


# ---------------------------------------------------------------------------
# Cookie set no-page
# ---------------------------------------------------------------------------


class TestCmdCookieSetNoPage:
    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_cookie_set(name="x", value="y")
        assert result["ok"] is False
        assert "No active page" in result["error"]


# ---------------------------------------------------------------------------
# LocalStorage list no-page
# ---------------------------------------------------------------------------


class TestCmdLocalstorageListNoPage:
    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_localstorage_list()
        assert result["ok"] is False
        assert "No active page" in result["error"]


# ---------------------------------------------------------------------------
# Response class tests (replaces _auto_snapshot / _format_page_info tests)
# ---------------------------------------------------------------------------


class TestResponse:
    def test_init(self):
        r = Response()
        assert r._errors == []
        assert r._results == []
        assert r._code is None
        assert r._include_snapshot is False
        assert r._include_full_snapshot is False
        assert r._is_snapshot_command is False

    def test_add_result(self):
        r = Response()
        r.add_result("hello")
        assert r._results == ["hello"]

    def test_add_error(self):
        r = Response()
        r.add_error("oops")
        assert r._errors == ["oops"]

    def test_add_code(self):
        r = Response()
        r.add_code("await page.click();")
        assert r._code == "await page.click();"

    def test_set_include_snapshot(self):
        r = Response()
        r.set_include_snapshot()
        assert r._include_snapshot is True

    def test_set_include_full_snapshot(self):
        r = Response()
        r.set_include_full_snapshot("test.yml")
        assert r._include_full_snapshot is True
        assert r._full_snapshot_filename == "test.yml"
        assert r._is_snapshot_command is True

    async def test_serialize_empty(self, browser_session):
        r = Response()
        output = await r.serialize(browser_session)
        assert output == ""

    async def test_serialize_with_result(self, browser_session):
        r = Response()
        r.add_result("test result")
        output = await r.serialize(browser_session)
        assert "### Result" in output
        assert "test result" in output

    async def test_serialize_with_error(self, browser_session):
        r = Response()
        r.add_error("test error")
        output = await r.serialize(browser_session)
        assert "### Error" in output
        assert "test error" in output

    async def test_serialize_with_code(self, browser_session):
        r = Response()
        r.add_code("await page.click();")
        output = await r.serialize(browser_session)
        assert "### Ran Playwright code" in output
        assert "await page.click();" in output

    async def test_serialize_with_snapshot(self, browser_session, mock_page):
        r = Response()
        r.set_include_snapshot()
        output = await r.serialize(browser_session)
        assert "### Page" in output
        assert "Page URL" in output
        assert "example.com" in output
        assert "### Snapshot" in output
        # Non-snapshot commands should NOT include console counts
        assert "Console" not in output

    async def test_serialize_with_full_snapshot_includes_console(
        self, browser_session, mock_page
    ):
        browser_session.console_messages = [
            {"type": "error", "text": "err1"},
            {"type": "warning", "text": "warn1"},
        ]
        r = Response()
        r.set_include_full_snapshot()
        output = await r.serialize(browser_session)
        assert "### Page" in output
        assert "Page URL" in output
        assert "### Snapshot" in output
        assert "- Console: 1 errors, 1 warnings" in output

    async def test_serialize_snapshot_omits_empty_title(
        self, browser_session, mock_page
    ):
        mock_page.title = AsyncMock(return_value="")
        r = Response()
        r.set_include_snapshot()
        output = await r.serialize(browser_session)
        assert "### Page" in output
        assert "Page URL" in output
        assert "Page Title" not in output

    async def test_serialize_snapshot_includes_nonempty_title(
        self, browser_session, mock_page
    ):
        mock_page.title = AsyncMock(return_value="My Title")
        r = Response()
        r.set_include_snapshot()
        output = await r.serialize(browser_session)
        assert "- Page Title: My Title" in output

    async def test_serialize_no_page_snapshot(self, browser_session):
        browser_session.pages = []
        r = Response()
        r.set_include_snapshot()
        output = await r.serialize(browser_session)
        # No snapshot section when no active page
        assert "### Snapshot" not in output


# ---------------------------------------------------------------------------
# New command tests
# ---------------------------------------------------------------------------


class TestCmdShow:
    async def test_show(self, browser_session):
        result = await browser_session.cmd_show()
        assert result["ok"] is True
        assert "not available" in result["output"].lower()


class TestCmdDevtoolsStart:
    async def test_devtools_start(self, browser_session):
        result = await browser_session.cmd_devtools_start()
        assert result["ok"] is True
        assert "not available" in result["output"].lower()


class TestCmdConfigPrint:
    async def test_config_print(self, browser_session):
        result = await browser_session.cmd_config_print()
        assert result["ok"] is True
        # Should be valid JSON
        import json

        parsed = json.loads(result["output"])
        assert "browser" in parsed


class TestCmdRunCode:
    async def test_success(self, browser_session, mock_page):
        mock_page.evaluate = AsyncMock(return_value=42)
        result = await browser_session.cmd_run_code(code="return 42;")
        assert result["ok"] is True
        assert "42" in result["output"]

    async def test_no_page(self, browser_session):
        browser_session.pages = []
        result = await browser_session.cmd_run_code(code="return 1;")
        assert result["ok"] is False
        assert "No active page" in result["error"]


class TestCmdTypeSubmit:
    async def test_submit(self, browser_session, mock_page):
        result = await browser_session.cmd_type(text="hello", submit=True)
        assert result["ok"] is True
        mock_page.keyboard.type.assert_awaited_once_with("hello")
        mock_page.keyboard.press.assert_awaited_once_with("Enter")


class TestCmdFillSubmit:
    async def test_submit(self, browser_session, mock_page):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "About",
            }
        }
        result = await browser_session.cmd_fill(ref="e0", text="hello", submit=True)
        assert result["ok"] is True
        mock_page.locator.return_value.fill.assert_awaited_once_with("hello")
        mock_page.keyboard.press.assert_awaited_once_with("Enter")


class TestCmdClickModifiers:
    async def test_with_modifiers(self, browser_session, mock_page):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "About",
            }
        }
        result = await browser_session.cmd_click(ref="e0", modifiers=["Shift"])
        assert result["ok"] is True
        mock_page.locator.return_value.click.assert_awaited_once_with(
            button="left", modifiers=["Shift"]
        )


class TestCmdConsoleClear:
    async def test_clear(self, browser_session):
        browser_session.console_messages = [{"type": "log", "text": "hi"}]
        browser_session._last_console_index = 1
        result = await browser_session.cmd_console(clear=True)
        assert result["ok"] is True
        assert "Console cleared" in result["output"]
        assert browser_session.console_messages == []
        assert browser_session._last_console_index == 0


class TestCmdNetworkClear:
    async def test_clear(self, browser_session):
        browser_session.network_log = [{"method": "GET", "url": "http://x"}]
        result = await browser_session.cmd_network(clear=True)
        assert result["ok"] is True
        assert "Network log cleared" in result["output"]
        assert browser_session.network_log == []


# ---------------------------------------------------------------------------
# start_daemon / _setup_logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def test_configures_logging(self, sessions_dir):
        import logging

        from patchright_cli.server import _setup_logging

        _setup_logging("log-test")
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        # Reset to avoid side effects
        for h in root.handlers[:]:
            if hasattr(h, "baseFilename") and "log-test" in h.baseFilename:
                root.removeHandler(h)


class TestStartDaemonEntry:
    def test_calls_run_server(self, sessions_dir, monkeypatch):
        from unittest.mock import patch

        from patchright_cli.server import start_daemon

        with (
            patch("patchright_cli.server.asyncio.run") as mock_run,
            patch("patchright_cli.server._setup_logging"),
        ):
            start_daemon("entry-test", '{"output_dir": ".patchright-cli"}')
            mock_run.assert_called_once()

    def test_accepts_dict(self, sessions_dir, monkeypatch):
        from unittest.mock import patch

        from patchright_cli.server import start_daemon

        with (
            patch("patchright_cli.server.asyncio.run") as mock_run,
            patch("patchright_cli.server._setup_logging"),
        ):
            start_daemon("entry-test", {"output_dir": ".patchright-cli"})
            mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# Phase 7: Code generation style tests
# ---------------------------------------------------------------------------


class TestRefToCode:
    """Tests for _ref_to_code semantic locator generation."""

    def test_named_role(self, browser_session):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "About",
            }
        }
        assert (
            browser_session._ref_to_code("e0")
            == "page.getByRole('link', { name: 'About' })"
        )

    def test_unnamed_role(self, browser_session):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "button",
                "name": None,
            }
        }
        assert browser_session._ref_to_code("e0") == "page.getByRole('button')"

    def test_missing_ref_fallback(self, browser_session):
        code = browser_session._ref_to_code("e99")
        assert "page.locator" in code

    def test_plain_string_fallback(self, browser_session):
        browser_session.element_refs = {"e0": "aria-ref=e0"}
        code = browser_session._ref_to_code("e0")
        assert "page.locator" in code

    def test_name_with_single_quotes_escaped(self, browser_session):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "it's",
            }
        }
        code = browser_session._ref_to_code("e0")
        assert "it\\'s" in code


class TestCodeGenSingleQuotes:
    """Tests that code generation uses single quotes."""

    async def test_goto_single_quotes(self, browser_session, mock_page):
        result = await browser_session.cmd_goto(url="https://example.com")
        output = result["output"]
        assert "page.goto('https://example.com')" in output

    async def test_eval_arrow_function(self, browser_session, mock_page):
        mock_page.evaluate = AsyncMock(return_value="title")
        result = await browser_session.cmd_eval(expression="document.title")
        output = result["output"]
        assert "page.evaluate('() => (document.title)')" in output

    async def test_click_semantic_locator(self, browser_session, mock_page):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "About",
            }
        }
        result = await browser_session.cmd_click(ref="e0")
        output = result["output"]
        assert "page.getByRole('link', { name: 'About' }).click()" in output

    async def test_fill_semantic_locator(self, browser_session, mock_page):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "textbox",
                "name": "Search",
            }
        }
        result = await browser_session.cmd_fill(ref="e0", text="hello")
        output = result["output"]
        assert "page.getByRole('textbox', { name: 'Search' }).fill('hello')" in output

    async def test_hover_semantic_locator(self, browser_session, mock_page):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "button",
                "name": "OK",
            }
        }
        result = await browser_session.cmd_hover(ref="e0")
        output = result["output"]
        assert "page.getByRole('button', { name: 'OK' }).hover()" in output

    async def test_keyboard_press_single_quotes(self, browser_session, mock_page):
        result = await browser_session.cmd_press(key="Enter")
        output = result["output"]
        assert "page.keyboard.press('Enter')" in output

    async def test_screenshot_full_options(self, browser_session, mock_page):
        mock_page.screenshot = AsyncMock(return_value=b"\x89PNG")
        result = await browser_session.cmd_screenshot()
        output = result["output"]
        assert "scale: 'css'" in output
        assert "type: 'png'" in output

    async def test_screenshot_element_semantic(self, browser_session, mock_page):
        browser_session.element_refs = {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "img",
                "name": "Logo",
            }
        }
        mock_page.locator.return_value.screenshot = AsyncMock(return_value=b"\x89PNG")
        result = await browser_session.cmd_screenshot(ref="e0")
        output = result["output"]
        assert "page.getByRole('img', { name: 'Logo' }).screenshot()" in output


# ---------------------------------------------------------------------------
# cmd_transcribe_audio
# ---------------------------------------------------------------------------


class TestCmdTranscribeAudio:
    async def test_no_page_returns_error(
        self, sessions_dir, output_dir, default_config
    ):
        session = BrowserSession("test", default_config)
        result = await session.cmd_transcribe_audio()
        assert result["ok"] is False
        assert "No active page" in result["error"]

    async def test_no_api_key_returns_error(
        self, browser_session, mock_page, monkeypatch
    ):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = await browser_session.cmd_transcribe_audio()
        assert result["ok"] is False
        assert "OPENAI_API_KEY" in result["error"]

    async def test_no_audio_found_returns_error(
        self, browser_session, mock_page, monkeypatch
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        with patch(
            "patchright_cli.captcha.find_audio_url", new_callable=AsyncMock
        ) as mock_find:
            mock_find.return_value = None
            result = await browser_session.cmd_transcribe_audio()
        assert result["ok"] is False
        assert "No audio element" in result["error"]

    async def test_success_with_auto_detect(
        self, browser_session, mock_page, mock_context, monkeypatch
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_resp = MagicMock()
        mock_resp.body = AsyncMock(return_value=b"fake-audio")
        mock_context.request = MagicMock()
        mock_context.request.get = AsyncMock(return_value=mock_resp)

        with (
            patch(
                "patchright_cli.captcha.find_audio_url", new_callable=AsyncMock
            ) as mock_find,
            patch(
                "patchright_cli.captcha.transcribe_audio", new_callable=AsyncMock
            ) as mock_transcribe,
        ):
            mock_find.return_value = "https://example.com/audio.mp3"
            mock_transcribe.return_value = "four two seven"
            result = await browser_session.cmd_transcribe_audio()

        assert result["ok"] is True
        assert "four two seven" in result["output"]
        mock_transcribe.assert_awaited_once_with(b"fake-audio", "sk-test")

    async def test_success_with_explicit_url(
        self, browser_session, mock_page, mock_context, monkeypatch
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_resp = MagicMock()
        mock_resp.body = AsyncMock(return_value=b"audio-data")
        mock_context.request = MagicMock()
        mock_context.request.get = AsyncMock(return_value=mock_resp)

        with patch(
            "patchright_cli.captcha.transcribe_audio", new_callable=AsyncMock
        ) as mock_transcribe:
            mock_transcribe.return_value = "hello world"
            result = await browser_session.cmd_transcribe_audio(
                url="https://direct.com/file.wav"
            )

        assert result["ok"] is True
        assert "hello world" in result["output"]
        mock_context.request.get.assert_awaited_once_with(
            "https://direct.com/file.wav"
        )

    async def test_file_save_with_filename(
        self, browser_session, mock_page, mock_context, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_resp = MagicMock()
        mock_resp.body = AsyncMock(return_value=b"audio-bytes")
        mock_context.request = MagicMock()
        mock_context.request.get = AsyncMock(return_value=mock_resp)

        audio_path = str(tmp_path / "saved.wav")
        with (
            patch(
                "patchright_cli.captcha.find_audio_url", new_callable=AsyncMock
            ) as mock_find,
            patch(
                "patchright_cli.captcha.transcribe_audio", new_callable=AsyncMock
            ) as mock_transcribe,
        ):
            mock_find.return_value = "https://example.com/a.wav"
            mock_transcribe.return_value = "transcribed"
            result = await browser_session.cmd_transcribe_audio(
                filename=audio_path
            )

        assert result["ok"] is True
        assert "transcribed" in result["output"]
        assert Path(audio_path).read_bytes() == b"audio-bytes"
