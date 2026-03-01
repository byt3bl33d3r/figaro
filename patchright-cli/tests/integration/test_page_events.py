"""Integration tests for page-level event capturing.

Verifies that console messages, network requests/responses, dialogs, and popup
pages are properly captured by BrowserSession's listeners when running against
a real headless Chromium instance.
"""

from __future__ import annotations

import urllib.parse

import pytest

from patchright_cli.server import BrowserSession


@pytest.mark.integration
@pytest.mark.asyncio
async def test_console_log_captured(browser_session_real: BrowserSession) -> None:
    """Console.log messages are captured with type='log'."""
    page = browser_session_real.active_page
    html = "data:text/html," + urllib.parse.quote(
        '<html><body><script>console.log("hello integration")</script></body></html>'
    )
    await page.goto(html)
    await page.wait_for_timeout(200)

    matches = [
        m
        for m in browser_session_real.console_messages
        if m["type"] == "log" and "hello integration" in m["text"]
    ]
    assert len(matches) >= 1, (
        f"Expected a console.log entry with 'hello integration', "
        f"got: {browser_session_real.console_messages}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_console_error_captured(browser_session_real: BrowserSession) -> None:
    """Console.error messages are captured with type='error'."""
    page = browser_session_real.active_page
    html = "data:text/html," + urllib.parse.quote(
        '<html><body><script>console.error("oops integration")</script></body></html>'
    )
    await page.goto(html)
    await page.wait_for_timeout(200)

    matches = [
        m
        for m in browser_session_real.console_messages
        if m["type"] == "error" and "oops integration" in m["text"]
    ]
    assert len(matches) >= 1, (
        f"Expected a console.error entry with 'oops integration', "
        f"got: {browser_session_real.console_messages}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_console_warning_captured(browser_session_real: BrowserSession) -> None:
    """Console.warn messages are captured with type='warning'."""
    page = browser_session_real.active_page
    html = "data:text/html," + urllib.parse.quote(
        '<html><body><script>console.warn("warn integration")</script></body></html>'
    )
    await page.goto(html)
    await page.wait_for_timeout(200)

    matches = [
        m
        for m in browser_session_real.console_messages
        if m["type"] == "warning" and "warn integration" in m["text"]
    ]
    assert len(matches) >= 1, (
        f"Expected a console.warn entry with 'warn integration', "
        f"got: {browser_session_real.console_messages}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_network_request_logged(browser_session_real: BrowserSession) -> None:
    """A fetch request produces at least one network log entry."""
    page = browser_session_real.active_page
    # data: URLs don't go through the network stack, so use a routed request
    await page.route(
        "**/test-endpoint", lambda route: route.fulfill(status=200, body="ok")
    )
    await page.evaluate("fetch('http://localhost/test-endpoint')")
    await page.wait_for_timeout(200)

    assert len(browser_session_real.network_log) >= 1, (
        "Expected at least one network log entry"
    )
    entry = browser_session_real.network_log[-1]
    assert "method" in entry, "Network log entry missing 'method' key"
    assert "url" in entry, "Network log entry missing 'url' key"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_network_response_status_backfilled(
    browser_session_real: BrowserSession,
) -> None:
    """Network log entries have their status backfilled once the response arrives."""
    page = browser_session_real.active_page
    await page.route(
        "**/test-status",
        lambda route: route.fulfill(status=200, body="ok"),
    )
    await page.evaluate("fetch('http://localhost/test-status')")
    await page.wait_for_timeout(200)

    entries_with_status = [
        e for e in browser_session_real.network_log if e.get("status") is not None
    ]
    assert len(entries_with_status) >= 1, (
        f"Expected at least one network log entry with a non-None status, "
        f"got: {browser_session_real.network_log}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dialog_captured_and_queued(browser_session_real: BrowserSession) -> None:
    """An alert() dialog is captured in the dialog_queue with correct metadata."""
    page = browser_session_real.active_page
    html = "data:text/html," + urllib.parse.quote(
        '<html><body><script>setTimeout(() => alert("hi"), 50)</script></body></html>'
    )
    await page.goto(html)
    await page.wait_for_timeout(500)

    assert len(browser_session_real.dialog_queue) >= 1, (
        "Expected at least one dialog in the queue"
    )
    entry = browser_session_real.dialog_queue[0]
    assert entry["type"] == "alert", (
        f"Expected dialog type 'alert', got '{entry['type']}'"
    )
    assert entry["message"] == "hi", (
        f"Expected dialog message 'hi', got '{entry['message']}'"
    )

    # Accept the dialog to clean up
    await browser_session_real.dialog_queue[0]["dialog"].accept()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_popup_page_added(browser_session_real: BrowserSession) -> None:
    """Opening a popup via window.open() adds a new page to session.pages."""
    page = browser_session_real.active_page
    await page.goto("data:text/html,<h1>Popup</h1>")

    initial_count = len(browser_session_real.pages)
    await page.evaluate("window.open('about:blank')")
    await page.wait_for_timeout(300)

    assert len(browser_session_real.pages) > initial_count, (
        f"Expected pages count to increase from {initial_count}, "
        f"but got {len(browser_session_real.pages)}"
    )
