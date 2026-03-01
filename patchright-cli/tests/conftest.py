"""Shared fixtures for patchright-cli tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from patchright_cli.config import CLIConfig
from patchright_cli.server import BrowserSession


@pytest.fixture
def sessions_dir(tmp_path, monkeypatch):
    """Patch Path.home() so session dirs live under tmp_path."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path / ".patchright-cli" / "sessions"


@pytest.fixture
def output_dir(tmp_path, monkeypatch):
    """Patch Path.cwd() so output dirs live under tmp_path."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    return tmp_path / ".patchright-cli"


@pytest.fixture
def default_config():
    """Return a default CLIConfig instance."""
    return CLIConfig()


@pytest.fixture
def config_dict(default_config):
    """Return a default config as a dict (for passing to daemons)."""
    return default_config.model_dump()


@pytest.fixture
def config_file(tmp_path):
    """Write a config JSON file and return its path."""
    config = {
        "browser": {
            "browser_name": "firefox",
            "isolated": True,
        },
        "output_dir": ".custom-output",
    }
    path = tmp_path / "test-config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


@pytest.fixture
def mock_page():
    """A MagicMock standing in for a Playwright Page."""
    page = MagicMock()
    page.url = "https://example.com"
    page.title = AsyncMock(return_value="Example")
    page.goto = AsyncMock()
    page.evaluate = AsyncMock(return_value="[]")
    page.screenshot = AsyncMock()
    page.pdf = AsyncMock()
    page.reload = AsyncMock()
    page.go_back = AsyncMock()
    page.go_forward = AsyncMock()
    page.close = AsyncMock()
    page.bring_to_front = AsyncMock()
    page.set_viewport_size = AsyncMock()
    page.video = None

    # Keyboard
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.keyboard.down = AsyncMock()
    page.keyboard.up = AsyncMock()

    # Mouse
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()
    page.mouse.down = AsyncMock()
    page.mouse.up = AsyncMock()
    page.mouse.wheel = AsyncMock()

    # Locator
    locator = MagicMock()
    locator.click = AsyncMock()
    locator.dblclick = AsyncMock()
    locator.fill = AsyncMock()
    locator.hover = AsyncMock()
    locator.select_option = AsyncMock()
    locator.check = AsyncMock()
    locator.uncheck = AsyncMock()
    locator.screenshot = AsyncMock()
    locator.set_input_files = AsyncMock()
    locator.evaluate = AsyncMock(return_value="result")
    locator.aria_snapshot = AsyncMock(return_value="- document")
    page.locator = MagicMock(return_value=locator)

    # get_by_role (used by snapshot.py for ref injection)
    role_locator = MagicMock()
    role_locator.nth = MagicMock(return_value=role_locator)
    role_locator.evaluate = AsyncMock(return_value=None)
    page.get_by_role = MagicMock(return_value=role_locator)

    # drag_and_drop
    page.drag_and_drop = AsyncMock()

    # snapshotForAI support (used by take_snapshot via Response.serialize)
    impl = MagicMock()
    channel = MagicMock()
    channel.send_return_as_dict = AsyncMock(
        return_value={"full": "- document\n"}
    )
    impl._channel = channel
    page._impl_obj = impl

    return page


@pytest.fixture
def mock_context(mock_page):
    """A MagicMock standing in for a Playwright BrowserContext."""
    ctx = MagicMock()
    ctx.pages = [mock_page]
    ctx.new_page = AsyncMock(return_value=mock_page)
    ctx.cookies = AsyncMock(return_value=[])
    ctx.add_cookies = AsyncMock()
    ctx.clear_cookies = AsyncMock()
    ctx.storage_state = AsyncMock()
    ctx.close = AsyncMock()
    ctx.route = AsyncMock()
    ctx.unroute = AsyncMock()
    ctx.set_default_timeout = MagicMock()
    ctx.set_default_navigation_timeout = MagicMock()
    ctx.add_init_script = AsyncMock()
    ctx.on = MagicMock()

    # Tracing
    ctx.tracing = MagicMock()
    ctx.tracing.start = AsyncMock()
    ctx.tracing.stop = AsyncMock()

    return ctx


@pytest.fixture
def mock_browser(mock_context):
    """A MagicMock standing in for a Playwright Browser."""
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=mock_context)
    browser.close = AsyncMock()
    browser.contexts = [mock_context]
    return browser


@pytest.fixture
def browser_session(
    sessions_dir, output_dir, default_config, mock_page, mock_context, mock_browser
):
    """A BrowserSession with mocked Playwright objects pre-wired."""
    session = BrowserSession("test-session", default_config)
    session.playwright = MagicMock()
    session.browser = mock_browser
    session.context = mock_context
    session.pages = [mock_page]
    session.active_page_index = 0
    return session
