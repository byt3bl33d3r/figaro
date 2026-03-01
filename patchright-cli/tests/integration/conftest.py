"""Shared fixtures for patchright-cli integration tests.

These fixtures launch a real headless Chromium browser via Patchright.
Every test gets a fresh browser instance (function-scoped) for isolation.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path

import pytest

from patchright_cli.config import BrowserConfig, CLIConfig
from patchright_cli.server import BrowserSession

# ---------------------------------------------------------------------------
# Test HTML page served via data: URL (no external HTTP server needed)
# ---------------------------------------------------------------------------

TEST_HTML = "data:text/html," + urllib.parse.quote(
    """<html><body>
<h1>Test Page</h1>
<p>Some text</p>
<a href="https://example.com" id="link1">Example Link</a>
<form>
  <input type="text" name="username" placeholder="Enter username">
  <input type="checkbox" name="agree" id="agree-cb">
  <button type="submit" id="submit-btn">Submit</button>
</form>
<select name="color"><option value="red">Red</option><option value="blue">Blue</option></select>
</body></html>"""
)


# ---------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def integration_config() -> CLIConfig:
    """CLIConfig for isolated headless Chromium (no sandbox)."""
    return CLIConfig(
        browser=BrowserConfig(
            isolated=True,
            launch_options={"headless": True, "chromium_sandbox": False},
            context_options={},
        ),
    )


@pytest.fixture
def integration_config_persistent(tmp_path: Path) -> CLIConfig:
    """CLIConfig for persistent (non-isolated) headless Chromium."""
    return CLIConfig(
        browser=BrowserConfig(
            isolated=False,
            user_data_dir=str(tmp_path / "user-data"),
            launch_options={"headless": True, "chromium_sandbox": False},
            context_options={},
        ),
    )


# ---------------------------------------------------------------------------
# Browser session fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def browser_session_real(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, integration_config: CLIConfig
) -> BrowserSession:
    """Launch a real isolated headless browser, yield BrowserSession, cleanup."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    session = BrowserSession("integration-test", integration_config)
    await session.launch_browser()
    try:
        yield session  # type: ignore[misc]
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


@pytest.fixture
async def browser_session_persistent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    integration_config_persistent: CLIConfig,
) -> BrowserSession:
    """Launch a real persistent headless browser, yield BrowserSession, cleanup."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    session = BrowserSession("integration-persistent", integration_config_persistent)
    await session.launch_browser()
    try:
        yield session  # type: ignore[misc]
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


@pytest.fixture
async def html_page(
    browser_session_real: BrowserSession,
) -> tuple[BrowserSession, object]:
    """Navigate the browser session's active page to TEST_HTML."""
    page = browser_session_real.active_page
    await page.goto(TEST_HTML)
    return browser_session_real, page
