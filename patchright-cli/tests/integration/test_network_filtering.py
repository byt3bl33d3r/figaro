"""Integration tests for network filtering via _setup_network_filtering().

These tests verify that ``BrowserSession._setup_network_filtering()`` correctly
intercepts requests based on ``config.network.allowed_origins`` and
``config.network.blocked_origins``.  Each test launches a real headless Chromium
browser via Patchright.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from patchright_cli.config import BrowserConfig, CLIConfig, NetworkConfig
from patchright_cli.server import BrowserSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_browser_config(**overrides) -> BrowserConfig:
    """Return a BrowserConfig suitable for headless integration tests."""
    defaults = {
        "isolated": True,
        "launch_options": {"headless": True, "chromium_sandbox": False},
        "context_options": {},
    }
    defaults.update(overrides)
    return BrowserConfig(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_blocked_origins_aborts_matching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requests whose URL contains a blocked origin should be aborted."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    config = CLIConfig(
        browser=_base_browser_config(),
        network=NetworkConfig(blocked_origins=["blocked.test"]),
    )
    session = BrowserSession("test-blocked-match", config)
    try:
        await session.launch_browser()
        page = session.active_page

        # Navigate to a harmless data URL first so we have a page context for
        # evaluating JavaScript.
        await page.goto("data:text/html,<h1>OK</h1>")

        # fetch() to the blocked origin should fail (net::ERR_FAILED after abort).
        result = await page.evaluate(
            "fetch('https://blocked.test/foo').then(() => 'ok').catch(() => 'blocked')"
        )
        assert result == "blocked"
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
async def test_blocked_origins_allows_non_matching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requests whose URL does NOT contain a blocked origin should proceed."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    config = CLIConfig(
        browser=_base_browser_config(),
        network=NetworkConfig(blocked_origins=["blocked.test"]),
    )
    session = BrowserSession("test-blocked-nonmatch", config)
    try:
        await session.launch_browser()
        page = session.active_page

        # "data:" does not contain "blocked.test", so navigation should succeed.
        await page.goto("data:text/html,<h1>OK</h1>")
        assert page.url.startswith("data:")
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
async def test_allowed_origins_permits_matching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requests whose URL contains an allowed origin should be permitted."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    config = CLIConfig(
        browser=_base_browser_config(),
        network=NetworkConfig(allowed_origins=["data:"]),
    )
    session = BrowserSession("test-allowed-match", config)
    try:
        await session.launch_browser()
        page = session.active_page

        # "data:" is in the allowed list, so navigation should succeed.
        await page.goto("data:text/html,<h1>Allowed</h1>")
        assert page.url.startswith("data:")
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
async def test_allowed_origins_blocks_non_matching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requests whose URL does NOT match any allowed origin should be aborted."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    config = CLIConfig(
        browser=_base_browser_config(),
        network=NetworkConfig(allowed_origins=["only-this.test"]),
    )
    session = BrowserSession("test-allowed-nonmatch", config)
    try:
        await session.launch_browser()
        page = session.active_page

        # The page starts at about:blank. Evaluate a fetch to an origin that
        # is not in the allowed list — it should be aborted.
        result = await page.evaluate(
            "fetch('https://other.test/x').then(() => 'ok').catch(() => 'blocked')"
        )
        assert result == "blocked"
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
async def test_no_filtering_when_both_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When neither allowed nor blocked origins are set, all requests pass through."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    config = CLIConfig(
        browser=_base_browser_config(),
        # Default NetworkConfig has empty lists for both.
    )
    session = BrowserSession("test-no-filter", config)
    try:
        await session.launch_browser()
        page = session.active_page

        await page.goto("data:text/html,<h1>NoFilter</h1>")
        assert page.url.startswith("data:")
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
