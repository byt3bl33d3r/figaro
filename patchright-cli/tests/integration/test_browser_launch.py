"""Integration tests for browser launch and lifecycle.

These tests use real headless Chromium via Patchright. Each test gets a fresh
browser instance to ensure isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from patchright_cli.config import BrowserConfig, CLIConfig
from patchright_cli.server import BrowserSession


@pytest.mark.integration
async def test_launch_isolated_creates_browser_and_context(
    browser_session_real: BrowserSession,
) -> None:
    """Isolated launch should create browser, context, and one initial page."""
    assert browser_session_real.browser is not None
    assert browser_session_real.context is not None
    assert len(browser_session_real.pages) == 1


@pytest.mark.integration
async def test_launch_isolated_page_url_is_blank(
    browser_session_real: BrowserSession,
) -> None:
    """The initial page of an isolated launch should be about:blank."""
    assert browser_session_real.active_page.url == "about:blank"


@pytest.mark.integration
async def test_launch_persistent_browser_is_context(
    browser_session_persistent: BrowserSession,
) -> None:
    """In persistent context mode, browser and context should be the same object."""
    assert browser_session_persistent.browser is browser_session_persistent.context


@pytest.mark.integration
async def test_launch_persistent_creates_user_data_dir(
    browser_session_persistent: BrowserSession,
    integration_config_persistent: CLIConfig,
) -> None:
    """Persistent launch should create the user_data_dir on disk."""
    assert integration_config_persistent.browser.user_data_dir is not None
    assert Path(integration_config_persistent.browser.user_data_dir).exists()


@pytest.mark.integration
async def test_cmd_open_launches_and_navigates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cmd_open should launch the browser and navigate to the given URL."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    config = CLIConfig(
        browser=BrowserConfig(
            isolated=True,
            launch_options={"headless": True, "chromium_sandbox": False},
            context_options={},
        ),
    )
    session = BrowserSession("test-cmd-open", config)
    try:
        result = await session.cmd_open(url="data:text/html,<h1>Hello</h1>")
        assert result["ok"] is True
        assert "Hello" in result["output"]
    finally:
        try:
            if session.context and session.context != session.browser:
                await session.context.close()
            if session.browser:
                await session.browser.close()
            if session.playwright:
                await session.playwright.stop()
        except Exception:
            pass


@pytest.mark.integration
async def test_cmd_open_headless_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cmd_open(headless=True) should override a config that has headless=False."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    config = CLIConfig(
        browser=BrowserConfig(
            isolated=True,
            launch_options={"headless": False, "chromium_sandbox": False},
            context_options={},
        ),
    )
    session = BrowserSession("test-headless-override", config)
    try:
        result = await session.cmd_open(headless=True)
        assert result["ok"] is True
    finally:
        try:
            if session.context and session.context != session.browser:
                await session.context.close()
            if session.browser:
                await session.browser.close()
            if session.playwright:
                await session.playwright.stop()
        except Exception:
            pass


@pytest.mark.integration
async def test_cmd_close_releases_resources(
    browser_session_real: BrowserSession,
) -> None:
    """cmd_close should cleanly shut down the browser and return ok."""
    result = await browser_session_real.cmd_close()
    assert result["ok"] is True
    # After close, playwright/browser/context are stopped — mark them as None
    # so the fixture teardown doesn't try to close them again.
    browser_session_real.browser = None
    browser_session_real.context = None
    browser_session_real.playwright = None


@pytest.mark.integration
async def test_launch_with_init_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """launch_browser with init_page should navigate to the specified URL."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    config = CLIConfig(
        browser=BrowserConfig(
            isolated=True,
            init_page=["data:text/html,<h1>Init</h1>"],
            launch_options={"headless": True, "chromium_sandbox": False},
            context_options={},
        ),
    )
    session = BrowserSession("test-init-page", config)
    try:
        await session.launch_browser()
        assert session.active_page.url.startswith("data:")
    finally:
        try:
            if session.context and session.context != session.browser:
                await session.context.close()
            if session.browser:
                await session.browser.close()
            if session.playwright:
                await session.playwright.stop()
        except Exception:
            pass
